"""Ponte entre o onboarding e o Brain.

O problema que este modulo resolve: ``onboarding_answers`` guarda pares
chave/valor genericos. Se uma resposta sobre posicionamento ficasse ali *e*
tambem no perfil do Brain, existiriam duas verdades divergindo com o tempo --
o usuario editaria a BrainPage e o onboarding continuaria mostrando a resposta
antiga.

A regra adotada:

* Tudo que tem casa no Brain **mora no Brain**. As etapas de estrategia do
  onboarding apontam para ``/brain`` e sao verificadas lendo as tabelas do
  Brain (ver ``AUTO_RESOLVERS`` em ``onboarding_service``).
* ``onboarding_answers`` fica reservado a perguntas que ainda nao tem destino
  canonico.
* Respostas legadas cujas chaves batem com campos do Brain sao materializadas
  por ``materialize_answers_into_brain`` e removidas da tabela de respostas,
  para nao sobrar copia.

A materializacao nunca sobrescreve dado ja preenchido no Brain: o que o
usuario editou na BrainPage e mais recente e mais deliberado que o que ele
digitou no onboarding.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models.brain_models import BrainBusinessProfile
from backend.models.onboarding_models import OnboardingAnswer

logger = logging.getLogger(__name__)

# Chave de resposta -> campo de texto no perfil estrategico.
ANSWER_TO_PROFILE_TEXT: Dict[str, str] = {
    "business_model": "business_model",
    "modelo_negocio": "business_model",
    "market": "market",
    "mercado": "market",
    "positioning": "positioning",
    "posicionamento": "positioning",
    "value_proposition": "value_proposition",
    "proposta_valor": "value_proposition",
    "revenue_model": "revenue_model",
    "sales_motion": "sales_motion",
}

# Chave de resposta -> campo de lista no perfil estrategico.
ANSWER_TO_PROFILE_LIST: Dict[str, str] = {
    "competitive_advantages": "competitive_advantages",
    "diferenciais": "competitive_advantages",
    "main_channels": "main_channels",
    "canais": "main_channels",
    "strategic_priorities": "strategic_priorities",
    "prioridades": "strategic_priorities",
    "constraints": "constraints",
    "restricoes": "constraints",
}

BRAIN_OWNED_ANSWER_KEYS = frozenset(ANSWER_TO_PROFILE_TEXT) | frozenset(ANSWER_TO_PROFILE_LIST)


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _as_list(value: Any) -> List[str]:
    """Aceita lista ou texto separado por vírgula/quebra de linha."""
    if isinstance(value, list):
        items = [str(item).strip() for item in value]
    elif value is None:
        items = []
    else:
        raw = str(value)
        separator = "\n" if "\n" in raw else ","
        items = [part.strip() for part in raw.split(separator)]
    return [item for item in items if item]


def get_or_create_profile(db: Session, company_id: int) -> BrainBusinessProfile:
    """Perfil estratégico da empresa, criando um vazio na primeira vez."""
    profile = (
        db.query(BrainBusinessProfile)
        .filter(BrainBusinessProfile.company_id == int(company_id))
        .first()
    )
    if profile is None:
        profile = BrainBusinessProfile(company_id=int(company_id))
        db.add(profile)
        db.flush()
    return profile


def materialize_answers_into_brain(
    db: Session,
    company_id: int,
    *,
    discard_materialized: bool = True,
) -> Dict[str, Any]:
    """Move respostas de onboarding com destino no Brain para o Brain.

    Idempotente: rodar de novo não muda nada, porque campo já preenchido no
    Brain nunca é sobrescrito e a resposta de origem é descartada.

    Devolve o que foi aplicado, para o chamador poder registrar.
    """
    company_id = int(company_id)
    answers = (
        db.query(OnboardingAnswer)
        .filter(
            OnboardingAnswer.company_id == company_id,
            OnboardingAnswer.field_key.in_(tuple(BRAIN_OWNED_ANSWER_KEYS)),
        )
        .all()
    )

    if not answers:
        return {"applied": [], "skipped": [], "discarded": []}

    profile = get_or_create_profile(db, company_id)
    applied: List[str] = []
    skipped: List[str] = []
    discarded: List[str] = []

    for answer in answers:
        raw_value = (answer.value or {}).get("value")

        if answer.field_key in ANSWER_TO_PROFILE_TEXT:
            target = ANSWER_TO_PROFILE_TEXT[answer.field_key]
            incoming = _as_text(raw_value)
            current = _as_text(getattr(profile, target, None))
            if incoming and not current:
                setattr(profile, target, incoming)
                applied.append(f"{answer.field_key}->{target}")
            else:
                skipped.append(answer.field_key)

        elif answer.field_key in ANSWER_TO_PROFILE_LIST:
            target = ANSWER_TO_PROFILE_LIST[answer.field_key]
            incoming = _as_list(raw_value)
            current = getattr(profile, target, None) or []
            if incoming and not current:
                setattr(profile, target, incoming)
                applied.append(f"{answer.field_key}->{target}")
            else:
                skipped.append(answer.field_key)

        if discard_materialized:
            db.delete(answer)
            discarded.append(answer.field_key)

    db.commit()

    if applied:
        logger.info(
            "Respostas de onboarding materializadas no Brain: company_id=%s campos=%s",
            company_id,
            ",".join(applied),
        )

    return {"applied": applied, "skipped": skipped, "discarded": discarded}
