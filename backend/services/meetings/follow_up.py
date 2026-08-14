"""Follow Up Intelligence — rascunho do próximo contato.

**Nada é enviado.** Esta fase gera um rascunho que a pessoa lê, edita e envia
pelo canal que já existe. Disparar automaticamente uma mensagem escrita por IA
para o cliente de um cliente é uma decisão de produto que ninguém tomou — e o
custo de errar cai sobre a reputação da empresa que usa o BrainfyOS.

Nenhum sistema de WhatsApp novo: o envio, quando acontecer, usa o que já está
no projeto.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models import Lead
from backend.models.meeting_models import Meeting, MeetingAnalysis, SalesMemory
from backend.services.meetings.llm import (
    OPERATION_FOLLOW_UP,
    MeetingLLMError,
    complete_json,
)

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 1200

SYSTEM_PROMPT = """Você escreve mensagens de follow-up comercial em JSON.

Regras:
- Responda SOMENTE com um objeto JSON válido.
- Use apenas o que foi realmente conversado. Não prometa nada que não foi combinado.
- Português do Brasil, tom profissional e direto, sem jargão de vendas.
- Mensagem curta: no máximo 6 linhas, pronta para enviar por WhatsApp.
- Retome um compromisso concreto e proponha o próximo passo.

Chaves esperadas:
subject (assunto curto), message (texto da mensagem),
key_points (lista com o que a mensagem retoma), suggested_channel (whatsapp|email)."""


class FollowUpError(RuntimeError):
    pass


def generate_follow_up(
    db: Session,
    company_id: int,
    meeting_id: int,
) -> Dict[str, Any]:
    """Rascunho de follow-up para a reunião. Não envia nada."""
    company_id = int(company_id)

    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == int(meeting_id), Meeting.company_id == company_id)
        .first()
    )
    if meeting is None:
        raise FollowUpError("Reunião não encontrada")

    analysis = (
        db.query(MeetingAnalysis)
        .filter(
            MeetingAnalysis.meeting_id == meeting.id,
            MeetingAnalysis.company_id == company_id,
        )
        .order_by(MeetingAnalysis.analysis_version.desc())
        .first()
    )
    if analysis is None:
        raise FollowUpError("A reunião ainda não foi analisada")

    memory = (
        db.query(SalesMemory)
        .filter(SalesMemory.company_id == company_id, SalesMemory.lead_id == meeting.lead_id)
        .first()
        if meeting.lead_id
        else None
    )
    lead = (
        db.query(Lead)
        .filter(Lead.id == meeting.lead_id, Lead.company_id == company_id)
        .first()
        if meeting.lead_id
        else None
    )

    try:
        raw = complete_json(
            db,
            company_id,
            operation=OPERATION_FOLLOW_UP,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=_build_prompt(db, company_id, meeting, analysis, memory, lead),
            meeting_id=meeting.id,
            lead_id=meeting.lead_id,
            temperature=0.4,
        )
    except MeetingLLMError as exc:
        raise FollowUpError(str(exc)) from None

    channel = str(raw.get("suggested_channel") or "whatsapp").strip().lower()
    return {
        "meeting_id": meeting.id,
        "lead_id": meeting.lead_id,
        "subject": _clean(raw.get("subject"), 160),
        "message": _clean(raw.get("message"), MAX_MESSAGE_CHARS),
        "key_points": [
            _clean(item, 200) for item in (raw.get("key_points") or [])[:6] if _clean(item, 200)
        ],
        "suggested_channel": channel if channel in {"whatsapp", "email"} else "whatsapp",
        # Rascunho: quem envia é a pessoa, pelo canal existente.
        "status": "draft",
        "source_refs": [
            {"source_type": "meeting", "meeting_id": meeting.id},
            {"source_type": "analysis", "analysis_id": analysis.id},
        ]
        + ([{"source_type": "sales_memory", "sales_memory_id": memory.id}] if memory else []),
    }


def _build_prompt(
    db: Session,
    company_id: int,
    meeting: Meeting,
    analysis: MeetingAnalysis,
    memory: Optional[SalesMemory],
    lead: Optional[Lead],
) -> str:
    blocks: List[str] = []

    strategy = _strategy_block(db, company_id)
    if strategy:
        blocks.append("Contexto da empresa que vai enviar:\n" + strategy)

    if lead is not None:
        blocks.append(f"Destinatário: {lead.name or 'cliente'}")

    reunion = [f"Reunião: {meeting.title or 'sem título'}"]
    if analysis.summary:
        reunion.append(f"Resumo: {analysis.summary}")
    for label, values in (
        ("Compromissos assumidos pela empresa", analysis.commitments_company),
        ("Compromissos do cliente", analysis.commitments_customer),
        ("Próximos passos", analysis.next_steps),
        ("Objeções em aberto", analysis.objections),
        ("Perguntas não respondidas", analysis.unanswered_questions),
    ):
        if values:
            reunion.append(f"{label}: {'; '.join(values)}")
    blocks.append("\n".join(reunion))

    if memory is not None and memory.next_best_action:
        blocks.append(f"Próxima melhor ação registrada: {memory.next_best_action}")

    return "\n\n---\n\n".join(blocks)


def _strategy_block(db: Session, company_id: int) -> str:
    try:
        from backend.services.brain.agent_adapter import compile_brain_briefing
        from backend.services.brain.context_service import BrainContextService
        from backend.services.brain.schemas import BrainScope

        context = BrainContextService(db).build(
            company_id=company_id, scopes=[BrainScope.BUSINESS.value]
        )
        return compile_brain_briefing(context)
    except Exception as exc:  # pragma: no cover - degradação
        logger.warning(
            "Estratégia indisponível para o follow-up: company_id=%s error_type=%s",
            company_id,
            exc.__class__.__name__,
        )
        return ""


def _clean(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None
