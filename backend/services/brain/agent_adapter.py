"""Adaptador entre o Brain e os agentes existentes.

**Nenhum agente e migrado nesta fase.** O fluxo atual continua exatamente como
esta: ``extract_runtime_context()`` le um objeto de contexto por duck-typing e
``build_agent_instructions(config, runtime_context=...)`` compila o prompt.

O que este modulo entrega e o ponto de encaixe para quando a migracao
acontecer, em duas formas:

``brain_runtime_context()``
    Devolve um dicionario com as **mesmas chaves** que o compilador ja consome,
    acrescido de ``brain``. Um agente migrado passa a receber estrategia sem
    que o compilador precise mudar de assinatura.

``compile_brain_briefing()``
    Renderiza o contexto como texto para prompt. Fica aqui, e nao no
    ``prompt_compiler``, porque o compilador nao deve conhecer o Brain -- a
    dependencia aponta do Brain para o compilador, nunca ao contrario.

Sem essa direcao, o compilador passaria a importar modelos do Brain e o Brain
viraria dependencia obrigatoria de todo agente, inclusive dos que nao querem
estrategia nenhuma.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from backend.services.brain.context_service import BrainContextService
from backend.services.brain.schemas import BrainContext, BrainScope

# Limite de itens por lista dentro do briefing. Contexto de prompt e caro; uma
# lista de vinte objecoes dilui as tres que importam.
BRIEFING_LIST_LIMIT = 5


def brain_runtime_context(
    db: Session,
    *,
    company_id: int,
    scopes: Optional[Sequence[str]] = None,
    lead_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    customer_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Contexto do Brain no formato que o prompt compiler ja aceita."""
    context = BrainContextService(db).build(
        company_id=company_id,
        scopes=scopes or (BrainScope.BUSINESS.value,),
        lead_id=lead_id,
        contact_id=contact_id,
        customer_id=customer_id,
    )

    business = context.business
    customer = context.customer

    return {
        "organization_name": business.name if business else None,
        "organization_data": {"organization_info": {"name": business.name}} if business else {},
        "contact_name": customer.contact.name if customer and customer.contact else None,
        "contact_phone": customer.contact.phone if customer and customer.contact else None,
        "brain": context,
        "brain_briefing": compile_brain_briefing(context),
    }


def compile_brain_briefing(context: BrainContext) -> str:
    """Renderiza o contexto como bloco de texto para prompt.

    Formato deliberadamente seco: rotulo, dois-pontos, valor. Sem markdown
    decorativo -- ele consome token e nao muda o que o modelo entende.
    """
    lines: List[str] = []

    business = context.business
    if business and business.available:
        lines.append(f"Empresa: {business.name}.")
        if business.business_type:
            lines.append(f"Segmento: {business.business_type}.")

    strategy = context.strategy
    if strategy and strategy.available:
        lines.extend(
            _labelled(label, value)
            for label, value in (
                ("Modelo de negócio", strategy.business_model),
                ("Mercado", strategy.market),
                ("Posicionamento", strategy.positioning),
                ("Proposta de valor", strategy.value_proposition),
                ("Movimento de vendas", strategy.sales_motion),
            )
        )
        lines.append(_listed("Diferenciais", strategy.competitive_advantages))
        lines.append(_listed("Prioridades estratégicas", strategy.strategic_priorities))
        lines.append(_listed("Restrições", strategy.constraints))

        primary = strategy.primary_offer
        if primary is not None:
            lines.append(f"Oferta principal: {primary.name}.")
            lines.append(_labelled("Promessa da oferta", primary.promise))
            lines.append(_labelled("Mecanismo da oferta", primary.mechanism))
            if primary.average_ticket is not None:
                origin = "plano associado" if primary.ticket_source == "plan" else "estimativa da oferta"
                lines.append(f"Ticket da oferta principal: {primary.average_ticket:.2f} ({origin}).")
            lines.append(_listed("Objeções comuns", primary.main_objections))
            lines.append(_listed("Provas disponíveis", primary.proof_points))

        if strategy.icps:
            leading = strategy.icps[0]
            lines.append(f"Cliente ideal principal: {leading.name}.")
            lines.append(_listed("Dores do cliente ideal", leading.pain_points))
            lines.append(_listed("Resultados desejados", leading.desired_outcomes))
            lines.append(_listed("Critérios de qualificação", leading.qualification_criteria))

    goals = context.goals
    if goals and goals.available and goals.goals:
        described = [
            f"{goal.name}"
            + (f" (meta {goal.target_value:g}{' ' + goal.unit if goal.unit else ''})" if goal.target_value is not None else "")
            for goal in goals.goals[:BRIEFING_LIST_LIMIT]
        ]
        lines.append(_listed("Objetivos ativos", described))

    return "\n".join(line for line in lines if line)


def _labelled(label: str, value: Optional[str]) -> str:
    cleaned = (value or "").strip()
    return f"{label}: {cleaned}." if cleaned else ""


def _listed(label: str, values: Sequence[str]) -> str:
    items = [str(value).strip() for value in (values or []) if str(value or "").strip()]
    if not items:
        return ""
    return f"{label}: {', '.join(items[:BRIEFING_LIST_LIMIT])}."
