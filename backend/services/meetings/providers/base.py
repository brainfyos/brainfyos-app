"""Contrato de provedor de reunião.

O domínio nunca fala com o Google. Ele fala com este contrato, e é isto que
permite que upload manual, Google Meet e — quando houver autenticação —
Microsoft Teams alimentem exatamente o mesmo pipeline de inteligência.

Os DTOs abaixo são deliberadamente pobres: só o que todo provedor consegue
entregar. O que é específico de um provedor viaja em ``raw``/``metadata`` e é
preservado sem interpretação, para não perder informação nem inventar campo
que a fonte não tem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol


@dataclass(frozen=True)
class ProviderCapabilities:
    """O que este provedor realmente consegue fazer *agora*.

    Existe para a UI dizer a verdade. Um provedor conectado cuja capacidade de
    transcrição não está autorizada não pode aparecer como "pronto" — e é o
    provedor quem sabe disso, não a tela.
    """

    provider: str
    label: str
    can_discover_meetings: bool = False
    can_import_transcripts: bool = False
    can_identify_participants: bool = False
    supports_realtime: bool = False
    # Quando algo está desligado, isto diz o que falta em português claro.
    unavailable_reason: Optional[str] = None
    missing_scopes: List[str] = field(default_factory=list)

    @property
    def is_operational(self) -> bool:
        return self.can_discover_meetings and self.can_import_transcripts


@dataclass
class ProviderMeeting:
    """Uma reunião como o provedor a descreve."""

    external_meeting_id: str
    title: Optional[str] = None
    calendar_event_id: Optional[str] = None
    external_conference_id: Optional[str] = None
    meeting_url: Optional[str] = None
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    status: str = "unknown"
    organizer_email: Optional[str] = None
    participants: List["ProviderParticipant"] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderParticipant:
    external_participant_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    attendance_status: Optional[str] = None
    joined_at: Optional[datetime] = None
    left_at: Optional[datetime] = None
    is_organizer: bool = False


@dataclass
class ProviderTranscriptSegment:
    text: str
    speaker: Optional[str] = None
    speaker_external_id: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    language_code: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "speaker": self.speaker,
            "speaker_external_id": self.speaker_external_id,
            "text": self.text,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "language_code": self.language_code,
        }


@dataclass
class ProviderTranscript:
    external_transcript_id: Optional[str]
    text: str
    segments: List[ProviderTranscriptSegment] = field(default_factory=list)
    language: Optional[str] = None
    duration_seconds: Optional[int] = None
    source_available_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MeetingProviderError(RuntimeError):
    """Falha do provedor cuja mensagem pode ser exibida com segurança."""


class MeetingProviderNotConfiguredError(MeetingProviderError):
    """Provedor sem credencial ou permissão suficiente para operar."""


class MeetingProvider(Protocol):
    """Interface que todo provedor implementa.

    ``Protocol`` e não classe base: os provedores não compartilham
    comportamento, apenas forma. Herança aqui só criaria um lugar para lógica
    do Google vazar para o upload manual.
    """

    name: str

    def capabilities(self, db: Any, company_id: int) -> ProviderCapabilities:
        """O que dá para fazer nesta empresa, agora."""
        ...

    def discover_meetings(
        self,
        db: Any,
        company_id: int,
        *,
        since: datetime,
        until: datetime,
    ) -> List[ProviderMeeting]:
        """Reuniões da janela. Deve ser seguro chamar repetidamente."""
        ...

    def fetch_transcript(
        self,
        db: Any,
        company_id: int,
        meeting: ProviderMeeting,
    ) -> Optional[ProviderTranscript]:
        """Transcrição, se já estiver disponível. ``None`` quando ainda não."""
        ...
