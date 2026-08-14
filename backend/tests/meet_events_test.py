"""Fluxo orientado a evento do Google Meet.

Cobre assinatura, entrega por Pub/Sub, idempotência, fallback e o
comportamento de reconsentimento — sem tocar em rede.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/brainfyos-meet-events-test.db")

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, CalendarIntegration, Company, Contact, Lead
from backend.models.meeting_models import Meeting, MeetingTranscript, PROVIDER_GOOGLE_MEET
from backend.services.meetings import google_workspace_events as events
from backend.services.meetings.capabilities import describe_capabilities
from backend.services.meetings.providers.google_meet import MEET_READONLY_SCOPE

COMPANY_A = 601
COMPANY_B = 602

CALENDAR_ONLY = "https://www.googleapis.com/auth/calendar.events.owned"
FULL_SCOPES = f"{CALENDAR_ONLY} {MEET_READONLY_SCOPE}"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        for company_id, suffix in ((COMPANY_A, "A"), (COMPANY_B, "B")):
            session.add(
                Company(
                    id=company_id, name=f"Empresa {suffix}",
                    cnpj=str(company_id).zfill(14), business_type_id=1, settings={},
                )
            )
        session.commit()
        yield session
    finally:
        session.close()


def _connect(db, company_id, scopes=FULL_SCOPES, status=events.STATUS_INACTIVE, name=None, expires=None):
    integration = CalendarIntegration(
        company_id=company_id,
        provider="google",
        google_oauth_token={"token": "x", "refresh_token": "y"},
        google_oauth_scopes=scopes,
        meet_subscription_status=status,
        meet_subscription_name=name,
        meet_subscription_expires_at=expires,
    )
    db.add(integration)
    db.commit()
    return integration


def _meeting(db, company_id, conference="abc-defg-hij", record="conferenceRecords/1", **kwargs):
    meeting = Meeting(
        company_id=company_id,
        provider=PROVIDER_GOOGLE_MEET,
        external_meeting_id=record,
        external_conference_id=conference,
        title=kwargs.pop("title", "Reunião"),
        status=kwargs.pop("status", "completed"),
        **kwargs,
    )
    db.add(meeting)
    db.commit()
    return meeting


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    """Registra chamadas para provar idempotência sem falar com o Google."""

    def __init__(self, existing=None, fail=False):
        self.existing = existing
        self.fail = fail
        self.posts = 0
        self.patches = 0

    def get(self, url, **_kwargs):
        if self.existing is None:
            return _FakeResponse({}, status_code=404)
        return _FakeResponse(self.existing)

    def post(self, url, **_kwargs):
        self.posts += 1
        if self.fail:
            raise RuntimeError("boom")
        return _FakeResponse(
            {
                "name": "subscriptions/sub-1",
                "expireTime": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            }
        )

    def patch(self, url, **_kwargs):
        self.patches += 1
        if self.fail:
            raise RuntimeError("boom")
        return _FakeResponse(
            {"expireTime": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()}
        )

    def delete(self, url, **_kwargs):
        return _FakeResponse({})


@pytest.fixture()
def google_ready(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv(events.PUBSUB_TOPIC_ENV, "projects/p/topics/meet")


# ---------------------------------------------------------------------------
# Assinatura
# ---------------------------------------------------------------------------

def test_subscription_is_created_once(db, google_ready, monkeypatch):
    _connect(db, COMPANY_A)
    session = _FakeSession()
    monkeypatch.setattr(events, "_authorized_session", lambda *_a: session)

    state = events.ensure_subscription(db, COMPANY_A)

    assert state.status == events.STATUS_ACTIVE
    assert session.posts == 1


def test_calling_ensure_again_renews_instead_of_duplicating(db, google_ready, monkeypatch):
    """Idempotência: assinatura viva é renovada, nunca recriada."""
    _connect(db, COMPANY_A, name="subscriptions/sub-1")
    session = _FakeSession(existing={"name": "subscriptions/sub-1"})
    monkeypatch.setattr(events, "_authorized_session", lambda *_a: session)

    events.ensure_subscription(db, COMPANY_A)
    events.ensure_subscription(db, COMPANY_A)

    assert session.posts == 0
    assert session.patches == 2


def test_subscription_is_recreated_when_google_forgot_it(db, google_ready, monkeypatch):
    _connect(db, COMPANY_A, name="subscriptions/velha")
    session = _FakeSession(existing=None)
    monkeypatch.setattr(events, "_authorized_session", lambda *_a: session)

    events.ensure_subscription(db, COMPANY_A)

    assert session.posts == 1


def test_subscription_failure_degrades_and_keeps_fallback(db, google_ready, monkeypatch):
    """Falha não desliga a Meeting Intelligence: o fallback assume."""
    _connect(db, COMPANY_A)
    monkeypatch.setattr(events, "_authorized_session", lambda *_a: _FakeSession(fail=True))

    state = events.ensure_subscription(db, COMPANY_A)

    assert state.status == events.STATUS_DEGRADED
    assert state.error
    # Estado degradado é exatamente o que o fallback procura.
    assert COMPANY_A in {int(i.company_id) for i in events.subscriptions_needing_renewal(db)}


def test_expired_subscription_is_reported_as_expired(db, google_ready):
    _connect(
        db, COMPANY_A, status=events.STATUS_ACTIVE, name="subscriptions/s",
        expires=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert events.get_subscription_state(db, COMPANY_A).status == events.STATUS_EXPIRED


def test_subscription_needs_meet_scope(db, google_ready, monkeypatch):
    _connect(db, COMPANY_A, scopes=CALENDAR_ONLY)
    with pytest.raises(events.WorkspaceEventsNotConfiguredError):
        events.ensure_subscription(db, COMPANY_A)


def test_subscription_needs_pubsub_topic(db, monkeypatch):
    monkeypatch.delenv(events.PUBSUB_TOPIC_ENV, raising=False)
    _connect(db, COMPANY_A)
    with pytest.raises(events.WorkspaceEventsNotConfiguredError, match="Pub/Sub"):
        events.ensure_subscription(db, COMPANY_A)


# ---------------------------------------------------------------------------
# Capabilities e reconsentimento
# ---------------------------------------------------------------------------

def test_calendar_only_shows_as_needing_additional_authorization(db, google_ready):
    """Não pode aparecer como conectado: falta permissão."""
    _connect(db, COMPANY_A, scopes=CALENDAR_ONLY)

    capabilities = describe_capabilities(db, COMPANY_A)

    assert capabilities.calendar_connected is True
    assert capabilities.meet_access is False
    assert capabilities.needs_reconsent is True
    assert capabilities.is_operational is False
    assert MEET_READONLY_SCOPE in capabilities.missing_scopes
    assert any("autorização adicional" in blocker for blocker in capabilities.blockers)


def test_missing_oauth_does_not_break_capabilities(db, monkeypatch):
    """OAuth ausente é estado reportável, não exceção."""
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)

    capabilities = describe_capabilities(db, COMPANY_A)

    assert capabilities.oauth_configured is False
    assert capabilities.is_operational is False
    assert capabilities.blockers


def test_full_setup_reports_operational(db, google_ready):
    _connect(
        db, COMPANY_A, status=events.STATUS_ACTIVE, name="subscriptions/s",
        expires=datetime.now(timezone.utc) + timedelta(days=5),
    )
    capabilities = describe_capabilities(db, COMPANY_A)

    assert capabilities.meet_access is True
    assert capabilities.event_subscription_active is True
    assert capabilities.is_operational is True


def test_auto_transcription_is_unknown_without_evidence(db, google_ready):
    """Sem prova, o valor é None — não um palpite exibido como fato."""
    _connect(
        db, COMPANY_A, status=events.STATUS_ACTIVE,
        expires=datetime.now(timezone.utc) + timedelta(days=5),
    )
    assert describe_capabilities(db, COMPANY_A).auto_transcription_available is None


def test_auto_transcription_true_after_a_real_import(db, google_ready):
    _connect(
        db, COMPANY_A, status=events.STATUS_ACTIVE,
        expires=datetime.now(timezone.utc) + timedelta(days=5),
    )
    _meeting(db, COMPANY_A, transcript_status="imported")
    assert describe_capabilities(db, COMPANY_A).auto_transcription_available is True


# ---------------------------------------------------------------------------
# Evento fileGenerated
# ---------------------------------------------------------------------------

def _event(record="conferenceRecords/1", message_id="m-1"):
    return {
        "message_id": message_id,
        "event_type": events.EVENT_TRANSCRIPT_FILE_GENERATED,
        "subject": f"{record}/transcripts/t1",
        "attributes": {},
        "payload": {"transcript": {"name": f"{record}/transcripts/t1"}},
    }


def test_company_is_resolved_from_the_conference_record(db):
    _meeting(db, COMPANY_A, record="conferenceRecords/9")
    assert events.resolve_company_for_conference(db, "conferenceRecords/9") == COMPANY_A


def test_event_from_company_a_never_resolves_to_company_b(db):
    _meeting(db, COMPANY_A, record="conferenceRecords/A", conference="aaa-aaaa-aaa")
    _meeting(db, COMPANY_B, record="conferenceRecords/B", conference="bbb-bbbb-bbb")

    assert events.resolve_company_for_conference(db, "conferenceRecords/A") == COMPANY_A
    assert events.resolve_company_for_conference(db, "conferenceRecords/B") == COMPANY_B


def test_unknown_conference_defers_instead_of_guessing(db):
    _meeting(db, COMPANY_A, record="conferenceRecords/A")
    assert events.resolve_company_for_conference(db, "conferenceRecords/desconhecido") is None


def test_file_generated_triggers_import(db, monkeypatch):
    from backend.worker import tasks_meet_events as worker

    meeting = _meeting(db, COMPANY_A, record="conferenceRecords/1")
    _connect(db, COMPANY_A, status=events.STATUS_ACTIVE)

    calls = {"import": 0, "analyze": 0}

    class _Ingestion:
        def __init__(self, _db):
            pass

        def import_transcript(self, meeting_id, company_id):
            calls["import"] += 1
            row = MeetingTranscript(
                company_id=company_id, meeting_id=meeting_id, provider=PROVIDER_GOOGLE_MEET,
                external_transcript_id="conferenceRecords/1/transcripts/t1", text="oi",
            )
            db.add(row)
            db.query(Meeting).filter(Meeting.id == meeting_id).one().transcript_status = "imported"
            db.commit()
            return True

    monkeypatch.setattr(worker, "SessionLocal", lambda: db)
    monkeypatch.setattr(worker, "_already_processed", lambda _m: False)
    monkeypatch.setattr(
        "backend.services.meetings.ingestion.MeetingIngestionService", _Ingestion
    )
    monkeypatch.setattr(
        "backend.worker.tasks_meetings.analyze_meeting_task",
        type("T", (), {"delay": staticmethod(lambda *a, **k: calls.__setitem__("analyze", calls["analyze"] + 1))}),
    )

    result = worker._handle_transcript_ready(None, _event())

    assert result["status"] == "imported"
    assert calls["import"] == 1
    assert calls["analyze"] == 1


def test_duplicate_event_does_not_duplicate_transcript(db, monkeypatch):
    """Reentrega do Pub/Sub é normal; duplicar dado não é."""
    from backend.worker import tasks_meet_events as worker

    meeting = _meeting(db, COMPANY_A, record="conferenceRecords/1", transcript_status="imported")
    _connect(db, COMPANY_A, status=events.STATUS_ACTIVE)
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)
    monkeypatch.setattr(worker, "_already_processed", lambda _m: False)

    result = worker._handle_transcript_ready(None, _event())

    assert result["status"] == "duplicate"
    assert db.query(MeetingTranscript).count() == 0


def test_redis_dedupe_short_circuits_a_repeated_message(monkeypatch):
    from backend.worker import tasks_meet_events as worker

    monkeypatch.setattr(worker, "_already_processed", lambda _m: True)
    # Chamada direta executa a task sincronamente (Task.__call__).
    result = worker.process_meet_event(_event())

    assert result["status"] == "duplicate"


def test_conference_ended_updates_state_from_the_provider(db, monkeypatch):
    """Estado real do provedor vence o horário previsto."""
    from backend.worker import tasks_meet_events as worker

    meeting = _meeting(db, COMPANY_A, record="conferenceRecords/1", status="scheduled")
    _connect(db, COMPANY_A, status=events.STATUS_ACTIVE)
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)

    worker._handle_conference_state(
        {"subject": "conferenceRecords/1", "payload": {}}, events.EVENT_CONFERENCE_ENDED
    )

    db.refresh(meeting)
    assert meeting.status == "completed"
    assert meeting.ended_at is not None


def test_receiving_an_event_recovers_a_degraded_subscription(db):
    integration = _connect(db, COMPANY_A, status=events.STATUS_DEGRADED)
    integration.meet_subscription_error = "falhou antes"
    db.commit()

    events.record_event_received(db, COMPANY_A)

    db.refresh(integration)
    assert integration.meet_subscription_status == events.STATUS_ACTIVE
    assert integration.meet_last_event_at is not None


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def test_fallback_targets_degraded_subscriptions_and_skips_healthy(db, monkeypatch):
    from backend.worker import tasks_meetings as worker

    # A: saudável e sem pendência → deve ser pulada.
    _connect(
        db, COMPANY_A, status=events.STATUS_ACTIVE,
        expires=datetime.now(timezone.utc) + timedelta(days=5),
    )
    # B: degradada → deve entrar na recuperação.
    _connect(db, COMPANY_B, status=events.STATUS_DEGRADED)

    scheduled = []
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        worker.sync_company_meetings, "delay", lambda cid: scheduled.append(cid)
    )

    summary = worker.sync_all_companies()

    assert summary["connected"] == 2
    assert scheduled == [COMPANY_B]


def test_fallback_rescues_a_stale_meeting_even_with_healthy_subscription(db, monkeypatch):
    from backend.worker import tasks_meetings as worker

    _connect(
        db, COMPANY_A, status=events.STATUS_ACTIVE,
        expires=datetime.now(timezone.utc) + timedelta(days=5),
    )
    _meeting(
        db, COMPANY_A, status="completed", transcript_status="pending",
        scheduled_end_at=datetime.now(timezone.utc) - timedelta(hours=6),
    )

    scheduled = []
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        worker.sync_company_meetings, "delay", lambda cid: scheduled.append(cid)
    )

    worker.sync_all_companies()

    assert scheduled == [COMPANY_A]


# ---------------------------------------------------------------------------
# Endpoint push
# ---------------------------------------------------------------------------

def test_push_endpoint_rejects_unauthenticated_delivery(monkeypatch):
    from fastapi import HTTPException

    from backend.routes import meet_events as route

    monkeypatch.setenv(route.PUBSUB_SERVICE_ACCOUNT_ENV, "pubsub@projeto.iam.gserviceaccount.com")

    with pytest.raises(HTTPException) as excinfo:
        route._verify_push_token(None)
    assert excinfo.value.status_code == 401


def test_push_endpoint_refuses_when_service_account_is_not_configured(monkeypatch):
    from fastapi import HTTPException

    from backend.routes import meet_events as route

    monkeypatch.delenv(route.PUBSUB_SERVICE_ACCOUNT_ENV, raising=False)

    with pytest.raises(HTTPException) as excinfo:
        route._verify_push_token("Bearer qualquer")
    # Recusar tudo é mais seguro que aceitar entrega não verificada.
    assert excinfo.value.status_code == 503


def test_push_envelope_is_decoded_from_base64():
    import base64
    import json as json_module

    from backend.routes import meet_events as route

    payload = {"transcript": {"name": "conferenceRecords/1/transcripts/t1"}}
    envelope = {
        "message": {
            "messageId": "m-99",
            "data": base64.b64encode(json_module.dumps(payload).encode()).decode(),
            "attributes": {"ce-type": events.EVENT_TRANSCRIPT_FILE_GENERATED},
        }
    }

    decoded = route._decode_message(envelope)

    assert decoded["message_id"] == "m-99"
    assert decoded["event_type"] == events.EVENT_TRANSCRIPT_FILE_GENERATED
    assert decoded["payload"] == payload


def test_unreadable_body_does_not_crash_the_endpoint():
    """Corpo inválido é ACK, não erro: reentrega não melhoraria."""
    from backend.routes import meet_events as route

    decoded = route._decode_message(
        {"message": {"messageId": "m-1", "data": "não-e-base64-valido!!", "attributes": {}}}
    )
    assert decoded["payload"] == {}
