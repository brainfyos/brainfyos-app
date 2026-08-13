"""Agregacoes do BrainfyOS Control.

Todas as consultas aqui cruzam companies, entao valem duas regras:

1. **Agregar no Postgres.** Nenhuma funcao devolve linha de evento bruto para o
   frontend somar. ``ai_usage_events`` cresce sem limite; carregar o periodo
   inteiro na memoria seria um vazamento de latencia garantido.
2. **Nunca N+1.** Cada painel e uma consulta agregada com ``GROUP BY``, ou um
   punhado delas -- nunca uma consulta por empresa.

Nada aqui inventa numero. Quando a fonte nao existe, a funcao devolve ``None``
e a rota omite o campo, para a UI mostrar estado vazio em vez de zero falso.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

# Janela padrao dos paineis. 30 dias cobre o ciclo de cobranca sem exigir
# particionamento de ai_usage_events.
DEFAULT_PERIOD_DAYS = 30
MAX_PERIOD_DAYS = 365
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
# Ranking e "eventos recentes" sao listas de leitura humana, nao exportacao.
TOP_N_DEFAULT = 10
RECENT_EVENTS_LIMIT = 20

# Estados terminais de falha gravados por backend/webhook_audit.py. Os demais
# ('received', 'queued', 'processing') sao transitorios e nao contam como erro.
WEBHOOK_FAILURE_STATUSES = ("failed", "queue_failed", "company_not_found")


def clamp_period_days(days: Optional[int]) -> int:
    if not days or days <= 0:
        return DEFAULT_PERIOD_DAYS
    return min(int(days), MAX_PERIOD_DAYS)


def period_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _int(value: Any) -> int:
    return int(value or 0)


def _optional_float(value: Any) -> Optional[float]:
    return None if value is None else _float(value)


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else None


# ---------------------------------------------------------------------------
# Visao geral
# ---------------------------------------------------------------------------

def get_overview(db: Session, *, days: int) -> Dict[str, Any]:
    since = period_start(days)

    accounts = db.execute(
        text(
            """
            SELECT
                COUNT(*)                                                    AS total,
                COUNT(*) FILTER (WHERE operational_status = 'active')       AS active,
                COUNT(*) FILTER (WHERE operational_status = 'inactive')     AS inactive,
                COUNT(*) FILTER (WHERE operational_status = 'blocked')      AS blocked,
                COUNT(*) FILTER (WHERE created_at >= :since)                AS created_in_period
            FROM companies
            """
        ),
        {"since": since},
    ).mappings().one()

    usage = db.execute(
        text(
            """
            SELECT
                COUNT(*)                                                  AS events,
                COUNT(*) FILTER (WHERE status = 'failed')                 AS failed_events,
                COUNT(DISTINCT company_id)                                AS active_companies,
                COALESCE(SUM(input_tokens), 0)                            AS input_tokens,
                COALESCE(SUM(output_tokens), 0)                           AS output_tokens,
                COALESCE(SUM(cached_tokens), 0)                           AS cached_tokens,
                COALESCE(SUM(reasoning_tokens), 0)                        AS reasoning_tokens,
                COALESCE(SUM(total_tokens), 0)                            AS total_tokens,
                COALESCE(SUM(estimated_cost_brl), 0)                      AS cost_brl,
                COALESCE(SUM(estimated_cost_usd), 0)                      AS cost_usd,
                SUM(revenue_brl)                                          AS revenue_brl,
                SUM(gross_profit_brl)                                     AS gross_profit_brl
            FROM ai_usage_events
            WHERE created_at >= :since
            """
        ),
        {"since": since},
    ).mappings().one()

    events = _int(usage["events"])
    failed = _int(usage["failed_events"])
    revenue = _optional_float(usage["revenue_brl"])
    gross_profit = _optional_float(usage["gross_profit_brl"])

    # Margem so e reportada quando ha receita registrada. Sem receita a divisao
    # nao tem significado -- e um zero enganoso, nao uma margem de 0%.
    margin_percent: Optional[float] = None
    if revenue and revenue > 0 and gross_profit is not None:
        margin_percent = round((gross_profit / revenue) * 100, 2)

    return {
        "period_days": days,
        "period_start": since.isoformat(),
        "accounts": {
            "total": _int(accounts["total"]),
            "active": _int(accounts["active"]),
            "inactive": _int(accounts["inactive"]),
            "blocked": _int(accounts["blocked"]),
            "created_in_period": _int(accounts["created_in_period"]),
            # "usando IA no periodo" e diferente de "operacionalmente ativa":
            # uma conta pode estar liberada e nao ter consumido nada.
            "consuming_ai_in_period": _int(usage["active_companies"]),
        },
        "ai": {
            "events": events,
            "failed_events": failed,
            "success_rate_percent": round(((events - failed) / events) * 100, 2) if events else None,
            "input_tokens": _int(usage["input_tokens"]),
            "output_tokens": _int(usage["output_tokens"]),
            "cached_tokens": _int(usage["cached_tokens"]),
            "reasoning_tokens": _int(usage["reasoning_tokens"]),
            "total_tokens": _int(usage["total_tokens"]),
            "cost_brl": _float(usage["cost_brl"]),
            "cost_usd": _float(usage["cost_usd"]),
            "revenue_brl": revenue,
            "gross_profit_brl": gross_profit,
            "margin_percent": margin_percent,
        },
    }


def get_top_companies_by_usage(db: Session, *, days: int, limit: int = TOP_N_DEFAULT) -> List[Dict[str, Any]]:
    since = period_start(days)
    rows = db.execute(
        text(
            """
            SELECT
                e.company_id,
                COALESCE(NULLIF(c.name_company, ''), c.name)  AS company_name,
                COUNT(*)                                      AS events,
                COUNT(*) FILTER (WHERE e.status = 'failed')   AS failed_events,
                COALESCE(SUM(e.total_tokens), 0)              AS total_tokens,
                COALESCE(SUM(e.estimated_cost_brl), 0)        AS cost_brl
            FROM ai_usage_events e
            JOIN companies c ON c.id = e.company_id
            WHERE e.created_at >= :since
            GROUP BY e.company_id, company_name
            ORDER BY cost_brl DESC, total_tokens DESC
            LIMIT :limit
            """
        ),
        {"since": since, "limit": limit},
    ).mappings().all()

    return [
        {
            "company_id": _int(row["company_id"]),
            "company_name": row["company_name"],
            "events": _int(row["events"]),
            "failed_events": _int(row["failed_events"]),
            "total_tokens": _int(row["total_tokens"]),
            "cost_brl": _float(row["cost_brl"]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Contas
# ---------------------------------------------------------------------------

_ACCOUNT_SORT_COLUMNS = {
    "name": "company_name",
    "created_at": "created_at",
    "tokens": "total_tokens",
    "cost": "cost_brl",
    "events": "ai_events",
    "errors": "ai_errors",
    "last_activity": "last_activity_at",
    "users": "user_count",
}


def list_accounts(
    db: Session,
    *,
    days: int,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    search: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: str = "cost",
    sort_dir: str = "desc",
) -> Dict[str, Any]:
    """Uma consulta agregada para a pagina inteira.

    Cada metrica vem de um LATERAL escopado a company da linha, entao o custo
    e proporcional ao ``page_size``, nao ao total de empresas.
    """
    since = period_start(days)
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    offset = (page - 1) * page_size

    sort_column = _ACCOUNT_SORT_COLUMNS.get(sort_by, "cost_brl")
    direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"

    filters = ["1 = 1"]
    params: Dict[str, Any] = {"since": since, "limit": page_size, "offset": offset}

    if search:
        filters.append(
            "(c.name ILIKE :search OR COALESCE(c.name_company, '') ILIKE :search OR c.cnpj ILIKE :search)"
        )
        params["search"] = f"%{search.strip()}%"

    if status:
        filters.append("c.operational_status = :status")
        params["status"] = status

    where_clause = " AND ".join(filters)

    total = db.execute(
        text(f"SELECT COUNT(*) FROM companies c WHERE {where_clause}"),
        {key: value for key, value in params.items() if key not in {"limit", "offset", "since"}},
    ).scalar_one()

    rows = db.execute(
        text(
            f"""
            SELECT
                c.id                                            AS company_id,
                COALESCE(NULLIF(c.name_company, ''), c.name)    AS company_name,
                c.operational_status                            AS status,
                c.created_at                                    AS created_at,
                c.waha_enabled                                  AS waha_enabled,
                c.waha_session_name                             AS waha_session_name,
                usage.events                                    AS ai_events,
                usage.failed_events                             AS ai_errors,
                usage.total_tokens                              AS total_tokens,
                usage.cost_brl                                  AS cost_brl,
                people.user_count                               AS user_count,
                activity.last_activity_at                       AS last_activity_at,
                integrations.integration_count                  AS integration_count,
                nps.responses                                   AS nps_responses,
                nps.promoters                                   AS nps_promoters,
                nps.detractors                                  AS nps_detractors
            FROM companies c
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*)                                    AS events,
                    COUNT(*) FILTER (WHERE e.status = 'failed') AS failed_events,
                    COALESCE(SUM(e.total_tokens), 0)            AS total_tokens,
                    COALESCE(SUM(e.estimated_cost_brl), 0)      AS cost_brl
                FROM ai_usage_events e
                WHERE e.company_id = c.id AND e.created_at >= :since
            ) usage ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS user_count
                FROM users u
                WHERE u.company_id = c.id AND u.is_active
            ) people ON TRUE
            LEFT JOIN LATERAL (
                SELECT MAX(m.timestamp) AS last_activity_at
                FROM messages m
                WHERE m.company_id = c.id
            ) activity ON TRUE
            LEFT JOIN LATERAL (
                SELECT (
                    (CASE WHEN c.waha_enabled AND c.waha_session_name IS NOT NULL THEN 1 ELSE 0 END)
                    + (SELECT COUNT(*) FROM calendar_integrations ci WHERE ci.company_id = c.id)
                    + (SELECT COUNT(*) FROM telegram_integrations ti WHERE ti.company_id = c.id)
                ) AS integration_count
            ) integrations ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) FILTER (WHERE n.score IS NOT NULL)      AS responses,
                    COUNT(*) FILTER (WHERE n.score >= 9)             AS promoters,
                    COUNT(*) FILTER (WHERE n.score <= 6)             AS detractors
                FROM nps_responses n
                WHERE n.company_id = c.id AND n.sent_at >= :since
            ) nps ON TRUE
            WHERE {where_clause}
            ORDER BY {sort_column} {direction} NULLS LAST, c.id ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()

    return {
        "page": page,
        "page_size": page_size,
        "total": _int(total),
        "period_days": days,
        "items": [_account_row_to_dict(row) for row in rows],
    }


def _account_row_to_dict(row: Any) -> Dict[str, Any]:
    nps_responses = _int(row["nps_responses"])
    # NPS = %promotores - %detratores. Abaixo de uma amostra minima o numero
    # oscila demais para ser exibido, entao devolvemos None.
    nps_score: Optional[float] = None
    if nps_responses >= 5:
        promoters = _int(row["nps_promoters"])
        detractors = _int(row["nps_detractors"])
        nps_score = round(((promoters - detractors) / nps_responses) * 100, 1)

    return {
        "company_id": _int(row["company_id"]),
        "company_name": row["company_name"],
        "status": row["status"],
        "created_at": _iso(row["created_at"]),
        "user_count": _int(row["user_count"]),
        "last_activity_at": _iso(row["last_activity_at"]),
        "ai_events": _int(row["ai_events"]),
        "ai_errors": _int(row["ai_errors"]),
        "total_tokens": _int(row["total_tokens"]),
        "cost_brl": _float(row["cost_brl"]),
        "integration_count": _int(row["integration_count"]),
        "whatsapp_connected": bool(row["waha_enabled"] and row["waha_session_name"]),
        "nps_responses": nps_responses,
        "nps_score": nps_score,
        # Health score depende de dados que ainda nao existem (SLA, churn,
        # adocao por modulo). Exposto como None para a UI desabilitar o card em
        # vez de exibir um numero fabricado.
        "health_score": None,
    }


def get_account_detail(db: Session, company_id: int, *, days: int) -> Optional[Dict[str, Any]]:
    since = period_start(days)

    company = db.execute(
        text(
            """
            SELECT
                c.id,
                c.name,
                c.name_company,
                c.cnpj,
                c.operational_status,
                c.created_at,
                c.waha_enabled,
                c.waha_session_name,
                bt.code AS business_type_code
            FROM companies c
            LEFT JOIN business_types bt ON bt.id = c.business_type_id
            WHERE c.id = :company_id
            """
        ),
        {"company_id": company_id},
    ).mappings().first()

    if not company:
        return None

    volumes = db.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*) FROM users u WHERE u.company_id = :company_id AND u.is_active)  AS active_users,
                (SELECT COUNT(*) FROM contacts ct WHERE ct.company_id = :company_id)             AS contacts,
                (SELECT COUNT(*) FROM leads l WHERE l.company_id = :company_id)                  AS leads,
                (SELECT MAX(m.timestamp) FROM messages m WHERE m.company_id = :company_id)       AS last_activity_at,
                (SELECT COUNT(*) FROM messages m
                  WHERE m.company_id = :company_id AND m.timestamp >= :since)                    AS messages_in_period
            """
        ),
        {"company_id": company_id, "since": since},
    ).mappings().one()

    usage = db.execute(
        text(
            """
            SELECT
                COUNT(*)                                    AS events,
                COUNT(*) FILTER (WHERE status = 'failed')   AS failed_events,
                COALESCE(SUM(input_tokens), 0)              AS input_tokens,
                COALESCE(SUM(output_tokens), 0)             AS output_tokens,
                COALESCE(SUM(total_tokens), 0)              AS total_tokens,
                COALESCE(SUM(estimated_cost_brl), 0)        AS cost_brl,
                SUM(revenue_brl)                            AS revenue_brl,
                SUM(gross_profit_brl)                       AS gross_profit_brl
            FROM ai_usage_events
            WHERE company_id = :company_id AND created_at >= :since
            """
        ),
        {"company_id": company_id, "since": since},
    ).mappings().one()

    wallet = db.execute(
        text(
            """
            SELECT balance_credits, total_granted_credits, total_used_credits, status
            FROM ai_credit_wallets
            WHERE company_id = :company_id
            """
        ),
        {"company_id": company_id},
    ).mappings().first()

    nps = db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE score IS NOT NULL)   AS responses,
                COUNT(*) FILTER (WHERE score >= 9)          AS promoters,
                COUNT(*) FILTER (WHERE score BETWEEN 7 AND 8) AS passives,
                COUNT(*) FILTER (WHERE score <= 6)          AS detractors,
                AVG(score) FILTER (WHERE score IS NOT NULL) AS average_score
            FROM nps_responses
            WHERE company_id = :company_id AND sent_at >= :since
            """
        ),
        {"company_id": company_id, "since": since},
    ).mappings().one()

    events = _int(usage["events"])
    failed = _int(usage["failed_events"])
    responses = _int(nps["responses"])

    return {
        "company_id": _int(company["id"]),
        "company_name": company["name_company"] or company["name"],
        "legal_name": company["name"],
        "document": company["cnpj"],
        "status": company["operational_status"],
        "business_type": company["business_type_code"],
        "created_at": _iso(company["created_at"]),
        "period_days": days,
        "volumes": {
            "active_users": _int(volumes["active_users"]),
            "contacts": _int(volumes["contacts"]),
            "leads": _int(volumes["leads"]),
            "messages_in_period": _int(volumes["messages_in_period"]),
            "last_activity_at": _iso(volumes["last_activity_at"]),
        },
        "ai": {
            "events": events,
            "failed_events": failed,
            "success_rate_percent": round(((events - failed) / events) * 100, 2) if events else None,
            "input_tokens": _int(usage["input_tokens"]),
            "output_tokens": _int(usage["output_tokens"]),
            "total_tokens": _int(usage["total_tokens"]),
            "cost_brl": _float(usage["cost_brl"]),
            "revenue_brl": _optional_float(usage["revenue_brl"]),
            "gross_profit_brl": _optional_float(usage["gross_profit_brl"]),
        },
        "wallet": None if not wallet else {
            "balance_credits": _float(wallet["balance_credits"]),
            "total_granted_credits": _float(wallet["total_granted_credits"]),
            "total_used_credits": _float(wallet["total_used_credits"]),
            "status": wallet["status"],
        },
        "satisfaction": None if responses == 0 else {
            "responses": responses,
            "promoters": _int(nps["promoters"]),
            "passives": _int(nps["passives"]),
            "detractors": _int(nps["detractors"]),
            "average_score": _optional_float(nps["average_score"]),
            "nps_score": (
                round(((_int(nps["promoters"]) - _int(nps["detractors"])) / responses) * 100, 1)
                if responses >= 5 else None
            ),
        },
        "health_score": None,
    }


# ---------------------------------------------------------------------------
# Consumo de IA
# ---------------------------------------------------------------------------

def _usage_filters(company_id: Optional[int]) -> Tuple[str, Dict[str, Any]]:
    if company_id is None:
        return "", {}
    return " AND e.company_id = :company_id", {"company_id": company_id}


def get_ai_usage_summary(db: Session, *, days: int, company_id: Optional[int] = None) -> Dict[str, Any]:
    since = period_start(days)
    extra_where, extra_params = _usage_filters(company_id)
    params = {"since": since, **extra_params}

    summary = db.execute(
        text(
            f"""
            SELECT
                COUNT(*)                                    AS events,
                COUNT(*) FILTER (WHERE e.status = 'failed') AS failed_events,
                COUNT(DISTINCT e.company_id)                AS companies,
                COALESCE(SUM(e.input_tokens), 0)            AS input_tokens,
                COALESCE(SUM(e.output_tokens), 0)           AS output_tokens,
                COALESCE(SUM(e.cached_tokens), 0)           AS cached_tokens,
                COALESCE(SUM(e.reasoning_tokens), 0)        AS reasoning_tokens,
                COALESCE(SUM(e.total_tokens), 0)            AS total_tokens,
                COALESCE(SUM(e.estimated_cost_brl), 0)      AS cost_brl,
                COALESCE(SUM(e.estimated_cost_usd), 0)      AS cost_usd,
                SUM(e.revenue_brl)                          AS revenue_brl,
                SUM(e.gross_profit_brl)                     AS gross_profit_brl,
                COALESCE(SUM(e.internal_credits_charged), 0) AS internal_credits
            FROM ai_usage_events e
            WHERE e.created_at >= :since{extra_where}
            """
        ),
        params,
    ).mappings().one()

    events = _int(summary["events"])
    failed = _int(summary["failed_events"])
    revenue = _optional_float(summary["revenue_brl"])
    gross_profit = _optional_float(summary["gross_profit_brl"])
    margin_percent = (
        round((gross_profit / revenue) * 100, 2)
        if revenue and revenue > 0 and gross_profit is not None
        else None
    )

    return {
        "events": events,
        "failed_events": failed,
        "success_rate_percent": round(((events - failed) / events) * 100, 2) if events else None,
        "companies": _int(summary["companies"]),
        "input_tokens": _int(summary["input_tokens"]),
        "output_tokens": _int(summary["output_tokens"]),
        "cached_tokens": _int(summary["cached_tokens"]),
        "reasoning_tokens": _int(summary["reasoning_tokens"]),
        "total_tokens": _int(summary["total_tokens"]),
        "cost_brl": _float(summary["cost_brl"]),
        "cost_usd": _float(summary["cost_usd"]),
        "revenue_brl": revenue,
        "gross_profit_brl": gross_profit,
        "margin_percent": margin_percent,
        "internal_credits": _float(summary["internal_credits"]),
    }


def get_ai_usage_timeseries(db: Session, *, days: int, company_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Serie diaria com dias vazios preenchidos.

    O ``generate_series`` a esquerda garante que um dia sem consumo apareca
    como zero em vez de sumir do grafico -- um buraco na linha mentiria sobre
    a continuidade da operacao.
    """
    since = period_start(days)
    extra_where, extra_params = _usage_filters(company_id)
    params = {"since": since, **extra_params}

    rows = db.execute(
        text(
            f"""
            WITH days AS (
                SELECT generate_series(
                    date_trunc('day', :since::timestamptz),
                    date_trunc('day', now()),
                    interval '1 day'
                ) AS bucket
            )
            SELECT
                d.bucket                                                AS bucket,
                COALESCE(COUNT(e.id), 0)                                AS events,
                COALESCE(COUNT(e.id) FILTER (WHERE e.status = 'failed'), 0) AS failed_events,
                COALESCE(SUM(e.total_tokens), 0)                        AS total_tokens,
                COALESCE(SUM(e.input_tokens), 0)                        AS input_tokens,
                COALESCE(SUM(e.output_tokens), 0)                       AS output_tokens,
                COALESCE(SUM(e.estimated_cost_brl), 0)                  AS cost_brl
            FROM days d
            LEFT JOIN ai_usage_events e
                   ON date_trunc('day', e.created_at) = d.bucket
                  AND e.created_at >= :since{extra_where}
            GROUP BY d.bucket
            ORDER BY d.bucket ASC
            """
        ),
        params,
    ).mappings().all()

    return [
        {
            "date": row["bucket"].date().isoformat(),
            "events": _int(row["events"]),
            "failed_events": _int(row["failed_events"]),
            "total_tokens": _int(row["total_tokens"]),
            "input_tokens": _int(row["input_tokens"]),
            "output_tokens": _int(row["output_tokens"]),
            "cost_brl": _float(row["cost_brl"]),
        }
        for row in rows
    ]


def _grouped_usage(
    db: Session,
    *,
    days: int,
    group_sql: str,
    label_alias: str,
    company_id: Optional[int],
    limit: int,
    include_company_name: bool = False,
) -> List[Dict[str, Any]]:
    since = period_start(days)
    extra_where, extra_params = _usage_filters(company_id)
    params = {"since": since, "limit": limit, **extra_params}

    join_clause = "JOIN companies c ON c.id = e.company_id" if include_company_name else ""

    rows = db.execute(
        text(
            f"""
            SELECT
                {group_sql} AS {label_alias},
                COUNT(*)                                    AS events,
                COUNT(*) FILTER (WHERE e.status = 'failed') AS failed_events,
                COALESCE(SUM(e.total_tokens), 0)            AS total_tokens,
                COALESCE(SUM(e.estimated_cost_brl), 0)      AS cost_brl
            FROM ai_usage_events e
            {join_clause}
            WHERE e.created_at >= :since{extra_where}
            GROUP BY {label_alias}
            ORDER BY cost_brl DESC, total_tokens DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    return [
        {
            "label": row[label_alias],
            "events": _int(row["events"]),
            "failed_events": _int(row["failed_events"]),
            "total_tokens": _int(row["total_tokens"]),
            "cost_brl": _float(row["cost_brl"]),
        }
        for row in rows
    ]


def get_ai_usage_by_agent(db: Session, *, days: int, company_id: Optional[int] = None, limit: int = TOP_N_DEFAULT):
    return _grouped_usage(
        db,
        days=days,
        # agent_name e opcional no evento; agent_key e o identificador estavel.
        group_sql="COALESCE(NULLIF(e.agent_name, ''), NULLIF(e.agent_key, ''), 'Sem agente')",
        label_alias="agent_label",
        company_id=company_id,
        limit=limit,
    )


def get_ai_usage_by_model(db: Session, *, days: int, company_id: Optional[int] = None, limit: int = TOP_N_DEFAULT):
    return _grouped_usage(
        db,
        days=days,
        group_sql="COALESCE(NULLIF(e.model, ''), 'Sem modelo')",
        label_alias="model_label",
        company_id=company_id,
        limit=limit,
    )


def get_ai_usage_by_provider(db: Session, *, days: int, company_id: Optional[int] = None, limit: int = TOP_N_DEFAULT):
    return _grouped_usage(
        db,
        days=days,
        group_sql="e.provider",
        label_alias="provider_label",
        company_id=company_id,
        limit=limit,
    )


def get_recent_ai_events(
    db: Session,
    *,
    days: int,
    company_id: Optional[int] = None,
    only_failed: bool = False,
    limit: int = RECENT_EVENTS_LIMIT,
) -> List[Dict[str, Any]]:
    since = period_start(days)
    extra_where, extra_params = _usage_filters(company_id)
    failed_clause = " AND e.status = 'failed'" if only_failed else ""
    params = {"since": since, "limit": limit, **extra_params}

    rows = db.execute(
        text(
            f"""
            SELECT
                e.id,
                e.company_id,
                COALESCE(NULLIF(c.name_company, ''), c.name) AS company_name,
                e.provider,
                e.operation,
                e.model,
                e.status,
                e.agent_name,
                e.agent_key,
                e.total_tokens,
                e.estimated_cost_brl,
                e.error_message,
                e.created_at
            FROM ai_usage_events e
            JOIN companies c ON c.id = e.company_id
            WHERE e.created_at >= :since{extra_where}{failed_clause}
            ORDER BY e.created_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    return [
        {
            "id": _int(row["id"]),
            "company_id": _int(row["company_id"]),
            "company_name": row["company_name"],
            "provider": row["provider"],
            "operation": row["operation"],
            "model": row["model"],
            "status": row["status"],
            "agent": row["agent_name"] or row["agent_key"],
            "total_tokens": _int(row["total_tokens"]),
            "cost_brl": _float(row["estimated_cost_brl"]),
            # error_message pode conter payload do provedor. Truncado porque a
            # tabela e de leitura rapida, nao de depuracao.
            "error_message": (row["error_message"] or "")[:280] or None,
            "created_at": _iso(row["created_at"]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Integracoes
# ---------------------------------------------------------------------------

def get_integrations_health(db: Session, *, days: int) -> List[Dict[str, Any]]:
    """Saude normalizada por conexao.

    Nao existe tabela unica de conexoes -- cada provedor guarda estado no seu
    proprio lugar (``companies`` para WhatsApp, ``calendar_integrations``,
    ``telegram_integrations``). A normalizacao acontece aqui, em leitura, e
    nao numa tabela nova: duplicar estado seria criar uma fonte de verdade
    concorrente que pode divergir.

    Nenhum segredo (token, senha, refresh token) entra na resposta.
    """
    since = period_start(days)

    whatsapp = db.execute(
        text(
            """
            SELECT
                c.id                    AS company_id,
                COALESCE(NULLIF(c.name_company, ''), c.name) AS company_name,
                c.waha_enabled,
                c.waha_session_name,
                wa.last_success_at,
                wa.last_failure_at,
                wa.failures
            FROM companies c
            LEFT JOIN LATERAL (
                SELECT
                    MAX(w.created_at) FILTER (WHERE w.status = 'completed')       AS last_success_at,
                    MAX(w.created_at) FILTER (WHERE w.status = ANY(:failure_statuses)) AS last_failure_at,
                    COUNT(*) FILTER (WHERE w.status = ANY(:failure_statuses))     AS failures
                FROM webhook_audit w
                WHERE w.company_id = c.id AND w.created_at >= :since
            ) wa ON TRUE
            WHERE c.waha_enabled OR c.waha_session_name IS NOT NULL
            ORDER BY company_name
            """
        ),
        {"since": since, "failure_statuses": list(WEBHOOK_FAILURE_STATUSES)},
    ).mappings().all()

    calendar = db.execute(
        text(
            """
            SELECT
                ci.company_id,
                COALESCE(NULLIF(c.name_company, ''), c.name) AS company_name,
                ci.provider,
                (ci.google_oauth_token IS NOT NULL)          AS google_authorized,
                ci.google_account_email,
                ci.clinicorp_subscriber_id
            FROM calendar_integrations ci
            JOIN companies c ON c.id = ci.company_id
            ORDER BY company_name
            """
        )
    ).mappings().all()

    telegram = db.execute(
        text(
            """
            SELECT
                ti.company_id,
                COALESCE(NULLIF(c.name_company, ''), c.name) AS company_name,
                ti.status,
                ti.last_error,
                ti.last_validated_at,
                ti.created_at
            FROM telegram_integrations ti
            JOIN companies c ON c.id = ti.company_id
            ORDER BY company_name
            """
        )
    ).mappings().all()

    items: List[Dict[str, Any]] = []

    for row in whatsapp:
        connected = bool(row["waha_enabled"] and row["waha_session_name"])
        failures = _int(row["failures"])
        items.append(
            {
                "company_id": _int(row["company_id"]),
                "company_name": row["company_name"],
                "provider": "whatsapp_waha",
                "status": "connected" if connected else "disconnected",
                "health_status": _health_from_signals(connected, failures),
                "connected_at": None,
                "last_success_at": _iso(row["last_success_at"]),
                "last_failure_at": _iso(row["last_failure_at"]),
                "failures_in_period": failures,
                "last_error": None,
            }
        )

    for row in calendar:
        provider = row["provider"] or "unknown"
        if provider == "google":
            connected = bool(row["google_authorized"])
        elif provider == "clinicorp":
            connected = bool(row["clinicorp_subscriber_id"])
        else:
            connected = False
        items.append(
            {
                "company_id": _int(row["company_id"]),
                "company_name": row["company_name"],
                "provider": f"calendar_{provider}",
                "status": "connected" if connected else "pending",
                "health_status": "healthy" if connected else "attention",
                "connected_at": None,
                "last_success_at": None,
                "last_failure_at": None,
                "failures_in_period": 0,
                "last_error": None,
            }
        )

    for row in telegram:
        status = row["status"] or "unknown"
        connected = status == "connected"
        items.append(
            {
                "company_id": _int(row["company_id"]),
                "company_name": row["company_name"],
                "provider": "telegram",
                "status": status,
                "health_status": "healthy" if connected and not row["last_error"] else "attention",
                "connected_at": _iso(row["created_at"]),
                "last_success_at": _iso(row["last_validated_at"]),
                "last_failure_at": None,
                "failures_in_period": 0,
                "last_error": (row["last_error"] or "")[:280] or None,
            }
        )

    return items


def _health_from_signals(connected: bool, failures: int) -> str:
    if not connected:
        return "down"
    if failures > 0:
        return "attention"
    return "healthy"


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------

# Uma conta parada por mais de uma semana e sinal de abandono, nao de fim de
# semana longo.
INACTIVITY_ALERT_DAYS = 7
# Abaixo disso a taxa de erro e ruido estatistico.
MIN_EVENTS_FOR_ERROR_RATE = 20
ERROR_RATE_ALERT_PERCENT = 10.0


def get_alerts(db: Session, *, days: int) -> List[Dict[str, Any]]:
    """Contas que precisam de atencao, derivadas de sinais reais.

    Tres regras hoje, todas verificaveis: taxa de erro de IA, inatividade, e
    WhatsApp habilitado mas sem sessao. Nada de score sintetico.
    """
    since = period_start(days)
    inactivity_cutoff = period_start(INACTIVITY_ALERT_DAYS)

    rows = db.execute(
        text(
            """
            SELECT
                c.id                                            AS company_id,
                COALESCE(NULLIF(c.name_company, ''), c.name)    AS company_name,
                c.operational_status                            AS status,
                c.waha_enabled                                  AS waha_enabled,
                c.waha_session_name                             AS waha_session_name,
                usage.events                                    AS ai_events,
                usage.failed_events                             AS ai_errors,
                activity.last_activity_at                       AS last_activity_at
            FROM companies c
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*)                                    AS events,
                    COUNT(*) FILTER (WHERE e.status = 'failed') AS failed_events
                FROM ai_usage_events e
                WHERE e.company_id = c.id AND e.created_at >= :since
            ) usage ON TRUE
            LEFT JOIN LATERAL (
                SELECT MAX(m.timestamp) AS last_activity_at
                FROM messages m
                WHERE m.company_id = c.id
            ) activity ON TRUE
            WHERE c.operational_status <> 'blocked'
            """
        ),
        {"since": since},
    ).mappings().all()

    alerts: List[Dict[str, Any]] = []

    for row in rows:
        company_id = _int(row["company_id"])
        company_name = row["company_name"]
        events = _int(row["ai_events"])
        errors = _int(row["ai_errors"])
        last_activity = row["last_activity_at"]

        if events >= MIN_EVENTS_FOR_ERROR_RATE:
            error_rate = (errors / events) * 100
            if error_rate >= ERROR_RATE_ALERT_PERCENT:
                alerts.append(
                    {
                        "company_id": company_id,
                        "company_name": company_name,
                        "severity": "critical" if error_rate >= 25 else "warning",
                        "kind": "ai_error_rate",
                        "title": "Taxa de erro de IA elevada",
                        "detail": f"{errors} de {events} eventos falharam ({error_rate:.1f}%).",
                    }
                )

        if row["waha_enabled"] and not row["waha_session_name"]:
            alerts.append(
                {
                    "company_id": company_id,
                    "company_name": company_name,
                    "severity": "warning",
                    "kind": "whatsapp_session_missing",
                    "title": "WhatsApp habilitado sem sessão",
                    "detail": "A empresa tem WAHA ligado mas nenhuma sessão registrada.",
                }
            )

        if last_activity is None:
            alerts.append(
                {
                    "company_id": company_id,
                    "company_name": company_name,
                    "severity": "info",
                    "kind": "never_active",
                    "title": "Nunca teve atividade",
                    "detail": "Nenhuma mensagem registrada desde a criação da conta.",
                }
            )
        elif last_activity < inactivity_cutoff:
            idle_days = (datetime.now(timezone.utc) - last_activity).days
            alerts.append(
                {
                    "company_id": company_id,
                    "company_name": company_name,
                    "severity": "warning",
                    "kind": "inactive",
                    "title": "Conta inativa",
                    "detail": f"Sem mensagens há {idle_days} dias.",
                }
            )

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda alert: (severity_order.get(alert["severity"], 3), alert["company_name"] or ""))
    return alerts
