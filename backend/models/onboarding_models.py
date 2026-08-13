"""Modelos do onboarding de workspaces.

Template -> Section -> Item descrevem o roteiro (conteudo versionado, igual
para todos os workspaces). Progress e Answer guardam o estado por empresa.

A separacao existe para que adicionar uma etapa nova seja um seed, nao um
deploy de frontend: nenhum componente conhece a lista de tarefas.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from backend.db import Base

ONBOARDING_STATUS_TODO = "todo"
ONBOARDING_STATUS_IN_PROGRESS = "in_progress"
ONBOARDING_STATUS_DONE = "done"
ONBOARDING_STATUS_BLOCKED = "blocked"
ONBOARDING_STATUS_SKIPPED = "skipped"

ONBOARDING_STATUSES = (
    ONBOARDING_STATUS_TODO,
    ONBOARDING_STATUS_IN_PROGRESS,
    ONBOARDING_STATUS_DONE,
    ONBOARDING_STATUS_BLOCKED,
    ONBOARDING_STATUS_SKIPPED,
)


class OnboardingTemplate(Base):
    __tablename__ = "onboarding_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(80), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, server_default="1")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    sections = relationship(
        "OnboardingSection",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="OnboardingSection.position",
    )

    __table_args__ = (
        UniqueConstraint("key", name="uq_onboarding_templates_key"),
    )


class OnboardingSection(Base):
    __tablename__ = "onboarding_sections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey("onboarding_templates.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(80), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    position = Column(Integer, nullable=False, server_default="0")

    template = relationship("OnboardingTemplate", back_populates="sections")
    items = relationship(
        "OnboardingItem",
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="OnboardingItem.position",
    )

    __table_args__ = (
        UniqueConstraint("template_id", "key", name="uq_onboarding_sections_template_key"),
        Index("idx_onboarding_sections_template", "template_id", "position"),
    )


class OnboardingItem(Base):
    __tablename__ = "onboarding_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    section_id = Column(Integer, ForeignKey("onboarding_sections.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(80), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    estimated_minutes = Column(Integer, nullable=True)
    action_label = Column(String(80), nullable=True)
    action_route = Column(String(255), nullable=True)
    # Lista de ``OnboardingItem.key`` que precisam estar concluidos para este
    # item sair de 'blocked'. JSONB e nao tabela de arestas: o grafo hoje e
    # raso e criar a tabela agora seria generalidade especulativa.
    requires_item_keys = Column(JSONB, nullable=False, server_default="[]")
    is_required = Column(Boolean, nullable=False, server_default="true")
    position = Column(Integer, nullable=False, server_default="0")

    section = relationship("OnboardingSection", back_populates="items")

    __table_args__ = (
        UniqueConstraint("section_id", "key", name="uq_onboarding_items_section_key"),
        Index("idx_onboarding_items_section", "section_id", "position"),
    )


class OnboardingProgress(Base):
    __tablename__ = "onboarding_progress"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("onboarding_items.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False, server_default=ONBOARDING_STATUS_TODO)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    updated_by_client_id = Column(Integer, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    updated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    item = relationship("OnboardingItem")

    __table_args__ = (
        UniqueConstraint("company_id", "item_id", name="uq_onboarding_progress_company_item"),
        CheckConstraint(
            "status IN ('todo', 'in_progress', 'done', 'blocked', 'skipped')",
            name="chk_onboarding_progress_status",
        ),
        Index("idx_onboarding_progress_company", "company_id"),
    )


class OnboardingAnswer(Base):
    """Resposta livre coletada durante o onboarding.

    Chave/valor por empresa para que novas perguntas nao exijam migration.
    Quando um dado amadurece e vira parte do Brain, ele migra para uma coluna
    propria e esta linha vira apenas historico.
    """

    __tablename__ = "onboarding_answers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("onboarding_items.id", ondelete="SET NULL"), nullable=True)
    field_key = Column(String(120), nullable=False)
    value = Column(JSONB, nullable=False, server_default="{}")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("company_id", "field_key", name="uq_onboarding_answers_company_field"),
        Index("idx_onboarding_answers_company", "company_id"),
    )
