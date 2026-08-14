"""Tarefas assíncronas de Meeting Intelligence.

Cadeia: descoberta → transcrição → análise → memória → sugestões.

Cada etapa é uma task separada e **idempotente**. Retry do Celery repete a
chamada inteira, então nenhuma delas pode duplicar efeito — a garantia vem dos
índices únicos do banco (`uq_meetings_company_calendar_event`,
`uq_meeting_transcript_external`, `uq_meeting_analysis_version`,
`uq_crm_suggestion_dedupe`), não de uma flag em memória.

**Estratégia de descoberta: sincronização agendada moderada, não polling.**
O Google só publica a transcrição depois que a conferência encerra, e o
artefato não muda depois disso. Um ciclo a cada 15 minutos captura a reunião
poucos minutos após o fim; qualquer coisa mais frequente gastaria cota da API
para receber a mesma resposta vazia. O Google Calendar oferece `watch`
(push notification), mas ele avisa sobre mudança de *evento*, não sobre
transcrição pronta — não resolveria o que precisamos observar.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.db import SessionLocal
from backend.worker.celery_app import app

logger = logging.getLogger(__name__)

# Retentativas com espaçamento crescente: uma falha de rede resolve rápido,
# uma indisponibilidade do provedor precisa de mais tempo.
RETRY_BACKOFF_SECONDS = 60
MAX_RETRIES = 3


@app.task(name="meetings.sync_company_meetings", bind=True, max_retries=MAX_RETRIES)
def sync_company_meetings(self, company_id: int, provider_name: Optional[str] = None) -> Dict[str, Any]:
    """Descobre e ingere reuniões de uma empresa."""
    from backend.services.meetings.ingestion import MeetingIngestionService

    db = SessionLocal()
    try:
        summary = MeetingIngestionService(db).sync_company(
            int(company_id), provider_name=provider_name
        )
        # A análise é encadeada aqui, não dentro da ingestão: manter a
        # transação de escrita separada do disparo evita agendar trabalho para
        # uma reunião cujo commit ainda pode falhar.
        _queue_pending_analyses(db, int(company_id))
        return summary
    except Exception as exc:
        logger.warning(
            "Falha ao sincronizar reuniões: company_id=%s error_type=%s",
            company_id,
            exc.__class__.__name__,
        )
        raise self.retry(exc=exc, countdown=RETRY_BACKOFF_SECONDS * (self.request.retries + 1))
    finally:
        db.close()


@app.task(name="meetings.sync_all_companies")
def sync_all_companies() -> Dict[str, Any]:
    """Ciclo agendado. Só varre empresas com agenda conectada."""
    from backend.models import CalendarIntegration

    db = SessionLocal()
    try:
        rows = (
            db.query(CalendarIntegration.company_id)
            .filter(
                CalendarIntegration.provider == "google",
                CalendarIntegration.google_oauth_token.isnot(None),
            )
            .distinct()
            .all()
        )
        company_ids = [int(row[0]) for row in rows]
    finally:
        db.close()

    for company_id in company_ids:
        sync_company_meetings.delay(company_id)

    return {"scheduled": len(company_ids)}


@app.task(name="meetings.import_transcript", bind=True, max_retries=MAX_RETRIES)
def import_transcript(self, meeting_id: int, company_id: int) -> Dict[str, Any]:
    from backend.services.meetings.ingestion import MeetingIngestionService

    db = SessionLocal()
    try:
        imported = MeetingIngestionService(db).import_transcript(int(meeting_id), int(company_id))
        if imported:
            analyze_meeting_task.delay(int(meeting_id), int(company_id))
        return {"meeting_id": meeting_id, "imported": imported}
    except Exception as exc:
        logger.warning(
            "Falha ao importar transcrição: meeting_id=%s error_type=%s",
            meeting_id,
            exc.__class__.__name__,
        )
        raise self.retry(exc=exc, countdown=RETRY_BACKOFF_SECONDS * (self.request.retries + 1))
    finally:
        db.close()


@app.task(name="meetings.analyze_meeting", bind=True, max_retries=MAX_RETRIES)
def analyze_meeting_task(self, meeting_id: int, company_id: int, force: bool = False) -> Dict[str, Any]:
    """Analisa e encadeia memória + sugestões."""
    from backend.services.meetings.analysis import MeetingAnalysisError, analyze_meeting

    db = SessionLocal()
    try:
        analysis = analyze_meeting(db, int(company_id), int(meeting_id), force_new_version=force)
        if analysis is None:
            return {"meeting_id": meeting_id, "analyzed": False}

        from backend.models.meeting_models import Meeting

        meeting = (
            db.query(Meeting)
            .filter(Meeting.id == int(meeting_id), Meeting.company_id == int(company_id))
            .first()
        )
        if meeting is not None and meeting.lead_id:
            rebuild_sales_memory_task.delay(int(company_id), int(meeting.lead_id))
            generate_crm_suggestions_task.delay(int(meeting_id), int(company_id))

        return {"meeting_id": meeting_id, "analyzed": True, "analysis_id": analysis.id}
    except MeetingAnalysisError as exc:
        # Erro de negócio (sem transcrição, IA indisponível): repetir não
        # muda o resultado e só consome fila.
        logger.info("Análise não concluída: meeting_id=%s motivo=%s", meeting_id, exc)
        return {"meeting_id": meeting_id, "analyzed": False, "error": str(exc)}
    except Exception as exc:
        raise self.retry(exc=exc, countdown=RETRY_BACKOFF_SECONDS * (self.request.retries + 1))
    finally:
        db.close()


@app.task(name="meetings.rebuild_sales_memory", bind=True, max_retries=MAX_RETRIES)
def rebuild_sales_memory_task(self, company_id: int, lead_id: int) -> Dict[str, Any]:
    from backend.services.meetings.sales_memory import SalesMemoryError, rebuild_sales_memory

    db = SessionLocal()
    try:
        memory = rebuild_sales_memory(db, int(company_id), int(lead_id))
        return {"lead_id": lead_id, "rebuilt": memory is not None}
    except SalesMemoryError as exc:
        logger.info("Memória não reconstruída: lead_id=%s motivo=%s", lead_id, exc)
        return {"lead_id": lead_id, "rebuilt": False, "error": str(exc)}
    except Exception as exc:
        raise self.retry(exc=exc, countdown=RETRY_BACKOFF_SECONDS * (self.request.retries + 1))
    finally:
        db.close()


@app.task(name="meetings.generate_crm_suggestions", bind=True, max_retries=MAX_RETRIES)
def generate_crm_suggestions_task(self, meeting_id: int, company_id: int) -> Dict[str, Any]:
    """Gera sugestões. Nenhuma delas altera o CRM — todas nascem 'pending'."""
    from backend.services.meetings.crm_intelligence import CrmSuggestionError, generate_suggestions

    db = SessionLocal()
    try:
        created = generate_suggestions(db, int(company_id), int(meeting_id))
        return {"meeting_id": meeting_id, "created": len(created)}
    except CrmSuggestionError as exc:
        logger.info("Sugestões não geradas: meeting_id=%s motivo=%s", meeting_id, exc)
        return {"meeting_id": meeting_id, "created": 0, "error": str(exc)}
    except Exception as exc:
        raise self.retry(exc=exc, countdown=RETRY_BACKOFF_SECONDS * (self.request.retries + 1))
    finally:
        db.close()


def _queue_pending_analyses(db: Any, company_id: int) -> None:
    """Enfileira análise das reuniões com transcrição pronta."""
    from backend.models.meeting_models import Meeting

    pending: List[Meeting] = (
        db.query(Meeting)
        .filter(
            Meeting.company_id == company_id,
            Meeting.transcript_status == "imported",
            Meeting.analysis_status.in_(("pending", "queued")),
        )
        .limit(50)
        .all()
    )
    for meeting in pending:
        analyze_meeting_task.delay(meeting.id, company_id)
