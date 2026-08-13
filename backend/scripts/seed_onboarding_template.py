"""Seed idempotente do roteiro de onboarding padrao.

Rodar depois de ``alembic upgrade head``::

    python -m backend.scripts.seed_onboarding_template

O conteudo vive aqui, e nao numa migration, porque e *dado editavel*: mudar o
texto de uma etapa nao deve exigir uma migration nova nem impedir rollback.
Reexecutar atualiza o que mudou e nao duplica nada.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Dict, List

from backend.db import SessionLocal
from backend.models.onboarding_models import (
    OnboardingItem,
    OnboardingSection,
    OnboardingTemplate,
)
from backend.services.onboarding_service import DEFAULT_TEMPLATE_KEY

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_onboarding")


TEMPLATE: Dict[str, Any] = {
    "key": DEFAULT_TEMPLATE_KEY,
    "name": "Preparar o sistema operacional da sua empresa",
    "description": (
        "Antes dos agentes começarem a trabalhar, precisamos entender seu "
        "negócio e conectar as principais fontes de dados."
    ),
    "sections": [
        {
            "key": "empresa",
            "title": "Sua empresa",
            "description": "O ponto de partida: quem é a empresa que os agentes vão representar.",
            "items": [
                {
                    "key": "company_profile",
                    "title": "Dados da empresa",
                    "description": "Nome, identidade visual e informações básicas do workspace.",
                    "estimated_minutes": 5,
                    "action_label": "Configurar",
                    "action_route": "/company",
                    "requires_item_keys": [],
                    "is_required": True,
                },
            ],
        },
        {
            "key": "conexoes",
            "title": "Conexões",
            "description": "Os canais por onde a operação acontece e o motor que responde.",
            "items": [
                {
                    "key": "whatsapp_connect",
                    "title": "Conectar o WhatsApp",
                    "description": "Leia o QR Code para o canal de atendimento entrar no ar.",
                    "estimated_minutes": 3,
                    "action_label": "Conectar",
                    "action_route": "/whatsapp",
                    "requires_item_keys": ["company_profile"],
                    "is_required": True,
                },
                {
                    "key": "ai_provider",
                    "title": "Configurar o provedor de IA",
                    "description": "Informe a chave do provedor que vai executar os agentes.",
                    "estimated_minutes": 3,
                    "action_label": "Configurar",
                    "action_route": "/company/ai-provider",
                    "requires_item_keys": ["company_profile"],
                    "is_required": True,
                },
            ],
        },
        {
            "key": "operacao",
            "title": "Operação com IA",
            "description": "Com os dados e os canais no lugar, os agentes entram em campo.",
            "items": [
                {
                    "key": "first_agent",
                    "title": "Criar o primeiro agente",
                    "description": "Monte o agente que vai atender no WhatsApp e publique.",
                    "estimated_minutes": 15,
                    "action_label": "Criar agente",
                    "action_route": "/agents",
                    # A dependencia do exemplo do produto: so libera depois de
                    # dados essenciais da empresa + uma integracao necessaria.
                    "requires_item_keys": ["company_profile", "whatsapp_connect", "ai_provider"],
                    "is_required": True,
                },
                {
                    "key": "pipeline_setup",
                    "title": "Desenhar o pipeline",
                    "description": "Defina as etapas pelas quais um lead passa até virar cliente.",
                    "estimated_minutes": 10,
                    "action_label": "Abrir pipeline",
                    "action_route": "/crm",
                    "requires_item_keys": ["company_profile"],
                    "is_required": False,
                },
            ],
        },
    ],
}


def seed(dry_run: bool = False) -> None:
    db = SessionLocal()
    created: List[str] = []
    updated: List[str] = []
    try:
        template = (
            db.query(OnboardingTemplate)
            .filter(OnboardingTemplate.key == TEMPLATE["key"])
            .first()
        )
        if template is None:
            template = OnboardingTemplate(key=TEMPLATE["key"])
            db.add(template)
            created.append(f"template:{TEMPLATE['key']}")
        else:
            updated.append(f"template:{TEMPLATE['key']}")

        template.name = TEMPLATE["name"]
        template.description = TEMPLATE["description"]
        template.is_active = True
        db.flush()

        for section_position, section_data in enumerate(TEMPLATE["sections"]):
            section = (
                db.query(OnboardingSection)
                .filter(
                    OnboardingSection.template_id == template.id,
                    OnboardingSection.key == section_data["key"],
                )
                .first()
            )
            if section is None:
                section = OnboardingSection(template_id=template.id, key=section_data["key"])
                db.add(section)
                created.append(f"section:{section_data['key']}")
            else:
                updated.append(f"section:{section_data['key']}")

            section.title = section_data["title"]
            section.description = section_data["description"]
            section.position = section_position
            db.flush()

            for item_position, item_data in enumerate(section_data["items"]):
                item = (
                    db.query(OnboardingItem)
                    .filter(
                        OnboardingItem.section_id == section.id,
                        OnboardingItem.key == item_data["key"],
                    )
                    .first()
                )
                if item is None:
                    item = OnboardingItem(section_id=section.id, key=item_data["key"])
                    db.add(item)
                    created.append(f"item:{item_data['key']}")
                else:
                    updated.append(f"item:{item_data['key']}")

                item.title = item_data["title"]
                item.description = item_data["description"]
                item.estimated_minutes = item_data["estimated_minutes"]
                item.action_label = item_data["action_label"]
                item.action_route = item_data["action_route"]
                item.requires_item_keys = item_data["requires_item_keys"]
                item.is_required = item_data["is_required"]
                item.position = item_position

        if dry_run:
            db.rollback()
            logger.info("dry-run: nada gravado")
        else:
            db.commit()

        logger.info("criados: %s", ", ".join(created) or "nenhum")
        logger.info("atualizados: %s", ", ".join(updated) or "nenhum")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed do roteiro de onboarding padrão")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o que faria sem gravar")
    args = parser.parse_args()
    seed(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
