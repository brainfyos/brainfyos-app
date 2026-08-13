"""Brain Readiness -- quanto do Brain esta pronto para orientar agentes.

Regras do calculo:

* **Determinístico.** Nenhuma IA participa. A mesma base produz o mesmo numero.
* **Explicável.** Cada verificacao devolve peso, resultado e detalhe, para o
  frontend poder mostrar exatamente o que falta em vez de um numero opaco.
* **Sem metrica inventada.** Toda verificacao consulta uma fonte real. Quando a
  fonte nao existe, a verificacao nao entra na conta.

Os pesos refletem o quanto cada peca muda a qualidade do contexto entregue a um
agente: estrategia, ICP e oferta valem mais porque sao a parte que so a empresa
sabe. Volume de CRM vale menos porque cresce sozinho com o uso.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models import Company, Contact, Message
from backend.models.brain_models import (
    BrainBusinessProfile,
    BrainGoal,
    BrainIcpProfile,
    BrainOffer,
)
from backend.models.revenue_models import Contract


@dataclass(frozen=True)
class ReadinessCheck:
    key: str
    label: str
    weight: int
    done: bool
    detail: str
    # Onde o usuario resolve a pendencia. None quando nao ha acao direta.
    action_route: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "weight": self.weight,
            "done": self.done,
            "detail": self.detail,
            "action_route": self.action_route,
        }


@dataclass
class ReadinessReport:
    percent: int
    checks: List[ReadinessCheck] = field(default_factory=list)
    last_updated_at: Optional[datetime] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "percent": self.percent,
            "earned_weight": sum(check.weight for check in self.checks if check.done),
            "total_weight": sum(check.weight for check in self.checks),
            "checks": [check.as_dict() for check in self.checks],
            "missing": [check.as_dict() for check in self.checks if not check.done],
            "last_updated_at": self.last_updated_at.isoformat() if self.last_updated_at else None,
        }


# Peso de cada verificacao. Somam 100 para que o percentual seja lido
# diretamente, sem normalizacao escondida.
WEIGHTS = {
    "strategy_profile": 25,
    "icp_defined": 20,
    "primary_offer": 20,
    "active_goal": 10,
    "crm_contacts": 10,
    "conversations": 5,
    "ai_provider": 5,
    "channel_connected": 5,
}

# Um perfil so conta como preenchido com estes tres campos. Sao os que
# realmente mudam o comportamento de um agente; o resto e refinamento.
REQUIRED_PROFILE_FIELDS = ("business_model", "positioning", "value_proposition")


def calculate_readiness(db: Session, company_id: int) -> ReadinessReport:
    company_id = int(company_id)
    checks: List[ReadinessCheck] = []
    timestamps: List[datetime] = []

    profile = (
        db.query(BrainBusinessProfile)
        .filter(BrainBusinessProfile.company_id == company_id)
        .first()
    )
    if profile is not None and profile.updated_at:
        timestamps.append(profile.updated_at)

    filled = [
        field_name
        for field_name in REQUIRED_PROFILE_FIELDS
        if str(getattr(profile, field_name, "") or "").strip()
    ]
    checks.append(
        ReadinessCheck(
            key="strategy_profile",
            label="Perfil estratégico",
            weight=WEIGHTS["strategy_profile"],
            done=len(filled) == len(REQUIRED_PROFILE_FIELDS),
            detail=(
                "Modelo de negócio, posicionamento e proposta de valor preenchidos"
                if len(filled) == len(REQUIRED_PROFILE_FIELDS)
                else f"{len(filled)} de {len(REQUIRED_PROFILE_FIELDS)} campos essenciais preenchidos"
            ),
            action_route="/brain?tab=strategy",
        )
    )

    active_icps = (
        db.query(func.count(BrainIcpProfile.id))
        .filter(BrainIcpProfile.company_id == company_id, BrainIcpProfile.is_active.is_(True))
        .scalar()
        or 0
    )
    checks.append(
        ReadinessCheck(
            key="icp_defined",
            label="Cliente ideal (ICP)",
            weight=WEIGHTS["icp_defined"],
            done=active_icps > 0,
            detail=(
                f"{active_icps} ICP ativo" if active_icps == 1
                else f"{active_icps} ICPs ativos" if active_icps > 1
                else "Nenhum ICP definido"
            ),
            action_route="/brain?tab=icp",
        )
    )

    primary_offer = (
        db.query(func.count(BrainOffer.id))
        .filter(
            BrainOffer.company_id == company_id,
            BrainOffer.is_active.is_(True),
            BrainOffer.is_primary.is_(True),
        )
        .scalar()
        or 0
    )
    total_offers = (
        db.query(func.count(BrainOffer.id))
        .filter(BrainOffer.company_id == company_id, BrainOffer.is_active.is_(True))
        .scalar()
        or 0
    )
    checks.append(
        ReadinessCheck(
            key="primary_offer",
            label="Oferta principal",
            weight=WEIGHTS["primary_offer"],
            done=primary_offer > 0,
            detail=(
                "Oferta principal definida" if primary_offer > 0
                else f"{total_offers} ofertas cadastradas, nenhuma marcada como principal" if total_offers
                else "Nenhuma oferta cadastrada"
            ),
            action_route="/brain?tab=offers",
        )
    )

    active_goals = (
        db.query(func.count(BrainGoal.id))
        .filter(BrainGoal.company_id == company_id, BrainGoal.status == "active")
        .scalar()
        or 0
    )
    checks.append(
        ReadinessCheck(
            key="active_goal",
            label="Objetivos",
            weight=WEIGHTS["active_goal"],
            done=active_goals > 0,
            detail=(
                f"{active_goals} objetivo ativo" if active_goals == 1
                else f"{active_goals} objetivos ativos" if active_goals > 1
                else "Nenhum objetivo ativo"
            ),
            action_route="/brain?tab=goals",
        )
    )

    contacts = (
        db.query(func.count(Contact.id)).filter(Contact.company_id == company_id).scalar() or 0
    )
    checks.append(
        ReadinessCheck(
            key="crm_contacts",
            label="Contatos no CRM",
            weight=WEIGHTS["crm_contacts"],
            done=contacts > 0,
            detail=f"{contacts} contatos" if contacts else "Nenhum contato registrado",
            action_route="/contacts",
        )
    )

    messages = (
        db.query(func.count(Message.id)).filter(Message.company_id == company_id).scalar() or 0
    )
    checks.append(
        ReadinessCheck(
            key="conversations",
            label="Conversas",
            weight=WEIGHTS["conversations"],
            done=messages > 0,
            detail=f"{messages} mensagens" if messages else "Nenhuma conversa registrada",
            action_route="/chat",
        )
    )

    # Import tardio: ai_provider_service carrega o SDK da OpenAI, e o readiness
    # e chamado em telas que nao precisam desse custo no import do modulo.
    from backend.services.ai_provider_service import describe_company_ai_provider_mode

    provider_mode = describe_company_ai_provider_mode(db, company_id)
    checks.append(
        ReadinessCheck(
            key="ai_provider",
            label="Provedor de IA",
            weight=WEIGHTS["ai_provider"],
            done=provider_mode["operational"],
            detail=provider_mode["description"],
            action_route="/company/ai-provider",
        )
    )

    company = db.query(Company).filter(Company.id == company_id).first()
    whatsapp_connected = bool(
        company is not None and company.waha_enabled and company.waha_session_name
    )
    checks.append(
        ReadinessCheck(
            key="channel_connected",
            label="Canal de atendimento",
            weight=WEIGHTS["channel_connected"],
            done=whatsapp_connected,
            detail="WhatsApp conectado" if whatsapp_connected else "WhatsApp não conectado",
            action_route="/whatsapp",
        )
    )

    total_weight = sum(check.weight for check in checks)
    earned = sum(check.weight for check in checks if check.done)
    percent = round((earned / total_weight) * 100) if total_weight else 0

    for model in (BrainIcpProfile, BrainOffer, BrainGoal):
        latest = (
            db.query(func.max(model.updated_at)).filter(model.company_id == company_id).scalar()
        )
        if latest:
            timestamps.append(latest)

    return ReadinessReport(
        percent=percent,
        checks=checks,
        last_updated_at=max(timestamps) if timestamps else None,
    )


def describe_data_sources(db: Session, company_id: int) -> List[Dict[str, Any]]:
    """Fontes canonicas que o Brain ja enxerga.

    Serve a aba "Dados": mostra ao cliente o que o Brain consegue ler hoje.
    Nenhum data warehouse novo -- e uma leitura das tabelas que ja existem.
    """
    company_id = int(company_id)

    def count(model, *filters) -> int:
        return int(db.query(func.count(model.id)).filter(*filters).scalar() or 0)

    def latest(model, column) -> Optional[datetime]:
        return db.query(func.max(column)).filter(model.company_id == company_id).scalar()

    from backend.models import Lead, NPSResponse
    from backend.models.ai_credit_models import AIUsageEvent
    from backend.models.revenue_models import Invoice, Payment

    company = db.query(Company).filter(Company.id == company_id).first()

    contacts = count(Contact, Contact.company_id == company_id)
    leads = count(Lead, Lead.company_id == company_id)
    messages = count(Message, Message.company_id == company_id)
    contracts = count(Contract, Contract.company_id == company_id)
    invoices = count(Invoice, Invoice.company_id == company_id)
    payments = count(Payment, Payment.company_id == company_id)
    nps = count(NPSResponse, NPSResponse.company_id == company_id, NPSResponse.score.isnot(None))
    ai_events = count(AIUsageEvent, AIUsageEvent.company_id == company_id)

    return [
        _source("crm_contacts", "Contatos", "crm", contacts, latest(Contact, Contact.last_message_at)),
        _source("crm_leads", "Leads", "crm", leads, latest(Lead, Lead.created_at)),
        _source("conversations", "Conversas", "conversation", messages, latest(Message, Message.timestamp)),
        _source("contracts", "Contratos", "contract", contracts, latest(Contract, Contract.updated_at)),
        _source("invoices", "Faturas", "invoice", invoices, latest(Invoice, Invoice.updated_at)),
        _source("payments", "Pagamentos", "payment", payments, latest(Payment, Payment.created_at)),
        _source("nps", "NPS", "nps", nps, latest(NPSResponse, NPSResponse.answered_at)),
        _source("ai_usage", "Consumo de IA", "ai", ai_events, latest(AIUsageEvent, AIUsageEvent.created_at)),
        {
            "key": "whatsapp",
            "label": "WhatsApp",
            "source_type": "integration",
            # Integracao nao tem "quantidade": informar 0 sugeriria base vazia
            # em vez de canal desconectado.
            "record_count": None,
            "last_updated_at": None,
            "connected": bool(company and company.waha_enabled and company.waha_session_name),
        },
    ]


def _source(
    key: str,
    label: str,
    source_type: str,
    record_count: int,
    last_updated_at: Optional[datetime],
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "source_type": source_type,
        "record_count": record_count,
        "last_updated_at": last_updated_at.isoformat() if last_updated_at else None,
        "connected": record_count > 0,
    }
