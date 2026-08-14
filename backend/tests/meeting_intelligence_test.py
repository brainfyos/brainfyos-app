"""Meeting Intelligence: isolamento, idempotência e fluxo integrado.

Contra banco real (SQLite em memória, padrão do projeto), sem mock para
isolamento. Duas empresas, dado igual nas duas, e cada asserção verifica que
nada da B aparece na A.

A IA é substituída por um duplo determinístico apenas onde o assunto é *o que
o sistema faz com a resposta* — nunca onde o assunto é escopo entre empresas.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/brainfyos-meetings-test.db")

import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import (
    Base,
    Company,
    Contact,
    ContactNote,
    Lead,
    Pipeline,
    PipelineStage,
)
from backend.models.meeting_models import (
    CrmUpdateSuggestion,
    Meeting,
    MeetingAnalysis,
    MeetingTranscript,
    PROVIDER_GOOGLE_MEET,
    SalesMemory,
)
from backend.services.meetings import analysis as analysis_module
from backend.services.meetings import crm_intelligence, sales_memory
from backend.services.meetings.crm_intelligence import (
    CrmSuggestionError,
    CrmSuggestionScopeError,
    accept_suggestion,
    generate_suggestions,
)
from backend.services.meetings.entity_resolver import MeetingEntityResolver
from backend.services.meetings.ingestion import MeetingIngestionService, MeetingScopeError
from backend.services.meetings.providers.base import (
    ProviderMeeting,
    ProviderParticipant,
    ProviderTranscript,
    ProviderTranscriptSegment,
)

COMPANY_A = 401
COMPANY_B = 402

NOW = datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        _seed(session)
        yield session
    finally:
        session.close()


def _seed(db):
    for company_id, suffix in ((COMPANY_A, "A"), (COMPANY_B, "B")):
        db.add(
            Company(
                id=company_id, name=f"Empresa {suffix}", cnpj=f"{company_id}".zfill(14),
                business_type_id=1, settings={},
            )
        )
    db.flush()

    for company_id, suffix, phone in (
        (COMPANY_A, "A", "5511900000001"),
        (COMPANY_B, "B", "5511900000002"),
    ):
        pipeline = Pipeline(company_id=company_id, name=f"Funil {suffix}", is_active=True)
        db.add(pipeline)
        db.flush()
        db.add(PipelineStage(pipeline_id=pipeline.id, name="Novo", order_index=0, order=0))
        db.add(Contact(client_id=1, company_id=company_id, phone=phone, name=f"Contato {suffix}"))
        db.flush()
        db.add(
            Lead(
                client_id=1, company_id=company_id, name=f"Lead {suffix}",
                phone=phone, pipeline_id=pipeline.id,
            )
        )
    db.commit()


def _lead(db, company_id):
    return db.query(Lead).filter(Lead.company_id == company_id).one()


def _provider_meeting(external_id="evt-1", email="cliente@exemplo.com", phone=None):
    return ProviderMeeting(
        external_meeting_id=external_id,
        calendar_event_id=external_id,
        external_conference_id="abc-defg-hij",
        title="Reunião comercial",
        meeting_url="https://meet.google.com/abc-defg-hij",
        scheduled_start_at=NOW - timedelta(hours=2),
        scheduled_end_at=NOW - timedelta(hours=1),
        status="completed",
        organizer_email="vendedor@empresa.com",
        participants=[
            ProviderParticipant(name="Cliente", email=email),
            ProviderParticipant(name="Vendedor", email="vendedor@empresa.com", is_organizer=True),
        ],
    )


def _transcript(text="Cliente falou sobre o problema."):
    return ProviderTranscript(
        external_transcript_id="conferenceRecords/1/transcripts/1",
        text=text,
        segments=[ProviderTranscriptSegment(text=text, speaker="p1", speaker_external_id="p1")],
        source_available_at=NOW,
    )


ANALYSIS_JSON = {
    "summary": "Cliente quer reduzir tempo de atendimento.",
    "main_problem": "Atendimento manual e lento",
    "budget_amount": 5000,
    "budget_confidence": "high",
    "budget_context": "Orçamento aprovado pelo diretor",
    "urgency": "high",
    "sentiment": "positive",
    "suggested_probability": 70,
    "pain_points": ["Fila de atendimento"],
    "objections": ["Preço acima do esperado"],
    "next_steps": ["Enviar proposta até sexta"],
    "commitments_company": ["Enviar proposta"],
    "commitments_customer": ["Validar com o diretor"],
    "risks": [],
    "positive_signals": ["Orçamento aprovado"],
    "negative_signals": [],
    "competitors": [],
}


@pytest.fixture()
def fake_llm(monkeypatch):
    """Substitui só a chamada de IA. Escopo e persistência continuam reais."""
    calls = {"count": 0}

    def _complete(db, company_id, *, operation, system_prompt, user_prompt, **kwargs):
        calls["count"] += 1
        if operation == "meeting_analysis":
            return dict(ANALYSIS_JSON)
        if operation == "sales_memory":
            return {
                "current_summary": "Oportunidade avançada",
                "business_problem": "Atendimento manual",
                "next_best_action": "Enviar proposta",
                "confidence": "high",
                "objections": ["Preço"],
                "risks": [],
                "buying_signals": ["Orçamento aprovado"],
                "open_questions": [],
            }
        return {"subject": "Retomando", "message": "Olá!", "key_points": [], "suggested_channel": "whatsapp"}

    monkeypatch.setattr(analysis_module, "complete_json", _complete)
    monkeypatch.setattr(sales_memory, "complete_json", _complete)
    return calls


def _ingest_with_transcript(db, company_id, monkeypatch, external_id="evt-1", email="cliente@exemplo.com"):
    """Ingere uma reunião e sua transcrição sem falar com o Google."""
    from backend.services.meetings import ingestion as ingestion_module

    provider_meeting = _provider_meeting(external_id, email)

    class _FakeProvider:
        name = PROVIDER_GOOGLE_MEET

        def fetch_transcript(self, *_args, **_kwargs):
            return _transcript()

    monkeypatch.setattr(ingestion_module, "get_provider", lambda _name: _FakeProvider())

    service = MeetingIngestionService(db)
    outcome = service.upsert_meeting(company_id, PROVIDER_GOOGLE_MEET, provider_meeting)
    service.import_transcript(outcome.meeting.id, company_id, provider_meeting)
    return outcome.meeting


# ---------------------------------------------------------------------------
# Isolamento entre empresas
# ---------------------------------------------------------------------------

def test_meeting_from_another_company_is_not_reachable(db, monkeypatch):
    meeting_b = _ingest_with_transcript(db, COMPANY_B, monkeypatch)

    with pytest.raises(MeetingScopeError):
        MeetingIngestionService(db).get_meeting(COMPANY_A, meeting_b.id)


def test_transcript_never_crosses_company(db, monkeypatch):
    meeting_b = _ingest_with_transcript(db, COMPANY_B, monkeypatch)

    found = (
        db.query(MeetingTranscript)
        .filter(
            MeetingTranscript.meeting_id == meeting_b.id,
            MeetingTranscript.company_id == COMPANY_A,
        )
        .first()
    )
    assert found is None


def test_analysis_never_crosses_company(db, monkeypatch, fake_llm):
    meeting_b = _ingest_with_transcript(db, COMPANY_B, monkeypatch)
    analysis_module.analyze_meeting(db, COMPANY_B, meeting_b.id)

    assert (
        db.query(MeetingAnalysis).filter(MeetingAnalysis.company_id == COMPANY_A).count() == 0
    )
    with pytest.raises(analysis_module.MeetingAnalysisError):
        analysis_module.analyze_meeting(db, COMPANY_A, meeting_b.id)


def test_sales_memory_never_crosses_company(db, monkeypatch, fake_llm):
    lead_b = _lead(db, COMPANY_B)
    meeting_b = _ingest_with_transcript(db, COMPANY_B, monkeypatch)
    MeetingIngestionService(db).associate(COMPANY_B, meeting_b.id, lead_id=lead_b.id)
    analysis_module.analyze_meeting(db, COMPANY_B, meeting_b.id)
    sales_memory.rebuild_sales_memory(db, COMPANY_B, lead_b.id)

    assert db.query(SalesMemory).filter(SalesMemory.company_id == COMPANY_A).count() == 0
    with pytest.raises(sales_memory.SalesMemoryError):
        sales_memory.rebuild_sales_memory(db, COMPANY_A, lead_b.id)


def test_crm_suggestion_never_crosses_company(db, monkeypatch, fake_llm):
    lead_b = _lead(db, COMPANY_B)
    meeting_b = _ingest_with_transcript(db, COMPANY_B, monkeypatch)
    MeetingIngestionService(db).associate(COMPANY_B, meeting_b.id, lead_id=lead_b.id)
    analysis_module.analyze_meeting(db, COMPANY_B, meeting_b.id)
    generate_suggestions(db, COMPANY_B, meeting_b.id)

    suggestion = db.query(CrmUpdateSuggestion).filter_by(company_id=COMPANY_B).first()
    assert suggestion is not None
    with pytest.raises(CrmSuggestionScopeError):
        crm_intelligence.get_suggestion(db, COMPANY_A, suggestion.id)


def test_cannot_associate_lead_from_another_company(db, monkeypatch):
    meeting_a = _ingest_with_transcript(db, COMPANY_A, monkeypatch)
    lead_b = _lead(db, COMPANY_B)

    with pytest.raises(MeetingScopeError):
        MeetingIngestionService(db).associate(COMPANY_A, meeting_a.id, lead_id=lead_b.id)


def test_cannot_associate_contact_from_another_company(db, monkeypatch):
    meeting_a = _ingest_with_transcript(db, COMPANY_A, monkeypatch)
    contact_b = db.query(Contact).filter(Contact.company_id == COMPANY_B).one()

    with pytest.raises(MeetingScopeError):
        MeetingIngestionService(db).associate(COMPANY_A, meeting_a.id, contact_id=contact_b.id)


def test_resolver_never_returns_entity_from_another_company(db):
    """Telefone idêntico em duas empresas não pode vazar o lead da outra."""
    lead_b = _lead(db, COMPANY_B)
    result = MeetingEntityResolver(db).resolve(
        COMPANY_A, participant_phones=[lead_b.phone]
    )
    assert all(candidate.lead_id != lead_b.id for candidate in result.candidates)


# ---------------------------------------------------------------------------
# Resolução conservadora
# ---------------------------------------------------------------------------

def test_unmatched_meeting_is_not_silently_associated(db, monkeypatch):
    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch, email="desconhecido@x.com")

    assert meeting.resolution_status == "unmatched"
    assert meeting.lead_id is None


def test_ambiguous_meeting_keeps_all_candidates_and_waits(db, monkeypatch):
    """Dois leads plausíveis: registra os dois e não escolhe."""
    phone = "5511911111111"
    for name in ("Lead X", "Lead Y"):
        db.add(Lead(client_id=1, company_id=COMPANY_A, name=name, phone=phone))
    db.commit()

    result = MeetingEntityResolver(db).resolve(COMPANY_A, participant_phones=[phone])

    assert result.status == "ambiguous"
    assert len(result.candidates) == 2
    assert result.chosen is None


def test_organizer_is_never_treated_as_the_lead(db):
    """O organizador é o vendedor; casá-lo criaria reunião com a própria equipe."""
    from backend.models import Customer

    contact = db.query(Contact).filter(Contact.company_id == COMPANY_A).one()
    db.add(
        Customer(
            contact_id=contact.id, company_id=COMPANY_A, nome="Vendedor",
            telefone="5511999999999", email="vendedor@empresa.com",
        )
    )
    db.commit()

    result = MeetingEntityResolver(db).resolve(
        COMPANY_A,
        participant_emails=["vendedor@empresa.com"],
        organizer_email="vendedor@empresa.com",
    )
    assert result.status == "unmatched"


# ---------------------------------------------------------------------------
# Idempotência
# ---------------------------------------------------------------------------

def test_same_calendar_event_never_creates_two_meetings(db, monkeypatch):
    from backend.services.meetings import ingestion as ingestion_module

    monkeypatch.setattr(ingestion_module, "get_provider", lambda _n: None)
    service = MeetingIngestionService(db)
    provider_meeting = _provider_meeting()

    first = service.upsert_meeting(COMPANY_A, PROVIDER_GOOGLE_MEET, provider_meeting)
    second = service.upsert_meeting(COMPANY_A, PROVIDER_GOOGLE_MEET, provider_meeting)

    assert first.created is True
    assert second.created is False
    assert first.meeting.id == second.meeting.id
    assert db.query(Meeting).filter(Meeting.company_id == COMPANY_A).count() == 1


def test_same_external_transcript_never_duplicates(db, monkeypatch):
    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch)
    MeetingIngestionService(db).import_transcript(meeting.id, COMPANY_A)

    assert db.query(MeetingTranscript).filter_by(meeting_id=meeting.id).count() == 1


def test_analysis_retry_does_not_duplicate(db, monkeypatch, fake_llm):
    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch)

    first = analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)
    second = analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)

    assert first.id == second.id
    assert db.query(MeetingAnalysis).filter_by(meeting_id=meeting.id).count() == 1
    # A segunda chamada nem gastou IA.
    assert fake_llm["count"] == 1


def test_suggestion_retry_does_not_duplicate(db, monkeypatch, fake_llm):
    lead = _lead(db, COMPANY_A)
    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch)
    MeetingIngestionService(db).associate(COMPANY_A, meeting.id, lead_id=lead.id)
    analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)

    first = generate_suggestions(db, COMPANY_A, meeting.id)
    second = generate_suggestions(db, COMPANY_A, meeting.id)

    assert len(first) > 0
    assert second == []


# ---------------------------------------------------------------------------
# Fronteira entre análise e CRM
# ---------------------------------------------------------------------------

def test_analysis_alone_never_changes_the_crm(db, monkeypatch, fake_llm):
    lead = _lead(db, COMPANY_A)
    original_value = lead.deal_value
    original_stage = lead.current_stage_id

    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch)
    MeetingIngestionService(db).associate(COMPANY_A, meeting.id, lead_id=lead.id)
    analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)
    generate_suggestions(db, COMPANY_A, meeting.id)

    db.refresh(lead)
    assert lead.deal_value == original_value
    assert lead.current_stage_id == original_stage
    assert db.query(ContactNote).count() == 0

    pending = db.query(CrmUpdateSuggestion).filter_by(company_id=COMPANY_A).all()
    assert pending and all(item.status == "pending" for item in pending)


def test_suggestion_must_be_accepted_before_it_applies(db, monkeypatch, fake_llm):
    lead = _lead(db, COMPANY_A)
    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch)
    MeetingIngestionService(db).associate(COMPANY_A, meeting.id, lead_id=lead.id, contact_id=None)
    analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)
    generate_suggestions(db, COMPANY_A, meeting.id)

    suggestion = (
        db.query(CrmUpdateSuggestion)
        .filter_by(company_id=COMPANY_A, suggestion_type="update_deal_value")
        .one()
    )
    with pytest.raises(CrmSuggestionError, match="aceita"):
        crm_intelligence.apply_suggestion(db, COMPANY_A, suggestion.id)

    accept_suggestion(db, COMPANY_A, suggestion.id)
    db.refresh(lead)
    # Numeric(12,2) devolve Decimal; comparar como texto dependeria da escala.
    assert Decimal(str(lead.deal_value)) == Decimal("5000")


def test_ai_can_never_mark_a_lead_as_won_or_lost(db, monkeypatch, fake_llm):
    """A lista de tipos é fechada no código e no CHECK do banco."""
    from backend.models.meeting_models import SUGGESTION_TYPES

    assert "won" not in SUGGESTION_TYPES
    assert "lost" not in SUGGESTION_TYPES
    assert "mark_won" not in SUGGESTION_TYPES

    lead = _lead(db, COMPANY_A)
    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch)
    MeetingIngestionService(db).associate(COMPANY_A, meeting.id, lead_id=lead.id)
    analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)
    created = generate_suggestions(db, COMPANY_A, meeting.id)

    assert all(item.suggestion_type in SUGGESTION_TYPES for item in created)


def test_invalid_analysis_output_is_discarded_not_stored(db, monkeypatch):
    """Enum inventado pelo modelo não chega ao banco."""
    def _garbage(*_args, **_kwargs):
        return {
            "summary": "ok",
            "sentiment": "eufórico",
            "urgency": "urgentíssimo",
            "suggested_probability": 900,
            "budget_amount": "não sei",
            "pain_points": "isto deveria ser lista",
        }

    monkeypatch.setattr(analysis_module, "complete_json", _garbage)
    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch)
    result = analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)

    assert result.sentiment is None
    assert result.urgency is None
    assert result.suggested_probability is None
    assert result.budget_amount is None
    assert result.pain_points == []


# ---------------------------------------------------------------------------
# Sales Memory e lineage
# ---------------------------------------------------------------------------

def test_sales_memory_preserves_lineage(db, monkeypatch, fake_llm):
    lead = _lead(db, COMPANY_A)
    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch)
    MeetingIngestionService(db).associate(COMPANY_A, meeting.id, lead_id=lead.id)
    analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)

    memory = sales_memory.rebuild_sales_memory(db, COMPANY_A, lead.id)
    types = {ref["source_type"] for ref in memory.source_refs}

    assert "meeting" in types
    assert "analysis" in types
    assert any(ref.get("meeting_id") == meeting.id for ref in memory.source_refs)


def test_sales_memory_does_not_replace_the_source(db, monkeypatch, fake_llm):
    """Reconstruir a memória não toca em reunião, transcrição nem análise."""
    lead = _lead(db, COMPANY_A)
    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch)
    MeetingIngestionService(db).associate(COMPANY_A, meeting.id, lead_id=lead.id)
    analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)

    before = db.query(MeetingTranscript).filter_by(meeting_id=meeting.id).one().text
    sales_memory.rebuild_sales_memory(db, COMPANY_A, lead.id)
    after = db.query(MeetingTranscript).filter_by(meeting_id=meeting.id).one().text

    assert before == after
    assert db.query(MeetingAnalysis).filter_by(meeting_id=meeting.id).count() == 1


def test_sales_memory_without_any_analyzed_meeting_is_not_invented(db):
    lead = _lead(db, COMPANY_A)
    assert sales_memory.rebuild_sales_memory(db, COMPANY_A, lead.id) is None


# ---------------------------------------------------------------------------
# Brain Context
# ---------------------------------------------------------------------------

def test_brain_context_sees_meeting_summary_without_the_transcript(db, monkeypatch, fake_llm):
    from backend.services.brain.context_service import BrainContextService
    from backend.services.brain.schemas import BrainScope

    lead = _lead(db, COMPANY_A)
    meeting = _ingest_with_transcript(
        db, COMPANY_A, monkeypatch, external_id="evt-brain",
    )
    MeetingIngestionService(db).associate(COMPANY_A, meeting.id, lead_id=lead.id)
    analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)
    sales_memory.rebuild_sales_memory(db, COMPANY_A, lead.id)

    context = BrainContextService(db).build(
        company_id=COMPANY_A, scopes=[BrainScope.SALES.value], lead_id=lead.id
    )

    assert len(context.sales.recent_meetings) == 1
    assert context.sales.recent_meetings[0].summary == ANALYSIS_JSON["summary"]
    assert context.sales.recent_meetings[0].has_transcript is True
    assert context.sales.sales_memory is not None

    # A transcrição não pode viajar no contexto por padrão.
    serialized = json.dumps(context.model_dump(mode="json"), default=str)
    assert "Cliente falou sobre o problema." not in serialized


def test_brain_context_never_injects_meeting_from_another_company(db, monkeypatch, fake_llm):
    from backend.services.brain.context_service import BrainContextService
    from backend.services.brain.schemas import BrainScope

    lead_a = _lead(db, COMPANY_A)
    lead_b = _lead(db, COMPANY_B)

    meeting_b = _ingest_with_transcript(db, COMPANY_B, monkeypatch, external_id="evt-b")
    MeetingIngestionService(db).associate(COMPANY_B, meeting_b.id, lead_id=lead_b.id)
    meeting_b.title = "SEGREDO-REUNIAO-B"
    db.commit()

    context = BrainContextService(db).build(
        company_id=COMPANY_A, scopes=[BrainScope.SALES.value], lead_id=lead_a.id
    )
    serialized = json.dumps(context.model_dump(mode="json"), default=str)

    assert "SEGREDO-REUNIAO-B" not in serialized
    assert context.sales.recent_meetings == []


# ---------------------------------------------------------------------------
# Fluxo integrado
# ---------------------------------------------------------------------------

def test_end_to_end_flow_from_calendar_event_to_brain(db, monkeypatch, fake_llm):
    """evento → meeting → transcript → analysis → memory → sugestões → Brain."""
    from backend.services.brain.context_service import BrainContextService
    from backend.services.brain.schemas import BrainScope

    lead = _lead(db, COMPANY_A)
    contact = db.query(Contact).filter(Contact.company_id == COMPANY_A).one()

    meeting = _ingest_with_transcript(db, COMPANY_A, monkeypatch, external_id="evt-e2e")
    assert meeting.transcript_status == "imported"

    MeetingIngestionService(db).associate(
        COMPANY_A, meeting.id, lead_id=lead.id, contact_id=contact.id
    )

    analysis = analysis_module.analyze_meeting(db, COMPANY_A, meeting.id)
    assert analysis.summary == ANALYSIS_JSON["summary"]

    memory = sales_memory.rebuild_sales_memory(db, COMPANY_A, lead.id)
    assert memory.next_best_action == "Enviar proposta"

    suggestions = generate_suggestions(db, COMPANY_A, meeting.id)
    assert {item.suggestion_type for item in suggestions} >= {"add_note", "update_deal_value"}

    context = BrainContextService(db).build(
        company_id=COMPANY_A, scopes=[BrainScope.SALES.value], lead_id=lead.id
    )
    assert context.sales.recent_meetings
    assert context.sales.sales_memory.next_best_action == "Enviar proposta"

    # Nada da empresa B entrou em nenhum ponto do fluxo.
    for model in (Meeting, MeetingTranscript, MeetingAnalysis, SalesMemory, CrmUpdateSuggestion):
        assert db.query(model).filter(model.company_id == COMPANY_B).count() == 0
