"""Escrita e leitura das entidades de estrategia do Brain.

Toda funcao recebe ``company_id`` e o aplica em cada consulta. Nenhuma delas
aceita uma entidade ja carregada pelo chamador -- resolver por id **e**
company_id aqui e o que garante que trocar um id na URL nao alcance outro
workspace.

Remocao e sempre logica. Uma oferta aponta para ICP e plano, e um objetivo
concluido e historico: apagar de verdade destruiria referencia e memoria.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models.brain_models import (
    BrainBusinessProfile,
    BrainGoal,
    BrainIcpProfile,
    BrainOffer,
)
from backend.models.revenue_models import Plan
from backend.services.brain.onboarding_bridge import get_or_create_profile

PROFILE_TEXT_FIELDS = (
    "business_model",
    "market",
    "positioning",
    "value_proposition",
    "revenue_model",
    "sales_motion",
    "additional_context",
)

PROFILE_LIST_FIELDS = (
    "competitive_advantages",
    "main_channels",
    "strategic_priorities",
    "constraints",
)

ICP_TEXT_FIELDS = (
    "name",
    "description",
    "customer_type",
    "industry",
    "company_size",
    "location",
    "revenue_range",
)

ICP_LIST_FIELDS = (
    "decision_makers",
    "pain_points",
    "desired_outcomes",
    "buying_triggers",
    "objections",
    "qualification_criteria",
    "disqualification_criteria",
)

OFFER_TEXT_FIELDS = (
    "name",
    "description",
    "promise",
    "mechanism",
    "pricing_strategy",
)

OFFER_LIST_FIELDS = ("main_objections", "proof_points")

GOAL_TEXT_FIELDS = ("name", "description", "metric_key", "unit")


class BrainNotFoundError(LookupError):
    """Entidade inexistente **ou** de outra empresa.

    Um unico erro para os dois casos de proposito: distinguir "nao existe" de
    "existe, mas nao e sua" confirmaria a existencia de um registro alheio.
    """


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _apply_fields(
    entity: Any,
    payload: Dict[str, Any],
    text_fields: tuple,
    list_fields: tuple,
) -> None:
    for field in text_fields:
        if field in payload:
            setattr(entity, field, _clean_text(payload[field]))
    for field in list_fields:
        if field in payload:
            setattr(entity, field, _clean_list(payload[field]))


# ---------------------------------------------------------------------------
# Perfil estratégico
# ---------------------------------------------------------------------------

def get_profile(db: Session, company_id: int) -> Optional[BrainBusinessProfile]:
    return (
        db.query(BrainBusinessProfile)
        .filter(BrainBusinessProfile.company_id == int(company_id))
        .first()
    )


def update_profile(db: Session, company_id: int, payload: Dict[str, Any]) -> BrainBusinessProfile:
    profile = get_or_create_profile(db, company_id)
    _apply_fields(profile, payload, PROFILE_TEXT_FIELDS, PROFILE_LIST_FIELDS)
    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# ICP
# ---------------------------------------------------------------------------

def list_icps(db: Session, company_id: int, *, include_archived: bool = False) -> List[BrainIcpProfile]:
    query = db.query(BrainIcpProfile).filter(BrainIcpProfile.company_id == int(company_id))
    if not include_archived:
        query = query.filter(BrainIcpProfile.is_active.is_(True))
    return query.order_by(BrainIcpProfile.priority.asc(), BrainIcpProfile.id.asc()).all()


def get_icp(db: Session, company_id: int, icp_id: int) -> BrainIcpProfile:
    icp = (
        db.query(BrainIcpProfile)
        .filter(BrainIcpProfile.id == int(icp_id), BrainIcpProfile.company_id == int(company_id))
        .first()
    )
    if icp is None:
        raise BrainNotFoundError("ICP não encontrado")
    return icp


def create_icp(db: Session, company_id: int, payload: Dict[str, Any]) -> BrainIcpProfile:
    name = _clean_text(payload.get("name"))
    if not name:
        raise ValueError("Nome do ICP é obrigatório")

    icp = BrainIcpProfile(company_id=int(company_id), name=name)
    _apply_fields(icp, payload, ICP_TEXT_FIELDS, ICP_LIST_FIELDS)
    icp.name = name
    icp.average_ticket = payload.get("average_ticket")
    icp.priority = int(payload.get("priority") or 1)
    icp.is_active = True
    db.add(icp)
    db.commit()
    db.refresh(icp)
    return icp


def update_icp(db: Session, company_id: int, icp_id: int, payload: Dict[str, Any]) -> BrainIcpProfile:
    icp = get_icp(db, company_id, icp_id)
    _apply_fields(icp, payload, ICP_TEXT_FIELDS, ICP_LIST_FIELDS)
    if "average_ticket" in payload:
        icp.average_ticket = payload["average_ticket"]
    if "priority" in payload and payload["priority"] is not None:
        icp.priority = int(payload["priority"])
    if "is_active" in payload:
        icp.is_active = bool(payload["is_active"])
        icp.archived_at = None if icp.is_active else datetime.now(timezone.utc)
    if not _clean_text(icp.name):
        raise ValueError("Nome do ICP é obrigatório")
    db.commit()
    db.refresh(icp)
    return icp


def archive_icp(db: Session, company_id: int, icp_id: int) -> BrainIcpProfile:
    icp = get_icp(db, company_id, icp_id)
    icp.is_active = False
    icp.archived_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(icp)
    return icp


# ---------------------------------------------------------------------------
# Ofertas
# ---------------------------------------------------------------------------

def list_offers(db: Session, company_id: int, *, include_archived: bool = False) -> List[BrainOffer]:
    query = db.query(BrainOffer).filter(BrainOffer.company_id == int(company_id))
    if not include_archived:
        query = query.filter(BrainOffer.is_active.is_(True))
    return query.order_by(BrainOffer.is_primary.desc(), BrainOffer.id.asc()).all()


def get_offer(db: Session, company_id: int, offer_id: int) -> BrainOffer:
    offer = (
        db.query(BrainOffer)
        .filter(BrainOffer.id == int(offer_id), BrainOffer.company_id == int(company_id))
        .first()
    )
    if offer is None:
        raise BrainNotFoundError("Oferta não encontrada")
    return offer


def _validate_offer_links(db: Session, company_id: int, payload: Dict[str, Any]) -> None:
    """Impede que uma oferta aponte para ICP ou plano de outra empresa.

    A FK sozinha nao protege disso: ela garante que o id existe, nao que ele
    pertence a este workspace.
    """
    icp_id = payload.get("target_icp_id")
    if icp_id:
        get_icp(db, company_id, int(icp_id))

    plan_id = payload.get("related_plan_id")
    if plan_id:
        plan = (
            db.query(Plan)
            .filter(Plan.id == int(plan_id), Plan.company_id == int(company_id))
            .first()
        )
        if plan is None:
            raise BrainNotFoundError("Plano não encontrado")


def _clear_other_primary_offers(db: Session, company_id: int, keep_offer_id: Optional[int]) -> None:
    """Garante uma unica oferta principal ativa.

    O indice parcial unico no banco impede o estado invalido; isto evita que o
    usuario receba um erro de constraint ao promover uma segunda oferta.
    """
    query = db.query(BrainOffer).filter(
        BrainOffer.company_id == int(company_id),
        BrainOffer.is_primary.is_(True),
        BrainOffer.is_active.is_(True),
    )
    if keep_offer_id is not None:
        query = query.filter(BrainOffer.id != int(keep_offer_id))
    for other in query.all():
        other.is_primary = False
    db.flush()


def create_offer(db: Session, company_id: int, payload: Dict[str, Any]) -> BrainOffer:
    name = _clean_text(payload.get("name"))
    if not name:
        raise ValueError("Nome da oferta é obrigatório")

    _validate_offer_links(db, company_id, payload)

    offer = BrainOffer(company_id=int(company_id), name=name)
    _apply_fields(offer, payload, OFFER_TEXT_FIELDS, OFFER_LIST_FIELDS)
    offer.name = name
    offer.target_icp_id = payload.get("target_icp_id")
    offer.related_plan_id = payload.get("related_plan_id")
    offer.average_ticket = payload.get("average_ticket")
    offer.margin_estimate = payload.get("margin_estimate")
    offer.sales_cycle_days = payload.get("sales_cycle_days")
    offer.is_active = True
    offer.is_primary = bool(payload.get("is_primary"))

    if offer.is_primary:
        _clear_other_primary_offers(db, company_id, keep_offer_id=None)

    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


def update_offer(db: Session, company_id: int, offer_id: int, payload: Dict[str, Any]) -> BrainOffer:
    offer = get_offer(db, company_id, offer_id)
    _validate_offer_links(db, company_id, payload)
    _apply_fields(offer, payload, OFFER_TEXT_FIELDS, OFFER_LIST_FIELDS)

    for field in ("target_icp_id", "related_plan_id", "average_ticket", "margin_estimate", "sales_cycle_days"):
        if field in payload:
            setattr(offer, field, payload[field])

    if "is_active" in payload:
        offer.is_active = bool(payload["is_active"])
        offer.archived_at = None if offer.is_active else datetime.now(timezone.utc)
        if not offer.is_active:
            offer.is_primary = False

    if payload.get("is_primary"):
        _clear_other_primary_offers(db, company_id, keep_offer_id=offer.id)
        offer.is_primary = True
    elif "is_primary" in payload:
        offer.is_primary = False

    if not _clean_text(offer.name):
        raise ValueError("Nome da oferta é obrigatório")

    db.commit()
    db.refresh(offer)
    return offer


def archive_offer(db: Session, company_id: int, offer_id: int) -> BrainOffer:
    offer = get_offer(db, company_id, offer_id)
    offer.is_active = False
    offer.is_primary = False
    offer.archived_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(offer)
    return offer


# ---------------------------------------------------------------------------
# Objetivos
# ---------------------------------------------------------------------------

def list_goals(db: Session, company_id: int, *, include_archived: bool = False) -> List[BrainGoal]:
    query = db.query(BrainGoal).filter(BrainGoal.company_id == int(company_id))
    if not include_archived:
        query = query.filter(BrainGoal.status != "archived")
    return query.order_by(BrainGoal.priority.asc(), BrainGoal.id.asc()).all()


def get_goal(db: Session, company_id: int, goal_id: int) -> BrainGoal:
    goal = (
        db.query(BrainGoal)
        .filter(BrainGoal.id == int(goal_id), BrainGoal.company_id == int(company_id))
        .first()
    )
    if goal is None:
        raise BrainNotFoundError("Objetivo não encontrado")
    return goal


def _apply_goal_payload(goal: BrainGoal, payload: Dict[str, Any]) -> None:
    _apply_fields(goal, payload, GOAL_TEXT_FIELDS, ())
    for field in ("baseline_value", "target_value", "period_start", "period_end"):
        if field in payload:
            setattr(goal, field, payload[field])
    if "priority" in payload and payload["priority"] is not None:
        goal.priority = int(payload["priority"])
    if "status" in payload and payload["status"]:
        goal.status = str(payload["status"])
        goal.archived_at = datetime.now(timezone.utc) if goal.status == "archived" else None


def create_goal(db: Session, company_id: int, payload: Dict[str, Any]) -> BrainGoal:
    name = _clean_text(payload.get("name"))
    if not name:
        raise ValueError("Nome do objetivo é obrigatório")

    goal = BrainGoal(company_id=int(company_id), name=name)
    _apply_goal_payload(goal, payload)
    goal.name = name
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def update_goal(db: Session, company_id: int, goal_id: int, payload: Dict[str, Any]) -> BrainGoal:
    goal = get_goal(db, company_id, goal_id)
    _apply_goal_payload(goal, payload)
    if not _clean_text(goal.name):
        raise ValueError("Nome do objetivo é obrigatório")
    db.commit()
    db.refresh(goal)
    return goal


def archive_goal(db: Session, company_id: int, goal_id: int) -> BrainGoal:
    goal = get_goal(db, company_id, goal_id)
    goal.status = "archived"
    goal.archived_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(goal)
    return goal
