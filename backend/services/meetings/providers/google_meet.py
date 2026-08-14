"""Provedor Google Meet.

Duas APIs distintas do Google, e a confusão entre elas é a origem de metade
dos mal-entendidos sobre "transcrição do Meet":

**Google Calendar API** — já integrada no projeto. Diz que um evento existe e
que ele tem uma conferência do Meet (``conferenceData`` / ``hangoutLink``).
Não sabe nada sobre o que foi falado.

**Google Meet REST API** (``meet.googleapis.com``) — não integrada. É ela que
expõe ``conferenceRecords`` (o registro do que de fato aconteceu),
``participants`` e ``transcripts`` com ``transcripts.entries``.

Consequência prática: descobrir a reunião funciona com o que já existe;
importar a transcrição exige um scope adicional e reconsentimento do usuário.
``capabilities()`` reporta isso honestamente em vez de a tela mentir.

Limites do próprio Google, que nenhuma implementação contorna:

* A transcrição precisa estar ligada na reunião (o organizador ativa, ou a
  política do Workspace ativa). Sem isso não existe artefato nenhum.
* Só fica disponível **depois** que a conferência encerra. Não há stream.
* Requer edição elegível do Google Workspace.
* ``conferenceRecords`` são retidos por 30 dias.

Por isso a estratégia de descoberta é sincronização agendada moderada, e não
polling: o artefato aparece minutos após o fim da reunião e não muda depois.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models.meeting_models import PROVIDER_GOOGLE_MEET
from backend.services.meetings.providers.base import (
    MeetingProviderNotConfiguredError,
    ProviderCapabilities,
    ProviderMeeting,
    ProviderParticipant,
    ProviderTranscript,
    ProviderTranscriptSegment,
)

logger = logging.getLogger(__name__)

# Scope da Google Meet REST API. Não está na lista atual do projeto
# (`google_calendar_service.GOOGLE_OAUTH_SCOPES`), então importar transcrição
# exige reconsentimento do usuário.
MEET_READONLY_SCOPE = "https://www.googleapis.com/auth/meetings.space.readonly"
MEET_API_BASE = "https://meet.googleapis.com/v2"

# O Google retém conferenceRecords por 30 dias; procurar além disso é gastar
# chamada para receber lista vazia.
CONFERENCE_RECORD_RETENTION_DAYS = 30


class GoogleMeetProvider:
    """Descobre reuniões pela agenda e importa transcrições pela Meet API."""

    name = PROVIDER_GOOGLE_MEET

    # ------------------------------------------------------------------
    # Credenciais
    # ------------------------------------------------------------------

    @staticmethod
    def _integration(db: Session, company_id: int):
        """Integração de calendário desta empresa -- sempre escopada."""
        from backend.models import CalendarIntegration

        return (
            db.query(CalendarIntegration)
            .filter(
                CalendarIntegration.company_id == int(company_id),
                CalendarIntegration.provider == "google",
            )
            .first()
        )

    @staticmethod
    def _granted_scopes(integration: Any) -> List[str]:
        raw = getattr(integration, "google_oauth_scopes", None) or ""
        # O Google devolve escopos separados por espaço; toleramos vírgula.
        return [scope for scope in raw.replace(",", " ").split() if scope]

    def _credentials(self, db: Session, company_id: int):
        """Credenciais OAuth desta empresa, já renovadas se preciso."""
        integration = self._integration(db, company_id)
        if integration is None or not integration.google_oauth_token:
            raise MeetingProviderNotConfiguredError(
                "Google Agenda não está conectado nesta empresa"
            )

        try:
            from google.oauth2.credentials import Credentials
        except ImportError as exc:  # pragma: no cover
            raise MeetingProviderNotConfiguredError(
                "Bibliotecas do Google não estão instaladas"
            ) from exc

        token = integration.google_oauth_token
        if not isinstance(token, dict):
            raise MeetingProviderNotConfiguredError("Token do Google em formato inesperado")

        return Credentials(
            token=token.get("token") or token.get("access_token"),
            refresh_token=token.get("refresh_token"),
            token_uri=token.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token.get("client_id"),
            client_secret=token.get("client_secret"),
            scopes=self._granted_scopes(integration) or None,
        )

    # ------------------------------------------------------------------
    # Capacidades
    # ------------------------------------------------------------------

    def capabilities(self, db: Session, company_id: int) -> ProviderCapabilities:
        integration = self._integration(db, company_id)

        if integration is None or not integration.google_oauth_token:
            return ProviderCapabilities(
                provider=self.name,
                label="Google Meet",
                unavailable_reason="Google Agenda não conectado",
                missing_scopes=[MEET_READONLY_SCOPE],
            )

        scopes = self._granted_scopes(integration)
        has_meet_scope = MEET_READONLY_SCOPE in scopes

        return ProviderCapabilities(
            provider=self.name,
            label="Google Meet",
            can_discover_meetings=True,
            can_import_transcripts=has_meet_scope,
            can_identify_participants=has_meet_scope,
            supports_realtime=False,
            unavailable_reason=(
                None
                if has_meet_scope
                else (
                    "Agenda conectada, mas a permissão de leitura do Google Meet ainda não "
                    "foi concedida. Sem ela o BrainfyOS enxerga as reuniões mas não consegue "
                    "importar transcrições."
                )
            ),
            missing_scopes=[] if has_meet_scope else [MEET_READONLY_SCOPE],
        )

    # ------------------------------------------------------------------
    # Descoberta
    # ------------------------------------------------------------------

    def discover_meetings(
        self,
        db: Session,
        company_id: int,
        *,
        since: datetime,
        until: datetime,
    ) -> List[ProviderMeeting]:
        """Eventos da agenda que têm conferência do Meet.

        Só eventos com Meet entram: um compromisso sem conferência não é uma
        reunião que se possa transcrever, e criar ``Meeting`` para ele encheria
        a tela de reuniões não associadas que nunca terão conteúdo.
        """
        credentials = self._credentials(db, company_id)
        integration = self._integration(db, company_id)
        calendar_id = getattr(integration, "google_calendar_id", None) or "primary"

        try:
            from googleapiclient.discovery import build

            service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
            response = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=since.astimezone(timezone.utc).isoformat(),
                    timeMax=until.astimezone(timezone.utc).isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                )
                .execute()
            )
        except Exception as exc:
            logger.warning(
                "Falha ao listar eventos do Google: company_id=%s error_type=%s",
                company_id,
                exc.__class__.__name__,
            )
            raise MeetingProviderNotConfiguredError(
                "Não foi possível consultar a agenda do Google"
            ) from None

        meetings: List[ProviderMeeting] = []
        for event in response.get("items", []):
            conference_id = _conference_id(event)
            if not conference_id:
                continue
            meetings.append(_event_to_provider_meeting(event, conference_id))
        return meetings

    # ------------------------------------------------------------------
    # Transcrição
    # ------------------------------------------------------------------

    def fetch_transcript(
        self,
        db: Session,
        company_id: int,
        meeting: ProviderMeeting,
    ) -> Optional[ProviderTranscript]:
        """Transcrição da conferência, quando o Google já a disponibilizou.

        Devolve ``None`` -- e não erro -- quando ainda não existe: "ainda não
        ficou pronta" é o caso normal logo após a reunião, não uma falha.
        """
        capabilities = self.capabilities(db, company_id)
        if not capabilities.can_import_transcripts:
            raise MeetingProviderNotConfiguredError(
                capabilities.unavailable_reason or "Permissão do Google Meet ausente"
            )

        if not meeting.external_conference_id:
            return None

        credentials = self._credentials(db, company_id)
        session = _authorized_session(credentials)

        record = self._find_conference_record(session, meeting)
        if record is None:
            return None

        transcripts = _get_json(
            session, f"{MEET_API_BASE}/{record}/transcripts"
        ).get("transcripts", [])
        ready = [item for item in transcripts if item.get("state") == "ENDED"]
        if not ready:
            return None

        transcript = ready[0]
        transcript_name = transcript.get("name")
        segments = self._fetch_entries(session, transcript_name)

        text = "\n".join(
            f"{segment.speaker}: {segment.text}" if segment.speaker else segment.text
            for segment in segments
        )

        return ProviderTranscript(
            external_transcript_id=transcript_name,
            text=text,
            segments=segments,
            language=None,
            source_available_at=_parse_time(transcript.get("endTime")),
            metadata={
                "conference_record": record,
                "transcript_state": transcript.get("state"),
                "drive_destination": transcript.get("docsDestination", {}).get("document"),
            },
        )

    def _find_conference_record(self, session: Any, meeting: ProviderMeeting) -> Optional[str]:
        """Localiza o conferenceRecord da reunião.

        O id do evento de agenda não serve aqui: o registro é indexado pelo
        *space*, que vem do código da sala no `meeting_url`.
        """
        space = meeting.external_conference_id
        if not space:
            return None

        cutoff = datetime.now(timezone.utc) - timedelta(days=CONFERENCE_RECORD_RETENTION_DAYS)
        payload = _get_json(
            session,
            f"{MEET_API_BASE}/conferenceRecords",
            params={
                "filter": f'space.meeting_code="{space}" start_time>="{cutoff.isoformat()}"',
                "pageSize": 5,
            },
        )
        records = payload.get("conferenceRecords", [])
        if not records:
            return None
        # O mais recente primeiro: uma sala recorrente acumula registros e o
        # que interessa é a ocorrência que acabou.
        records.sort(key=lambda item: item.get("startTime") or "", reverse=True)
        return records[0].get("name")

    @staticmethod
    def _fetch_entries(session: Any, transcript_name: str) -> List[ProviderTranscriptSegment]:
        segments: List[ProviderTranscriptSegment] = []
        page_token: Optional[str] = None

        while True:
            params: Dict[str, Any] = {"pageSize": 1000}
            if page_token:
                params["pageToken"] = page_token
            payload = _get_json(
                session, f"{MEET_API_BASE}/{transcript_name}/entries", params=params
            )
            for entry in payload.get("transcriptEntries", []):
                segments.append(
                    ProviderTranscriptSegment(
                        text=entry.get("text") or "",
                        # `participant` é o id do participante na conferência;
                        # a associação a um Contact acontece depois, e de forma
                        # conservadora.
                        speaker_external_id=entry.get("participant"),
                        speaker=entry.get("participant"),
                        start_time=_seconds_between(
                            payload.get("_base_time"), entry.get("startTime")
                        ),
                    )
                )
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        return segments

    def fetch_participants(
        self,
        db: Session,
        company_id: int,
        conference_record: str,
    ) -> List[ProviderParticipant]:
        credentials = self._credentials(db, company_id)
        session = _authorized_session(credentials)
        payload = _get_json(session, f"{MEET_API_BASE}/{conference_record}/participants")

        participants: List[ProviderParticipant] = []
        for item in payload.get("participants", []):
            signed_in = item.get("signedinUser") or {}
            anonymous = item.get("anonymousUser") or {}
            participants.append(
                ProviderParticipant(
                    external_participant_id=item.get("name"),
                    name=signed_in.get("displayName") or anonymous.get("displayName"),
                    # A Meet API não devolve e-mail do participante; resolver
                    # identidade fica a cargo do MeetingEntityResolver, com os
                    # convidados do evento de agenda.
                    email=None,
                    joined_at=_parse_time(item.get("earliestStartTime")),
                    left_at=_parse_time(item.get("latestEndTime")),
                )
            )
        return participants


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def _authorized_session(credentials: Any) -> Any:
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedSession(credentials)


def _get_json(session: Any, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = session.get(url, params=params or {}, timeout=30)
    if response.status_code == 404:
        return {}
    response.raise_for_status()
    return response.json() or {}


def _conference_id(event: Dict[str, Any]) -> Optional[str]:
    """Código da sala do Meet (ex.: ``abc-defg-hij``).

    É o que a Meet API usa para filtrar ``conferenceRecords`` — o id do evento
    de agenda não serve para isso.
    """
    conference = event.get("conferenceData") or {}
    if conference.get("conferenceId"):
        return conference["conferenceId"]

    link = event.get("hangoutLink") or ""
    for entry in conference.get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            link = entry["uri"]
            break

    if "meet.google.com/" in link:
        return link.rsplit("meet.google.com/", 1)[-1].split("?")[0].strip("/") or None
    return None


def _event_to_provider_meeting(event: Dict[str, Any], conference_id: str) -> ProviderMeeting:
    start = _parse_time((event.get("start") or {}).get("dateTime"))
    end = _parse_time((event.get("end") or {}).get("dateTime"))

    participants = [
        ProviderParticipant(
            name=attendee.get("displayName"),
            email=attendee.get("email"),
            attendance_status=attendee.get("responseStatus"),
            is_organizer=bool(attendee.get("organizer")),
        )
        for attendee in event.get("attendees") or []
    ]

    return ProviderMeeting(
        external_meeting_id=event.get("id") or conference_id,
        calendar_event_id=event.get("id"),
        external_conference_id=conference_id,
        title=event.get("summary"),
        meeting_url=event.get("hangoutLink"),
        scheduled_start_at=start,
        scheduled_end_at=end,
        # O horário previsto não é estado. Só marcamos 'completed' depois do
        # fim previsto; a fonte confiável (conferenceRecord) corrige depois.
        status=_status_from_schedule(event, end),
        organizer_email=(event.get("organizer") or {}).get("email"),
        participants=participants,
        raw={"etag": event.get("etag"), "status": event.get("status")},
    )


def _status_from_schedule(event: Dict[str, Any], end: Optional[datetime]) -> str:
    if (event.get("status") or "").lower() == "cancelled":
        return "canceled"
    if end is None:
        return "unknown"
    return "completed" if end < datetime.now(timezone.utc) else "scheduled"


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _seconds_between(base: Optional[str], value: Optional[str]) -> Optional[float]:
    start = _parse_time(base)
    point = _parse_time(value)
    if start is None or point is None:
        return None
    return max(0.0, (point - start).total_seconds())
