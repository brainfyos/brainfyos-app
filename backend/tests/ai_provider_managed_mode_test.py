"""Modo managed do provedor de IA.

O contrato que vinha da fase anterior continua valendo: **nenhum call site le
``OPENAI_API_KEY`` diretamente**. O que muda e que o resolvedor -- o unico
lugar que escolhe uma chave -- agora tem duas fontes, e a preferencia entre
elas precisa ser explicita e testada.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/brainfyos-managed-mode-test.db")

import pytest
from cryptography.fernet import Fernet

from backend.services import ai_provider_service as service

COMPANY = 11
MANAGED_KEY = "sk-platform-managed-key"
COMPANY_KEY = "sk-company-own-key"


class _FakeDB:
    """Sessao minima: o resolvedor so precisa de query().filter_by().first()."""

    def __init__(self, credential=None):
        self._credential = credential

    def query(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._credential


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.delenv("AI_PROVIDER_TOKEN_ENCRYPTION_KEY_FILE", raising=False)
    yield


def _credential(status="valid", api_key=COMPANY_KEY):
    from backend.models import AIProviderCredential

    return AIProviderCredential(
        company_id=COMPANY,
        provider="openai",
        api_key_encrypted=service.encrypt_openai_api_key(api_key),
        status=status,
    )


def test_managed_mode_serves_a_company_without_its_own_credential(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", MANAGED_KEY)
    monkeypatch.delenv("AI_PROVIDER_ALLOW_MANAGED", raising=False)

    resolution = service.resolve_company_openai_credential(_FakeDB(None), COMPANY)

    assert resolution.mode == service.AI_PROVIDER_MODE_MANAGED
    assert resolution.api_key == MANAGED_KEY


def test_company_credential_always_wins_over_the_platform_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", MANAGED_KEY)

    resolution = service.resolve_company_openai_credential(_FakeDB(_credential()), COMPANY)

    assert resolution.mode == service.AI_PROVIDER_MODE_BYOK
    assert resolution.api_key == COMPANY_KEY
    assert resolution.api_key != MANAGED_KEY


def test_invalid_company_credential_does_not_silently_fall_back(monkeypatch):
    """Cair para managed aqui cobraria consumo de quem nao pediu isso."""
    monkeypatch.setenv("OPENAI_API_KEY", MANAGED_KEY)

    with pytest.raises(service.AIProviderNotConfiguredError, match="não está validada"):
        service.resolve_company_openai_credential(_FakeDB(_credential(status="invalid")), COMPANY)


def test_without_any_key_the_error_is_still_raised(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(service.AIProviderNotConfiguredError, match="não configurada"):
        service.resolve_company_openai_credential(_FakeDB(None), COMPANY)


def test_managed_can_be_switched_off_without_a_redeploy(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", MANAGED_KEY)
    monkeypatch.setenv("AI_PROVIDER_ALLOW_MANAGED", "false")

    with pytest.raises(service.AIProviderNotConfiguredError):
        service.resolve_company_openai_credential(_FakeDB(None), COMPANY)


def test_mode_description_never_exposes_key_material(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", MANAGED_KEY)

    described = service.describe_company_ai_provider_mode(_FakeDB(None), COMPANY)

    assert described["mode"] == service.AI_PROVIDER_MODE_MANAGED
    assert described["operational"] is True
    assert MANAGED_KEY not in str(described)


def test_byok_description_never_exposes_key_material(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    described = service.describe_company_ai_provider_mode(_FakeDB(_credential()), COMPANY)

    assert described["mode"] == service.AI_PROVIDER_MODE_BYOK
    assert described["operational"] is True
    assert COMPANY_KEY not in str(described)


def test_get_company_openai_api_key_still_returns_a_plain_key(monkeypatch):
    """Assinatura preservada: nenhum call site existente precisa mudar."""
    monkeypatch.setenv("OPENAI_API_KEY", MANAGED_KEY)

    assert service.get_company_openai_api_key(_FakeDB(None), COMPANY) == MANAGED_KEY
    assert service.get_company_openai_api_key(_FakeDB(_credential()), COMPANY) == COMPANY_KEY
