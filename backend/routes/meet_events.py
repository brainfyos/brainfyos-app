"""Endpoint push do Pub/Sub para eventos do Google Meet.

É por aqui que o fluxo deixa de ser periódico: o Google avisa quando a
transcrição fica pronta, em vez de perguntarmos.

**Autenticidade.** O Pub/Sub assina cada POST com um JWT OIDC no header
``Authorization: Bearer``. Validamos assinatura, emissor, audiência e o e-mail
da service account configurada. Não usamos "token secreto na querystring":
isso aparece em log de proxy, em referer e em histórico de acesso.

**Resposta rápida.** O Pub/Sub reentrega quando não recebe 2xx a tempo. Todo
trabalho real vai para o Celery e a rota responde imediatamente. Um erro de
processamento **não** vira 500: isso faria o Pub/Sub reentregar em laço um
evento que continuará falhando.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meet-events", tags=["meet-events"])

PUBSUB_SERVICE_ACCOUNT_ENV = "GOOGLE_MEET_PUBSUB_SERVICE_ACCOUNT"
PUBSUB_AUDIENCE_ENV = "GOOGLE_MEET_PUBSUB_AUDIENCE"
PUBSUB_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


def _verify_push_token(authorization: Optional[str]) -> None:
    """Valida o JWT OIDC que o Pub/Sub anexa ao POST.

    Sem service account configurada a rota recusa tudo. Aceitar entrega não
    verificada deixaria qualquer um injetar eventos de reunião.
    """
    expected_account = (os.getenv(PUBSUB_SERVICE_ACCOUNT_ENV) or "").strip()
    if not expected_account:
        logger.error("Push do Meet recebido sem %s configurada", PUBSUB_SERVICE_ACCOUNT_ENV)
        raise HTTPException(status_code=503, detail="Integração de eventos não configurada")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Requisição não autenticada")

    token = authorization.split(" ", 1)[1].strip()

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        audience = (os.getenv(PUBSUB_AUDIENCE_ENV) or "").strip() or None
        claims = id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=audience
        )
    except Exception as exc:
        logger.warning("Push do Meet rejeitado: error_type=%s", exc.__class__.__name__)
        raise HTTPException(status_code=401, detail="Token inválido") from None

    if claims.get("iss") not in PUBSUB_ISSUERS:
        raise HTTPException(status_code=401, detail="Emissor inválido")

    if (claims.get("email") or "").lower() != expected_account.lower():
        logger.warning("Push do Meet com service account inesperada")
        raise HTTPException(status_code=403, detail="Origem não autorizada")

    if claims.get("email_verified") is False:
        raise HTTPException(status_code=401, detail="Token inválido")


def _decode_message(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Extrai o evento do envelope do Pub/Sub."""
    message = envelope.get("message") or {}
    attributes = message.get("attributes") or {}

    payload: Dict[str, Any] = {}
    raw = message.get("data")
    if raw:
        try:
            payload = json.loads(base64.b64decode(raw).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
            # Corpo ilegível não é motivo para reentrega infinita — os
            # atributos ainda podem trazer o tipo e o recurso.
            logger.warning("Evento do Meet com corpo ilegível")
            payload = {}

    return {
        "message_id": message.get("messageId") or message.get("message_id"),
        "publish_time": message.get("publishTime"),
        # O tipo vem no atributo `ce-type` (CloudEvents) e também no corpo.
        "event_type": attributes.get("ce-type") or payload.get("eventType"),
        "subject": attributes.get("ce-subject") or payload.get("subject"),
        "attributes": attributes,
        "payload": payload,
    }


@router.post("/google/pubsub")
async def receive_meet_event(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Recebe um evento do Workspace Events via Pub/Sub push.

    Sempre responde 2xx depois de autenticar: o processamento é assíncrono e
    idempotente, e devolver erro só faria o Pub/Sub reentregar.
    """
    _verify_push_token(authorization)

    try:
        envelope = await request.json()
    except Exception:
        # ACK: corpo inválido não melhora com reentrega.
        logger.warning("Push do Meet com envelope inválido")
        return {"status": "ignored", "reason": "invalid_envelope"}

    event = _decode_message(envelope if isinstance(envelope, dict) else {})

    if not event["event_type"]:
        return {"status": "ignored", "reason": "missing_event_type"}

    from backend.worker.tasks_meet_events import process_meet_event

    process_meet_event.delay(event)

    # Nunca logamos `payload`: ele carrega identificadores da reunião.
    logger.info(
        "Evento do Meet enfileirado: type=%s message_id=%s",
        event["event_type"],
        event["message_id"],
    )
    return {"status": "queued"}
