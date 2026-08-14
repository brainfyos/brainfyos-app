"""Registro de provedores de reunião.

**Microsoft Teams não está aqui de propósito.** O projeto não tem nenhuma
infraestrutura de autenticação Microsoft — sem OAuth da Microsoft Identity
Platform, sem token, sem refresh. Um `MicrosoftTeamsProvider` hoje seria um
arquivo que levanta "não configurado" em toda chamada: custo de manutenção sem
capacidade nenhuma.

O contrato em ``base.MeetingProvider`` já é o que o Teams vai implementar. O
que falta para ativá-lo está documentado em ``docs/MEETING-INTELLIGENCE.md``.
"""

from typing import Dict, List

from backend.services.meetings.providers.base import (
    MeetingProvider,
    MeetingProviderError,
    MeetingProviderNotConfiguredError,
    ProviderCapabilities,
    ProviderMeeting,
    ProviderParticipant,
    ProviderTranscript,
    ProviderTranscriptSegment,
)
from backend.services.meetings.providers.google_meet import GoogleMeetProvider
from backend.services.meetings.providers.manual_upload import ManualUploadProvider

_REGISTRY: Dict[str, MeetingProvider] = {
    GoogleMeetProvider.name: GoogleMeetProvider(),
    ManualUploadProvider.name: ManualUploadProvider(),
}


def get_provider(name: str) -> MeetingProvider:
    provider = _REGISTRY.get(name)
    if provider is None:
        raise MeetingProviderError(f"Provedor de reunião desconhecido: {name}")
    return provider


def available_providers() -> List[MeetingProvider]:
    return list(_REGISTRY.values())


def discoverable_providers() -> List[MeetingProvider]:
    """Provedores que a sincronização agendada deve varrer."""
    return [provider for provider in _REGISTRY.values() if provider.name != ManualUploadProvider.name]


__all__ = [
    "MeetingProvider",
    "MeetingProviderError",
    "MeetingProviderNotConfiguredError",
    "ProviderCapabilities",
    "ProviderMeeting",
    "ProviderParticipant",
    "ProviderTranscript",
    "ProviderTranscriptSegment",
    "GoogleMeetProvider",
    "ManualUploadProvider",
    "get_provider",
    "available_providers",
    "discoverable_providers",
]
