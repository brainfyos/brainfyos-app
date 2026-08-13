"""Onboarding integrado ao Brain.

O que precisa ficar provado: nao existem duas verdades. Uma resposta de
onboarding cujo campo tem casa no Brain acaba **no Brain**, e nao sobra copia
na tabela de respostas.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/brainfyos-brain-onboarding-test.db")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, BrainBusinessProfile, BrainIcpProfile, BrainOffer, Company
from backend.models.onboarding_models import OnboardingAnswer
from backend.services.brain.onboarding_bridge import materialize_answers_into_brain
from backend.services.onboarding_service import (
    _has_brain_icp,
    _has_brain_offer,
    _has_brain_strategy,
)

COMPANY = 55



@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add(Company(id=COMPANY, name="Empresa", cnpj="55555555555555", business_type_id=1, settings={}))
        db.commit()
        yield db
    finally:
        db.close()


def _answer(db, key, value):
    db.add(OnboardingAnswer(company_id=COMPANY, field_key=key, value={"value": value}))
    db.commit()


def test_answers_are_materialized_into_the_brain_profile(db_session):
    _answer(db_session, "positioning", "A referência em ortodontia digital")
    _answer(db_session, "modelo_negocio", "Assinatura mensal")

    result = materialize_answers_into_brain(db_session, COMPANY)

    profile = db_session.query(BrainBusinessProfile).filter_by(company_id=COMPANY).one()
    assert profile.positioning == "A referência em ortodontia digital"
    assert profile.business_model == "Assinatura mensal"
    assert len(result["applied"]) == 2


def test_materialized_answers_leave_no_copy_behind(db_session):
    """Duas verdades comecam exatamente aqui: a copia que ninguem apagou."""
    _answer(db_session, "positioning", "Texto original")

    materialize_answers_into_brain(db_session, COMPANY)

    remaining = db_session.query(OnboardingAnswer).filter_by(company_id=COMPANY).all()
    assert remaining == []


def test_materialization_never_overwrites_what_the_user_edited_in_the_brain(db_session):
    db_session.add(
        BrainBusinessProfile(
            company_id=COMPANY,
            positioning="Editado na BrainPage",
            competitive_advantages=[],
            main_channels=[],
            strategic_priorities=[],
            constraints=[],
        )
    )
    db_session.commit()
    _answer(db_session, "positioning", "Resposta antiga do onboarding")

    materialize_answers_into_brain(db_session, COMPANY)

    profile = db_session.query(BrainBusinessProfile).filter_by(company_id=COMPANY).one()
    assert profile.positioning == "Editado na BrainPage"


def test_list_answers_accept_comma_separated_text(db_session):
    _answer(db_session, "diferenciais", "Atendimento rápido, equipe própria, garantia")

    materialize_answers_into_brain(db_session, COMPANY)

    profile = db_session.query(BrainBusinessProfile).filter_by(company_id=COMPANY).one()
    assert profile.competitive_advantages == ["Atendimento rápido", "equipe própria", "garantia"]


def test_materialization_is_idempotent(db_session):
    _answer(db_session, "positioning", "Texto")

    first = materialize_answers_into_brain(db_session, COMPANY)
    second = materialize_answers_into_brain(db_session, COMPANY)

    assert first["applied"] == ["positioning->positioning"]
    assert second["applied"] == []


def test_answers_from_another_company_are_not_touched(db_session):
    other = 66
    db_session.add(Company(id=other, name="Outra", cnpj="66666666666666", business_type_id=1, settings={}))
    db_session.add(OnboardingAnswer(company_id=other, field_key="positioning", value={"value": "Da outra"}))
    db_session.commit()

    materialize_answers_into_brain(db_session, COMPANY)

    survivor = db_session.query(OnboardingAnswer).filter_by(company_id=other).one()
    assert survivor.value == {"value": "Da outra"}
    assert db_session.query(BrainBusinessProfile).filter_by(company_id=other).first() is None


# ---------------------------------------------------------------------------
# Resolvedores automáticos das etapas de estratégia
# ---------------------------------------------------------------------------

def test_strategy_step_completes_only_with_the_three_essential_fields(db_session):
    assert _has_brain_strategy(db_session, COMPANY) is False

    profile = BrainBusinessProfile(
        company_id=COMPANY,
        business_model="Modelo",
        positioning="Posicionamento",
        competitive_advantages=[],
        main_channels=[],
        strategic_priorities=[],
        constraints=[],
    )
    db_session.add(profile)
    db_session.commit()
    assert _has_brain_strategy(db_session, COMPANY) is False

    profile.value_proposition = "Proposta"
    db_session.commit()
    assert _has_brain_strategy(db_session, COMPANY) is True


def test_icp_step_reads_the_brain_not_the_answers_table(db_session):
    _answer(db_session, "icp", "Clínicas de médio porte")
    assert _has_brain_icp(db_session, COMPANY) is False

    db_session.add(
        BrainIcpProfile(
            company_id=COMPANY, name="Clínicas", pain_points=[], decision_makers=[],
            desired_outcomes=[], buying_triggers=[], objections=[],
            qualification_criteria=[], disqualification_criteria=[],
            priority=1, is_active=True,
        )
    )
    db_session.commit()
    assert _has_brain_icp(db_session, COMPANY) is True


def test_offer_step_requires_a_primary_offer(db_session):
    db_session.add(
        BrainOffer(
            company_id=COMPANY, name="Oferta secundária",
            main_objections=[], proof_points=[], is_primary=False, is_active=True,
        )
    )
    db_session.commit()
    assert _has_brain_offer(db_session, COMPANY) is False

    db_session.add(
        BrainOffer(
            company_id=COMPANY, name="Oferta principal",
            main_objections=[], proof_points=[], is_primary=True, is_active=True,
        )
    )
    db_session.commit()
    assert _has_brain_offer(db_session, COMPANY) is True
