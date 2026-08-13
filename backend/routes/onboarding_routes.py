"""Onboarding do workspace.

Escopo: o company_id vem sempre da conta autenticada, nunca do corpo ou da
query. Um workspace nao consegue ler nem escrever o onboarding de outro.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import get_db
from backend.models import Client, User
from backend.services import onboarding_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class ItemStatusPayload(BaseModel):
    status: str = Field(..., description="todo | in_progress | done")


class AnswersPayload(BaseModel):
    answers: Dict[str, Any] = Field(default_factory=dict)
    item_key: Optional[str] = None


def _company_id(user: Union[Client, User]) -> int:
    company_id = getattr(user, "company_id", None)
    if company_id is None:
        raise HTTPException(status_code=400, detail="Conta sem workspace ativo")
    return int(company_id)


@router.get("/state")
def get_state(
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    return onboarding_service.get_onboarding_state(db, _company_id(user))


@router.put("/items/{item_key}")
def update_item(
    item_key: str,
    payload: ItemStatusPayload,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return onboarding_service.set_item_status(
            db,
            _company_id(user),
            item_key,
            payload.status,
            actor=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/answers")
def read_answers(
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    return {"answers": onboarding_service.get_answers(db, _company_id(user))}


@router.put("/answers")
def write_answers(
    payload: AnswersPayload,
    db: Session = Depends(get_db),
    user: Union[Client, User] = Depends(get_current_user),
) -> Dict[str, Any]:
    answers = onboarding_service.save_answers(
        db,
        _company_id(user),
        payload.answers,
        item_key=payload.item_key,
    )
    return {"answers": answers}
