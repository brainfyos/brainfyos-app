"""Domínio de reuniões.

Camadas separadas de propósito:

``Meeting``            o fato: houve (ou haverá) uma conversa.
``MeetingTranscript``  a fonte importada do provedor. Não é reescrita por análise.
``MeetingAnalysis``    o que a IA entendeu. Derivado e versionado.
``SalesMemory``        síntese comercial do lead, reconstruível a partir das fontes.
``CrmUpdateSuggestion`` o que a IA propõe mudar no CRM. Ninguém aplica sozinho.

A separação existe porque cada camada tem tempo de vida e confiabilidade
diferentes. Misturá-las tornaria impossível reprocessar uma análise sem
arriscar a fonte, ou contestar uma conclusão sem perder o que a gerou.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import relationship

from backend.db import Base

JsonList = JSONB().with_variant(JSON(), "sqlite")

# --- Providers ---
PROVIDER_GOOGLE_MEET = "google_meet"
PROVIDER_MICROSOFT_TEAMS = "microsoft_teams"
PROVIDER_MANUAL_UPLOAD = "manual_upload"

# --- Estados ---
MEETING_STATUSES = ("scheduled", "in_progress", "completed", "canceled", "unknown")
TRANSCRIPT_STATUSES = ("pending", "unavailable", "importing", "imported", "failed")
ANALYSIS_STATUSES = ("pending", "queued", "running", "completed", "failed", "skipped")
RESOLUTION_MATCHED = "matched"
RESOLUTION_AMBIGUOUS = "ambiguous"
RESOLUTION_UNMATCHED = "unmatched"
RESOLUTION_MANUAL = "manual"

SUGGESTION_PENDING = "pending"
SUGGESTION_ACCEPTED = "accepted"
SUGGESTION_REJECTED = "rejected"
SUGGESTION_APPLIED = "applied"
SUGGESTION_FAILED = "failed"

# Tipos que a IA pode propor. Fechada de propósito: fechamento de negócio
# (won/lost) não está aqui, e o CHECK no banco recusa qualquer outro valor.
SUGGESTION_TYPES = (
    "move_stage",
    "update_deal_value",
    "create_task",
    "add_note",
    "add_tag",
    "register_objection",
    "register_next_step",
)


def _json_list(name: str) -> Column:
    return Column(name, JsonList, nullable=False, server_default="[]", default=list)


def _json_object(name: str) -> Column:
    return Column(name, JsonList, nullable=False, server_default="{}", default=dict)


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    customer_id = Column(BigInteger, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id", ondelete="SET NULL"), nullable=True)
    pipeline_stage_id = Column(Integer, ForeignKey("pipeline_stages.id", ondelete="SET NULL"), nullable=True)

    calendar_event_id = Column(String(255), nullable=True)
    provider = Column(String(40), nullable=False)
    external_meeting_id = Column(String(255), nullable=True)
    external_conference_id = Column(String(255), nullable=True)

    title = Column(String(500), nullable=True)
    meeting_type = Column(String(40), nullable=True)
    source = Column(String(40), nullable=False, server_default="calendar", default="calendar")
    status = Column(String(20), nullable=False, server_default="scheduled", default="scheduled")

    scheduled_start_at = Column(TIMESTAMP(timezone=True), nullable=True)
    scheduled_end_at = Column(TIMESTAMP(timezone=True), nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    ended_at = Column(TIMESTAMP(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    meeting_url = Column(Text, nullable=True)

    transcript_status = Column(String(20), nullable=False, server_default="pending", default="pending")
    analysis_status = Column(String(20), nullable=False, server_default="pending", default="pending")
    sync_status = Column(String(20), nullable=False, server_default="pending", default="pending")
    resolution_status = Column(String(20), nullable=False, server_default="unmatched", default="unmatched")
    resolution_candidates = _json_list("resolution_candidates")

    last_synced_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    participants = relationship(
        "MeetingParticipant", back_populates="meeting", cascade="all, delete-orphan"
    )
    transcripts = relationship(
        "MeetingTranscript", back_populates="meeting", cascade="all, delete-orphan"
    )
    analyses = relationship(
        "MeetingAnalysis", back_populates="meeting", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'in_progress', 'completed', 'canceled', 'unknown')",
            name="chk_meeting_status",
        ),
        CheckConstraint(
            "transcript_status IN ('pending', 'unavailable', 'importing', 'imported', 'failed')",
            name="chk_meeting_transcript_status",
        ),
        CheckConstraint(
            "analysis_status IN ('pending', 'queued', 'running', 'completed', 'failed', 'skipped')",
            name="chk_meeting_analysis_status",
        ),
        CheckConstraint(
            "sync_status IN ('pending', 'synced', 'failed')",
            name="chk_meeting_sync_status",
        ),
        CheckConstraint(
            "resolution_status IN ('matched', 'ambiguous', 'unmatched', 'manual')",
            name="chk_meeting_resolution_status",
        ),
        Index("idx_meetings_company", "company_id"),
        Index("idx_meetings_company_lead", "company_id", "lead_id"),
        Index("idx_meetings_company_start", "company_id", "scheduled_start_at"),
        Index("idx_meetings_resolution", "company_id", "resolution_status"),
    )


class MeetingParticipant(Base):
    __tablename__ = "meeting_participants"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    meeting_id = Column(BigInteger, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    contact_id = Column(BigInteger, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    external_participant_id = Column(String(255), nullable=True)

    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=True)
    participant_type = Column(String(20), nullable=False, server_default="unknown", default="unknown")
    role = Column(String(40), nullable=True)
    attendance_status = Column(String(20), nullable=True)
    joined_at = Column(TIMESTAMP(timezone=True), nullable=True)
    left_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    meeting = relationship("Meeting", back_populates="participants")

    __table_args__ = (
        CheckConstraint(
            "participant_type IN ('internal', 'external', 'unknown')",
            name="chk_meeting_participant_type",
        ),
        Index("idx_meeting_participants_meeting", "meeting_id"),
        Index("idx_meeting_participants_company", "company_id"),
    )


class MeetingTranscript(Base):
    """A transcrição como o provedor entregou.

    Nunca é sobrescrita por análise. Reprocessar uma análise não pode custar a
    fonte — é ela que permite auditar qualquer conclusão depois.
    """

    __tablename__ = "meeting_transcripts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    meeting_id = Column(BigInteger, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(40), nullable=False)
    external_transcript_id = Column(String(255), nullable=True)
    language = Column(String(20), nullable=True)
    text = Column(Text, nullable=False)
    segments = _json_list("segments")
    speaker_map = _json_object("speaker_map")
    word_count = Column(Integer, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, server_default="imported", default="imported")
    provider_metadata = _json_object("provider_metadata")
    source_available_at = Column(TIMESTAMP(timezone=True), nullable=True)
    imported_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    meeting = relationship("Meeting", back_populates="transcripts")

    __table_args__ = (
        CheckConstraint(
            "status IN ('imported', 'partial', 'failed')",
            name="chk_meeting_transcript_row_status",
        ),
        Index("idx_meeting_transcripts_meeting", "meeting_id"),
        Index("idx_meeting_transcripts_company", "company_id"),
    )


class MeetingAnalysis(Base):
    """O que a IA entendeu da reunião. Descreve; não altera nada."""

    __tablename__ = "meeting_analyses"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    meeting_id = Column(BigInteger, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    transcript_id = Column(BigInteger, ForeignKey("meeting_transcripts.id", ondelete="SET NULL"), nullable=True)

    summary = Column(Text, nullable=True)
    meeting_purpose = Column(Text, nullable=True)
    customer_context = Column(Text, nullable=True)
    main_problem = Column(Text, nullable=True)
    budget_context = Column(Text, nullable=True)
    budget_amount = Column(Numeric(14, 2), nullable=True)
    budget_confidence = Column(String(10), nullable=True)
    urgency = Column(String(10), nullable=True)
    timeline = Column(Text, nullable=True)
    sentiment = Column(String(10), nullable=True)
    suggested_probability = Column(Integer, nullable=True)
    probability_reason = Column(Text, nullable=True)
    suggested_next_step_date = Column(Date, nullable=True)

    pain_points = _json_list("pain_points")
    needs = _json_list("needs")
    desired_outcomes = _json_list("desired_outcomes")
    decision_makers = _json_list("decision_makers")
    influencers = _json_list("influencers")
    competitors = _json_list("competitors")
    objections = _json_list("objections")
    questions = _json_list("questions")
    unanswered_questions = _json_list("unanswered_questions")
    products_discussed = _json_list("products_discussed")
    offers_discussed = _json_list("offers_discussed")
    prices_mentioned = _json_list("prices_mentioned")
    commitments_company = _json_list("commitments_company")
    commitments_customer = _json_list("commitments_customer")
    next_steps = _json_list("next_steps")
    risks = _json_list("risks")
    positive_signals = _json_list("positive_signals")
    negative_signals = _json_list("negative_signals")
    evidence_snippets = _json_list("evidence_snippets")

    provider = Column(String(40), nullable=True)
    model = Column(String(120), nullable=True)
    prompt_version = Column(String(20), nullable=True)
    analysis_version = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    meeting = relationship("Meeting", back_populates="analyses")

    __table_args__ = (
        CheckConstraint(
            "budget_confidence IS NULL OR budget_confidence IN ('low', 'medium', 'high')",
            name="chk_meeting_analysis_budget_confidence",
        ),
        CheckConstraint(
            "urgency IS NULL OR urgency IN ('low', 'medium', 'high')",
            name="chk_meeting_analysis_urgency",
        ),
        CheckConstraint(
            "sentiment IS NULL OR sentiment IN ('positive', 'neutral', 'negative', 'mixed')",
            name="chk_meeting_analysis_sentiment",
        ),
        CheckConstraint(
            "suggested_probability IS NULL OR "
            "(suggested_probability >= 0 AND suggested_probability <= 100)",
            name="chk_meeting_analysis_probability",
        ),
        Index("idx_meeting_analyses_meeting", "meeting_id"),
        Index("idx_meeting_analyses_company", "company_id"),
        Index("uq_meeting_analysis_version", "meeting_id", "analysis_version", unique=True),
    )


class SalesMemory(Base):
    """Visão comercial consolidada de um lead.

    Derivada, não canônica: se divergir de mensagens, reuniões ou CRM, a fonte
    ganha. ``source_refs`` guarda de onde cada pedaço veio.
    """

    __tablename__ = "sales_memories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)

    current_summary = Column(Text, nullable=True)
    business_context = Column(Text, nullable=True)
    business_problem = Column(Text, nullable=True)
    decision_process = Column(Text, nullable=True)
    budget_context = Column(Text, nullable=True)
    timeline = Column(Text, nullable=True)
    next_best_action = Column(Text, nullable=True)
    confidence = Column(String(10), nullable=True)

    desired_outcomes = _json_list("desired_outcomes")
    stakeholders = _json_list("stakeholders")
    objections = _json_list("objections")
    competitors = _json_list("competitors")
    commitments_company = _json_list("commitments_company")
    commitments_customer = _json_list("commitments_customer")
    risks = _json_list("risks")
    buying_signals = _json_list("buying_signals")
    negative_signals = _json_list("negative_signals")
    open_questions = _json_list("open_questions")
    source_refs = _json_list("source_refs")

    last_rebuilt_at = Column(TIMESTAMP(timezone=True), nullable=True)
    provider = Column(String(40), nullable=True)
    model = Column(String(120), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "lead_id", name="uq_sales_memory_company_lead"),
        CheckConstraint(
            "confidence IS NULL OR confidence IN ('low', 'medium', 'high')",
            name="chk_sales_memory_confidence",
        ),
        Index("idx_sales_memories_company", "company_id"),
    )


class CrmUpdateSuggestion(Base):
    """Proposta de alteração no CRM. Só vira mudança depois de aceita."""

    __tablename__ = "crm_update_suggestions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    meeting_id = Column(BigInteger, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)

    field = Column(String(60), nullable=False)
    suggestion_type = Column(String(40), nullable=False)
    current_value = Column(Text, nullable=True)
    suggested_value = Column(Text, nullable=True)
    payload = _json_object("payload")
    reason = Column(Text, nullable=True)
    confidence = Column(String(10), nullable=True)
    source_refs = _json_list("source_refs")
    status = Column(String(20), nullable=False, server_default="pending", default="pending")
    # Chave estável do conteúdo: impede que um retry gere a mesma sugestão.
    dedupe_key = Column(String(120), nullable=False)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    reviewed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    applied_at = Column(TIMESTAMP(timezone=True), nullable=True)
    apply_error = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'applied', 'failed')",
            name="chk_crm_suggestion_status",
        ),
        CheckConstraint(
            "suggestion_type IN ('move_stage', 'update_deal_value', 'create_task', "
            "'add_note', 'add_tag', 'register_objection', 'register_next_step')",
            name="chk_crm_suggestion_type",
        ),
        UniqueConstraint("company_id", "lead_id", "dedupe_key", name="uq_crm_suggestion_dedupe"),
        Index("idx_crm_suggestions_company_status", "company_id", "status"),
        Index("idx_crm_suggestions_lead", "lead_id"),
        Index("idx_crm_suggestions_meeting", "meeting_id"),
    )
