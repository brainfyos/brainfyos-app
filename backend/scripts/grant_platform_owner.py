"""Concede ou revoga o papel de proprietario da plataforma.

O papel fica no banco (``clients.platform_role``) em vez de numa variavel de
ambiente para que a concessao seja auditavel e reversivel sem redeploy.

    python -m backend.scripts.grant_platform_owner --email dono@empresa.com
    python -m backend.scripts.grant_platform_owner --email dono@empresa.com --revoke
    python -m backend.scripts.grant_platform_owner --list

Somente contas master (``clients``) podem receber o papel: sub-usuarios sao
escopados a uma company por construcao.
"""

from __future__ import annotations

import argparse
import logging
import sys

from backend.db import SessionLocal
from backend.models import Client
from backend.models.platform_models import PLATFORM_ROLE_OWNER

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("grant_platform_owner")


def _normalize(email: str) -> str:
    return (email or "").strip().lower()


def list_owners() -> int:
    db = SessionLocal()
    try:
        owners = (
            db.query(Client)
            .filter(Client.platform_role == PLATFORM_ROLE_OWNER)
            .order_by(Client.email)
            .all()
        )
        if not owners:
            logger.info("Nenhum proprietario de plataforma definido.")
            return 0
        for owner in owners:
            logger.info("id=%s email=%s ativo=%s", owner.id, owner.email, owner.is_active)
        return 0
    finally:
        db.close()


def set_role(email: str, revoke: bool) -> int:
    normalized = _normalize(email)
    if not normalized:
        logger.error("Informe --email")
        return 2

    db = SessionLocal()
    try:
        client = db.query(Client).filter(Client.email == normalized).first()
        if client is None:
            logger.error(
                "Nenhuma conta master com o e-mail %s. "
                "Sub-usuarios (tabela users) nao podem receber este papel.",
                normalized,
            )
            return 1

        client.platform_role = None if revoke else PLATFORM_ROLE_OWNER
        db.commit()
        logger.info(
            "%s: %s (client_id=%s)",
            "Papel revogado" if revoke else "Papel concedido",
            normalized,
            client.id,
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Gerencia o papel platform_owner")
    parser.add_argument("--email", help="E-mail da conta master")
    parser.add_argument("--revoke", action="store_true", help="Remove o papel em vez de conceder")
    parser.add_argument("--list", action="store_true", help="Lista os proprietarios atuais")
    args = parser.parse_args()

    if args.list:
        return list_owners()
    return set_role(args.email or "", args.revoke)


if __name__ == "__main__":
    sys.exit(main())
