"""Ingestão automática de reuniões.

Ponto único por onde toda reunião entra no sistema, venha da agenda ou de um
upload. Responsável por descobrir, criar/atualizar, resolver participantes,
associar ao lead e importar a transcrição — sempre de forma idempotente.

Idempotência não é detalhe aqui: a sincronização roda de novo a cada ciclo e
tarefas Celery podem repetir. Ela é garantida em dois níveis, e o segundo é
o que realmente importa:

1. Consulta por chave externa antes de inserir.
2. Índices únicos parciais no banco (`uq_meetings_company_calendar_event`,
   `uq_meeting_transcript_external`). Dois workers concorrentes passam pela
   verificação (1) ao mesmo tempo; só o banco decide quem grava.

Segurança: `company_id` é sempre explícito. Nenhum id externo é aceito como
autorização — um `calendar_event_id` conhecido só resolve dentro da empresa
que fez a chamada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models import Company, Contact, Customer, Lead
from backend.models.meeting_models import (
    Meeting,
    MeetingParticipant,
    MeetingTranscript,
    PROVIDER_MANUAL_UPLOAD,
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_MANUAL,
    RESOLUTION_MATCHED,
    RESOLUTION_UNMATCHED,
)
from backend.services.meetings.entity_resolver import (
    MeetingEntityResolver,
    normalize_email,
    normalize_phone,
)
from backend.services.meetings.providers import (
    MeetingProviderError,
    MeetingProviderNotConfiguredError,
    ProviderMeeting,
    ProviderTranscript,
    discoverable_providers,
    get_provider,
)

logger = logging.getLogger(__name__)

# Janela padrão da sincronização. Cobre reuniões que acabaram de terminar e
# as próximas, sem varrer histórico a cada ciclo.
SYNC_LOOKBACK_HOURS = 48
SYNC_LOOKAHEAD_HOURS = 24
# Só faz sentido buscar transcrição depois que a reunião acabou -- a margem
# absorve atraso de relógio e término após o horário previsto.
TRANSCRIPT_GRACE_MINUTES = 5


class MeetingScopeError(PermissionError):
    """Tentativa de ligar entidades de empresas diferentes."""


@dataclass
class IngestionOutcome:
    meeting: Meeting
    created: bool
    transcript_imported: bool = False


class MeetingIngestionService:
    def __init__(self, db: Session):
        self._db = db
        self._resolver = MeetingEntityResolver(db)

    # ------------------------------------------------------------------
    # Descoberta
    # ------------------------------------------------------------------

    def sync_company(
        self,
        company_id: int,
        *,
        provider_name: Optional[str] = None,
        lookback_hours: int = SYNC_LOOKBACK_HOURS,
        lookahead_hours: int = SYNC_LOOKAHEAD_HOURS,
    ) -> Dict[str, Any]:
        """Varre os provedores e ingere o que encontrar.

        Nunca levanta por provedor não configurado: uma empresa sem agenda
        conectada é o caso normal, não um erro operacional.
        """
        company_id = int(company_id)
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=lookback_hours)
        until = now + timedelta(hours=lookahead_hours)

        providers = (
            [get_provider(provider_name)] if provider_name else discoverable_providers()
        )

        summary: Dict[str, Any] = {
            "company_id": company_id,
            "discovered": 0,
            "created": 0,
            "updated": 0,
            "transcripts_imported": 0,
            "skipped_providers": [],
            "errors": [],
        }

        for provider in providers:
            try:
                capabilities = provider.capabilities(self._db, company_id)
                if not capabilities.can_discover_meetings:
                    summary["skipped_providers"].append(
                        {"provider": provider.name, "reason": capabilities.unavailable_reason}
                    )
                    continue

                found = provider.discover_meetings(
                    self._db, company_id, since=since, until=until
                )
            except MeetingProviderNotConfiguredError as exc:
                summary["skipped_providers"].append(
                    {"provider": provider.name, "reason": str(exc)}
                )
                continue
            except MeetingProviderError as exc:
                summary["errors"].append({"provider": provider.name, "error": str(exc)})
                continue

            summary["discovered"] += len(found)

            for provider_meeting in found:
                try:
                    outcome = self.upsert_meeting(
                        company_id, provider.name, provider_meeting
                    )
                except Exception as exc:
                    self._db.rollback()
                    logger.warning(
                        "Falha ao ingerir reunião: company_id=%s provider=%s error_type=%s",
                        company_id,
                        provider.name,
                        exc.__class__.__name__,
                    )
                    summary["errors"].append(
                        {"provider": provider.name, "error": exc.__class__.__name__}
                    )
                    continue

                summary["created" if outcome.created else "updated"] += 1

                if self._should_try_transcript(outcome.meeting, capabilities):
                    if self.import_transcript(outcome.meeting.id, company_id, provider_meeting):
                        summary["transcripts_imported"] += 1

        return summary

    @staticmethod
    def _should_try_transcript(meeting: Meeting, capabilities: Any) -> bool:
        if not capabilities.can_import_transcripts:
            return False
        if meeting.transcript_status in {"imported", "importing", "failed"}:
            return False
        reference = meeting.ended_at or meeting.scheduled_end_at
        if reference is None:
            return False
        # Buscar antes do fim é chamada garantida a vazio: o Google só publica
        # o artefato depois que a conferência encerra.
        return reference + timedelta(minutes=TRANSCRIPT_GRACE_MINUTES) <= datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Criação / atualização
    # ------------------------------------------------------------------

    def upsert_meeting(
        self,
        company_id: int,
        provider_name: str,
        provider_meeting: ProviderMeeting,
    ) -> IngestionOutcome:
        company_id = int(company_id)
        self._ensure_company(company_id)

        existing = self._find_existing(company_id, provider_name, provider_meeting)
        created = existing is None

        meeting = existing or Meeting(
            company_id=company_id,
            provider=provider_name,
            source="calendar" if provider_name != PROVIDER_MANUAL_UPLOAD else "manual",
        )

        meeting.calendar_event_id = provider_meeting.calendar_event_id or meeting.calendar_event_id
        meeting.external_meeting_id = provider_meeting.external_meeting_id or meeting.external_meeting_id
        meeting.external_conference_id = (
            provider_meeting.external_conference_id or meeting.external_conference_id
        )
        meeting.title = provider_meeting.title or meeting.title
        meeting.meeting_url = provider_meeting.meeting_url or meeting.meeting_url
        meeting.scheduled_start_at = provider_meeting.scheduled_start_at or meeting.scheduled_start_at
        meeting.scheduled_end_at = provider_meeting.scheduled_end_at or meeting.scheduled_end_at
        meeting.started_at = provider_meeting.started_at or meeting.started_at
        meeting.ended_at = provider_meeting.ended_at or meeting.ended_at
        meeting.status = provider_meeting.status or meeting.status
        meeting.sync_status = "synced"
        meeting.last_synced_at = datetime.now(timezone.utc)

        if meeting.started_at and meeting.ended_at:
            meeting.duration_seconds = int(
                (meeting.ended_at - meeting.started_at).total_seconds()
            )
        elif meeting.scheduled_start_at and meeting.scheduled_end_at:
            meeting.duration_seconds = int(
                (meeting.scheduled_end_at - meeting.scheduled_start_at).total_seconds()
            )

        if created:
            self._db.add(meeting)

        try:
            self._db.flush()
        except IntegrityError:
            # Outro worker criou a mesma reunião entre a busca e o insert.
            # O índice único resolveu o empate; recarregamos o vencedor.
            self._db.rollback()
            existing = self._find_existing(company_id, provider_name, provider_meeting)
            if existing is None:
                raise
            return IngestionOutcome(meeting=existing, created=False)

        self._sync_participants(meeting, provider_meeting)

        # Reunião já associada por uma pessoa nunca é re-resolvida: a decisão
        # humana vale mais do que qualquer heurística rodando de novo.
        if meeting.resolution_status != RESOLUTION_MANUAL:
            self._apply_resolution(meeting, provider_meeting)

        self._db.commit()
        return IngestionOutcome(meeting=meeting, created=created)

    def _find_existing(
        self,
        company_id: int,
        provider_name: str,
        provider_meeting: ProviderMeeting,
    ) -> Optional[Meeting]:
        query = self._db.query(Meeting).filter(
            Meeting.company_id == company_id,
            Meeting.provider == provider_name,
        )
        if provider_meeting.calendar_event_id:
            found = query.filter(
                Meeting.calendar_event_id == provider_meeting.calendar_event_id
            ).first()
            if found is not None:
                return found
        if provider_meeting.external_meeting_id:
            return query.filter(
                Meeting.external_meeting_id == provider_meeting.external_meeting_id
            ).first()
        return None

    def _sync_participants(self, meeting: Meeting, provider_meeting: ProviderMeeting) -> None:
        """Atualiza participantes sem duplicar em re-sincronizações."""
        existing = {
            (participant.external_participant_id, normalize_email(participant.email)): participant
            for participant in meeting.participants
        }

        for incoming in provider_meeting.participants:
            key = (incoming.external_participant_id, normalize_email(incoming.email))
            participant = existing.get(key)
            if participant is None:
                participant = MeetingParticipant(
                    meeting_id=meeting.id,
                    company_id=meeting.company_id,
                    external_participant_id=incoming.external_participant_id,
                )
                self._db.add(participant)

            participant.name = incoming.name or participant.name
            participant.email = incoming.email or participant.email
            participant.attendance_status = incoming.attendance_status or participant.attendance_status
            participant.joined_at = incoming.joined_at or participant.joined_at
            participant.left_at = incoming.left_at or participant.left_at
            participant.role = "organizer" if incoming.is_organizer else participant.role
            participant.participant_type = self._classify_participant(meeting.company_id, incoming.email)

        self._db.flush()

    def _classify_participant(self, company_id: int, email: Optional[str]) -> str:
        """Interno quando o e-mail é de um usuário da própria empresa."""
        normalized = normalize_email(email)
        if not normalized:
            return "unknown"

        from backend.models import User

        is_internal = (
            self._db.query(User.id)
            .filter(User.company_id == company_id, User.email == normalized)
            .first()
            is not None
        )
        return "internal" if is_internal else "external"

    def _apply_resolution(self, meeting: Meeting, provider_meeting: ProviderMeeting) -> None:
        result = self._resolver.resolve(
            meeting.company_id,
            participant_emails=[p.email for p in provider_meeting.participants if p.email],
            participant_phones=[p.phone for p in meeting.participants if p.phone],
            organizer_email=provider_meeting.organizer_email,
            calendar_event_id=meeting.calendar_event_id,
        )

        meeting.resolution_status = result.status
        meeting.resolution_candidates = result.as_payload()

        chosen = result.chosen
        if chosen is None:
            return

        meeting.lead_id = chosen.lead_id
        meeting.contact_id = chosen.contact_id
        meeting.customer_id = chosen.customer_id
        self._sync_pipeline_position(meeting)

    def _sync_pipeline_position(self, meeting: Meeting) -> None:
        if not meeting.lead_id:
            return
        lead = (
            self._db.query(Lead)
            .filter(Lead.id == meeting.lead_id, Lead.company_id == meeting.company_id)
            .first()
        )
        if lead is not None:
            meeting.pipeline_id = lead.pipeline_id
            meeting.pipeline_stage_id = lead.current_stage_id

    # ------------------------------------------------------------------
    # Associação manual
    # ------------------------------------------------------------------

    def associate(
        self,
        company_id: int,
        meeting_id: int,
        *,
        lead_id: Optional[int] = None,
        contact_id: Optional[int] = None,
        customer_id: Optional[int] = None,
    ) -> Meeting:
        """Associação feita por uma pessoa. Valida escopo em cada entidade.

        A FK garante que o id existe; ela não garante que ele é desta empresa.
        Sem esta validação, trocar um número no corpo da requisição ligaria a
        reunião ao lead de outro workspace.
        """
        company_id = int(company_id)
        meeting = self.get_meeting(company_id, meeting_id)

        if lead_id is not None:
            self._require_same_company(Lead, lead_id, company_id, "Lead")
        if contact_id is not None:
            self._require_same_company(Contact, contact_id, company_id, "Contato")
        if customer_id is not None:
            self._require_same_company(Customer, customer_id, company_id, "Cliente")

        meeting.lead_id = lead_id
        meeting.contact_id = contact_id
        meeting.customer_id = customer_id
        meeting.resolution_status = RESOLUTION_MANUAL
        self._sync_pipeline_position(meeting)
        self._db.commit()
        return meeting

    def _require_same_company(self, model: Any, entity_id: int, company_id: int, label: str) -> None:
        found = (
            self._db.query(model)
            .filter(model.id == int(entity_id), model.company_id == company_id)
            .first()
        )
        if found is None:
            # Mesma mensagem para inexistente e de outra empresa: distinguir
            # confirmaria a existência de um registro alheio.
            raise MeetingScopeError(f"{label} não encontrado nesta empresa")

    def get_meeting(self, company_id: int, meeting_id: int) -> Meeting:
        meeting = (
            self._db.query(Meeting)
            .filter(Meeting.id == int(meeting_id), Meeting.company_id == int(company_id))
            .first()
        )
        if meeting is None:
            raise MeetingScopeError("Reunião não encontrada")
        return meeting

    # ------------------------------------------------------------------
    # Transcrição
    # ------------------------------------------------------------------

    def import_transcript(
        self,
        meeting_id: int,
        company_id: int,
        provider_meeting: Optional[ProviderMeeting] = None,
    ) -> bool:
        """Importa a transcrição se o provedor já a disponibilizou.

        ``False`` significa "ainda não há" — o caso normal logo depois da
        reunião —, não falha.
        """
        company_id = int(company_id)
        meeting = self.get_meeting(company_id, meeting_id)

        if meeting.transcript_status == "imported":
            return False

        provider = get_provider(meeting.provider)
        reference = provider_meeting or _meeting_to_provider_dto(meeting)

        meeting.transcript_status = "importing"
        self._db.commit()

        try:
            transcript = provider.fetch_transcript(self._db, company_id, reference)
        except MeetingProviderNotConfiguredError as exc:
            meeting.transcript_status = "unavailable"
            meeting.last_error = str(exc)
            self._db.commit()
            return False
        except Exception as exc:
            meeting.transcript_status = "failed"
            # Só o tipo: a exceção do provedor pode carregar trecho de conversa.
            meeting.last_error = exc.__class__.__name__
            self._db.commit()
            logger.warning(
                "Falha ao importar transcrição: meeting_id=%s error_type=%s",
                meeting_id,
                exc.__class__.__name__,
            )
            return False

        if transcript is None:
            meeting.transcript_status = "pending"
            self._db.commit()
            return False

        stored = self._store_transcript(meeting, transcript)
        return stored is not None

    def _store_transcript(
        self, meeting: Meeting, transcript: ProviderTranscript
    ) -> Optional[MeetingTranscript]:
        if transcript.external_transcript_id:
            duplicate = (
                self._db.query(MeetingTranscript)
                .filter(
                    MeetingTranscript.company_id == meeting.company_id,
                    MeetingTranscript.provider == meeting.provider,
                    MeetingTranscript.external_transcript_id == transcript.external_transcript_id,
                )
                .first()
            )
            if duplicate is not None:
                meeting.transcript_status = "imported"
                self._db.commit()
                return duplicate

        row = MeetingTranscript(
            company_id=meeting.company_id,
            meeting_id=meeting.id,
            provider=meeting.provider,
            external_transcript_id=transcript.external_transcript_id,
            language=transcript.language,
            text=transcript.text,
            segments=[segment.as_dict() for segment in transcript.segments],
            speaker_map=self._build_speaker_map(meeting, transcript),
            word_count=len(transcript.text.split()),
            duration_seconds=transcript.duration_seconds or meeting.duration_seconds,
            status="imported",
            provider_metadata=transcript.metadata or {},
            source_available_at=transcript.source_available_at,
            imported_at=datetime.now(timezone.utc),
        )
        self._db.add(row)

        meeting.transcript_status = "imported"
        meeting.analysis_status = "queued"

        try:
            self._db.commit()
        except IntegrityError:
            # Retry concorrente: o índice único cortou a segunda gravação.
            self._db.rollback()
            meeting.transcript_status = "imported"
            self._db.commit()
            return None

        return row

    @staticmethod
    def _build_speaker_map(meeting: Meeting, transcript: ProviderTranscript) -> Dict[str, Any]:
        """Liga id de falante do provedor ao participante interno.

        Só mapeia o que o provedor identificou. Um falante sem correspondência
        continua anônimo em vez de ser atribuído por aproximação.
        """
        by_external = {
            participant.external_participant_id: participant
            for participant in meeting.participants
            if participant.external_participant_id
        }
        speaker_map: Dict[str, Any] = {}
        for segment in transcript.segments:
            external = segment.speaker_external_id
            if not external or external in speaker_map:
                continue
            participant = by_external.get(external)
            speaker_map[external] = {
                "participant_id": participant.id if participant else None,
                "name": participant.name if participant else None,
                "type": participant.participant_type if participant else "unknown",
            }
        return speaker_map

    # ------------------------------------------------------------------

    def _ensure_company(self, company_id: int) -> None:
        exists = self._db.query(Company.id).filter(Company.id == company_id).first()
        if exists is None:
            raise MeetingScopeError("Empresa não encontrada")


def _meeting_to_provider_dto(meeting: Meeting) -> ProviderMeeting:
    return ProviderMeeting(
        external_meeting_id=meeting.external_meeting_id or str(meeting.id),
        calendar_event_id=meeting.calendar_event_id,
        external_conference_id=meeting.external_conference_id,
        title=meeting.title,
        meeting_url=meeting.meeting_url,
        scheduled_start_at=meeting.scheduled_start_at,
        scheduled_end_at=meeting.scheduled_end_at,
        started_at=meeting.started_at,
        ended_at=meeting.ended_at,
        status=meeting.status,
    )
