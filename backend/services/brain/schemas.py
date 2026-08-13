"""Contratos do contexto do Brain.

Um agente nao deve precisar conhecer vinte tabelas. Ele pede um escopo e
recebe estes objetos -- normalizados, sem ORM, sem campo que ele nao va usar.

Duas regras que sustentam o desenho:

1. **Nada de objeto ORM atravessa esta fronteira.** Entregar uma entidade
   viva convidaria o agente a navegar relacionamentos e disparar consultas
   fora de qualquer escopo de company.

2. **Todo bloco declara sua origem.** ``sources`` diz de onde cada informacao
   veio. Sem isso, um agente que afirma "o cliente tem 3 contratos ativos" nao
   consegue provar; com isso, a afirmacao e rastreavel ate a linha.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BrainScope(str, Enum):
    """Fatias de contexto que um chamador pode pedir."""

    BUSINESS = "business"
    SALES = "sales"
    CUSTOMER = "customer"
    FINANCIAL = "financial"
    MARKETING = "marketing"


ALL_SCOPES = tuple(scope.value for scope in BrainScope)
DEFAULT_SCOPES = (BrainScope.BUSINESS.value,)


class SourceType(str, Enum):
    """Procedencia de um bloco de contexto.

    Separa o que a empresa *declarou* (strategy, icp, offer, goal) do que o
    sistema *observou* (crm, conversation, contract, ...). A distincao importa:
    um agente pode contestar uma estrategia desatualizada, mas nao deveria
    contestar o numero de faturas pagas.
    """

    COMPANY = "company"
    STRATEGY = "strategy"
    ICP = "icp"
    OFFER = "offer"
    GOAL = "goal"
    CRM = "crm"
    CONVERSATION = "conversation"
    CUSTOMER = "customer"
    CONTRACT = "contract"
    INVOICE = "invoice"
    PAYMENT = "payment"
    NPS = "nps"


class SourceRef(BaseModel):
    """Rastro minimo de onde a informacao veio.

    Deliberadamente raso: tipo, tabela, quantidade e -- quando ha poucas --
    as chaves. Um sistema completo de lineage nao se justifica ainda.
    """

    source_type: SourceType
    table: str
    record_count: Optional[int] = None
    record_ids: Optional[List[int]] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ContextBlock(BaseModel):
    """Base de todo bloco: presenca de dado e procedencia explicitas."""

    available: bool = True
    # Preenchido quando ``available`` e falso. Um bloco vazio nunca fica mudo:
    # o agente precisa distinguir "nao ha clientes" de "nao consultei".
    unavailable_reason: Optional[str] = None
    sources: List[SourceRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Negocio e estrategia
# ---------------------------------------------------------------------------

class BusinessContext(ContextBlock):
    """Identidade da empresa. Sempre presente."""

    company_id: int
    name: str
    legal_name: Optional[str] = None
    business_type: Optional[str] = None
    timezone: str = "America/Sao_Paulo"
    created_at: Optional[datetime] = None


class IcpSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    customer_type: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    location: Optional[str] = None
    average_ticket: Optional[float] = None
    priority: int = 1
    pain_points: List[str] = Field(default_factory=list)
    desired_outcomes: List[str] = Field(default_factory=list)
    buying_triggers: List[str] = Field(default_factory=list)
    objections: List[str] = Field(default_factory=list)
    qualification_criteria: List[str] = Field(default_factory=list)
    disqualification_criteria: List[str] = Field(default_factory=list)


class OfferSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    promise: Optional[str] = None
    mechanism: Optional[str] = None
    pricing_strategy: Optional[str] = None
    # Vem de ``plans.price`` quando ha plano associado; so entao
    # ``ticket_source`` diz 'plan'. Sem plano, e a estimativa da propria oferta.
    average_ticket: Optional[float] = None
    ticket_source: Optional[str] = None
    sales_cycle_days: Optional[int] = None
    main_objections: List[str] = Field(default_factory=list)
    proof_points: List[str] = Field(default_factory=list)
    target_icp_id: Optional[int] = None
    target_icp_name: Optional[str] = None
    related_plan_id: Optional[int] = None
    related_plan_name: Optional[str] = None
    is_primary: bool = False


class StrategyContext(ContextBlock):
    """Como a empresa quer competir. Declarado, nao observado."""

    business_model: Optional[str] = None
    market: Optional[str] = None
    positioning: Optional[str] = None
    value_proposition: Optional[str] = None
    revenue_model: Optional[str] = None
    sales_motion: Optional[str] = None
    additional_context: Optional[str] = None
    competitive_advantages: List[str] = Field(default_factory=list)
    main_channels: List[str] = Field(default_factory=list)
    strategic_priorities: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    icps: List[IcpSummary] = Field(default_factory=list)
    offers: List[OfferSummary] = Field(default_factory=list)
    primary_offer: Optional[OfferSummary] = None
    updated_at: Optional[datetime] = None


class GoalSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    metric_key: Optional[str] = None
    baseline_value: Optional[float] = None
    target_value: Optional[float] = None
    unit: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    priority: int = 1
    status: str = "active"


class GoalContext(ContextBlock):
    """Metas ativas, em ordem de prioridade."""

    goals: List[GoalSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Operacao
# ---------------------------------------------------------------------------

class PipelineStageSummary(BaseModel):
    id: int
    name: str
    order: int
    is_converted_stage: bool = False
    is_lost_stage: bool = False
    lead_count: int = 0


class LeadSummary(BaseModel):
    id: int
    name: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[datetime] = None
    pipeline_id: Optional[int] = None
    pipeline_name: Optional[str] = None
    stage_id: Optional[int] = None
    stage_name: Optional[str] = None
    entered_stage_at: Optional[datetime] = None
    deal_value: Optional[float] = None
    source: Optional[str] = None


class SalesContext(ContextBlock):
    """Estado comercial: funil, volumes e -- quando pedido -- um lead."""

    pipeline_id: Optional[int] = None
    pipeline_name: Optional[str] = None
    stages: List[PipelineStageSummary] = Field(default_factory=list)
    total_leads: int = 0
    leads_in_period: int = 0
    converted_in_period: int = 0
    lost_in_period: int = 0
    focus_lead: Optional[LeadSummary] = None
    recent_leads: List[LeadSummary] = Field(default_factory=list)


class MessageSummary(BaseModel):
    from_me: bool
    content: str
    message_type: str
    timestamp: Optional[datetime] = None


class ContactSummary(BaseModel):
    id: int
    name: Optional[str] = None
    phone: str
    human_mode: bool = False
    last_message_at: Optional[datetime] = None
    unread_count: int = 0
    tags: List[str] = Field(default_factory=list)


class CustomerSummary(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    first_visit_at: Optional[datetime] = None
    last_visit_at: Optional[datetime] = None
    total_visits: int = 0
    lifetime_value: Optional[float] = None


class CustomerContext(ContextBlock):
    """A pessoa do outro lado: contato, cliente e conversa recente."""

    contact: Optional[ContactSummary] = None
    customer: Optional[CustomerSummary] = None
    recent_messages: List[MessageSummary] = Field(default_factory=list)
    message_count: int = 0
    nps_score: Optional[int] = None
    upcoming_appointments: List[Dict[str, Any]] = Field(default_factory=list)


class ContractSummary(BaseModel):
    id: int
    status: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    total_value: Optional[float] = None
    total_paid: Optional[float] = None
    payment_method: Optional[str] = None


class FinancialContext(ContextBlock):
    """Receita observada. Todos os numeros vem de contracts/invoices/payments."""

    active_contracts: int = 0
    total_contract_value: Optional[float] = None
    total_paid: Optional[float] = None
    open_invoices: int = 0
    overdue_invoices: int = 0
    open_invoice_amount: Optional[float] = None
    paid_in_period: Optional[float] = None
    contracts: List[ContractSummary] = Field(default_factory=list)


class MarketingContext(ContextBlock):
    """Reservado. Nenhuma fonte canonica de marketing existe ainda."""

    pass


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

class BrainContext(BaseModel):
    """Resposta do Context Engine.

    Um bloco ausente significa "escopo nao pedido"; um bloco presente com
    ``available=False`` significa "pedido, mas nao ha dado" -- e diz por que.
    """

    company_id: int
    scopes: List[str]
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    business: Optional[BusinessContext] = None
    strategy: Optional[StrategyContext] = None
    goals: Optional[GoalContext] = None
    sales: Optional[SalesContext] = None
    customer: Optional[CustomerContext] = None
    financial: Optional[FinancialContext] = None
    marketing: Optional[MarketingContext] = None

    def all_sources(self) -> List[SourceRef]:
        """Lineage consolidado de tudo que entrou nesta resposta."""
        collected: List[SourceRef] = []
        for block in (
            self.business, self.strategy, self.goals,
            self.sales, self.customer, self.financial, self.marketing,
        ):
            if block is not None:
                collected.extend(block.sources)
        return collected
