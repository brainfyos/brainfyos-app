"""Brain Core: perfil estrategico, ICPs, ofertas e objetivos

Quatro tabelas de *estrategia*. Nenhuma delas copia dado operacional: CRM,
contatos, mensagens, contratos, faturas, pagamentos, NPS e consumo de IA
continuam sendo as fontes canonicas e sao lidas onde estao.

Tipagem: JSONB apenas onde o valor e genuinamente uma lista de texto livre
sem necessidade de consulta (dores, diferenciais, objecoes). Todo escalar com
significado -- ticket medio, prioridade, datas, metas -- e coluna real, para
que ordenacao, agregacao e CHECK continuem sendo trabalho do banco.

Remocao e sempre logica (``is_active`` + ``archived_at``). Uma oferta aponta
para um ICP e um plano; apagar de verdade quebraria referencia e historico.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _text_list(name: str) -> sa.Column:
    """Lista de strings livres. JSONB porque nao ha consulta sobre os itens."""
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]')


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Perfil estrategico -- um por company
    # ------------------------------------------------------------------
    op.create_table(
        'brain_business_profiles',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('business_model', sa.Text(), nullable=True),
        sa.Column('market', sa.Text(), nullable=True),
        sa.Column('positioning', sa.Text(), nullable=True),
        sa.Column('value_proposition', sa.Text(), nullable=True),
        sa.Column('revenue_model', sa.Text(), nullable=True),
        sa.Column('sales_motion', sa.Text(), nullable=True),
        sa.Column('additional_context', sa.Text(), nullable=True),
        _text_list('competitive_advantages'),
        _text_list('main_channels'),
        _text_list('strategic_priorities'),
        _text_list('constraints'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('company_id', name='uq_brain_business_profile_company'),
    )

    # ------------------------------------------------------------------
    # ICPs -- uma empresa pode ter varios
    # ------------------------------------------------------------------
    op.create_table(
        'brain_icp_profiles',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('customer_type', sa.String(length=40), nullable=True),
        sa.Column('industry', sa.String(length=255), nullable=True),
        sa.Column('company_size', sa.String(length=120), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=True),
        sa.Column('revenue_range', sa.String(length=120), nullable=True),
        sa.Column('average_ticket', sa.Numeric(12, 2), nullable=True),
        _text_list('decision_makers'),
        _text_list('pain_points'),
        _text_list('desired_outcomes'),
        _text_list('buying_triggers'),
        _text_list('objections'),
        _text_list('qualification_criteria'),
        _text_list('disqualification_criteria'),
        # 1 = principal. Inteiro e nao booleano "is_primary" porque a empresa
        # ordena varios ICPs secundarios entre si.
        sa.Column('priority', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "customer_type IS NULL OR customer_type IN ('b2b', 'b2c', 'b2b2c')",
            name='chk_brain_icp_customer_type',
        ),
        sa.CheckConstraint('priority >= 1', name='chk_brain_icp_priority'),
        sa.CheckConstraint('average_ticket IS NULL OR average_ticket >= 0', name='chk_brain_icp_ticket'),
    )
    op.create_index('idx_brain_icp_company', 'brain_icp_profiles', ['company_id'])
    op.create_index('idx_brain_icp_company_active', 'brain_icp_profiles', ['company_id', 'is_active'])

    # ------------------------------------------------------------------
    # Ofertas -- como aquilo e vendido, nao o que e cobrado
    # ------------------------------------------------------------------
    op.create_table(
        'brain_offers',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('target_icp_id', sa.BigInteger(), nullable=True),
        # Plan continua dono do preco e do intervalo de cobranca. A oferta so
        # aponta para ele; nada de financeiro e copiado.
        sa.Column('related_plan_id', sa.Integer(), nullable=True),
        sa.Column('promise', sa.Text(), nullable=True),
        sa.Column('mechanism', sa.Text(), nullable=True),
        sa.Column('pricing_strategy', sa.Text(), nullable=True),
        # Preenchido apenas quando nao houver plano associado -- quando houver,
        # o valor autoritativo e plans.price.
        sa.Column('average_ticket', sa.Numeric(12, 2), nullable=True),
        sa.Column('margin_estimate', sa.Numeric(5, 2), nullable=True),
        sa.Column('sales_cycle_days', sa.Integer(), nullable=True),
        _text_list('main_objections'),
        _text_list('proof_points'),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_icp_id'], ['brain_icp_profiles.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['related_plan_id'], ['plans.id'], ondelete='SET NULL'),
        sa.CheckConstraint('average_ticket IS NULL OR average_ticket >= 0', name='chk_brain_offer_ticket'),
        sa.CheckConstraint(
            'margin_estimate IS NULL OR (margin_estimate >= 0 AND margin_estimate <= 100)',
            name='chk_brain_offer_margin',
        ),
        sa.CheckConstraint(
            'sales_cycle_days IS NULL OR sales_cycle_days >= 0',
            name='chk_brain_offer_cycle',
        ),
    )
    op.create_index('idx_brain_offer_company', 'brain_offers', ['company_id'])
    op.create_index('idx_brain_offer_company_active', 'brain_offers', ['company_id', 'is_active'])
    # Uma unica oferta principal ativa por empresa. Indice parcial unico e a
    # forma de expressar isso sem trigger.
    op.execute(
        'CREATE UNIQUE INDEX uq_brain_offer_primary_per_company '
        'ON brain_offers (company_id) WHERE is_primary AND is_active'
    )

    # ------------------------------------------------------------------
    # Objetivos
    # ------------------------------------------------------------------
    op.create_table(
        'brain_goals',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        # Chave livre por enquanto (ex.: 'mrr', 'cac', 'meeting_to_sale').
        # Vira enum quando existir um catalogo de metricas calculadas.
        sa.Column('metric_key', sa.String(length=80), nullable=True),
        sa.Column('baseline_value', sa.Numeric(18, 4), nullable=True),
        sa.Column('target_value', sa.Numeric(18, 4), nullable=True),
        sa.Column('unit', sa.String(length=30), nullable=True),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "status IN ('active', 'achieved', 'missed', 'archived')",
            name='chk_brain_goal_status',
        ),
        sa.CheckConstraint('priority >= 1', name='chk_brain_goal_priority'),
        sa.CheckConstraint(
            'period_end IS NULL OR period_start IS NULL OR period_end >= period_start',
            name='chk_brain_goal_period',
        ),
    )
    op.create_index('idx_brain_goal_company', 'brain_goals', ['company_id'])
    op.create_index('idx_brain_goal_company_status', 'brain_goals', ['company_id', 'status'])


def downgrade() -> None:
    op.drop_table('brain_goals')
    op.execute('DROP INDEX IF EXISTS uq_brain_offer_primary_per_company')
    op.drop_table('brain_offers')
    op.drop_table('brain_icp_profiles')
    op.drop_table('brain_business_profiles')
