"""Meeting Analysis — o que a IA entendeu da conversa.

Duas regras estruturais:

**A análise descreve, não altera.** Nada aqui escreve no CRM. O que a IA acha
que deveria mudar vira sugestão em ``crm_intelligence``, e sugestão precisa
ser aceita. Sem essa separação, uma alucinação vira mudança operacional
silenciosa.

**Saída validada antes de gravar.** O modelo devolve JSON e ele passa por
``_coerce_analysis`` antes de encostar no banco: enums restritos, listas
truncadas, números em faixa. Campo fora do contrato é descartado, não gravado.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.meeting_models import Meeting, MeetingAnalysis, MeetingTranscript
from backend.services.ai_provider_service import REQUIRED_OPENAI_RUNTIME_MODEL
from backend.services.meetings.llm import (
    OPERATION_MEETING_ANALYSIS,
    MeetingLLMError,
    complete_json,
    truncate_transcript,
)

logger = logging.getLogger(__name__)

PROMPT_VERSION = "2026-08-14.1"

# Teto por lista. Uma análise com trinta objeções não é mais informativa que
# uma com seis — só mais cara de ler e de enviar como contexto depois.
MAX_LIST_ITEMS = 8
MAX_TEXT_CHARS = 2000
MAX_ITEM_CHARS = 400

ENUM_FIELDS = {
    "budget_confidence": {"low", "medium", "high"},
    "urgency": {"low", "medium", "high"},
    "sentiment": {"positive", "neutral", "negative", "mixed"},
}

TEXT_FIELDS = (
    "summary",
    "meeting_purpose",
    "customer_context",
    "main_problem",
    "budget_context",
    "timeline",
    "probability_reason",
)

LIST_FIELDS = (
    "pain_points",
    "needs",
    "desired_outcomes",
    "decision_makers",
    "influencers",
    "competitors",
    "objections",
    "questions",
    "unanswered_questions",
    "products_discussed",
    "offers_discussed",
    "prices_mentioned",
    "commitments_company",
    "commitments_customer",
    "next_steps",
    "risks",
    "positive_signals",
    "negative_signals",
    "evidence_snippets",
)

SYSTEM_PROMPT = """Você analisa reuniões comerciais e devolve dados estruturados em JSON.

Regras:
- Responda SOMENTE com um objeto JSON válido.
- Use exclusivamente o que foi dito na transcrição. Não invente, não deduza além do texto.
- Campo sem informação na conversa: use null (texto) ou [] (lista). Nunca preencha por suposição.
- Escreva em português do Brasil.
- Listas: no máximo 8 itens, cada um com uma frase objetiva.

Chaves esperadas:
summary, meeting_purpose, customer_context, main_problem, budget_context,
budget_amount (número ou null), budget_confidence (low|medium|high|null),
urgency (low|medium|high|null), timeline, sentiment (positive|neutral|negative|mixed|null),
suggested_probability (0-100 ou null), probability_reason,
suggested_next_step_date (YYYY-MM-DD ou null),
pain_points, needs, desired_outcomes, decision_makers, influencers, competitors,
objections, questions, unanswered_questions, products_discussed, offers_discussed,
prices_mentioned, commitments_company, commitments_customer, next_steps, risks,
positive_signals, negative_signals, evidence_snippets (citações curtas e literais)."""


class MeetingAnalysisError(RuntimeError):
    pass


def analyze_meeting(
    db: Session,
    company_id: int,
    meeting_id: int,
    *,
    force_new_version: bool = False,
) -> Optional[MeetingAnalysis]:
    """Analisa a transcrição mais recente da reunião.

    Idempotente: se já existe análise para o transcript atual e ninguém pediu
    reprocessamento, devolve a existente sem gastar uma chamada de IA.
    """
    company_id = int(company_id)

    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == int(meeting_id), Meeting.company_id == company_id)
        .first()
    )
    if meeting is None:
        raise MeetingAnalysisError("Reunião não encontrada")

    transcript = (
        db.query(MeetingTranscript)
        .filter(
            MeetingTranscript.meeting_id == meeting.id,
            MeetingTranscript.company_id == company_id,
        )
        .order_by(MeetingTranscript.id.desc())
        .first()
    )
    if transcript is None or not (transcript.text or "").strip():
        meeting.analysis_status = "skipped"
        db.commit()
        return None

    existing = (
        db.query(MeetingAnalysis)
        .filter(
            MeetingAnalysis.meeting_id == meeting.id,
            MeetingAnalysis.company_id == company_id,
        )
        .order_by(MeetingAnalysis.analysis_version.desc())
        .first()
    )
    if existing is not None and not force_new_version and existing.transcript_id == transcript.id:
        return existing

    meeting.analysis_status = "running"
    db.commit()

    try:
        raw = complete_json(
            db,
            company_id,
            operation=OPERATION_MEETING_ANALYSIS,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(meeting, transcript),
            meeting_id=meeting.id,
            lead_id=meeting.lead_id,
        )
    except MeetingLLMError as exc:
        meeting.analysis_status = "failed"
        meeting.last_error = str(exc)
        db.commit()
        raise MeetingAnalysisError(str(exc)) from None

    payload = _coerce_analysis(raw)
    version = (existing.analysis_version + 1) if existing is not None else 1

    analysis = MeetingAnalysis(
        company_id=company_id,
        meeting_id=meeting.id,
        transcript_id=transcript.id,
        provider="openai",
        model=REQUIRED_OPENAI_RUNTIME_MODEL,
        prompt_version=PROMPT_VERSION,
        analysis_version=version,
        **payload,
    )
    db.add(analysis)
    meeting.analysis_status = "completed"

    try:
        db.commit()
    except IntegrityError:
        # Outro worker gravou esta mesma versão. O índice único cortou; a
        # análise existente vale e o retry não duplica.
        db.rollback()
        return (
            db.query(MeetingAnalysis)
            .filter(
                MeetingAnalysis.meeting_id == meeting.id,
                MeetingAnalysis.company_id == company_id,
            )
            .order_by(MeetingAnalysis.analysis_version.desc())
            .first()
        )

    return analysis


def _build_user_prompt(meeting: Meeting, transcript: MeetingTranscript) -> str:
    header = [
        f"Título da reunião: {meeting.title or 'não informado'}",
        f"Data: {meeting.scheduled_start_at.isoformat() if meeting.scheduled_start_at else 'não informada'}",
    ]
    if meeting.duration_seconds:
        header.append(f"Duração: {round(meeting.duration_seconds / 60)} minutos")

    participants = [
        f"- {participant.name or participant.email or 'participante'}"
        f" ({participant.participant_type})"
        for participant in meeting.participants
    ]
    if participants:
        header.append("Participantes:\n" + "\n".join(participants))

    return (
        "\n".join(header)
        + "\n\nTranscrição:\n"
        + truncate_transcript(transcript.text or "")
    )


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------

def _coerce_analysis(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Converte a saída do modelo no que o banco aceita.

    Tudo que não couber no contrato é descartado. Nenhum CHECK do banco deve
    ser a primeira linha de defesa contra o que o modelo devolveu.
    """
    payload: Dict[str, Any] = {}

    for field in TEXT_FIELDS:
        payload[field] = _clean_text(raw.get(field))

    for field in LIST_FIELDS:
        payload[field] = _clean_list(raw.get(field))

    for field, allowed in ENUM_FIELDS.items():
        value = raw.get(field)
        normalized = str(value).strip().lower() if value is not None else None
        payload[field] = normalized if normalized in allowed else None

    payload["budget_amount"] = _clean_decimal(raw.get("budget_amount"))
    payload["suggested_probability"] = _clean_probability(raw.get("suggested_probability"))
    payload["suggested_next_step_date"] = _clean_date(raw.get("suggested_next_step_date"))

    return payload


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    return text[:MAX_TEXT_CHARS]


def _clean_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    cleaned: List[str] = []
    for item in value:
        if isinstance(item, dict):
            # Alguns modelos devolvem {"item": "..."} em vez de string.
            item = item.get("text") or item.get("item") or item.get("description") or ""
        text = str(item).strip()
        if text:
            cleaned.append(text[:MAX_ITEM_CHARS])
        if len(cleaned) >= MAX_LIST_ITEMS:
            break
    return cleaned


def _clean_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        amount = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount >= 0 else None


def _clean_probability(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 100 else None


def _clean_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None
