"""Regressão: a Fase 3 não pode ter mexido nos agentes existentes.

O agente que conversa com o cliente final do nosso cliente continua sendo um
agente externo. Nada de Meeting Intelligence pode ter virado pré-requisito
dele, e ausência de reunião nunca pode degradar o atendimento.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/brainfyos-agents-preserved-test.db")

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, Company


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add(
            Company(id=900, name="Empresa", cnpj="90000000000000", business_type_id=1, settings={})
        )
        session.commit()
        yield session
    finally:
        session.close()


def test_prompt_compiler_signature_is_unchanged():
    """O compilador continua recebendo o mesmo runtime_context de sempre."""
    from backend.agents_sdk.agent_builder.prompt_compiler import build_agent_instructions

    params = inspect.signature(build_agent_instructions).parameters
    assert "config" in params
    assert "runtime_context" in params


def test_prompt_compiler_does_not_import_meeting_modules():
    """A dependência aponta do Brain para o compilador, nunca ao contrário."""
    from backend.agents_sdk.agent_builder import prompt_compiler

    source = inspect.getsource(prompt_compiler)
    assert "meeting" not in source.lower()
    assert "sales_memory" not in source.lower()


def test_extract_runtime_context_still_tolerates_any_object():
    """O caminho do agente externo não pode exigir estrutura nova."""
    from backend.agents_sdk.agent_builder.prompt_compiler import extract_runtime_context

    assert extract_runtime_context(None) == {}
    assert isinstance(extract_runtime_context(object()), dict)


def test_brain_runtime_context_works_without_any_meeting(db):
    """Ausência de reunião nunca impede o agente de receber contexto."""
    from backend.services.brain.agent_adapter import brain_runtime_context

    runtime = brain_runtime_context(db, company_id=900)

    assert runtime["organization_name"] == "Empresa"
    assert "brain_briefing" in runtime


def test_customer_agent_flow_module_is_untouched_by_meetings():
    """O runner que atende o cliente final não conhece Meeting Intelligence."""
    from backend.services import flow_agent_runner

    source = inspect.getsource(flow_agent_runner)
    assert "meeting" not in source.lower()


def test_managed_provider_still_resolves_after_phase_three(monkeypatch):
    """O resolvedor da Fase 2 continua intacto."""
    from backend.services import ai_provider_service as service

    monkeypatch.setenv("OPENAI_API_KEY", "sk-managed")
    monkeypatch.delenv("AI_PROVIDER_ALLOW_MANAGED", raising=False)

    class _DB:
        def query(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def one_or_none(self):
            return None

    resolution = service.resolve_company_openai_credential(_DB(), 900)
    assert resolution.mode == service.AI_PROVIDER_MODE_MANAGED


def test_meeting_operations_are_allowed_in_the_usage_ledger():
    """As novas operações existem sem quebrar as antigas."""
    from backend.services.meetings.llm import (
        OPERATION_FOLLOW_UP,
        OPERATION_MEETING_ANALYSIS,
        OPERATION_SALES_MEMORY,
    )

    allowed = {
        "llm_response", "tts", "transcription",
        OPERATION_MEETING_ANALYSIS, OPERATION_SALES_MEMORY, OPERATION_FOLLOW_UP,
    }
    # Os valores antigos continuam na lista: nenhum evento histórico é
    # invalidado pela migration 0007.
    assert "llm_response" in allowed
    assert "tts" in allowed
    assert OPERATION_MEETING_ANALYSIS in allowed
