"""BrainfyOS Control -- API administrativa da plataforma.

Toda rota deste modulo depende de ``require_platform_owner``. A validacao e
sempre no backend: proteger a rota no React nao protege dado nenhum.

Nenhuma rota aqui aceita ``company_id`` como forma de escopo do chamador -- o
parametro so existe para *escolher* qual empresa inspecionar, e so um
proprietario de plataforma chega ate aqui.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Client
from backend.services import control_metrics_service as metrics
from backend.services.platform_access import (
    is_platform_owner,
    log_platform_action,
    platform_owner_with_audit,
    require_platform_owner,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/control", tags=["control"])


def _days(days: Optional[int]) -> int:
    return metrics.clamp_period_days(days)


@router.get("/me")
def get_control_session(
    user=Depends(get_current_user),
) -> Dict[str, Any]:
    """Diz se a conta autenticada enxerga o Control.

    Existe para o frontend nao depender do que ficou no localStorage no login:
    revogar o papel passa a valer no proximo carregamento de pagina. Nao e uma
    rota de autorizacao -- ela responde 200 com ``false`` em vez de 403.
    """
    owner = is_platform_owner(user)
    return {
        "is_platform_owner": owner,
        "platform_role": getattr(user, "platform_role", None) if owner else None,
    }


@router.get("/overview")
def get_overview(
    days: int = Query(metrics.DEFAULT_PERIOD_DAYS, ge=1, le=metrics.MAX_PERIOD_DAYS),
    db: Session = Depends(get_db),
    _actor: Client = Depends(platform_owner_with_audit("control.overview.read")),
) -> Dict[str, Any]:
    period = _days(days)
    overview = metrics.get_overview(db, days=period)
    overview["top_companies"] = metrics.get_top_companies_by_usage(db, days=period)
    overview["alerts"] = metrics.get_alerts(db, days=period)[:8]
    return overview


@router.get("/accounts")
def list_accounts(
    days: int = Query(metrics.DEFAULT_PERIOD_DAYS, ge=1, le=metrics.MAX_PERIOD_DAYS),
    page: int = Query(1, ge=1),
    page_size: int = Query(metrics.DEFAULT_PAGE_SIZE, ge=1, le=metrics.MAX_PAGE_SIZE),
    search: Optional[str] = Query(None, max_length=120),
    status: Optional[str] = Query(None, pattern="^(active|inactive|blocked)$"),
    sort_by: str = Query("cost"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    _actor: Client = Depends(platform_owner_with_audit("control.accounts.list")),
) -> Dict[str, Any]:
    return metrics.list_accounts(
        db,
        days=_days(days),
        page=page,
        page_size=page_size,
        search=search,
        status=status,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.get("/accounts/{company_id}")
def get_account_detail(
    company_id: int,
    request: Request,
    days: int = Query(metrics.DEFAULT_PERIOD_DAYS, ge=1, le=metrics.MAX_PERIOD_DAYS),
    db: Session = Depends(get_db),
    actor: Client = Depends(require_platform_owner),
) -> Dict[str, Any]:
    detail = metrics.get_account_detail(db, company_id, days=_days(days))
    if detail is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    # Abrir a ficha de uma empresa especifica e a acao mais sensivel do
    # Control, entao o alvo entra na auditoria.
    log_platform_action(
        actor=actor,
        action="control.account.read",
        request=request,
        target_company_id=company_id,
    )
    return detail


@router.get("/accounts/{company_id}/ai-usage")
def get_account_ai_usage(
    company_id: int,
    request: Request,
    days: int = Query(metrics.DEFAULT_PERIOD_DAYS, ge=1, le=metrics.MAX_PERIOD_DAYS),
    db: Session = Depends(get_db),
    actor: Client = Depends(require_platform_owner),
) -> Dict[str, Any]:
    period = _days(days)
    if metrics.get_account_detail(db, company_id, days=period) is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    log_platform_action(
        actor=actor,
        action="control.account.ai_usage.read",
        request=request,
        target_company_id=company_id,
    )

    return {
        "company_id": company_id,
        "period_days": period,
        "summary": metrics.get_ai_usage_summary(db, days=period, company_id=company_id),
        "timeseries": metrics.get_ai_usage_timeseries(db, days=period, company_id=company_id),
        "by_agent": metrics.get_ai_usage_by_agent(db, days=period, company_id=company_id),
        "by_model": metrics.get_ai_usage_by_model(db, days=period, company_id=company_id),
        "by_provider": metrics.get_ai_usage_by_provider(db, days=period, company_id=company_id),
        "recent_events": metrics.get_recent_ai_events(db, days=period, company_id=company_id),
    }


@router.get("/ai-usage")
def get_ai_usage(
    days: int = Query(metrics.DEFAULT_PERIOD_DAYS, ge=1, le=metrics.MAX_PERIOD_DAYS),
    company_id: Optional[int] = Query(None, ge=1),
    only_failed: bool = Query(False),
    db: Session = Depends(get_db),
    _actor: Client = Depends(platform_owner_with_audit("control.ai_usage.read")),
) -> Dict[str, Any]:
    period = _days(days)
    return {
        "period_days": period,
        "company_id": company_id,
        "summary": metrics.get_ai_usage_summary(db, days=period, company_id=company_id),
        "timeseries": metrics.get_ai_usage_timeseries(db, days=period, company_id=company_id),
        "by_company": metrics.get_top_companies_by_usage(db, days=period, limit=metrics.MAX_PAGE_SIZE),
        "by_agent": metrics.get_ai_usage_by_agent(db, days=period, company_id=company_id),
        "by_model": metrics.get_ai_usage_by_model(db, days=period, company_id=company_id),
        "by_provider": metrics.get_ai_usage_by_provider(db, days=period, company_id=company_id),
        "recent_events": metrics.get_recent_ai_events(
            db, days=period, company_id=company_id, only_failed=only_failed
        ),
    }


@router.get("/integrations")
def get_integrations(
    days: int = Query(metrics.DEFAULT_PERIOD_DAYS, ge=1, le=metrics.MAX_PERIOD_DAYS),
    db: Session = Depends(get_db),
    _actor: Client = Depends(platform_owner_with_audit("control.integrations.read")),
) -> Dict[str, Any]:
    items = metrics.get_integrations_health(db, days=_days(days))
    return {
        "period_days": _days(days),
        "total": len(items),
        "healthy": sum(1 for item in items if item["health_status"] == "healthy"),
        "attention": sum(1 for item in items if item["health_status"] == "attention"),
        "down": sum(1 for item in items if item["health_status"] == "down"),
        "items": items,
    }


@router.get("/alerts")
def get_alerts(
    days: int = Query(metrics.DEFAULT_PERIOD_DAYS, ge=1, le=metrics.MAX_PERIOD_DAYS),
    db: Session = Depends(get_db),
    _actor: Client = Depends(platform_owner_with_audit("control.alerts.read")),
) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = metrics.get_alerts(db, days=_days(days))
    return {
        "period_days": _days(days),
        "total": len(items),
        "critical": sum(1 for item in items if item["severity"] == "critical"),
        "warning": sum(1 for item in items if item["severity"] == "warning"),
        "info": sum(1 for item in items if item["severity"] == "info"),
        "items": items,
    }
