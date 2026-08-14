"""Assinaturas da Google Workspace Events API para o Google Meet.

É isto que torna o fluxo orientado a evento: em vez de perguntar de tempos em
tempos "já tem transcrição?", o Google avisa quando o arquivo fica pronto.

**Push, não pull.** A Workspace Events API entrega em Pub/Sub, e Pub/Sub
oferece dois modos. Escolhemos *push*: o Pub/Sub faz POST num endpoint HTTPS
nosso. O motivo é concreto — pull exigiria a biblioteca ``google-cloud-pubsub``
e um processo residente novo para supervisionar. Push reaproveita o que já
existe (FastAPI, nginx com TLS válido, Celery) e não adiciona **nenhuma**
dependência: a verificação do token OIDC usa ``google-auth``, que já está no
projeto por causa do Calendar.

Autenticidade da entrega: o Pub/Sub assina cada POST com um JWT OIDC no header
``Authorization``. Validamos assinatura, emissor, audiência e o e-mail da
service account. Nada de "segredo na URL", que vaza em log de proxy.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models import CalendarIntegration
from backend.services.meetings.providers.google_meet import (
    MEET_READONLY_SCOPE,
    GoogleMeetProvider,
)

logger = logging.getLogger(__name__)

WORKSPACE_EVENTS_API = "https://workspaceevents.googleapis.com/v1"

# O evento que interessa: o Google terminou de gerar o arquivo de transcrição.
EVENT_TRANSCRIPT_FILE_GENERATED = "google.workspace.meet.transcript.v2.fileGenerated"
# Assinados junto porque vêm de graça na mesma assinatura e dão estado
# confiável de início/fim — melhor que inferir pelo horário previsto.
EVENT_CONFERENCE_STARTED = "google.workspace.meet.conference.v2.started"
EVENT_CONFERENCE_ENDED = "google.workspace.meet.conference.v2.ended"

SUBSCRIBED_EVENT_TYPES = (
    EVENT_TRANSCRIPT_FILE_GENERATED,
    EVENT_CONFERENCE_STARTED,
    EVENT_CONFERENCE_ENDED,
)

# Assinaturas do Workspace Events duram no máximo 7 dias. Renovamos com folga
# para que uma falha isolada de renovação ainda tenha tentativas antes de
# expirar de fato.
RENEWAL_MARGIN_HOURS = 24
SUBSCRIPTION_TTL_SECONDS = 604800  # 7 dias

STATUS_INACTIVE = "inactive"
STATUS_ACTIVE = "active"
STATUS_DEGRADED = "degraded"
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"

PUBSUB_TOPIC_ENV = "GOOGLE_MEET_PUBSUB_TOPIC"


class WorkspaceEventsError(RuntimeError):
    """Falha cuja mensagem é segura para exibir ao usuário."""


class WorkspaceEventsNotConfiguredError(WorkspaceEventsError):
    """Falta credencial, scope ou tópico Pub/Sub."""


@dataclass(frozen=True)
class SubscriptionState:
    status: str
    name: Optional[str] = None
    expires_at: Optional[datetime] = None
    last_event_at: Optional[datetime] = None
    error: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE


def pubsub_topic() -> Optional[str]:
    """Tópico que recebe os eventos: ``projects/<id>/topics/<nome>``."""
    return (os.getenv(PUBSUB_TOPIC_ENV) or "").strip() or None


def _integration(db: Session, company_id: int) -> Optional[CalendarIntegration]:
    return (
        db.query(CalendarIntegration)
        .filter(
            CalendarIntegration.company_id == int(company_id),
            CalendarIntegration.provider == "google",
        )
        .first()
    )


def get_subscription_state(db: Session, company_id: int) -> SubscriptionState:
    integration = _integration(db, company_id)
    if integration is None:
        return SubscriptionState(status=STATUS_INACTIVE)

    status = integration.meet_subscription_status or STATUS_INACTIVE
    expires_at = integration.meet_subscription_expires_at

    # Expiração é fato, não opinião: se a data passou, o estado gravado está
    # desatualizado e o que vale é o relógio.
    if status == STATUS_ACTIVE and expires_at and expires_at <= datetime.now(timezone.utc):
        status = STATUS_EXPIRED

    return SubscriptionState(
        status=status,
        name=integration.meet_subscription_name,
        expires_at=expires_at,
        last_event_at=integration.meet_last_event_at,
        error=integration.meet_subscription_error,
    )


def ensure_subscription(db: Session, company_id: int) -> SubscriptionState:
    """Cria ou renova a assinatura da empresa. Idempotente.

    Chamar de novo com uma assinatura saudável não cria uma segunda: consulta
    o Google pelo nome guardado e só recria se ele não reconhecer mais.
    """
    company_id = int(company_id)
    integration = _integration(db, company_id)

    if integration is None or not integration.google_oauth_token:
        raise WorkspaceEventsNotConfiguredError("Google Agenda não está conectado nesta empresa")

    topic = pubsub_topic()
    if not topic:
        raise WorkspaceEventsNotConfiguredError(
            f"Tópico Pub/Sub não configurado ({PUBSUB_TOPIC_ENV})"
        )

    provider = GoogleMeetProvider()
    capabilities = provider.capabilities(db, company_id)
    if not capabilities.can_import_transcripts:
        raise WorkspaceEventsNotConfiguredError(
            capabilities.unavailable_reason or "Permissão do Google Meet ausente"
        )

    session = _authorized_session(provider, db, company_id)

    # Assinatura conhecida e viva: renova em vez de criar outra.
    if integration.meet_subscription_name:
        existing = _get_subscription(session, integration.meet_subscription_name)
        if existing is not None:
            return _renew(db, integration, session, existing)

    return _create(db, integration, session, topic)


def _create(
    db: Session,
    integration: CalendarIntegration,
    session: Any,
    topic: str,
) -> SubscriptionState:
    payload = {
        # `user:me` assina os eventos de todos os espaços do usuário
        # autenticado — é o recorte que a Meet API oferece.
        "targetResource": "//meet.googleapis.com/spaces/-",
        "eventTypes": list(SUBSCRIBED_EVENT_TYPES),
        "notificationEndpoint": {"pubsubTopic": topic},
        "payloadOptions": {"includeResource": False},
        "ttl": f"{SUBSCRIPTION_TTL_SECONDS}s",
    }

    try:
        response = session.post(f"{WORKSPACE_EVENTS_API}/subscriptions", json=payload, timeout=30)
        response.raise_for_status()
        body = response.json() or {}
    except Exception as exc:
        return _mark_failure(db, integration, exc, "criar")

    # A criação é uma operação de longa duração; o nome pode vir no envelope.
    name = body.get("name") or (body.get("response") or {}).get("name")
    expires_at = _parse_time((body.get("response") or {}).get("expireTime") or body.get("expireTime"))

    integration.meet_subscription_name = name
    integration.meet_subscription_expires_at = expires_at or (
        datetime.now(timezone.utc) + timedelta(seconds=SUBSCRIPTION_TTL_SECONDS)
    )
    integration.meet_subscription_status = STATUS_ACTIVE
    integration.meet_subscription_error = None
    db.commit()

    logger.info("Assinatura Meet criada: company_id=%s", integration.company_id)
    return get_subscription_state(db, integration.company_id)


def _renew(
    db: Session,
    integration: CalendarIntegration,
    session: Any,
    existing: Dict[str, Any],
) -> SubscriptionState:
    name = existing.get("name") or integration.meet_subscription_name

    try:
        response = session.patch(
            f"{WORKSPACE_EVENTS_API}/{name}",
            params={"updateMask": "ttl"},
            json={"ttl": f"{SUBSCRIPTION_TTL_SECONDS}s"},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json() or {}
    except Exception as exc:
        return _mark_failure(db, integration, exc, "renovar")

    expires_at = _parse_time(
        (body.get("response") or {}).get("expireTime") or body.get("expireTime")
    )
    integration.meet_subscription_name = name
    integration.meet_subscription_expires_at = expires_at or (
        datetime.now(timezone.utc) + timedelta(seconds=SUBSCRIPTION_TTL_SECONDS)
    )
    integration.meet_subscription_status = STATUS_ACTIVE
    integration.meet_subscription_error = None
    db.commit()
    return get_subscription_state(db, integration.company_id)


def _mark_failure(
    db: Session,
    integration: CalendarIntegration,
    exc: Exception,
    action: str,
) -> SubscriptionState:
    """Registra a falha e deixa a empresa em estado degradado.

    Degradado, não desligado: o fallback periódico continua rodando e é
    exatamente para isso que ele existe.
    """
    integration.meet_subscription_status = STATUS_DEGRADED
    # Só o tipo: a resposta do Google pode conter identificadores da conta.
    integration.meet_subscription_error = f"Falha ao {action} assinatura ({exc.__class__.__name__})"
    db.commit()
    logger.warning(
        "Assinatura Meet em estado degradado: company_id=%s acao=%s error_type=%s",
        integration.company_id,
        action,
        exc.__class__.__name__,
    )
    return get_subscription_state(db, integration.company_id)


def _get_subscription(session: Any, name: str) -> Optional[Dict[str, Any]]:
    try:
        response = session.get(f"{WORKSPACE_EVENTS_API}/{name}", timeout=30)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json() or {}
    except Exception as exc:
        logger.info(
            "Assinatura Meet não pôde ser consultada: error_type=%s", exc.__class__.__name__
        )
        return None


def delete_subscription(db: Session, company_id: int) -> None:
    """Remove a assinatura. Usado ao desconectar o Google."""
    integration = _integration(db, int(company_id))
    if integration is None or not integration.meet_subscription_name:
        return

    try:
        provider = GoogleMeetProvider()
        session = _authorized_session(provider, db, int(company_id))
        session.delete(f"{WORKSPACE_EVENTS_API}/{integration.meet_subscription_name}", timeout=30)
    except Exception as exc:
        logger.info("Falha ao remover assinatura Meet: error_type=%s", exc.__class__.__name__)

    integration.meet_subscription_name = None
    integration.meet_subscription_expires_at = None
    integration.meet_subscription_status = STATUS_INACTIVE
    integration.meet_subscription_error = None
    db.commit()


def subscriptions_needing_renewal(db: Session) -> List[CalendarIntegration]:
    """Assinaturas perto de expirar, expiradas ou degradadas."""
    cutoff = datetime.now(timezone.utc) + timedelta(hours=RENEWAL_MARGIN_HOURS)
    return (
        db.query(CalendarIntegration)
        .filter(
            CalendarIntegration.provider == "google",
            CalendarIntegration.google_oauth_token.isnot(None),
            CalendarIntegration.meet_subscription_status.in_(
                (STATUS_ACTIVE, STATUS_DEGRADED, STATUS_EXPIRED)
            ),
            (CalendarIntegration.meet_subscription_expires_at.is_(None))
            | (CalendarIntegration.meet_subscription_expires_at <= cutoff),
        )
        .all()
    )


def record_event_received(db: Session, company_id: int) -> None:
    """Carimba que a entrega está funcionando de verdade."""
    integration = _integration(db, int(company_id))
    if integration is None:
        return
    integration.meet_last_event_at = datetime.now(timezone.utc)
    if integration.meet_subscription_status == STATUS_DEGRADED:
        # Chegou evento: a entrega voltou, independentemente do que a última
        # tentativa de renovação disse.
        integration.meet_subscription_status = STATUS_ACTIVE
        integration.meet_subscription_error = None
    db.commit()


def resolve_company_for_conference(db: Session, conference_record: str) -> Optional[int]:
    """Descobre a empresa dona de um conferenceRecord recebido por evento.

    O evento não traz company_id — ele é do Google. A resolução é pelo que já
    conhecemos: a reunião já ingerida com aquele conferenceRecord, ou o espaço
    correspondente.

    Devolver ``None`` é resposta legítima: um evento de conta conectada cuja
    reunião ainda não foi ingerida cai no fallback, em vez de ser atribuído a
    alguém por aproximação.
    """
    from backend.models.meeting_models import Meeting

    row = (
        db.query(Meeting.company_id)
        .filter(Meeting.external_meeting_id == conference_record)
        .first()
    )
    if row:
        return int(row[0])

    # `conferenceRecords/{id}` não carrega o código da sala; tentamos casar
    # pelo prefixo que o próprio Google usa nos nomes de recurso.
    space = conference_record.split("/")[-1] if conference_record else None
    if not space:
        return None

    row = (
        db.query(Meeting.company_id)
        .filter(Meeting.external_conference_id == space)
        .first()
    )
    return int(row[0]) if row else None


def _authorized_session(provider: GoogleMeetProvider, db: Session, company_id: int) -> Any:
    from google.auth.transport.requests import AuthorizedSession

    # Reutiliza a resolução de credencial do provider: um único lugar sabe ler
    # e renovar o token do Google.
    credentials = provider._credentials(db, company_id)  # noqa: SLF001
    return AuthorizedSession(credentials)


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = [
    "EVENT_CONFERENCE_ENDED",
    "EVENT_CONFERENCE_STARTED",
    "EVENT_TRANSCRIPT_FILE_GENERATED",
    "MEET_READONLY_SCOPE",
    "STATUS_ACTIVE",
    "STATUS_DEGRADED",
    "STATUS_EXPIRED",
    "STATUS_FAILED",
    "STATUS_INACTIVE",
    "SubscriptionState",
    "WorkspaceEventsError",
    "WorkspaceEventsNotConfiguredError",
    "delete_subscription",
    "ensure_subscription",
    "get_subscription_state",
    "pubsub_topic",
    "record_event_received",
    "resolve_company_for_conference",
    "subscriptions_needing_renewal",
]
