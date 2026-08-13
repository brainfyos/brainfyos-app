"""Engine de onboarding de workspaces.

Duas ideias sustentam este modulo:

1. **Conteudo e dado, nao codigo.** Nenhum componente do frontend conhece a
   lista de tarefas. Adicionar uma etapa e um seed, nao um deploy.

2. **Verificar em vez de perguntar.** Quando uma tarefa pode ser conferida no
   banco -- WhatsApp conectado, provedor de IA configurado, agente criado --
   ela e conferida. Marcar manualmente uma coisa que o sistema sabe medir
   produz um checklist que mente. So itens sem sinal verificavel dependem de
   ``set_item_status``.

O status ``blocked`` nunca e persistido: e derivado das dependencias na
leitura, para que desbloquear uma etapa nao exija varrer tabela nenhuma.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from sqlalchemy import text
from sqlalchemy.orm import Session, selectinload

from backend.models import Client, User
from backend.models.onboarding_models import (
    ONBOARDING_STATUS_BLOCKED,
    ONBOARDING_STATUS_DONE,
    ONBOARDING_STATUS_IN_PROGRESS,
    ONBOARDING_STATUS_TODO,
    ONBOARDING_STATUSES,
    OnboardingAnswer,
    OnboardingItem,
    OnboardingProgress,
    OnboardingSection,
    OnboardingTemplate,
)

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_KEY = "workspace_default"

# Status que o usuario pode gravar. 'blocked' e derivado e 'skipped' ainda nao
# tem UI -- aceita-lo agora criaria estado que ninguem consegue reverter.
SETTABLE_STATUSES = (
    ONBOARDING_STATUS_TODO,
    ONBOARDING_STATUS_IN_PROGRESS,
    ONBOARDING_STATUS_DONE,
)


# ---------------------------------------------------------------------------
# Verificadores automaticos
# ---------------------------------------------------------------------------

def _has_company_profile(db: Session, company_id: int) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM companies
            WHERE id = :company_id
              AND COALESCE(NULLIF(TRIM(name_company), ''), NULLIF(TRIM(name), '')) IS NOT NULL
            LIMIT 1
            """
        ),
        {"company_id": company_id},
    ).first()
    return row is not None


def _has_whatsapp(db: Session, company_id: int) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM companies
            WHERE id = :company_id AND waha_enabled AND waha_session_name IS NOT NULL
            LIMIT 1
            """
        ),
        {"company_id": company_id},
    ).first()
    return row is not None


def _has_ai_provider(db: Session, company_id: int) -> bool:
    """Provedor operacional -- credencial propria **ou** modo managed.

    Exigir ``ai_provider_credentials`` bloqueava o onboarding de uma empresa
    que ja podia operar com a infraestrutura da plataforma. A etapa mede se a
    IA funciona, nao se ha uma linha numa tabela.
    """
    # Import tardio: o modulo do provedor carrega o SDK da OpenAI.
    from backend.services.ai_provider_service import describe_company_ai_provider_mode

    return bool(describe_company_ai_provider_mode(db, company_id)["operational"])


def _has_brain_strategy(db: Session, company_id: int) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM brain_business_profiles
            WHERE company_id = :company_id
              AND COALESCE(NULLIF(TRIM(business_model), ''), NULL) IS NOT NULL
              AND COALESCE(NULLIF(TRIM(positioning), ''), NULL) IS NOT NULL
              AND COALESCE(NULLIF(TRIM(value_proposition), ''), NULL) IS NOT NULL
            LIMIT 1
            """
        ),
        {"company_id": company_id},
    ).first()
    return row is not None


def _has_brain_icp(db: Session, company_id: int) -> bool:
    row = db.execute(
        text("SELECT 1 FROM brain_icp_profiles WHERE company_id = :company_id AND is_active LIMIT 1"),
        {"company_id": company_id},
    ).first()
    return row is not None


def _has_brain_offer(db: Session, company_id: int) -> bool:
    row = db.execute(
        text(
            "SELECT 1 FROM brain_offers "
            "WHERE company_id = :company_id AND is_active AND is_primary LIMIT 1"
        ),
        {"company_id": company_id},
    ).first()
    return row is not None


def _has_agent(db: Session, company_id: int) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM agent_workforces
            WHERE company_id = :company_id AND status <> 'draft'
            LIMIT 1
            """
        ),
        {"company_id": company_id},
    ).first()
    return row is not None


def _has_pipeline_stages(db: Session, company_id: int) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM pipelines p
            JOIN pipeline_stages s ON s.pipeline_id = p.id
            WHERE p.company_id = :company_id
            GROUP BY p.id
            HAVING COUNT(s.id) >= 2
            LIMIT 1
            """
        ),
        {"company_id": company_id},
    ).first()
    return row is not None


# Item key -> verificador. Um item ausente daqui e puramente manual.
#
# As etapas de estrategia leem as tabelas do Brain, nao ``onboarding_answers``.
# E o que impede duas verdades: o dado tem uma casa so, e o onboarding apenas
# observa se ela esta preenchida.
AUTO_RESOLVERS: Dict[str, Callable[[Session, int], bool]] = {
    "company_profile": _has_company_profile,
    "whatsapp_connect": _has_whatsapp,
    "ai_provider": _has_ai_provider,
    "first_agent": _has_agent,
    "pipeline_setup": _has_pipeline_stages,
    "brain_strategy": _has_brain_strategy,
    "brain_icp": _has_brain_icp,
    "brain_offer": _has_brain_offer,
}


# ---------------------------------------------------------------------------
# Leitura do estado
# ---------------------------------------------------------------------------

def get_active_template(db: Session, template_key: str = DEFAULT_TEMPLATE_KEY) -> Optional[OnboardingTemplate]:
    return (
        db.query(OnboardingTemplate)
        .options(selectinload(OnboardingTemplate.sections).selectinload(OnboardingSection.items))
        .filter(OnboardingTemplate.key == template_key, OnboardingTemplate.is_active.is_(True))
        .first()
    )


def get_onboarding_state(
    db: Session,
    company_id: int,
    *,
    template_key: str = DEFAULT_TEMPLATE_KEY,
) -> Dict[str, Any]:
    template = get_active_template(db, template_key)
    if template is None:
        # Sem template ativo o onboarding simplesmente nao existe para este
        # workspace -- nao e erro, e ausencia de conteudo.
        return {
            "template": None,
            "sections": [],
            "progress": {"total": 0, "completed": 0, "percent": 0},
            "is_complete": True,
            "next_item": None,
        }

    # Uma consulta para todo o progresso gravado; o resto e memoria.
    stored: Dict[int, OnboardingProgress] = {
        row.item_id: row
        for row in db.query(OnboardingProgress).filter(OnboardingProgress.company_id == company_id).all()
    }

    # Primeira passada: status efetivo de cada item, sem considerar bloqueio.
    resolved: Dict[str, str] = {}
    items_by_key: Dict[str, OnboardingItem] = {}
    for section in template.sections:
        for item in section.items:
            items_by_key[item.key] = item
            resolved[item.key] = _effective_status(db, company_id, item, stored.get(item.id))

    # Segunda passada: bloqueio por dependencia. Um item concluido continua
    # concluido mesmo que uma dependencia tenha regredido -- reverter uma
    # conquista confundiria mais do que ajudaria.
    sections_payload: List[Dict[str, Any]] = []
    total = 0
    completed = 0
    next_item: Optional[Dict[str, Any]] = None

    for section in template.sections:
        items_payload: List[Dict[str, Any]] = []
        for item in section.items:
            status = resolved[item.key]
            missing = [
                key for key in _requirement_keys(item)
                if resolved.get(key) != ONBOARDING_STATUS_DONE
            ]
            if missing and status != ONBOARDING_STATUS_DONE:
                status = ONBOARDING_STATUS_BLOCKED

            total += 1
            if status == ONBOARDING_STATUS_DONE:
                completed += 1

            payload = {
                "key": item.key,
                "title": item.title,
                "description": item.description,
                "estimated_minutes": item.estimated_minutes,
                "action_label": item.action_label,
                "action_route": item.action_route,
                "is_required": bool(item.is_required),
                "status": status,
                "is_automatic": item.key in AUTO_RESOLVERS,
                "blocked_by": [
                    {"key": key, "title": items_by_key[key].title}
                    for key in missing
                    if key in items_by_key
                ],
            }
            items_payload.append(payload)

            if next_item is None and status in (ONBOARDING_STATUS_TODO, ONBOARDING_STATUS_IN_PROGRESS):
                next_item = payload

        sections_payload.append(
            {
                "key": section.key,
                "title": section.title,
                "description": section.description,
                "items": items_payload,
                "completed": sum(1 for entry in items_payload if entry["status"] == ONBOARDING_STATUS_DONE),
                "total": len(items_payload),
            }
        )

    required_done = all(
        entry["status"] == ONBOARDING_STATUS_DONE
        for section in sections_payload
        for entry in section["items"]
        if entry["is_required"]
    )

    return {
        "template": {"key": template.key, "name": template.name, "description": template.description},
        "sections": sections_payload,
        "progress": {
            "total": total,
            "completed": completed,
            "percent": round((completed / total) * 100) if total else 0,
        },
        "is_complete": required_done,
        "next_item": next_item,
    }


def _requirement_keys(item: OnboardingItem) -> List[str]:
    raw = item.requires_item_keys
    if not isinstance(raw, list):
        return []
    return [str(entry) for entry in raw if entry]


def _effective_status(
    db: Session,
    company_id: int,
    item: OnboardingItem,
    stored: Optional[OnboardingProgress],
) -> str:
    resolver = AUTO_RESOLVERS.get(item.key)
    if resolver is not None:
        try:
            if resolver(db, company_id):
                return ONBOARDING_STATUS_DONE
        except Exception as exc:  # pragma: no cover - degradacao
            logger.warning(
                "Verificador de onboarding falhou: item=%s error_type=%s",
                item.key,
                exc.__class__.__name__,
            )
        # Um item automatico ainda pode estar marcado como "em andamento"
        # manualmente; so 'done' e ignorado, porque o banco discorda dele.
        if stored and stored.status == ONBOARDING_STATUS_IN_PROGRESS:
            return ONBOARDING_STATUS_IN_PROGRESS
        return ONBOARDING_STATUS_TODO

    if stored and stored.status in ONBOARDING_STATUSES:
        return stored.status
    return ONBOARDING_STATUS_TODO


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------

def set_item_status(
    db: Session,
    company_id: int,
    item_key: str,
    status: str,
    *,
    actor: Union[Client, User, None] = None,
    template_key: str = DEFAULT_TEMPLATE_KEY,
) -> Dict[str, Any]:
    if status not in SETTABLE_STATUSES:
        raise ValueError(f"Status inválido: {status}")

    item = (
        db.query(OnboardingItem)
        .join(OnboardingSection, OnboardingSection.id == OnboardingItem.section_id)
        .join(OnboardingTemplate, OnboardingTemplate.id == OnboardingSection.template_id)
        .filter(OnboardingTemplate.key == template_key, OnboardingItem.key == item_key)
        .first()
    )
    if item is None:
        raise LookupError(f"Item de onboarding não encontrado: {item_key}")

    progress = (
        db.query(OnboardingProgress)
        .filter(
            OnboardingProgress.company_id == company_id,
            OnboardingProgress.item_id == item.id,
        )
        .first()
    )
    if progress is None:
        progress = OnboardingProgress(company_id=company_id, item_id=item.id)
        db.add(progress)

    progress.status = status
    progress.completed_at = datetime.now(timezone.utc) if status == ONBOARDING_STATUS_DONE else None
    progress.updated_by_client_id = int(actor.id) if isinstance(actor, Client) else None
    progress.updated_by_user_id = int(actor.id) if isinstance(actor, User) else None

    db.commit()
    return get_onboarding_state(db, company_id, template_key=template_key)


def save_answers(
    db: Session,
    company_id: int,
    answers: Dict[str, Any],
    *,
    item_key: Optional[str] = None,
    template_key: str = DEFAULT_TEMPLATE_KEY,
) -> Dict[str, Any]:
    """Grava respostas chave/valor do onboarding.

    Chaves que tem casa no Brain nao ficam aqui: elas sao gravadas na tabela
    canonica e a resposta e descartada. E o que impede o onboarding e a
    BrainPage divergirem sobre o mesmo campo.

    O valor e sempre embrulhado em ``{"value": ...}`` para que a coluna JSONB
    aceite escalares sem depender do modo de serializacao do driver.
    """
    # Import tardio: brain importa modelos que importam este modulo.
    from backend.services.brain.onboarding_bridge import (
        BRAIN_OWNED_ANSWER_KEYS,
        materialize_answers_into_brain,
    )

    brain_owned = {key: value for key, value in answers.items() if key in BRAIN_OWNED_ANSWER_KEYS}
    answers = {key: value for key, value in answers.items() if key not in BRAIN_OWNED_ANSWER_KEYS}

    item_id: Optional[int] = None
    if item_key:
        item = (
            db.query(OnboardingItem)
            .join(OnboardingSection, OnboardingSection.id == OnboardingItem.section_id)
            .join(OnboardingTemplate, OnboardingTemplate.id == OnboardingSection.template_id)
            .filter(OnboardingTemplate.key == template_key, OnboardingItem.key == item_key)
            .first()
        )
        item_id = item.id if item else None

    for field_key, value in answers.items():
        normalized_key = str(field_key)[:120]
        existing = (
            db.query(OnboardingAnswer)
            .filter(
                OnboardingAnswer.company_id == company_id,
                OnboardingAnswer.field_key == normalized_key,
            )
            .first()
        )
        if existing is None:
            db.add(
                OnboardingAnswer(
                    company_id=company_id,
                    item_id=item_id,
                    field_key=normalized_key,
                    value={"value": value},
                )
            )
        else:
            existing.value = {"value": value}
            if item_id is not None:
                existing.item_id = item_id

    # As chaves do Brain sao gravadas como resposta e imediatamente movidas
    # para a tabela canonica. Passar pela tabela de respostas mantem um unico
    # caminho de escrita e deixa a materializacao idempotente.
    if brain_owned:
        for field_key, value in brain_owned.items():
            normalized_key = str(field_key)[:120]
            existing = (
                db.query(OnboardingAnswer)
                .filter(
                    OnboardingAnswer.company_id == company_id,
                    OnboardingAnswer.field_key == normalized_key,
                )
                .first()
            )
            if existing is None:
                db.add(
                    OnboardingAnswer(
                        company_id=company_id,
                        item_id=item_id,
                        field_key=normalized_key,
                        value={"value": value},
                    )
                )
            else:
                existing.value = {"value": value}
        db.flush()

    db.commit()

    if brain_owned:
        materialize_answers_into_brain(db, company_id)

    return get_answers(db, company_id)


def get_answers(db: Session, company_id: int) -> Dict[str, Any]:
    rows = db.query(OnboardingAnswer).filter(OnboardingAnswer.company_id == company_id).all()
    return {row.field_key: (row.value or {}).get("value") for row in rows}
