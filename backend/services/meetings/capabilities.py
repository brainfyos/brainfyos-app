"""O que a Meeting Intelligence consegue fazer nesta empresa, agora.

Existe porque "OAuth funcionou" não significa "transcrição automática
funciona". São quatro coisas independentes e cada uma pode faltar sozinha:

1. **Calendar conectado** — há token OAuth.
2. **Acesso ao Meet** — o token inclui o scope de leitura do Meet.
3. **Assinatura de eventos ativa** — existe subscription viva no Workspace
   Events, e ela está entregando.
4. **Transcrição gerada** — o Google Workspace precisa estar gerando o
   artefato. Isso depende da edição do Workspace e da configuração da
   reunião, e nenhuma API nossa consegue afirmar de fora.

Cada campo abaixo vem de um fato verificável. Onde não dá para afirmar, o
valor é ``None`` e a UI diz "não foi possível determinar" — nunca inventa
sucesso.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models import CalendarIntegration
from backend.models.meeting_models import Meeting
from backend.services.meetings import google_workspace_events as events
from backend.services.meetings.providers.google_meet import MEET_READONLY_SCOPE

logger = logging.getLogger(__name__)

# Sem evento nesse tempo, com assinatura supostamente ativa, tratamos a
# entrega como suspeita. Não é falha: pode simplesmente não ter havido
# reunião. Por isso vira sinal para o fallback, não erro para o usuário.
EVENT_SILENCE_HOURS = 72


@dataclass
class MeetingCapabilities:
    calendar_connected: bool = False
    meet_access: bool = False
    event_subscription_active: bool = False
    transcript_access: bool = False
    # `None` = não dá para determinar de fora. O Google não expõe a política
    # de transcrição do Workspace por API acessível ao app.
    auto_transcription_available: Optional[bool] = None
    subscription_status: str = events.STATUS_INACTIVE
    subscription_expires_at: Optional[datetime] = None
    last_event_received_at: Optional[datetime] = None
    oauth_configured: bool = False
    pubsub_configured: bool = False
    missing_scopes: List[str] = None  # type: ignore[assignment]
    needs_reconsent: bool = False
    # Mensagens prontas para a UI, na ordem em que devem ser resolvidas.
    blockers: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.missing_scopes is None:
            self.missing_scopes = []
        if self.blockers is None:
            self.blockers = []

    @property
    def is_operational(self) -> bool:
        """Automático de ponta a ponta, sem ação humana por reunião."""
        return self.calendar_connected and self.meet_access and self.event_subscription_active

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["subscription_expires_at"] = (
            self.subscription_expires_at.isoformat() if self.subscription_expires_at else None
        )
        payload["last_event_received_at"] = (
            self.last_event_received_at.isoformat() if self.last_event_received_at else None
        )
        payload["is_operational"] = self.is_operational
        return payload


def describe_capabilities(db: Session, company_id: int) -> MeetingCapabilities:
    company_id = int(company_id)
    capabilities = MeetingCapabilities()

    capabilities.oauth_configured = bool(
        (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
        and (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()
    )
    capabilities.pubsub_configured = bool(events.pubsub_topic())

    if not capabilities.oauth_configured:
        capabilities.blockers.append(
            "OAuth do Google não configurado no servidor (GOOGLE_OAUTH_CLIENT_ID e "
            "GOOGLE_OAUTH_CLIENT_SECRET)."
        )

    integration = (
        db.query(CalendarIntegration)
        .filter(
            CalendarIntegration.company_id == company_id,
            CalendarIntegration.provider == "google",
        )
        .first()
    )

    if integration is None or not integration.google_oauth_token:
        capabilities.blockers.append("Google Agenda não conectado.")
        capabilities.missing_scopes = [MEET_READONLY_SCOPE]
        return capabilities

    capabilities.calendar_connected = True

    granted = (integration.google_oauth_scopes or "").replace(",", " ").split()
    capabilities.meet_access = MEET_READONLY_SCOPE in granted

    if not capabilities.meet_access:
        # Conta antiga que autorizou só Calendar. Não é erro nem "conectado":
        # é reconsentimento pendente, e a UI precisa dizer isso.
        capabilities.missing_scopes = [MEET_READONLY_SCOPE]
        capabilities.needs_reconsent = True
        capabilities.blockers.append(
            "Requer autorização adicional: reconecte o Google para permitir a leitura "
            "das transcrições do Meet."
        )
        return capabilities

    state = events.get_subscription_state(db, company_id)
    capabilities.subscription_status = state.status
    capabilities.subscription_expires_at = state.expires_at
    capabilities.last_event_received_at = state.last_event_at
    capabilities.transcript_access = True

    if not capabilities.pubsub_configured:
        capabilities.blockers.append(
            "Tópico Pub/Sub não configurado no servidor (GOOGLE_MEET_PUBSUB_TOPIC)."
        )
        return capabilities

    capabilities.event_subscription_active = state.is_active

    if state.status == events.STATUS_INACTIVE:
        capabilities.blockers.append("Assinatura de eventos do Meet ainda não foi criada.")
    elif state.status == events.STATUS_EXPIRED:
        capabilities.blockers.append(
            "Assinatura de eventos expirou. A sincronização periódica segue como reserva."
        )
    elif state.status in (events.STATUS_DEGRADED, events.STATUS_FAILED):
        capabilities.blockers.append(
            state.error or "Assinatura de eventos com falha. Sincronização periódica ativa."
        )

    capabilities.auto_transcription_available = _infer_auto_transcription(db, company_id, state)
    return capabilities


def _infer_auto_transcription(
    db: Session,
    company_id: int,
    state: events.SubscriptionState,
) -> Optional[bool]:
    """A transcrição está de fato sendo gerada?

    Não há API que responda isso: a política vive no Google Workspace e a
    decisão é por reunião. O que dá para fazer é **observar**: se alguma
    reunião já produziu transcrição, está gerando. Se várias terminaram e
    nenhuma produziu, provavelmente não está.

    Sem evidência suficiente, devolve ``None`` — "não sei" é uma resposta
    honesta e melhor do que um palpite exibido como fato.
    """
    imported = (
        db.query(Meeting.id)
        .filter(Meeting.company_id == company_id, Meeting.transcript_status == "imported")
        .first()
    )
    if imported is not None:
        return True

    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    finished_without_transcript = (
        db.query(Meeting.id)
        .filter(
            Meeting.company_id == company_id,
            Meeting.status == "completed",
            Meeting.scheduled_end_at.isnot(None),
            Meeting.scheduled_end_at <= cutoff,
            Meeting.transcript_status.in_(("pending", "unavailable")),
        )
        .limit(3)
        .all()
    )
    if len(finished_without_transcript) >= 3:
        return False

    return None


def transcription_guidance() -> List[str]:
    """O que o usuário precisa habilitar do lado do Google.

    Exibido quando ``auto_transcription_available`` é falso ou desconhecido.
    """
    return [
        "A transcrição precisa estar ativada na reunião — o organizador liga em "
        "Atividades → Transcrições, ou o administrador ativa por política no Workspace.",
        "Transcrição do Meet exige uma edição elegível do Google Workspace "
        "(Business Standard ou superior).",
        "O arquivo só fica disponível depois que a reunião encerra. Não existe "
        "transcrição durante a chamada.",
        "Registros de conferência ficam disponíveis por 30 dias.",
    ]
