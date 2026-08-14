"""Brain Context Engine.

Monta contexto confiavel para qualquer agente a partir das fontes que ja
existem. Um agente pede um escopo; recebe objetos normalizados com procedencia.

Tres decisoes que valem explicar:

**ORM e nao SQL cru.** O Control usa SQL cru porque precisa de LATERAL sobre
todas as empresas. Aqui cada consulta e de uma company so e cabe no ORM -- e o
ORM tem a vantagem de quebrar no import quando uma coluna some, em vez de
quebrar em producao quando alguem abre a tela.

**company_id e parametro obrigatorio, nunca herdado.** Toda consulta filtra por
ele explicitamente. Nao existe caminho em que uma consulta escape do escopo por
esquecimento: a assinatura obriga.

**Nada e copiado.** O engine le contacts, leads, messages, contracts, invoices,
payments e nps_responses onde eles vivem. Se um contrato mudar, a proxima
chamada ja reflete -- nao ha cache para envelhecer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from backend.models import (
    Agendamento,
    Company,
    Contact,
    ContactTag,
    Customer,
    Lead,
    Message,
    NPSResponse,
    Pipeline,
    PipelineStage,
    Tag,
)
from backend.models.brain_models import (
    BrainBusinessProfile,
    BrainGoal,
    BrainIcpProfile,
    BrainOffer,
)
from backend.models.revenue_models import Contract, Invoice, Payment, Plan
from backend.services.brain.schemas import (
    ALL_SCOPES,
    BrainContext,
    BrainScope,
    BusinessContext,
    ContactSummary,
    ContextBlock,
    ContractSummary,
    CustomerContext,
    CustomerSummary,
    FinancialContext,
    GoalContext,
    GoalSummary,
    IcpSummary,
    LeadSummary,
    MarketingContext,
    MeetingSummary,
    MessageSummary,
    OfferSummary,
    PipelineStageSummary,
    SalesContext,
    SalesMemorySummary,
    SourceRef,
    SourceType,
    StrategyContext,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/Sao_Paulo"
# Janela padrao das metricas de periodo. Casa com o ciclo de cobranca sem
# exigir varredura longa em messages.
DEFAULT_PERIOD_DAYS = 30
# Teto de itens por lista. O contexto vai para dentro de um prompt: uma lista
# longa custa token e afoga o sinal.
DEFAULT_LIMIT = 10
MAX_LIMIT = 50

# Valores reais dos CHECK em revenue_models.py. Nomeados aqui porque literais
# soltos numa query silenciosamente nao casam com nada e devolvem zero -- um
# erro que passa por "cliente sem faturas" em vez de estourar.
CONTRACT_STATUS_ACTIVE = "active"
INVOICE_STATUS_OPEN = "open"
INVOICE_STATUS_OVERDUE = "overdue"
INVOICE_STATUSES_RECEIVABLE = (INVOICE_STATUS_OPEN, INVOICE_STATUS_OVERDUE)
PAYMENT_STATUS_SUCCEEDED = "succeeded"


def _float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _string_list(value: Any) -> List[str]:
    """Normaliza uma coluna JSONB de lista para strings limpas."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


class BrainContextService:
    """Compositor de contexto. Uma instancia por sessao de banco."""

    def __init__(self, db: Session):
        self._db = db

    # ------------------------------------------------------------------
    # Entrada publica
    # ------------------------------------------------------------------

    def build(
        self,
        *,
        company_id: int,
        scopes: Optional[Sequence[str]] = None,
        lead_id: Optional[int] = None,
        contact_id: Optional[int] = None,
        customer_id: Optional[int] = None,
        limit: int = DEFAULT_LIMIT,
        period_days: int = DEFAULT_PERIOD_DAYS,
    ) -> BrainContext:
        if not company_id or int(company_id) <= 0:
            raise ValueError("company_id é obrigatório para montar contexto do Brain")

        company_id = int(company_id)
        limit = max(1, min(int(limit), MAX_LIMIT))
        requested = self._normalize_scopes(scopes)

        context = BrainContext(company_id=company_id, scopes=list(requested))

        # `business` sempre entra: um agente sem saber de que empresa fala nao
        # tem contexto nenhum, so fragmentos.
        context.business = self._build_business(company_id)

        if BrainScope.BUSINESS.value in requested:
            context.strategy = self._build_strategy(company_id)
            context.goals = self._build_goals(company_id)

        if BrainScope.SALES.value in requested:
            context.sales = self._build_sales(
                company_id, lead_id=lead_id, limit=limit, period_days=period_days
            )

        if BrainScope.CUSTOMER.value in requested:
            context.customer = self._build_customer(
                company_id,
                lead_id=lead_id,
                contact_id=contact_id,
                customer_id=customer_id,
                limit=limit,
            )

        if BrainScope.FINANCIAL.value in requested:
            context.financial = self._build_financial(
                company_id, customer_id=customer_id, limit=limit, period_days=period_days
            )

        if BrainScope.MARKETING.value in requested:
            context.marketing = MarketingContext(
                available=False,
                unavailable_reason=(
                    "Nenhuma fonte canônica de marketing está conectada. "
                    "Campanhas, anúncios e conteúdo chegam em fases seguintes."
                ),
            )

        return context

    @staticmethod
    def _normalize_scopes(scopes: Optional[Sequence[str]]) -> List[str]:
        if not scopes:
            return [BrainScope.BUSINESS.value]
        valid = [scope for scope in scopes if scope in ALL_SCOPES]
        return valid or [BrainScope.BUSINESS.value]

    # ------------------------------------------------------------------
    # Negocio
    # ------------------------------------------------------------------

    def _build_business(self, company_id: int) -> BusinessContext:
        # joinedload no business_type: sem ele, ler ``company.business_type``
        # abaixo dispara uma segunda consulta a cada montagem de contexto.
        company = (
            self._db.query(Company)
            .options(joinedload(Company.business_type))
            .filter(Company.id == company_id)
            .first()
        )
        if company is None:
            return BusinessContext(
                available=False,
                unavailable_reason="Empresa não encontrada",
                company_id=company_id,
                name="",
            )

        settings = company.settings if isinstance(company.settings, dict) else {}
        business_type = getattr(getattr(company, "business_type", None), "code", None)

        return BusinessContext(
            company_id=company_id,
            name=(company.name_company or company.name or "").strip(),
            legal_name=company.name,
            business_type=business_type,
            timezone=str(settings.get("timezone") or DEFAULT_TIMEZONE),
            created_at=company.created_at,
            sources=[SourceRef(source_type=SourceType.COMPANY, table="companies", record_ids=[company_id])],
        )

    # ------------------------------------------------------------------
    # Estrategia
    # ------------------------------------------------------------------

    def _build_strategy(self, company_id: int) -> StrategyContext:
        profile = (
            self._db.query(BrainBusinessProfile)
            .filter(BrainBusinessProfile.company_id == company_id)
            .first()
        )

        icps = (
            self._db.query(BrainIcpProfile)
            .filter(
                BrainIcpProfile.company_id == company_id,
                BrainIcpProfile.is_active.is_(True),
            )
            .order_by(BrainIcpProfile.priority.asc(), BrainIcpProfile.id.asc())
            .all()
        )

        offers = (
            self._db.query(BrainOffer)
            .filter(
                BrainOffer.company_id == company_id,
                BrainOffer.is_active.is_(True),
            )
            .order_by(BrainOffer.is_primary.desc(), BrainOffer.id.asc())
            .all()
        )

        icp_names = {icp.id: icp.name for icp in icps}
        plan_map = self._plans_for_offers(company_id, offers)

        icp_summaries = [self._icp_summary(icp) for icp in icps]
        offer_summaries = [self._offer_summary(offer, icp_names, plan_map) for offer in offers]
        primary = next((summary for summary in offer_summaries if summary.is_primary), None)

        sources: List[SourceRef] = []
        if profile is not None:
            sources.append(
                SourceRef(
                    source_type=SourceType.STRATEGY,
                    table="brain_business_profiles",
                    record_ids=[profile.id],
                )
            )
        if icps:
            sources.append(
                SourceRef(
                    source_type=SourceType.ICP,
                    table="brain_icp_profiles",
                    record_count=len(icps),
                    record_ids=[icp.id for icp in icps],
                )
            )
        if offers:
            sources.append(
                SourceRef(
                    source_type=SourceType.OFFER,
                    table="brain_offers",
                    record_count=len(offers),
                    record_ids=[offer.id for offer in offers],
                )
            )

        has_anything = profile is not None or bool(icps) or bool(offers)

        return StrategyContext(
            available=has_anything,
            unavailable_reason=None if has_anything else "Estratégia ainda não preenchida no Brain",
            business_model=getattr(profile, "business_model", None),
            market=getattr(profile, "market", None),
            positioning=getattr(profile, "positioning", None),
            value_proposition=getattr(profile, "value_proposition", None),
            revenue_model=getattr(profile, "revenue_model", None),
            sales_motion=getattr(profile, "sales_motion", None),
            additional_context=getattr(profile, "additional_context", None),
            competitive_advantages=_string_list(getattr(profile, "competitive_advantages", None)),
            main_channels=_string_list(getattr(profile, "main_channels", None)),
            strategic_priorities=_string_list(getattr(profile, "strategic_priorities", None)),
            constraints=_string_list(getattr(profile, "constraints", None)),
            icps=icp_summaries,
            offers=offer_summaries,
            primary_offer=primary,
            updated_at=getattr(profile, "updated_at", None),
            sources=sources,
        )

    def _plans_for_offers(self, company_id: int, offers: Iterable[BrainOffer]) -> Dict[int, Plan]:
        """Carrega os planos referenciados de uma vez -- nada de N+1.

        O filtro por company_id e redundante com a FK, e permanece de proposito:
        se uma oferta apontar para plano de outra empresa por dado corrompido,
        o vazamento e cortado aqui em vez de virar contexto.
        """
        plan_ids = {offer.related_plan_id for offer in offers if offer.related_plan_id}
        if not plan_ids:
            return {}
        plans = (
            self._db.query(Plan)
            .filter(Plan.id.in_(plan_ids), Plan.company_id == company_id)
            .all()
        )
        return {plan.id: plan for plan in plans}

    @staticmethod
    def _icp_summary(icp: BrainIcpProfile) -> IcpSummary:
        return IcpSummary(
            id=icp.id,
            name=icp.name,
            description=icp.description,
            customer_type=icp.customer_type,
            industry=icp.industry,
            company_size=icp.company_size,
            location=icp.location,
            average_ticket=_float(icp.average_ticket),
            priority=int(icp.priority or 1),
            pain_points=_string_list(icp.pain_points),
            desired_outcomes=_string_list(icp.desired_outcomes),
            buying_triggers=_string_list(icp.buying_triggers),
            objections=_string_list(icp.objections),
            qualification_criteria=_string_list(icp.qualification_criteria),
            disqualification_criteria=_string_list(icp.disqualification_criteria),
        )

    @staticmethod
    def _offer_summary(
        offer: BrainOffer,
        icp_names: Dict[int, str],
        plan_map: Dict[int, Plan],
    ) -> OfferSummary:
        plan = plan_map.get(offer.related_plan_id) if offer.related_plan_id else None

        # Plan e dono do preco. A estimativa da oferta so aparece quando nao
        # ha plano -- caso contrario o agente veria dois numeros e teria que
        # escolher entre eles.
        if plan is not None:
            ticket = _float(plan.price)
            ticket_source = "plan"
        else:
            ticket = _float(offer.average_ticket)
            ticket_source = "offer" if ticket is not None else None

        return OfferSummary(
            id=offer.id,
            name=offer.name,
            description=offer.description,
            promise=offer.promise,
            mechanism=offer.mechanism,
            pricing_strategy=offer.pricing_strategy,
            average_ticket=ticket,
            ticket_source=ticket_source,
            sales_cycle_days=offer.sales_cycle_days,
            main_objections=_string_list(offer.main_objections),
            proof_points=_string_list(offer.proof_points),
            target_icp_id=offer.target_icp_id,
            target_icp_name=icp_names.get(offer.target_icp_id) if offer.target_icp_id else None,
            related_plan_id=offer.related_plan_id,
            related_plan_name=plan.name if plan is not None else None,
            is_primary=bool(offer.is_primary),
        )

    # ------------------------------------------------------------------
    # Objetivos
    # ------------------------------------------------------------------

    def _build_goals(self, company_id: int) -> GoalContext:
        goals = (
            self._db.query(BrainGoal)
            .filter(BrainGoal.company_id == company_id, BrainGoal.status == "active")
            .order_by(BrainGoal.priority.asc(), BrainGoal.id.asc())
            .all()
        )

        return GoalContext(
            available=bool(goals),
            unavailable_reason=None if goals else "Nenhum objetivo ativo definido",
            goals=[
                GoalSummary(
                    id=goal.id,
                    name=goal.name,
                    description=goal.description,
                    metric_key=goal.metric_key,
                    baseline_value=_float(goal.baseline_value),
                    target_value=_float(goal.target_value),
                    unit=goal.unit,
                    period_start=goal.period_start,
                    period_end=goal.period_end,
                    priority=int(goal.priority or 1),
                    status=goal.status,
                )
                for goal in goals
            ],
            sources=(
                [
                    SourceRef(
                        source_type=SourceType.GOAL,
                        table="brain_goals",
                        record_count=len(goals),
                        record_ids=[goal.id for goal in goals],
                    )
                ]
                if goals
                else []
            ),
        )

    # ------------------------------------------------------------------
    # Comercial
    # ------------------------------------------------------------------

    def _build_sales(
        self,
        company_id: int,
        *,
        lead_id: Optional[int],
        limit: int,
        period_days: int,
    ) -> SalesContext:
        since = datetime.now(timezone.utc) - timedelta(days=period_days)

        pipeline = (
            self._db.query(Pipeline)
            .filter(Pipeline.company_id == company_id, Pipeline.is_active.is_(True))
            .order_by(Pipeline.id.asc())
            .first()
        )

        stages: List[PipelineStageSummary] = []
        stage_names: Dict[int, str] = {}
        if pipeline is not None:
            stage_rows = (
                self._db.query(
                    PipelineStage.id,
                    PipelineStage.name,
                    PipelineStage.order,
                    PipelineStage.is_converted_stage,
                    PipelineStage.is_lost_stage,
                    func.count(Lead.id).label("lead_count"),
                )
                .outerjoin(
                    Lead,
                    (Lead.current_stage_id == PipelineStage.id) & (Lead.company_id == company_id),
                )
                .filter(PipelineStage.pipeline_id == pipeline.id)
                .group_by(
                    PipelineStage.id,
                    PipelineStage.name,
                    PipelineStage.order,
                    PipelineStage.is_converted_stage,
                    PipelineStage.is_lost_stage,
                )
                .order_by(PipelineStage.order.asc())
                .all()
            )
            for row in stage_rows:
                stage_names[row.id] = row.name
                stages.append(
                    PipelineStageSummary(
                        id=row.id,
                        name=row.name,
                        order=int(row.order or 0),
                        is_converted_stage=bool(row.is_converted_stage),
                        is_lost_stage=bool(row.is_lost_stage),
                        lead_count=int(row.lead_count or 0),
                    )
                )

        total_leads = (
            self._db.query(func.count(Lead.id)).filter(Lead.company_id == company_id).scalar() or 0
        )
        leads_in_period = (
            self._db.query(func.count(Lead.id))
            .filter(Lead.company_id == company_id, Lead.created_at >= since)
            .scalar()
            or 0
        )

        converted_stage_ids = [stage.id for stage in stages if stage.is_converted_stage]
        lost_stage_ids = [stage.id for stage in stages if stage.is_lost_stage]
        converted = self._leads_moved_into(company_id, converted_stage_ids, since)
        lost = self._leads_moved_into(company_id, lost_stage_ids, since)

        recent = (
            self._db.query(Lead)
            .filter(Lead.company_id == company_id)
            .order_by(Lead.created_at.desc().nullslast(), Lead.id.desc())
            .limit(limit)
            .all()
        )

        focus: Optional[LeadSummary] = None
        if lead_id:
            focus_lead = (
                self._db.query(Lead)
                .filter(Lead.id == lead_id, Lead.company_id == company_id)
                .first()
            )
            if focus_lead is not None:
                focus = self._lead_summary(focus_lead, pipeline, stage_names)

        sources = [
            SourceRef(
                source_type=SourceType.CRM,
                table="leads",
                record_count=total_leads,
                record_ids=[lead.id for lead in recent] or None,
            )
        ]
        if pipeline is not None:
            sources.append(
                SourceRef(
                    source_type=SourceType.CRM,
                    table="pipeline_stages",
                    record_count=len(stages),
                    record_ids=[stage.id for stage in stages],
                )
            )

        meetings = self._recent_meetings(company_id, lead_id=lead_id, limit=limit)
        if meetings:
            sources.append(
                SourceRef(
                    source_type=SourceType.MEETING,
                    table="meetings",
                    record_count=len(meetings),
                    record_ids=[meeting.id for meeting in meetings],
                )
            )

        memory = self._sales_memory(company_id, lead_id) if lead_id else None
        if memory is not None:
            sources.append(
                SourceRef(source_type=SourceType.SALES_MEMORY, table="sales_memories")
            )

        return SalesContext(
            recent_meetings=meetings,
            sales_memory=memory,
            available=pipeline is not None or total_leads > 0,
            unavailable_reason=(
                None if (pipeline is not None or total_leads > 0) else "Nenhum pipeline ou lead cadastrado"
            ),
            pipeline_id=pipeline.id if pipeline else None,
            pipeline_name=pipeline.name if pipeline else None,
            stages=stages,
            total_leads=int(total_leads),
            leads_in_period=int(leads_in_period),
            converted_in_period=converted,
            lost_in_period=lost,
            focus_lead=focus,
            recent_leads=[self._lead_summary(lead, pipeline, stage_names) for lead in recent],
            sources=sources,
        )

    def _leads_moved_into(self, company_id: int, stage_ids: List[int], since: datetime) -> int:
        """Conversoes contadas pelo historico, nao pelo estado atual.

        Olhar so ``leads.current_stage_id`` perderia todo lead que converteu e
        depois foi movido, e contaria uma conversao antiga como se fosse do
        periodo.
        """
        if not stage_ids:
            return 0
        from backend.models import LeadPipelineHistory

        return int(
            self._db.query(func.count(func.distinct(LeadPipelineHistory.lead_id)))
            .filter(
                LeadPipelineHistory.company_id == company_id,
                LeadPipelineHistory.to_stage_id.in_(stage_ids),
                LeadPipelineHistory.moved_at >= since,
            )
            .scalar()
            or 0
        )

    @staticmethod
    def _lead_summary(
        lead: Lead,
        pipeline: Optional[Pipeline],
        stage_names: Dict[int, str],
    ) -> LeadSummary:
        return LeadSummary(
            id=lead.id,
            name=lead.name,
            phone=lead.phone,
            created_at=lead.created_at,
            pipeline_id=lead.pipeline_id or (pipeline.id if pipeline else None),
            pipeline_name=pipeline.name if pipeline and lead.pipeline_id == pipeline.id else None,
            stage_id=lead.current_stage_id,
            stage_name=stage_names.get(lead.current_stage_id) if lead.current_stage_id else None,
            entered_stage_at=lead.pipeline_entered_at,
            deal_value=_float(lead.deal_value),
            source=lead.source_id,
        )

    # ------------------------------------------------------------------
    # Cliente
    # ------------------------------------------------------------------

    def _build_customer(
        self,
        company_id: int,
        *,
        lead_id: Optional[int],
        contact_id: Optional[int],
        customer_id: Optional[int],
        limit: int,
    ) -> CustomerContext:
        contact = self._resolve_contact(company_id, lead_id=lead_id, contact_id=contact_id, customer_id=customer_id)
        customer = self._resolve_customer(company_id, customer_id=customer_id, contact=contact)

        if contact is None and customer is None:
            return CustomerContext(
                available=False,
                unavailable_reason=(
                    "Informe lead_id, contact_id ou customer_id para montar contexto de cliente"
                ),
            )

        phone = (contact.phone if contact else None) or (customer.telefone if customer else None)

        messages: List[MessageSummary] = []
        message_count = 0
        if phone:
            message_count = (
                self._db.query(func.count(Message.id))
                .filter(Message.company_id == company_id, Message.contact_phone == phone)
                .scalar()
                or 0
            )
            rows = (
                self._db.query(Message)
                .filter(Message.company_id == company_id, Message.contact_phone == phone)
                .order_by(Message.timestamp.desc(), Message.id.desc())
                .limit(limit)
                .all()
            )
            # Reordenado para leitura cronologica: um historico invertido faz o
            # modelo interpretar a resposta como pergunta.
            messages = [
                MessageSummary(
                    from_me=bool(row.from_me),
                    content=row.content or "",
                    message_type=row.message_type or "text",
                    timestamp=row.timestamp,
                )
                for row in reversed(rows)
            ]

        nps_score = None
        if phone:
            nps_row = (
                self._db.query(NPSResponse.score)
                .filter(
                    NPSResponse.company_id == company_id,
                    NPSResponse.contact_phone == phone,
                    NPSResponse.score.isnot(None),
                )
                .order_by(NPSResponse.answered_at.desc().nullslast(), NPSResponse.id.desc())
                .first()
            )
            nps_score = int(nps_row[0]) if nps_row and nps_row[0] is not None else None

        appointments = self._upcoming_appointments(company_id, phone=phone, limit=limit)

        sources: List[SourceRef] = []
        if contact is not None:
            sources.append(SourceRef(source_type=SourceType.CRM, table="contacts", record_ids=[contact.id]))
        if customer is not None:
            sources.append(
                SourceRef(source_type=SourceType.CUSTOMER, table="customers", record_ids=[customer.id])
            )
        if message_count:
            sources.append(
                SourceRef(source_type=SourceType.CONVERSATION, table="messages", record_count=int(message_count))
            )
        if nps_score is not None:
            sources.append(SourceRef(source_type=SourceType.NPS, table="nps_responses", record_count=1))

        contact_meetings = self._recent_meetings(
            company_id, contact_id=contact.id if contact else None, limit=limit
        )
        if contact_meetings:
            sources.append(
                SourceRef(
                    source_type=SourceType.MEETING,
                    table="meetings",
                    record_count=len(contact_meetings),
                    record_ids=[meeting.id for meeting in contact_meetings],
                )
            )

        return CustomerContext(
            recent_meetings=contact_meetings,
            contact=self._contact_summary(contact) if contact else None,
            customer=self._customer_summary(customer) if customer else None,
            recent_messages=messages,
            message_count=int(message_count),
            nps_score=nps_score,
            upcoming_appointments=appointments,
            sources=sources,
        )

    def _resolve_contact(
        self,
        company_id: int,
        *,
        lead_id: Optional[int],
        contact_id: Optional[int],
        customer_id: Optional[int],
    ) -> Optional[Contact]:
        if contact_id:
            return (
                self._db.query(Contact)
                .filter(Contact.id == contact_id, Contact.company_id == company_id)
                .first()
            )

        if customer_id:
            customer = (
                self._db.query(Customer)
                .filter(Customer.id == customer_id, Customer.company_id == company_id)
                .first()
            )
            if customer is not None:
                return (
                    self._db.query(Contact)
                    .filter(Contact.id == customer.contact_id, Contact.company_id == company_id)
                    .first()
                )
            return None

        if lead_id:
            lead = (
                self._db.query(Lead)
                .filter(Lead.id == lead_id, Lead.company_id == company_id)
                .first()
            )
            if lead is not None and lead.phone:
                return (
                    self._db.query(Contact)
                    .filter(Contact.company_id == company_id, Contact.phone == lead.phone)
                    .first()
                )

        return None

    def _resolve_customer(
        self,
        company_id: int,
        *,
        customer_id: Optional[int],
        contact: Optional[Contact],
    ) -> Optional[Customer]:
        if customer_id:
            return (
                self._db.query(Customer)
                .filter(Customer.id == customer_id, Customer.company_id == company_id)
                .first()
            )
        if contact is not None:
            return (
                self._db.query(Customer)
                .filter(Customer.contact_id == contact.id, Customer.company_id == company_id)
                .first()
            )
        return None

    def _contact_summary(self, contact: Contact) -> ContactSummary:
        tag_rows = (
            self._db.query(Tag.name)
            .join(ContactTag, ContactTag.tag_id == Tag.id)
            .filter(ContactTag.contact_id == contact.id, Tag.company_id == contact.company_id)
            .all()
        )
        return ContactSummary(
            id=contact.id,
            name=contact.name,
            phone=contact.phone,
            human_mode=bool(contact.human_mode),
            last_message_at=contact.last_message_at,
            unread_count=int(contact.unread_count or 0),
            tags=[row[0] for row in tag_rows],
        )

    @staticmethod
    def _customer_summary(customer: Customer) -> CustomerSummary:
        return CustomerSummary(
            id=customer.id,
            name=customer.nome,
            phone=customer.telefone,
            email=customer.email,
            status=customer.status,
            category=customer.categoria,
            first_visit_at=customer.primeira_consulta,
            last_visit_at=customer.ultima_consulta,
            total_visits=int(customer.total_consultas or 0),
            lifetime_value=_float(customer.valor_total_tratamentos),
        )

    def _upcoming_appointments(
        self,
        company_id: int,
        *,
        phone: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        if not phone:
            return []
        rows = (
            self._db.query(Agendamento)
            .filter(
                Agendamento.company_id == company_id,
                Agendamento.phone == phone,
                Agendamento.consulta_data >= datetime.now(timezone.utc),
            )
            .order_by(Agendamento.consulta_data.asc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": row.id,
                "scheduled_for": row.consulta_data.isoformat() if row.consulta_data else None,
                "status": row.status,
                "interest": row.interesse,
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Reunioes
    # ------------------------------------------------------------------

    def _recent_meetings(
        self,
        company_id: int,
        *,
        lead_id: Optional[int] = None,
        contact_id: Optional[int] = None,
        limit: int = DEFAULT_LIMIT,
    ) -> List[MeetingSummary]:
        """Reunioes como resumo estruturado -- nunca a transcricao.

        A transcricao inteira num prompt gasta o orcamento de token e afoga o
        sinal. ``has_transcript`` diz que o detalhe existe; quem precisar dele
        busca pelo endpoint proprio.
        """
        from backend.models.meeting_models import Meeting, MeetingAnalysis

        if lead_id is None and contact_id is None:
            return []

        query = (
            self._db.query(Meeting)
            .filter(Meeting.company_id == company_id)
        )
        if lead_id is not None:
            query = query.filter(Meeting.lead_id == int(lead_id))
        else:
            query = query.filter(Meeting.contact_id == int(contact_id))

        meetings = (
            query.order_by(Meeting.scheduled_start_at.desc().nullslast(), Meeting.id.desc())
            .limit(limit)
            .all()
        )
        if not meetings:
            return []

        # Uma consulta para todas as analises; sem isto seria um SELECT por
        # reuniao dentro do laco.
        analyses = (
            self._db.query(MeetingAnalysis)
            .filter(
                MeetingAnalysis.company_id == company_id,
                MeetingAnalysis.meeting_id.in_([meeting.id for meeting in meetings]),
            )
            .order_by(MeetingAnalysis.analysis_version.asc())
            .all()
        )
        latest: Dict[int, Any] = {}
        for analysis in analyses:
            latest[analysis.meeting_id] = analysis

        summaries: List[MeetingSummary] = []
        for meeting in meetings:
            analysis = latest.get(meeting.id)
            summaries.append(
                MeetingSummary(
                    id=meeting.id,
                    title=meeting.title,
                    occurred_at=meeting.scheduled_start_at,
                    duration_minutes=(
                        round(meeting.duration_seconds / 60) if meeting.duration_seconds else None
                    ),
                    provider=meeting.provider,
                    status=meeting.status,
                    summary=getattr(analysis, "summary", None),
                    main_problem=getattr(analysis, "main_problem", None),
                    sentiment=getattr(analysis, "sentiment", None),
                    objections=_string_list(getattr(analysis, "objections", None)),
                    next_steps=_string_list(getattr(analysis, "next_steps", None)),
                    commitments_company=_string_list(getattr(analysis, "commitments_company", None)),
                    commitments_customer=_string_list(getattr(analysis, "commitments_customer", None)),
                    has_transcript=meeting.transcript_status == "imported",
                )
            )
        return summaries

    def _sales_memory(self, company_id: int, lead_id: int) -> Optional[SalesMemorySummary]:
        from backend.models.meeting_models import SalesMemory

        memory = (
            self._db.query(SalesMemory)
            .filter(SalesMemory.company_id == company_id, SalesMemory.lead_id == int(lead_id))
            .first()
        )
        if memory is None:
            return None

        return SalesMemorySummary(
            current_summary=memory.current_summary,
            business_problem=memory.business_problem,
            next_best_action=memory.next_best_action,
            confidence=memory.confidence,
            objections=_string_list(memory.objections),
            risks=_string_list(memory.risks),
            buying_signals=_string_list(memory.buying_signals),
            open_questions=_string_list(memory.open_questions),
            last_rebuilt_at=memory.last_rebuilt_at,
        )

    # ------------------------------------------------------------------
    # Financeiro
    # ------------------------------------------------------------------

    def _build_financial(
        self,
        company_id: int,
        *,
        customer_id: Optional[int],
        limit: int,
        period_days: int,
    ) -> FinancialContext:
        since = datetime.now(timezone.utc) - timedelta(days=period_days)

        contract_query = self._db.query(Contract).filter(Contract.company_id == company_id)
        invoice_query = self._db.query(Invoice).filter(Invoice.company_id == company_id)
        payment_query = self._db.query(Payment).filter(Payment.company_id == company_id)

        # Quando ha um cliente em foco, o bloco fala dele; sem foco, fala da
        # empresa inteira. Os dois usos existem: Sales Agent quer um, Management
        # Agent quer o outro.
        if customer_id:
            contract_query = contract_query.filter(Contract.customer_id == customer_id)
            invoice_query = invoice_query.filter(Invoice.customer_id == customer_id)
            payment_query = payment_query.filter(Payment.customer_id == customer_id)

        totals = contract_query.with_entities(
            func.count(Contract.id),
            func.sum(Contract.total_value),
            func.sum(Contract.total_paid),
        ).filter(Contract.status == CONTRACT_STATUS_ACTIVE).one()

        active_contracts = int(totals[0] or 0)
        total_value = _float(totals[1])
        total_paid = _float(totals[2])

        open_invoices = int(
            invoice_query.with_entities(func.count(Invoice.id))
            .filter(Invoice.status == INVOICE_STATUS_OPEN)
            .scalar()
            or 0
        )
        overdue_invoices = int(
            invoice_query.with_entities(func.count(Invoice.id))
            .filter(Invoice.status == INVOICE_STATUS_OVERDUE)
            .scalar()
            or 0
        )
        open_amount = _float(
            invoice_query.with_entities(func.sum(Invoice.total - Invoice.amount_paid))
            .filter(Invoice.status.in_(INVOICE_STATUSES_RECEIVABLE))
            .scalar()
        )
        paid_in_period = _float(
            payment_query.with_entities(func.sum(Payment.amount))
            .filter(Payment.status == PAYMENT_STATUS_SUCCEEDED, Payment.payment_date >= since)
            .scalar()
        )

        contracts = (
            contract_query.order_by(Contract.start_date.desc().nullslast(), Contract.id.desc())
            .limit(limit)
            .all()
        )

        has_data = active_contracts > 0 or open_invoices > 0 or bool(contracts)

        return FinancialContext(
            available=has_data,
            unavailable_reason=None if has_data else "Nenhum contrato ou fatura registrado",
            active_contracts=active_contracts,
            total_contract_value=total_value,
            total_paid=total_paid,
            open_invoices=open_invoices,
            overdue_invoices=overdue_invoices,
            open_invoice_amount=open_amount,
            paid_in_period=paid_in_period,
            contracts=[
                ContractSummary(
                    id=contract.id,
                    status=contract.status,
                    start_date=contract.start_date,
                    end_date=contract.end_date,
                    total_value=_float(contract.total_value),
                    total_paid=_float(contract.total_paid),
                    payment_method=contract.payment_method,
                )
                for contract in contracts
            ],
            sources=[
                SourceRef(
                    source_type=SourceType.CONTRACT,
                    table="contracts",
                    record_count=active_contracts,
                    record_ids=[contract.id for contract in contracts] or None,
                ),
                SourceRef(source_type=SourceType.INVOICE, table="invoices", record_count=open_invoices),
                SourceRef(source_type=SourceType.PAYMENT, table="payments"),
            ],
        )
