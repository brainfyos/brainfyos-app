"""Autorizacao global de plataforma (BrainfyOS Control).

O sistema de identidade tem exatamente dois tipos de conta:

* ``Client`` -- conta master, ligada a N companies via ``client_companies``;
* ``User``   -- sub-usuario, preso a uma unica company.

Nenhum dos dois tem escopo acima de company. O Control precisa disso, entao
``clients.platform_role`` foi adicionado como a menor extensao possivel. Nao
existe um segundo sistema de autenticacao: o token, o ``get_current_user`` e a
sessao continuam sendo os mesmos.

Regra que este modulo garante: **um usuario de workspace nunca consegue ler
outra company trocando o company_id**. Todo endpoint do Control depende de
``require_platform_owner``, que valida no backend.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.db import SessionLocal
from backend.models import Client, PlatformAuditLog, User
from backend.models.platform_models import PLATFORM_ROLE_OWNER
from backend.security import get_client_ip

logger = logging.getLogger(__name__)

PLATFORM_FORBIDDEN_MESSAGE = "Acesso restrito ao BrainfyOS Control"


def is_platform_owner(user: Union[Client, User, None]) -> bool:
    """True somente para contas master marcadas como proprietarias da plataforma.

    Sub-usuarios (``User``) nunca sao proprietarios, mesmo com ``role='admin'``:
    aquele role e escopado ao workspace e promove-lo aqui vazaria dados entre
    empresas para qualquer admin de cliente.
    """
    if not isinstance(user, Client):
        return False
    if not user.is_active:
        return False
    return (user.platform_role or "") == PLATFORM_ROLE_OWNER


def require_platform_owner(
    user: Union[Client, User] = Depends(get_current_user),
) -> Client:
    """Dependencia FastAPI para qualquer rota do Control."""
    if not is_platform_owner(user):
        logger.warning(
            "Acesso negado ao Control: account_type=%s account_id=%s",
            type(user).__name__,
            getattr(user, "id", None),
        )
        raise HTTPException(status_code=403, detail=PLATFORM_FORBIDDEN_MESSAGE)
    return user  # type: ignore[return-value]


def log_platform_action(
    *,
    actor: Client,
    action: str,
    request: Optional[Request] = None,
    target_company_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Grava uma acao administrativa sensivel.

    Usa sessao propria de proposito: a auditoria precisa de um commit imediato,
    e commitar a sessao da requisicao arrastaria junto qualquer trabalho ainda
    pendente nela.

    Falha de auditoria nunca derruba a requisicao que a originou -- mas e
    logada em WARNING, porque um log de auditoria mudo e pior do que nenhum.
    """
    audit_db: Optional[Session] = None
    try:
        audit_db = SessionLocal()
        audit_db.add(
            PlatformAuditLog(
                actor_client_id=int(actor.id),
                actor_email=actor.email or "",
                action=action,
                target_company_id=int(target_company_id) if target_company_id is not None else None,
                request_ip=get_client_ip(request) if request is not None else None,
                details=details or {},
            )
        )
        audit_db.commit()
    except Exception as exc:  # pragma: no cover - caminho de degradacao
        if audit_db is not None:
            audit_db.rollback()
        logger.warning(
            "Falha ao registrar auditoria administrativa: action=%s error_type=%s",
            action,
            exc.__class__.__name__,
        )
    finally:
        if audit_db is not None:
            audit_db.close()


def platform_owner_with_audit(action: str):
    """Fabrica de dependencia que autoriza e audita em um passo.

    Uso::

        @router.get("/accounts")
        def list_accounts(
            actor: Client = Depends(platform_owner_with_audit("control.accounts.list")),
        ):
    """

    def dependency(
        request: Request,
        actor: Client = Depends(require_platform_owner),
    ) -> Client:
        log_platform_action(actor=actor, action=action, request=request)
        return actor

    return dependency
