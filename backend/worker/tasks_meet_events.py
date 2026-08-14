"""Processamento assíncrono dos eventos do Google Meet.

Entrada: um evento do Workspace Events entregue por Pub/Sub push.
Saída: transcrição importada e a cadeia de inteligência disparada.

Idempotência em três camadas, e a terceira é a que realmente garante:

1. Cache curto por ``message_id`` no Redis — corta reentrega imediata sem
   tocar no banco.
2. Verificação de estado antes de importar.
3. ``uq_meeting_transcript_external`` no Postgres — dois workers concorrentes
   passam pelas duas primeiras ao mesmo tempo; só o banco decide.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.db import SessionLocal
from backend.worker.celery_app import app

logger = logging.getLogger(__name__)

# Janela do corte rápido por message_id. Curta de propósito: é otimização,
# não garantia — a garantia é o índice único.
DEDUPE_TTL_SECONDS = 3600
RETRY_BACKOFF_SECONDS = 30
MAX_RETRIES = 3


def _already_processed(message_id: Optional[str]) -> bool:
    """Corte rápido em Redis. Falha do Redis nunca bloqueia o processamento."""
    if not message_id:
        return False
    try:
        import redis

        from backend.worker.celery_app import REDIS_URL

        client = redis.Redis.from_url(REDIS_URL)
        key = f"brainfyos:meet-event:{message_id}"
        # SET NX: quem gravar primeiro processa.
        return not bool(client.set(key, "1", nx=True, ex=DEDUPE_TTL_SECONDS))
    except Exception as exc:
        logger.info(
            "Deduplicação de evento indisponível, seguindo: error_type=%s",
            exc.__class__.__name__,
        )
        return False


@app.task(name="meetings.process_meet_event", bind=True, max_retries=MAX_RETRIES)
def process_meet_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
    from backend.services.meetings import google_workspace_events as events

    event_type = event.get("event_type")
    message_id = event.get("message_id")

    if _already_processed(message_id):
        return {"status": "duplicate", "message_id": message_id}

    if event_type == events.EVENT_TRANSCRIPT_FILE_GENERATED:
        return _handle_transcript_ready(self, event)

    if event_type in (events.EVENT_CONFERENCE_STARTED, events.EVENT_CONFERENCE_ENDED):
        return _handle_conference_state(event, event_type)

    return {"status": "ignored", "event_type": event_type}


def _conference_record(event: Dict[str, Any]) -> Optional[str]:
    """Nome do conferenceRecord referenciado pelo evento.

    Vem em ``ce-subject`` (CloudEvents) e, dependendo do formato, no corpo.
    """
    subject = event.get("subject")
    if subject:
        return str(subject)

    payload = event.get("payload") or {}
    for key in ("transcript", "conferenceRecord"):
        value = payload.get(key)
        if isinstance(value, dict) and value.get("name"):
            name = str(value["name"])
            # `conferenceRecords/x/transcripts/y` → `conferenceRecords/x`
            return name.split("/transcripts/")[0]
        if isinstance(value, str) and value:
            return value.split("/transcripts/")[0]
    return None


def _transcript_name(event: Dict[str, Any]) -> Optional[str]:
    payload = event.get("payload") or {}
    transcript = payload.get("transcript")
    if isinstance(transcript, dict) and transcript.get("name"):
        return str(transcript["name"])
    if isinstance(transcript, str):
        return transcript
    subject = event.get("subject")
    return str(subject) if subject and "/transcripts/" in str(subject) else None


def _handle_transcript_ready(task: Any, event: Dict[str, Any]) -> Dict[str, Any]:
    from backend.services.meetings import google_workspace_events as events
    from backend.services.meetings.ingestion import MeetingIngestionService

    conference_record = _conference_record(event)
    if not conference_record:
        return {"status": "ignored", "reason": "missing_conference_record"}

    db = SessionLocal()
    try:
        company_id = events.resolve_company_for_conference(db, conference_record)
        if company_id is None:
            # Reunião ainda não ingerida (evento chegou antes do sync). Não é
            # erro: o fallback pega na próxima passada, e forçar uma empresa
            # aqui seria adivinhar.
            logger.info(
                "Evento do Meet sem empresa resolvida; fallback assume: record=%s",
                conference_record,
            )
            return {"status": "deferred", "reason": "company_unresolved"}

        events.record_event_received(db, company_id)

        from backend.models.meeting_models import Meeting

        meeting = (
            db.query(Meeting)
            .filter(
                Meeting.company_id == company_id,
                (Meeting.external_meeting_id == conference_record)
                | (Meeting.external_conference_id == conference_record.split("/")[-1]),
            )
            .order_by(Meeting.id.desc())
            .first()
        )
        if meeting is None:
            return {"status": "deferred", "reason": "meeting_unresolved"}

        if meeting.transcript_status == "imported":
            return {"status": "duplicate", "meeting_id": meeting.id}

        imported = MeetingIngestionService(db).import_transcript(meeting.id, company_id)

        if imported:
            from backend.worker.tasks_meetings import analyze_meeting_task

            analyze_meeting_task.delay(meeting.id, company_id)

        return {
            "status": "imported" if imported else "pending",
            "meeting_id": meeting.id,
            "company_id": company_id,
        }
    except Exception as exc:
        logger.warning(
            "Falha ao processar evento de transcrição: error_type=%s",
            exc.__class__.__name__,
        )
        raise task.retry(exc=exc, countdown=RETRY_BACKOFF_SECONDS * (task.request.retries + 1))
    finally:
        db.close()


def _handle_conference_state(event: Dict[str, Any], event_type: str) -> Dict[str, Any]:
    """Atualiza início/fim com a fonte confiável do provedor.

    Melhor que inferir pelo horário previsto: uma reunião pode começar tarde
    ou terminar cedo, e o estado real vem daqui.
    """
    from datetime import datetime, timezone

    from backend.models.meeting_models import Meeting
    from backend.services.meetings import google_workspace_events as events

    conference_record = _conference_record(event)
    if not conference_record:
        return {"status": "ignored", "reason": "missing_conference_record"}

    db = SessionLocal()
    try:
        company_id = events.resolve_company_for_conference(db, conference_record)
        if company_id is None:
            return {"status": "deferred", "reason": "company_unresolved"}

        events.record_event_received(db, company_id)

        meeting = (
            db.query(Meeting)
            .filter(
                Meeting.company_id == company_id,
                (Meeting.external_meeting_id == conference_record)
                | (Meeting.external_conference_id == conference_record.split("/")[-1]),
            )
            .order_by(Meeting.id.desc())
            .first()
        )
        if meeting is None:
            return {"status": "deferred", "reason": "meeting_unresolved"}

        now = datetime.now(timezone.utc)
        if event_type == events.EVENT_CONFERENCE_STARTED:
            meeting.status = "in_progress"
            meeting.started_at = meeting.started_at or now
        else:
            meeting.status = "completed"
            meeting.ended_at = meeting.ended_at or now
            if meeting.started_at and meeting.ended_at:
                meeting.duration_seconds = int(
                    (meeting.ended_at - meeting.started_at).total_seconds()
                )

        db.commit()
        return {"status": "updated", "meeting_id": meeting.id, "state": meeting.status}
    finally:
        db.close()


@app.task(name="meetings.renew_event_subscriptions")
def renew_event_subscriptions() -> Dict[str, Any]:
    """Renova assinaturas antes de expirarem.

    Falha de renovação deixa a empresa em estado degradado e **mantém** o
    fallback periódico — é para isso que ele existe.
    """
    from backend.services.meetings import google_workspace_events as events

    db = SessionLocal()
    try:
        pending = events.subscriptions_needing_renewal(db)
        company_ids = [int(item.company_id) for item in pending]
    finally:
        db.close()

    renewed = 0
    degraded = 0
    for company_id in company_ids:
        session = SessionLocal()
        try:
            state = events.ensure_subscription(session, company_id)
            if state.is_active:
                renewed += 1
            else:
                degraded += 1
        except events.WorkspaceEventsError as exc:
            degraded += 1
            logger.info(
                "Assinatura não renovada: company_id=%s motivo=%s", company_id, exc
            )
        except Exception as exc:
            degraded += 1
            logger.warning(
                "Erro ao renovar assinatura: company_id=%s error_type=%s",
                company_id,
                exc.__class__.__name__,
            )
        finally:
            session.close()

    return {"checked": len(company_ids), "renewed": renewed, "degraded": degraded}
