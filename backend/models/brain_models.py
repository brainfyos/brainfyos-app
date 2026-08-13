"""Modelos do Brain Core -- a camada de estrategia.

O que **nao** esta aqui e tao importante quanto o que esta: nenhum contato,
lead, mensagem, contrato, fatura ou pagamento. Esses dados tem casa propria e
o Brain os le de la. Duplicar criaria duas verdades e a copia envelheceria.

O que esta aqui e aquilo que o sistema nao consegue observar sozinho: como a
empresa quer competir, para quem vende, o que promete e onde quer chegar.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import relationship

from backend.db import Base

# JSONB no Postgres; JSON no SQLite usado pelos testes. Sem a variante, criar
# as tabelas em memoria falharia e os testes de isolamento precisariam de
# mock -- justamente o que nao queremos neles.
TextList = JSONB(astext_type=Text()).with_variant(JSON(), "sqlite")

ICP_CUSTOMER_TYPES = ("b2b", "b2c", "b2b2c")
GOAL_STATUSES = ("active", "achieved", "missed", "archived")


def _text_list_column(name: str) -> Column:
    return Column(name, TextList, nullable=False, server_default="[]", default=list)


class BrainBusinessProfile(Base):
    """Perfil estrategico da empresa. Exatamente um por company."""

    __tablename__ = "brain_business_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    business_model = Column(Text, nullable=True)
    market = Column(Text, nullable=True)
    positioning = Column(Text, nullable=True)
    value_proposition = Column(Text, nullable=True)
    revenue_model = Column(Text, nullable=True)
    sales_motion = Column(Text, nullable=True)
    additional_context = Column(Text, nullable=True)

    competitive_advantages = _text_list_column("competitive_advantages")
    main_channels = _text_list_column("main_channels")
    strategic_priorities = _text_list_column("strategic_priorities")
    constraints = _text_list_column("constraints")

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company", foreign_keys=[company_id])

    __table_args__ = (
        UniqueConstraint("company_id", name="uq_brain_business_profile_company"),
    )


class BrainIcpProfile(Base):
    """Perfil de cliente ideal. Uma empresa pode ter varios."""

    __tablename__ = "brain_icp_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    customer_type = Column(String(40), nullable=True)
    industry = Column(String(255), nullable=True)
    company_size = Column(String(120), nullable=True)
    location = Column(String(255), nullable=True)
    revenue_range = Column(String(120), nullable=True)
    average_ticket = Column(Numeric(12, 2), nullable=True)

    decision_makers = _text_list_column("decision_makers")
    pain_points = _text_list_column("pain_points")
    desired_outcomes = _text_list_column("desired_outcomes")
    buying_triggers = _text_list_column("buying_triggers")
    objections = _text_list_column("objections")
    qualification_criteria = _text_list_column("qualification_criteria")
    disqualification_criteria = _text_list_column("disqualification_criteria")

    # 1 = principal; numeros maiores sao secundarios em ordem.
    priority = Column(Integer, nullable=False, server_default="1", default=1)
    is_active = Column(Boolean, nullable=False, server_default="true", default=True)
    archived_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company", foreign_keys=[company_id])

    __table_args__ = (
        CheckConstraint(
            "customer_type IS NULL OR customer_type IN ('b2b', 'b2c', 'b2b2c')",
            name="chk_brain_icp_customer_type",
        ),
        CheckConstraint("priority >= 1", name="chk_brain_icp_priority"),
        CheckConstraint("average_ticket IS NULL OR average_ticket >= 0", name="chk_brain_icp_ticket"),
        Index("idx_brain_icp_company", "company_id"),
        Index("idx_brain_icp_company_active", "company_id", "is_active"),
    )


class BrainOffer(Base):
    """Como um produto ou servico e levado ao mercado.

    Distinto de ``Plan``: Plan e a estrutura comercial (preco, intervalo de
    cobranca) e continua sendo dono desses numeros. A oferta descreve promessa,
    mecanismo e prova -- e opcionalmente aponta para o plano que a cobra.
    """

    __tablename__ = "brain_offers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    target_icp_id = Column(BigInteger, ForeignKey("brain_icp_profiles.id", ondelete="SET NULL"), nullable=True)
    related_plan_id = Column(Integer, ForeignKey("plans.id", ondelete="SET NULL"), nullable=True)

    promise = Column(Text, nullable=True)
    mechanism = Column(Text, nullable=True)
    pricing_strategy = Column(Text, nullable=True)
    # So faz sentido quando nao ha plano associado; com plano, o valor
    # autoritativo e plans.price.
    average_ticket = Column(Numeric(12, 2), nullable=True)
    margin_estimate = Column(Numeric(5, 2), nullable=True)
    sales_cycle_days = Column(Integer, nullable=True)

    main_objections = _text_list_column("main_objections")
    proof_points = _text_list_column("proof_points")

    is_primary = Column(Boolean, nullable=False, server_default="false", default=False)
    is_active = Column(Boolean, nullable=False, server_default="true", default=True)
    archived_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company", foreign_keys=[company_id])
    target_icp = relationship("BrainIcpProfile", foreign_keys=[target_icp_id])
    related_plan = relationship("Plan", foreign_keys=[related_plan_id])

    __table_args__ = (
        CheckConstraint("average_ticket IS NULL OR average_ticket >= 0", name="chk_brain_offer_ticket"),
        CheckConstraint(
            "margin_estimate IS NULL OR (margin_estimate >= 0 AND margin_estimate <= 100)",
            name="chk_brain_offer_margin",
        ),
        CheckConstraint(
            "sales_cycle_days IS NULL OR sales_cycle_days >= 0",
            name="chk_brain_offer_cycle",
        ),
        Index("idx_brain_offer_company", "company_id"),
        Index("idx_brain_offer_company_active", "company_id", "is_active"),
    )


class BrainGoal(Base):
    """Meta que os agentes usarao para priorizar acoes."""

    __tablename__ = "brain_goals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    metric_key = Column(String(80), nullable=True)
    baseline_value = Column(Numeric(18, 4), nullable=True)
    target_value = Column(Numeric(18, 4), nullable=True)
    unit = Column(String(30), nullable=True)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    priority = Column(Integer, nullable=False, server_default="1", default=1)
    status = Column(String(20), nullable=False, server_default="active", default="active")
    archived_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    company = relationship("Company", foreign_keys=[company_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'achieved', 'missed', 'archived')",
            name="chk_brain_goal_status",
        ),
        CheckConstraint("priority >= 1", name="chk_brain_goal_priority"),
        CheckConstraint(
            "period_end IS NULL OR period_start IS NULL OR period_end >= period_start",
            name="chk_brain_goal_period",
        ),
        Index("idx_brain_goal_company", "company_id"),
        Index("idx_brain_goal_company_status", "company_id", "status"),
    )
