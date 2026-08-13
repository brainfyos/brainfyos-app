"""API do Brain.

Regra de escopo, sem excecao: ``company_id`` vem **sempre** de
``get_current_user``. Nenhuma rota deste modulo aceita company_id em query,
path ou corpo. Trocar um numero na URL nao alcanca outro workspace porque nao
ha numero de workspace na URL.

Ids de entidade (icp_id, offer_id, goal_id) chegam pela URL, e por isso todo
acesso passa pelo repositorio, que resolve por id **e** company_id.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Client, User
from backend.models.revenue_models import Plan
from backend.services.brain import repository
from backend.services.brain.context_service import BrainContextService
from backend.services.brain.readiness import calculate_readiness, describe_data_sources
from backend.services.brain.repository import BrainNotFoundError
from backend.services.brain.schemas import ALL_SCOPES, BrainScope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/brain", tags=["brain"])


def _company_id(user: Union[Client, User]) -> int:
    company_id = getattr(user, "company_id", None)
    if company_id is None:
        raise HTTPException(status_code=400, detail="Conta sem workspace ativo")
    return int(company_id)


def _float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

class ProfilePayload(BaseModel):
    business_model: Optional[str] = None
    market: Optional[str] = None
    positioning: Optional[str] = None
    value_proposition: Optional[str] = None
    revenue_model: Optional[str] = None
    sales_motion: Optional[str] = None
    additional_context: Optional[str] = None
    competitive_advantages: Optional[List[str]] = None
    main_channels: Optional[List[str]] = None
    strategic_priorities: Optional[List[str]] = None
    constraints: Optional[List[str]] = None


class IcpPayload(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    customer_type: Optional[str] = Field(default=None, pattern="^(b2b|b2c|b2b2c)$")
    industry: Optional[str] = None
    company_size: Optional[str] = None
    location: Optional[str] = None
    revenue_range: Optional[str] = None
    average_ticket: Optional[Decimal] = Field(default=None, ge=0)
    decision_makers: Optional[List[str]] = None
    pain_points: Optional[List[str]] = None
    desired_outcomes: Optional[List[str]] = None
    buying_triggers: Optional[List[str]] = None
    objections: Optional[List[str]] = None
    qualification_criteria: Optional[List[str]] = None
    disqualification_criteria: Optional[List[str]] = None
    priority: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None


class OfferPayload(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_icp_id: Optional[int] = None
    related_plan_id: Optional[int] = None
    promise: Optional[str] = None
    mechanism: Optional[str] = None
    pricing_strategy: Optional[str] = None
    average_ticket: Optional[Decimal] = Field(default=None, ge=0)
    margin_estimate: Optional[Decimal] = Field(default=None, ge=0, le=100)
    sales_cycle_days: Optional[int] = Field(default=None, ge=0)
    main_objections: Optional[List[str]] = None
    proof_points: Optional[List[str]] = None
    is_primary: Optional[bool] = None
    is_active: Optional[bool] = None


class GoalPayload(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metric_key: Optional[str] = None
    baseline_value: Optional[Decimal] = None
    target_value: Optional[Decimal] = None
    unit: Optional[str] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    priority: Optional[int] = Field(default=None, ge=1)
    status: Optional[str] = Field(default=None, pattern="^(active|achieved|missed|archived)$")


# ---------------------------------------------------------------------------
# Serialização
# ---------------------------------------------------------------------------

def _profile_dict(profile) -> Dict[str, Any]:
    if profile is None:
        # Perfil ausente devolve a forma vazia, nao 404: o frontend renderiza o
        # mesmo formulario nos dois casos.
        return {
            field: None for field in repository.PROFILE_TEXT_FIELDS
        } | {field: [] for field in repository.PROFILE_LIST_FIELDS} | {
            "id": None,
            "updated_at": None,
        }

    return {
        "id": profile.id,
        **{field: getattr(profile, field) for field in repository.PROFILE_TEXT_FIELDS},
        **{field: list(getattr(profile, field) or []) for field in repository.PROFILE_LIST_FIELDS},
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _icp_dict(icp) -> Dict[str, Any]:
    return {
        "id": icp.id,
        **{field: getattr(icp, field) for field in repository.ICP_TEXT_FIELDS},
        **{field: list(getattr(icp, field) or []) for field in repository.ICP_LIST_FIELDS},
        "average_ticket": _float(icp.average_ticket),
        "priority": int(icp.priority or 1),
        "is_active": bool(icp.is_active),
        "updated_at": icp.updated_at.isoformat() if icp.updated_at else None,
    }


def _offer_dict(offer, plan_names: Dict[int, str], icp_names: Dict[int, str]) -> Dict[str, Any]:
    return {
        "id": offer.id,
        **{field: getattr(offer, field) for field in repository.OFFER_TEXT_FIELDS},
        **{field: list(getattr(offer, field) or []) for field in repository.OFFER_LIST_FIELDS},
        "target_icp_id": offer.target_icp_id,
        "target_icp_name": icp_names.get(offer.target_icp_id),
        "related_plan_id": offer.related_plan_id,
        "related_plan_name": plan_names.get(offer.related_plan_id),
        "average_ticket": _float(offer.average_ticket),
        "margin_estimate": _float(offer.margin_estimate),
        "sales_cycle_days": offer.sales_cycle_days,
        "is_primary": bool(offer.is_primary),
        "is_active": bool(offer.is_active),
        "updated_at": offer.updated_at.isoformat() if offer.updated_at else None,
    }


def _goal_dict(goal) -> Dict[str, Any]:
    return {
        "id": goal.id,
        **{field: getattr(goal, field) for field in repository.GOAL_TEXT_FIELDS},
        "baseline_value": _float(goal.baseline_value),
        "target_value": _float(goal.target_value),
        "period_start": goal.period_start.isoformat() if goal.period_start else None,
        "period_end": goal.period_end.isoformat() if goal.period_end else None,
        "priority": int(goal.priority or 1),
        "status": goal.status,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
    }


def _offer_lookup_maps(db: Session, company_id: int) -> tuple[Dict[int, str], Dict[int, str]]:
    plan_names = {
        plan.id: plan.name
        for plan in db.query(Plan).filter(Plan.company_id == company_id).all()
    }
    icp_names = {
        icp.id: icp.name
        for icp in repository.list_icps(db, company_id, include_archived=True)
    }
    return plan_names, icp_names


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("/overview")
def get_overview(
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    readiness = calculate_readiness(db, company_id).as_dict()
    return {
        "company_id": company_id,
        "readiness": readiness,
        "sources": describe_data_sources(db, company_id),
    }


@router.get("/sources")
def get_sources(
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    return {"company_id": company_id, "sources": describe_data_sources(db, company_id)}


# ---------------------------------------------------------------------------
# Perfil estratégico
# ---------------------------------------------------------------------------

@router.get("/profile")
def get_profile(
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    return _profile_dict(repository.get_profile(db, _company_id(user)))


@router.put("/profile")
def put_profile(
    payload: ProfilePayload,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    profile = repository.update_profile(
        db, _company_id(user), payload.model_dump(exclude_unset=True)
    )
    return _profile_dict(profile)


# ---------------------------------------------------------------------------
# ICP
# ---------------------------------------------------------------------------

@router.get("/icps")
def list_icps(
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    icps = repository.list_icps(db, _company_id(user), include_archived=include_archived)
    return {"items": [_icp_dict(icp) for icp in icps]}


@router.post("/icps", status_code=201)
def create_icp(
    payload: IcpPayload,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        icp = repository.create_icp(db, _company_id(user), payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _icp_dict(icp)


@router.put("/icps/{icp_id}")
def update_icp(
    icp_id: int,
    payload: IcpPayload,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        icp = repository.update_icp(
            db, _company_id(user), icp_id, payload.model_dump(exclude_unset=True)
        )
    except BrainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _icp_dict(icp)


@router.post("/icps/{icp_id}/archive")
def archive_icp(
    icp_id: int,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        icp = repository.archive_icp(db, _company_id(user), icp_id)
    except BrainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _icp_dict(icp)


# ---------------------------------------------------------------------------
# Ofertas
# ---------------------------------------------------------------------------

@router.get("/offers")
def list_offers(
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    offers = repository.list_offers(db, company_id, include_archived=include_archived)
    plan_names, icp_names = _offer_lookup_maps(db, company_id)
    return {"items": [_offer_dict(offer, plan_names, icp_names) for offer in offers]}


@router.post("/offers", status_code=201)
def create_offer(
    payload: OfferPayload,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    try:
        offer = repository.create_offer(db, company_id, payload.model_dump(exclude_unset=True))
    except BrainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    plan_names, icp_names = _offer_lookup_maps(db, company_id)
    return _offer_dict(offer, plan_names, icp_names)


@router.put("/offers/{offer_id}")
def update_offer(
    offer_id: int,
    payload: OfferPayload,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    try:
        offer = repository.update_offer(
            db, company_id, offer_id, payload.model_dump(exclude_unset=True)
        )
    except BrainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    plan_names, icp_names = _offer_lookup_maps(db, company_id)
    return _offer_dict(offer, plan_names, icp_names)


@router.post("/offers/{offer_id}/archive")
def archive_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    company_id = _company_id(user)
    try:
        offer = repository.archive_offer(db, company_id, offer_id)
    except BrainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    plan_names, icp_names = _offer_lookup_maps(db, company_id)
    return _offer_dict(offer, plan_names, icp_names)


@router.get("/plans")
def list_linkable_plans(
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Planos aos quais uma oferta pode ser associada.

    Existe para o seletor da BrainPage sem obrigar o frontend a falar com a
    API de faturamento e filtrar de novo por empresa.
    """
    company_id = _company_id(user)
    plans = (
        db.query(Plan)
        .filter(Plan.company_id == company_id, Plan.is_active.is_(True))
        .order_by(Plan.name.asc())
        .all()
    )
    return {
        "items": [
            {
                "id": plan.id,
                "name": plan.name,
                "price": _float(plan.price),
                "billing_interval": plan.billing_interval,
            }
            for plan in plans
        ]
    }


# ---------------------------------------------------------------------------
# Objetivos
# ---------------------------------------------------------------------------

@router.get("/goals")
def list_goals(
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    goals = repository.list_goals(db, _company_id(user), include_archived=include_archived)
    return {"items": [_goal_dict(goal) for goal in goals]}


@router.post("/goals", status_code=201)
def create_goal(
    payload: GoalPayload,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        goal = repository.create_goal(db, _company_id(user), payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _goal_dict(goal)


@router.put("/goals/{goal_id}")
def update_goal(
    goal_id: int,
    payload: GoalPayload,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        goal = repository.update_goal(
            db, _company_id(user), goal_id, payload.model_dump(exclude_unset=True)
        )
    except BrainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _goal_dict(goal)


@router.post("/goals/{goal_id}/archive")
def archive_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        goal = repository.archive_goal(db, _company_id(user), goal_id)
    except BrainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _goal_dict(goal)


# ---------------------------------------------------------------------------
# Context Engine
# ---------------------------------------------------------------------------

@router.get("/context")
def get_context(
    scope: List[str] = Query(default=[BrainScope.BUSINESS.value]),
    lead_id: Optional[int] = Query(None, ge=1),
    contact_id: Optional[int] = Query(None, ge=1),
    customer_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Contexto composto para inspeção e para consumo por agentes.

    Escopo desconhecido é ignorado em vez de rejeitado: o chamador pede o que
    conhece, e o engine devolve o que sabe montar.
    """
    company_id = _company_id(user)
    unknown = [item for item in scope if item not in ALL_SCOPES]
    if unknown:
        logger.info("Escopos ignorados no contexto do Brain: %s", ",".join(unknown))

    context = BrainContextService(db).build(
        company_id=company_id,
        scopes=scope,
        lead_id=lead_id,
        contact_id=contact_id,
        customer_id=customer_id,
        limit=limit,
    )
    return context.model_dump(mode="json")
