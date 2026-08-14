"""Sales Memory — visão comercial consolidada de um lead.

Ela é **derivada**. Se divergir de mensagens, reuniões ou CRM, a fonte ganha.
Por isso é reconstruída inteira a cada rebuild em vez de ser atualizada
incrementalmente: uma memória que só recebe patches acumula afirmações cuja
origem ninguém consegue mais apontar.

Não usa apenas a última reunião. Consolida as reuniões analisadas, o estado do
funil e a estratégia do Brain — e registra em ``source_refs`` de onde cada
parte veio, para que qualquer afirmação seja rastreável.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models import Lead
from backend.models.meeting_models import Meeting, MeetingAnalysis, SalesMemory
from backend.services.ai_provider_service import REQUIRED_OPENAI_RUNTIME_MODEL
from backend.services.meetings.llm import (
    OPERATION_SALES_MEMORY,
    MeetingLLMError,
    complete_json,
)

logger = logging.getLogger(__name__)

# Quantas reuniões entram na consolidação. Além disso o custo cresce e o sinal
# antigo passa a competir com o recente.
MAX_MEETINGS_IN_MEMORY = 6
MAX_LIST_ITEMS = 8
MAX_ITEM_CHARS = 400
MAX_TEXT_CHARS = 2000

TEXT_FIELDS = (
    "current_summary",
    "business_context",
    "business_problem",
    "decision_process",
    "budget_context",
    "timeline",
    "next_best_action",
)

LIST_FIELDS = (
    "desired_outcomes",
    "stakeholders",
    "objections",
    "competitors",
    "commitments_company",
    "commitments_customer",
    "risks",
    "buying_signals",
    "negative_signals",
    "open_questions",
)

SYSTEM_PROMPT = """Você consolida o histórico comercial de uma oportunidade em JSON.

Regras:
- Responda SOMENTE com um objeto JSON válido.
- Baseie-se apenas no material fornecido. Não invente fatos nem números.
- Prefira o mais recente quando houver contradição, mas registre a mudança se for relevante.
- Campo sem base no material: null (texto) ou [] (lista).
- Português do Brasil, objetivo, sem floreio.
- Listas: no máximo 8 itens.

Chaves esperadas:
current_summary, business_context, business_problem, decision_process, budget_context,
timeline, next_best_action, confidence (low|medium|high),
desired_outcomes, stakeholders, objections, competitors, commitments_company,
commitments_customer, risks, buying_signals, negative_signals, open_questions."""


class SalesMemoryError(RuntimeError):
    pass


def rebuild_sales_memory(db: Session, company_id: int, lead_id: int) -> Optional[SalesMemory]:
    """Reconstrói a memória comercial do lead a partir das fontes."""
    company_id = int(company_id)

    lead = (
        db.query(Lead)
        .filter(Lead.id == int(lead_id), Lead.company_id == company_id)
        .first()
    )
    if lead is None:
        raise SalesMemoryError("Lead não encontrado nesta empresa")

    analyses = (
        db.query(MeetingAnalysis, Meeting)
        .join(Meeting, Meeting.id == MeetingAnalysis.meeting_id)
        .filter(
            MeetingAnalysis.company_id == company_id,
            Meeting.company_id == company_id,
            Meeting.lead_id == lead.id,
        )
        .order_by(Meeting.scheduled_start_at.desc().nullslast(), MeetingAnalysis.id.desc())
        .limit(MAX_MEETINGS_IN_MEMORY)
        .all()
    )

    if not analyses:
        # Sem reunião analisada não há o que consolidar. Gravar uma memória
        # vazia daria a impressão de que o sistema "não encontrou nada",
        # quando na verdade nada foi observado ainda.
        return None

    source_refs = _build_source_refs(analyses)
    prompt = _build_prompt(lead, analyses, _brain_strategy_block(db, company_id))

    try:
        raw = complete_json(
            db,
            company_id,
            operation=OPERATION_SALES_MEMORY,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            lead_id=lead.id,
        )
    except MeetingLLMError as exc:
        raise SalesMemoryError(str(exc)) from None

    memory = (
        db.query(SalesMemory)
        .filter(SalesMemory.company_id == company_id, SalesMemory.lead_id == lead.id)
        .first()
    )
    if memory is None:
        memory = SalesMemory(company_id=company_id, lead_id=lead.id)
        db.add(memory)

    for field in TEXT_FIELDS:
        setattr(memory, field, _clean_text(raw.get(field)))
    for field in LIST_FIELDS:
        setattr(memory, field, _clean_list(raw.get(field)))

    confidence = str(raw.get("confidence") or "").strip().lower()
    memory.confidence = confidence if confidence in {"low", "medium", "high"} else None

    memory.source_refs = source_refs
    memory.last_rebuilt_at = datetime.now(timezone.utc)
    memory.provider = "openai"
    memory.model = REQUIRED_OPENAI_RUNTIME_MODEL

    db.commit()
    return memory


def _build_source_refs(analyses: List[Any]) -> List[Dict[str, Any]]:
    """Lineage: qual reunião e qual análise sustentam esta memória."""
    refs: List[Dict[str, Any]] = []
    for analysis, meeting in analyses:
        refs.append(
            {
                "source_type": "meeting",
                "meeting_id": meeting.id,
                "title": meeting.title,
                "occurred_at": (
                    meeting.scheduled_start_at.isoformat()
                    if meeting.scheduled_start_at
                    else None
                ),
            }
        )
        refs.append(
            {
                "source_type": "analysis",
                "analysis_id": analysis.id,
                "meeting_id": meeting.id,
                "analysis_version": analysis.analysis_version,
            }
        )
    return refs


def _brain_strategy_block(db: Session, company_id: int) -> str:
    """Estratégia do Brain como contexto — reaproveita o adaptador da Fase 2."""
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
            "Estratégia do Brain indisponível para a memória: company_id=%s error_type=%s",
            company_id,
            exc.__class__.__name__,
        )
        return ""


def _build_prompt(lead: Lead, analyses: List[Any], strategy_block: str) -> str:
    blocks: List[str] = []

    if strategy_block:
        blocks.append("Contexto estratégico da empresa:\n" + strategy_block)

    blocks.append(
        "Oportunidade:\n"
        f"- Nome: {lead.name or 'não informado'}\n"
        f"- Valor no CRM: {lead.deal_value if lead.deal_value is not None else 'não informado'}"
    )

    # Da mais recente para a mais antiga: o modelo dá mais peso ao topo, que é
    # exatamente a ordem de relevância comercial.
    for analysis, meeting in analyses:
        parts = [
            f"Reunião: {meeting.title or 'sem título'}"
            f" ({meeting.scheduled_start_at.date().isoformat() if meeting.scheduled_start_at else 'sem data'})"
        ]
        if analysis.summary:
            parts.append(f"Resumo: {analysis.summary}")
        for label, value in (
            ("Problema principal", analysis.main_problem),
            ("Contexto de orçamento", analysis.budget_context),
            ("Prazo", analysis.timeline),
        ):
            if value:
                parts.append(f"{label}: {value}")
        for label, values in (
            ("Dores", analysis.pain_points),
            ("Objeções", analysis.objections),
            ("Concorrentes", analysis.competitors),
            ("Compromissos da empresa", analysis.commitments_company),
            ("Compromissos do cliente", analysis.commitments_customer),
            ("Próximos passos", analysis.next_steps),
            ("Riscos", analysis.risks),
            ("Sinais positivos", analysis.positive_signals),
            ("Sinais negativos", analysis.negative_signals),
        ):
            if values:
                parts.append(f"{label}: {'; '.join(values)}")
        blocks.append("\n".join(parts))

    return "\n\n---\n\n".join(blocks)


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
            item = item.get("text") or item.get("item") or item.get("name") or ""
        text = str(item).strip()
        if text:
            cleaned.append(text[:MAX_ITEM_CHARS])
        if len(cleaned) >= MAX_LIST_ITEMS:
            break
    return cleaned
