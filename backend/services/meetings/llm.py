"""Chamada de LLM para inteligência de reunião.

Ponto único das chamadas desta fase, por dois motivos:

1. **Credencial.** Passa sempre por ``resolve_company_openai_credential`` — o
   resolvedor da Fase 2. Nenhuma chave é lida do ambiente aqui; managed e BYOK
   continuam funcionando exatamente como antes.

2. **Ledger.** Todo consumo é registrado em ``ai_usage_events`` com a operação
   correta (``meeting_analysis``, ``sales_memory``, ``follow_up_generation``) e
   com ``meeting_id`` no metadata, que é o que permitirá saber depois quanto
   cada reunião custou.

A saída do modelo é sempre JSON validado contra schema. Um LLM devolvendo
estrutura livre direto para o banco é como aceitar input de usuário sem
validar — só que mais difícil de auditar depois.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.services.ai_provider_service import (
    REQUIRED_OPENAI_RUNTIME_MODEL,
    resolve_company_openai_credential,
)
from backend.services.ai_usage_service import safe_record_ai_usage_event

logger = logging.getLogger(__name__)

OPERATION_MEETING_ANALYSIS = "meeting_analysis"
OPERATION_SALES_MEMORY = "sales_memory"
OPERATION_FOLLOW_UP = "follow_up_generation"

# Teto de caracteres da transcrição enviada ao modelo. Uma reunião de uma hora
# passa de 60 mil caracteres; mandar tudo custa caro e afoga o sinal. O corte
# preserva o começo (contexto) e o fim (compromissos e próximos passos), que é
# onde a informação comercial se concentra.
MAX_TRANSCRIPT_CHARS = 24_000
HEAD_RATIO = 0.4


class MeetingLLMError(RuntimeError):
    """Falha de análise cuja mensagem é segura para exibir."""


def truncate_transcript(text: str, limit: int = MAX_TRANSCRIPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * HEAD_RATIO)
    tail = limit - head
    return (
        f"{text[:head]}\n\n[...trecho intermediário omitido por tamanho...]\n\n{text[-tail:]}"
    )


def complete_json(
    db: Session,
    company_id: int,
    *,
    operation: str,
    system_prompt: str,
    user_prompt: str,
    meeting_id: Optional[int] = None,
    lead_id: Optional[int] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """Uma completion JSON, com consumo registrado no ledger."""
    from openai import OpenAI

    resolution = resolve_company_openai_credential(db, company_id)
    chosen_model = model or REQUIRED_OPENAI_RUNTIME_MODEL

    client = OpenAI(api_key=resolution.api_key)

    try:
        response = client.chat.completions.create(
            model=chosen_model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as exc:
        _record_usage(
            db,
            company_id,
            operation=operation,
            model=chosen_model,
            usage=None,
            status="failed",
            meeting_id=meeting_id,
            lead_id=lead_id,
            provider_mode=resolution.mode,
            # Só o tipo: a exceção pode carregar trecho da transcrição.
            error_message=exc.__class__.__name__,
        )
        logger.error(
            "Falha na análise de IA: company_id=%s operation=%s error_type=%s",
            company_id,
            operation,
            exc.__class__.__name__,
        )
        raise MeetingLLMError("Não foi possível concluir a análise de IA") from None

    _record_usage(
        db,
        company_id,
        operation=operation,
        model=chosen_model,
        usage=getattr(response, "usage", None),
        status="success",
        meeting_id=meeting_id,
        lead_id=lead_id,
        provider_mode=resolution.mode,
    )

    content = (response.choices[0].message.content or "").strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # O conteúdo devolvido não entra no log: é derivado da transcrição.
        logger.warning(
            "Resposta de IA não era JSON: company_id=%s operation=%s", company_id, operation
        )
        raise MeetingLLMError("A análise de IA retornou um formato inesperado") from None

    if not isinstance(parsed, dict):
        raise MeetingLLMError("A análise de IA retornou um formato inesperado")
    return parsed


def _record_usage(
    db: Session,
    company_id: int,
    *,
    operation: str,
    model: str,
    usage: Any,
    status: str,
    meeting_id: Optional[int],
    lead_id: Optional[int],
    provider_mode: str,
    error_message: Optional[str] = None,
) -> None:
    from backend.services.ai_usage_service import extract_openai_usage

    normalized = extract_openai_usage(usage) if usage is not None else {
        "input_tokens": None,
        "output_tokens": None,
        "cached_tokens": None,
        "reasoning_tokens": None,
        "total_tokens": None,
    }

    safe_record_ai_usage_event(
        db=db,
        company_id=company_id,
        provider="openai",
        operation=operation,
        status=status,
        model=model,
        input_tokens=normalized["input_tokens"],
        output_tokens=normalized["output_tokens"],
        cached_tokens=normalized["cached_tokens"],
        reasoning_tokens=normalized["reasoning_tokens"],
        total_tokens=normalized["total_tokens"],
        error_message=error_message,
        # Referência da reunião no metadata: é assim que o custo por reunião
        # vira consultável sem criar sistema financeiro novo.
        usage_metadata={
            "meeting_id": meeting_id,
            "lead_id": lead_id,
            "provider_mode": provider_mode,
        },
    )
