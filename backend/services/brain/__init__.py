"""Brain Core -- a camada que conhece o negócio e dá contexto aos agentes.

O Brain não é um banco vetorial, uma base de conhecimento nem um prompt
gigante. Ele tem duas metades:

**Estratégia** (``brain_business_profiles``, ``brain_icp_profiles``,
``brain_offers``, ``brain_goals``) — o que só a empresa sabe: como quer
competir, para quem vende, o que promete, onde quer chegar.

**Composição** (``BrainContextService``) — leitura das fontes canônicas que já
existem. Nada de CRM, conversa, contrato ou pagamento é copiado para cá.
"""

from backend.services.brain.context_service import BrainContextService
from backend.services.brain.readiness import calculate_readiness, describe_data_sources
from backend.services.brain.schemas import BrainContext, BrainScope

__all__ = [
    "BrainContextService",
    "BrainContext",
    "BrainScope",
    "calculate_readiness",
    "describe_data_sources",
]
