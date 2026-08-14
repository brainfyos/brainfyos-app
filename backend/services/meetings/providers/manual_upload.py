"""Provedor de upload manual -- o fallback.

Existe para os casos que nenhuma integração cobre: reunião presencial, áudio
enviado pelo cliente, provedor sem API. Não é o fluxo principal e a UI não o
destaca.

Ele não *descobre* nada: quem cria a reunião é a pessoa. A transcrição vem da
infraestrutura de áudio que o projeto já usa para mensagens de voz do WhatsApp
(``prompt/media/audio_processing``), com a mesma resolução de credencial da
Fase 2 -- managed ou BYOK.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from backend.models.meeting_models import PROVIDER_MANUAL_UPLOAD
from backend.services.meetings.providers.base import (
    MeetingProviderError,
    ProviderCapabilities,
    ProviderMeeting,
    ProviderTranscript,
    ProviderTranscriptSegment,
)

logger = logging.getLogger(__name__)


class ManualUploadProvider:
    """Transcreve um arquivo enviado pela pessoa."""

    name = PROVIDER_MANUAL_UPLOAD

    def capabilities(self, db: Session, company_id: int) -> ProviderCapabilities:
        from backend.services.ai_provider_service import describe_company_ai_provider_mode

        provider_mode = describe_company_ai_provider_mode(db, company_id)
        return ProviderCapabilities(
            provider=self.name,
            label="Upload manual",
            # Nunca descobre: a reunião nasce de uma ação humana.
            can_discover_meetings=False,
            can_import_transcripts=bool(provider_mode["operational"]),
            can_identify_participants=False,
            supports_realtime=False,
            unavailable_reason=(
                None if provider_mode["operational"] else "Nenhum provedor de IA disponível"
            ),
        )

    def discover_meetings(
        self,
        db: Session,
        company_id: int,
        *,
        since: datetime,
        until: datetime,
    ) -> List[ProviderMeeting]:
        return []

    def fetch_transcript(
        self,
        db: Session,
        company_id: int,
        meeting: ProviderMeeting,
    ) -> Optional[ProviderTranscript]:
        """Transcreve a mídia apontada por ``meeting.raw['media_url']``."""
        media_url = (meeting.raw or {}).get("media_url")
        if not media_url:
            return None

        from backend.prompt.media.audio_processing import transcribe_audio
        from backend.services.ai_provider_service import resolve_company_openai_credential

        # Mesma resolução da Fase 2: BYOK primeiro, managed depois. Nenhuma
        # chave é lida do ambiente aqui.
        resolution = resolve_company_openai_credential(db, company_id)

        try:
            text = transcribe_audio(media_url, api_key=resolution.api_key)
        except Exception as exc:
            # A exceção do provedor pode carregar trecho do áudio ou material
            # de credencial; só o tipo entra no log.
            logger.error(
                "Falha ao transcrever mídia enviada: company_id=%s error_type=%s",
                company_id,
                exc.__class__.__name__,
            )
            raise MeetingProviderError("Não foi possível transcrever o arquivo enviado") from None

        cleaned = (text or "").strip()
        if not cleaned:
            return None

        return ProviderTranscript(
            # Sem id externo: a unicidade vem do par (meeting, upload).
            external_transcript_id=None,
            text=cleaned,
            # Um único segmento sem falante: a transcrição de áudio bruto não
            # tem diarização. Inventar falantes seria pior que não ter.
            segments=[ProviderTranscriptSegment(text=cleaned)],
            source_available_at=datetime.now(timezone.utc),
            metadata={"source": "manual_upload", "media_url": media_url},
        )
