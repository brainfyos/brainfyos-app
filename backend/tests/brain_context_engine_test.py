"""Comportamento do Context Engine, do adaptador de agentes e do modo managed.

Complementa ``brain_isolation_test``: la o assunto e escopo entre empresas,
aqui e o contrato do contexto em si.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/brainfyos-brain-engine-test.db")

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import (
    Base,
    BrainBusinessProfile,
    BrainGoal,
    BrainIcpProfile,
    BrainOffer,
    Company,
    Contact,
    Lead,
    Message,
)
from backend.models.revenue_models import Contract, Plan
from backend.services.brain.agent_adapter import brain_runtime_context, compile_brain_briefing
from backend.services.brain.context_service import BrainContextService
from backend.services.brain.schemas import BrainScope, SourceType

COMPANY = 7

TABLES = [
    Company.__table__,
    Contact.__table__,
    Lead.__table__,
    Message.__table__,
    Plan.__table__,
    Contract.__table__,
    BrainBusinessProfile.__table__,
    BrainIcpProfile.__table__,
    BrainOffer.__table__,
    BrainGoal.__table__,
]


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=TABLES)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add(
            Company(
                id=COMPANY, name="Clínica Norte", name_company="Clínica Norte",
                cnpj="44444444444444", business_type_id=1, settings={},
            )
        )
        db.commit()
        yield db
    finally:
        db.close()


def _add_strategy(db):
    db.add(
        BrainBusinessProfile(
            company_id=COMPANY,
            business_model="Assinatura mensal de acompanhamento",
            market="Clínicas odontológicas no Sudeste",
            positioning="A alternativa premium ao consultório de bairro",
            value_proposition="Agenda cheia sem depender de indicação",
            competitive_advantages=["Atendimento em 2 minutos", "Equipe própria"],
            main_channels=["WhatsApp"],
            strategic_priorities=["Dobrar receita recorrente"],
            constraints=["Capacidade de 300 atendimentos/mês"],
        )
    )
    icp = BrainIcpProfile(
        company_id=COMPANY,
        name="Clínica de médio porte",
        pain_points=["Agenda ociosa", "Faltas frequentes"],
        desired_outcomes=["Ocupação acima de 85%"],
        buying_triggers=[],
        objections=[],
        decision_makers=[],
        qualification_criteria=["Mais de 3 cadeiras"],
        disqualification_criteria=[],
        priority=1,
        is_active=True,
    )
    db.add(icp)
    db.flush()
    return icp


def test_business_context_is_always_present_even_without_scope(db_session):
    """Um agente sem saber de que empresa fala nao tem contexto, tem fragmento."""
    context = BrainContextService(db_session).build(company_id=COMPANY, scopes=[])

    assert context.business is not None
    assert context.business.name == "Clínica Norte"


def test_unknown_scope_falls_back_to_business(db_session):
    context = BrainContextService(db_session).build(company_id=COMPANY, scopes=["astrologia"])

    assert context.scopes == [BrainScope.BUSINESS.value]
    assert context.business is not None


def test_empty_blocks_say_why_instead_of_staying_silent(db_session):
    context = BrainContextService(db_session).build(
        company_id=COMPANY, scopes=[BrainScope.BUSINESS.value, BrainScope.FINANCIAL.value]
    )

    assert context.strategy.available is False
    assert context.strategy.unavailable_reason
    assert context.financial.available is False
    assert context.financial.unavailable_reason


def test_context_declares_its_sources(db_session):
    _add_strategy(db_session)
    db_session.commit()

    context = BrainContextService(db_session).build(
        company_id=COMPANY, scopes=[BrainScope.BUSINESS.value]
    )
    source_types = {source.source_type for source in context.all_sources()}

    assert SourceType.COMPANY in source_types
    assert SourceType.STRATEGY in source_types
    assert SourceType.ICP in source_types


def test_offer_ticket_comes_from_the_linked_plan_not_a_copy(db_session):
    """Plan e dono do preco. A oferta aponta; nao duplica."""
    icp = _add_strategy(db_session)
    db_session.add(Plan(id=9, company_id=COMPANY, name="Plano Ouro", price=1500))
    db_session.flush()
    db_session.add(
        BrainOffer(
            company_id=COMPANY,
            name="Programa Ocupação Total",
            target_icp_id=icp.id,
            related_plan_id=9,
            # Valor obsoleto de propósito: o plano precisa vencer.
            average_ticket=100,
            main_objections=[],
            proof_points=[],
            is_primary=True,
            is_active=True,
        )
    )
    db_session.commit()

    context = BrainContextService(db_session).build(
        company_id=COMPANY, scopes=[BrainScope.BUSINESS.value]
    )
    offer = context.strategy.primary_offer

    assert offer is not None
    assert offer.average_ticket == 1500.0
    assert offer.ticket_source == "plan"
    assert offer.related_plan_name == "Plano Ouro"


def test_offer_ticket_uses_own_estimate_when_there_is_no_plan(db_session):
    icp = _add_strategy(db_session)
    db_session.add(
        BrainOffer(
            company_id=COMPANY, name="Diagnóstico avulso", target_icp_id=icp.id,
            average_ticket=350, main_objections=[], proof_points=[],
            is_primary=True, is_active=True,
        )
    )
    db_session.commit()

    context = BrainContextService(db_session).build(
        company_id=COMPANY, scopes=[BrainScope.BUSINESS.value]
    )
    offer = context.strategy.primary_offer

    assert offer.average_ticket == 350.0
    assert offer.ticket_source == "offer"


def test_recent_messages_are_returned_in_chronological_order(db_session):
    """Historico invertido faz o modelo ler resposta como pergunta."""
    db_session.add(Contact(id=1, client_id=1, company_id=COMPANY, phone="5511999", name="Ana"))
    base = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    for index in range(3):
        db_session.add(
            Message(
                id=index + 1, client_id=1, company_id=COMPANY, contact_phone="5511999",
                message_type="text", content=f"mensagem {index}", sender_phone="5511999",
                from_me=False, timestamp=base.replace(hour=10 + index),
            )
        )
    db_session.commit()

    context = BrainContextService(db_session).build(
        company_id=COMPANY, scopes=[BrainScope.CUSTOMER.value], contact_id=1
    )
    contents = [message.content for message in context.customer.recent_messages]

    assert contents == ["mensagem 0", "mensagem 1", "mensagem 2"]


def test_customer_scope_without_any_identifier_explains_itself(db_session):
    context = BrainContextService(db_session).build(
        company_id=COMPANY, scopes=[BrainScope.CUSTOMER.value]
    )

    assert context.customer.available is False
    assert "lead_id" in context.customer.unavailable_reason


def test_limit_is_capped_so_a_caller_cannot_dump_the_table(db_session):
    db_session.add(Contact(id=1, client_id=1, company_id=COMPANY, phone="5511999", name="Ana"))
    for index in range(80):
        db_session.add(
            Message(
                id=index + 1, client_id=1, company_id=COMPANY, contact_phone="5511999",
                message_type="text", content=f"m{index}", sender_phone="5511999",
                from_me=False, timestamp=datetime.now(timezone.utc),
            )
        )
    db_session.commit()

    context = BrainContextService(db_session).build(
        company_id=COMPANY, scopes=[BrainScope.CUSTOMER.value], contact_id=1, limit=9999
    )

    assert len(context.customer.recent_messages) == 50
    # A contagem total continua honesta mesmo com a lista truncada.
    assert context.customer.message_count == 80


# ---------------------------------------------------------------------------
# Adaptador de agentes
# ---------------------------------------------------------------------------

def test_agent_adapter_returns_keys_the_prompt_compiler_already_consumes(db_session):
    """O adaptador nao muda a assinatura do compilador -- ele a respeita."""
    from backend.agents_sdk.agent_builder.prompt_compiler import extract_runtime_context

    _add_strategy(db_session)
    db_session.commit()

    runtime = brain_runtime_context(db_session, company_id=COMPANY)

    assert runtime["organization_name"] == "Clínica Norte"
    # As mesmas chaves que extract_runtime_context produz hoje.
    expected = set(extract_runtime_context(object()).keys())
    assert expected.issubset(set(runtime.keys()) | {"contact_lifecycle", "channel", "current_stage", "conversation_step"})


def test_briefing_renders_strategy_as_prompt_text(db_session):
    icp = _add_strategy(db_session)
    db_session.add(
        BrainOffer(
            company_id=COMPANY, name="Programa Ocupação Total", target_icp_id=icp.id,
            promise="Ocupação acima de 85% em 90 dias",
            main_objections=["Preço"], proof_points=["12 clínicas atendidas"],
            is_primary=True, is_active=True,
        )
    )
    db_session.add(BrainGoal(company_id=COMPANY, name="Dobrar receita", status="active", priority=1))
    db_session.commit()

    context = BrainContextService(db_session).build(
        company_id=COMPANY, scopes=[BrainScope.BUSINESS.value]
    )
    briefing = compile_brain_briefing(context)

    assert "Clínica Norte" in briefing
    assert "A alternativa premium ao consultório de bairro" in briefing
    assert "Programa Ocupação Total" in briefing
    assert "Dobrar receita" in briefing


def test_briefing_is_empty_when_there_is_no_strategy(db_session):
    """Sem estrategia o briefing nao inventa texto -- so nomeia a empresa."""
    context = BrainContextService(db_session).build(
        company_id=COMPANY, scopes=[BrainScope.BUSINESS.value]
    )
    briefing = compile_brain_briefing(context)

    assert briefing.strip() == "Empresa: Clínica Norte."
