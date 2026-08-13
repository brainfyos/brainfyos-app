"""Isolamento por company no Brain -- contra um banco real, sem mocks.

Este e o teste principal de integracao do Brain e ele nao usa mock nenhum:
duas empresas sao criadas de verdade, com dado de verdade, e cada assercao
verifica que nada da empresa A aparece no contexto da empresa B.

Mock aqui seria inutil. Um mock so prova que o codigo chamou o filtro que o
teste mandou ele chamar; o que precisa ser provado e que uma consulta real
contra um banco real nao devolve linha alheia.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/brainfyos-brain-isolation-test.db")

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import (
    Base,
    BusinessType,
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
from backend.services.brain import repository
from backend.services.brain.context_service import BrainContextService
from backend.services.brain.readiness import calculate_readiness
from backend.services.brain.repository import BrainNotFoundError
from backend.services.brain.schemas import BrainScope

COMPANY_A = 101
COMPANY_B = 202



@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    # Schema inteiro: o Context Engine toca muitas tabelas e enumerá-las
    # à mão faz o teste quebrar por tabela faltando, não por regressão.
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        _seed_two_companies(db)
        yield db
    finally:
        db.close()


def _seed_two_companies(db):
    """Duas empresas com o mesmo formato de dado, para colisao ser visivel."""
    db.add_all(
        [
            Company(id=COMPANY_A, name="Empresa A", cnpj="11111111111111", business_type_id=1, settings={}),
            Company(id=COMPANY_B, name="Empresa B", cnpj="22222222222222", business_type_id=1, settings={}),
        ]
    )
    db.flush()

    db.add_all(
        [
            BrainBusinessProfile(
                company_id=COMPANY_A,
                business_model="Modelo A",
                positioning="Posicionamento A",
                value_proposition="Proposta A",
                competitive_advantages=["Vantagem A"],
                main_channels=[],
                strategic_priorities=[],
                constraints=[],
            ),
            BrainBusinessProfile(
                company_id=COMPANY_B,
                business_model="Modelo B",
                positioning="Posicionamento B",
                value_proposition="Proposta B",
                competitive_advantages=["Vantagem B"],
                main_channels=[],
                strategic_priorities=[],
                constraints=[],
            ),
        ]
    )

    db.add_all(
        [
            _icp(COMPANY_A, "ICP da A", ["Dor da A"]),
            _icp(COMPANY_B, "ICP da B", ["Dor da B"]),
        ]
    )
    db.flush()

    icp_a = db.query(BrainIcpProfile).filter_by(company_id=COMPANY_A).one()
    icp_b = db.query(BrainIcpProfile).filter_by(company_id=COMPANY_B).one()

    db.add_all(
        [
            _offer(COMPANY_A, "Oferta da A", icp_a.id),
            _offer(COMPANY_B, "Oferta da B", icp_b.id),
        ]
    )

    db.add_all(
        [
            BrainGoal(company_id=COMPANY_A, name="Meta da A", status="active", priority=1),
            BrainGoal(company_id=COMPANY_B, name="Meta da B", status="active", priority=1),
        ]
    )

    db.add_all(
        [
            Contact(id=1, client_id=1, company_id=COMPANY_A, phone="5511000000001", name="Contato A"),
            Contact(id=2, client_id=1, company_id=COMPANY_B, phone="5511000000002", name="Contato B"),
        ]
    )
    db.add_all(
        [
            Lead(id=1, client_id=1, company_id=COMPANY_A, name="Lead A", phone="5511000000001"),
            Lead(id=2, client_id=1, company_id=COMPANY_B, name="Lead B", phone="5511000000002"),
        ]
    )
    db.add_all(
        [
            Message(
                id=1, client_id=1, company_id=COMPANY_A, contact_phone="5511000000001",
                message_type="text", content="Mensagem secreta da A",
                sender_phone="5511000000001", from_me=False,
                timestamp=datetime.now(timezone.utc),
            ),
            Message(
                id=2, client_id=1, company_id=COMPANY_B, contact_phone="5511000000002",
                message_type="text", content="Mensagem secreta da B",
                sender_phone="5511000000002", from_me=False,
                timestamp=datetime.now(timezone.utc),
            ),
        ]
    )
    db.add_all(
        [
            Contract(
                id=1, company_id=COMPANY_A, status="active",
                start_date=date.today(), total_value=1000, total_paid=500,
            ),
            Contract(
                id=2, company_id=COMPANY_B, status="active",
                start_date=date.today(), total_value=9999, total_paid=9999,
            ),
        ]
    )
    db.commit()


def _icp(company_id, name, pains):
    return BrainIcpProfile(
        company_id=company_id,
        name=name,
        pain_points=pains,
        decision_makers=[],
        desired_outcomes=[],
        buying_triggers=[],
        objections=[],
        qualification_criteria=[],
        disqualification_criteria=[],
        priority=1,
        is_active=True,
    )


def _offer(company_id, name, icp_id):
    return BrainOffer(
        company_id=company_id,
        name=name,
        target_icp_id=icp_id,
        main_objections=[],
        proof_points=[],
        is_primary=True,
        is_active=True,
    )


def _all_text(payload) -> str:
    """Serializa o contexto inteiro para procurar vazamento por substring."""
    import json

    return json.dumps(payload, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Context Engine
# ---------------------------------------------------------------------------

def test_context_never_returns_another_company_strategy(db_session):
    context = BrainContextService(db_session).build(
        company_id=COMPANY_A, scopes=[BrainScope.BUSINESS.value]
    )
    serialized = _all_text(context.model_dump(mode="json"))

    assert "Modelo A" in serialized
    assert "Modelo B" not in serialized
    assert "Posicionamento B" not in serialized
    assert "Vantagem B" not in serialized


def test_context_never_returns_another_company_icp_or_offer(db_session):
    context = BrainContextService(db_session).build(
        company_id=COMPANY_A, scopes=[BrainScope.BUSINESS.value]
    )

    assert [icp.name for icp in context.strategy.icps] == ["ICP da A"]
    assert [offer.name for offer in context.strategy.offers] == ["Oferta da A"]
    assert "ICP da B" not in _all_text(context.model_dump(mode="json"))
    assert "Oferta da B" not in _all_text(context.model_dump(mode="json"))


def test_context_never_returns_another_company_goals(db_session):
    context = BrainContextService(db_session).build(
        company_id=COMPANY_B, scopes=[BrainScope.BUSINESS.value]
    )

    assert [goal.name for goal in context.goals.goals] == ["Meta da B"]
    assert "Meta da A" not in _all_text(context.model_dump(mode="json"))


def test_context_never_returns_another_company_conversations(db_session):
    context = BrainContextService(db_session).build(
        company_id=COMPANY_A,
        scopes=[BrainScope.CUSTOMER.value],
        contact_id=1,
    )
    serialized = _all_text(context.model_dump(mode="json"))

    assert "Mensagem secreta da A" in serialized
    assert "Mensagem secreta da B" not in serialized


def test_context_ignores_foreign_ids_instead_of_leaking(db_session):
    """Pedir o contato da empresa B a partir da empresa A nao devolve nada.

    O ponto e que o id existe -- so nao pertence a este workspace. A resposta
    correta e "sem contexto de cliente", nao o registro alheio.
    """
    context = BrainContextService(db_session).build(
        company_id=COMPANY_A,
        scopes=[BrainScope.CUSTOMER.value],
        contact_id=2,
    )

    assert context.customer.available is False
    assert context.customer.contact is None
    assert "Contato B" not in _all_text(context.model_dump(mode="json"))


def test_financial_context_never_crosses_workspace(db_session):
    context = BrainContextService(db_session).build(
        company_id=COMPANY_A, scopes=[BrainScope.FINANCIAL.value]
    )

    assert context.financial.active_contracts == 1
    assert context.financial.total_contract_value == 1000.0
    # 9999 e o valor da empresa B; se aparecesse, o filtro teria falhado.
    assert context.financial.total_contract_value != 9999.0


def test_sales_context_counts_only_own_leads(db_session):
    context = BrainContextService(db_session).build(
        company_id=COMPANY_A, scopes=[BrainScope.SALES.value]
    )

    assert context.sales.total_leads == 1
    assert [lead.name for lead in context.sales.recent_leads] == ["Lead A"]


def test_context_requires_company_id(db_session):
    with pytest.raises(ValueError):
        BrainContextService(db_session).build(company_id=0)


def test_marketing_scope_declares_absence_instead_of_faking_data(db_session):
    context = BrainContextService(db_session).build(
        company_id=COMPANY_A, scopes=[BrainScope.MARKETING.value]
    )

    assert context.marketing.available is False
    assert context.marketing.unavailable_reason


# ---------------------------------------------------------------------------
# Repositório
# ---------------------------------------------------------------------------

def test_repository_cannot_read_foreign_icp(db_session):
    foreign = db_session.query(BrainIcpProfile).filter_by(company_id=COMPANY_B).one()
    with pytest.raises(BrainNotFoundError):
        repository.get_icp(db_session, COMPANY_A, foreign.id)


def test_repository_cannot_update_foreign_offer(db_session):
    foreign = db_session.query(BrainOffer).filter_by(company_id=COMPANY_B).one()
    with pytest.raises(BrainNotFoundError):
        repository.update_offer(db_session, COMPANY_A, foreign.id, {"name": "Sequestrada"})

    db_session.rollback()
    assert db_session.query(BrainOffer).filter_by(id=foreign.id).one().name == "Oferta da B"


def test_repository_cannot_archive_foreign_goal(db_session):
    foreign = db_session.query(BrainGoal).filter_by(company_id=COMPANY_B).one()
    with pytest.raises(BrainNotFoundError):
        repository.archive_goal(db_session, COMPANY_A, foreign.id)


def test_offer_cannot_target_icp_from_another_company(db_session):
    """A FK garante que o id existe; ela nao garante que ele e seu."""
    foreign_icp = db_session.query(BrainIcpProfile).filter_by(company_id=COMPANY_B).one()

    with pytest.raises(BrainNotFoundError):
        repository.create_offer(
            db_session,
            COMPANY_A,
            {"name": "Oferta cruzada", "target_icp_id": foreign_icp.id},
        )


def test_offer_cannot_link_plan_from_another_company(db_session):
    plan = Plan(id=50, company_id=COMPANY_B, name="Plano da B", price=500)
    db_session.add(plan)
    db_session.commit()

    with pytest.raises(BrainNotFoundError):
        repository.create_offer(
            db_session,
            COMPANY_A,
            {"name": "Oferta cruzada", "related_plan_id": plan.id},
        )


def test_promoting_an_offer_demotes_the_previous_primary(db_session):
    second = repository.create_offer(db_session, COMPANY_A, {"name": "Segunda oferta"})
    repository.update_offer(db_session, COMPANY_A, second.id, {"is_primary": True})

    primaries = [
        offer.name
        for offer in repository.list_offers(db_session, COMPANY_A)
        if offer.is_primary
    ]
    assert primaries == ["Segunda oferta"]


def test_archived_icp_disappears_from_context_but_survives_in_database(db_session):
    icp = db_session.query(BrainIcpProfile).filter_by(company_id=COMPANY_A).one()
    repository.archive_icp(db_session, COMPANY_A, icp.id)

    context = BrainContextService(db_session).build(
        company_id=COMPANY_A, scopes=[BrainScope.BUSINESS.value]
    )
    assert context.strategy.icps == []
    # Arquivamento e logico: a linha continua la para nao quebrar a oferta que
    # aponta para ela.
    assert db_session.query(BrainIcpProfile).filter_by(id=icp.id).one() is not None


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

def test_readiness_is_deterministic_and_explainable(db_session):
    first = calculate_readiness(db_session, COMPANY_A)
    second = calculate_readiness(db_session, COMPANY_A)

    assert first.percent == second.percent
    assert sum(check.weight for check in first.checks) == 100
    earned = sum(check.weight for check in first.checks if check.done)
    assert first.percent == round((earned / 100) * 100)
    # Cada verificacao precisa explicar o proprio resultado.
    assert all(check.detail for check in first.checks)


def test_readiness_does_not_count_another_company_data(db_session):
    empty_company = 303
    db_session.add(
        Company(id=empty_company, name="Empresa Vazia", cnpj="33333333333333", business_type_id=1, settings={})
    )
    db_session.commit()

    report = calculate_readiness(db_session, empty_company)
    done = {check.key for check in report.checks if check.done}

    assert "strategy_profile" not in done
    assert "icp_defined" not in done
    assert "primary_offer" not in done
    assert "crm_contacts" not in done


def test_readiness_reports_what_is_missing(db_session):
    report = calculate_readiness(db_session, COMPANY_A)
    missing_keys = {check.key for check in report.checks if not check.done}

    # A empresa A nao tem canal conectado no seed.
    assert "channel_connected" in missing_keys
    assert all(check.action_route for check in report.checks if check.key in missing_keys)
