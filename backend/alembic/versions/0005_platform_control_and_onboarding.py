"""Fundacao BrainfyOS: papel de plataforma, auditoria administrativa e onboarding

Tres blocos independentes:

1. ``clients.platform_role`` -- menor extensao possivel para suportar um
   administrador global. O sistema de identidade atual nao tem nenhum conceito
   de escopo acima de company; ``users.role`` so existe para sub-usuarios de um
   workspace. Uma coluna nullable em ``clients`` evita criar um segundo sistema
   de autenticacao.

   Nao confundir com ``ADMIN_EMAILS`` (usado por ``require_internal_admin`` em
   routes/company.py): aquilo e provisionamento por variavel de ambiente e nao
   e auditavel. O Control exige o papel gravado no banco.

2. ``platform_audit_log`` -- toda leitura/acao administrativa que cruza
   fronteira de company fica registrada com o ator.

3. Tabelas de onboarding -- template/section/item descrevem o roteiro,
   progress/answers guardam o estado por empresa. Nenhuma estrutura
   equivalente existe no schema atual.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Papel global de plataforma
    # ------------------------------------------------------------------
    op.add_column('clients', sa.Column('platform_role', sa.String(length=30), nullable=True))
    op.create_check_constraint(
        'chk_clients_platform_role',
        'clients',
        "platform_role IS NULL OR platform_role IN ('platform_owner')",
    )
    # Indice parcial: a esmagadora maioria das linhas tem NULL e nunca e
    # consultada por esta coluna.
    op.execute(
        'CREATE INDEX idx_clients_platform_role ON clients (platform_role) '
        'WHERE platform_role IS NOT NULL'
    )

    # ------------------------------------------------------------------
    # 2. Auditoria de acoes administrativas
    # ------------------------------------------------------------------
    op.create_table(
        'platform_audit_log',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('actor_client_id', sa.Integer(), nullable=True),
        sa.Column('actor_email', sa.String(length=255), nullable=False),
        sa.Column('action', sa.String(length=80), nullable=False),
        sa.Column('target_company_id', sa.BigInteger(), nullable=True),
        sa.Column('request_ip', sa.String(length=64), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        # SET NULL: o registro de auditoria sobrevive a remocao do ator.
        sa.ForeignKeyConstraint(['actor_client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['target_company_id'], ['companies.id'], ondelete='SET NULL'),
    )
    op.create_index('idx_platform_audit_log_created', 'platform_audit_log', ['created_at'])
    op.create_index('idx_platform_audit_log_actor', 'platform_audit_log', ['actor_client_id', 'created_at'])
    op.create_index('idx_platform_audit_log_target', 'platform_audit_log', ['target_company_id', 'created_at'])

    # ------------------------------------------------------------------
    # 3. Onboarding
    # ------------------------------------------------------------------
    op.create_table(
        'onboarding_templates',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', name='uq_onboarding_templates_key'),
    )

    op.create_table(
        'onboarding_sections',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['template_id'], ['onboarding_templates.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('template_id', 'key', name='uq_onboarding_sections_template_key'),
    )
    op.create_index('idx_onboarding_sections_template', 'onboarding_sections', ['template_id', 'position'])

    op.create_table(
        'onboarding_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('section_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('estimated_minutes', sa.Integer(), nullable=True),
        sa.Column('action_label', sa.String(length=80), nullable=True),
        sa.Column('action_route', sa.String(length=255), nullable=True),
        # Chaves de outros onboarding_items que precisam estar concluidos.
        # Guardadas como JSONB de strings para nao criar uma tabela de arestas
        # antes de haver grafo real de dependencias.
        sa.Column('requires_item_keys', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['section_id'], ['onboarding_sections.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('section_id', 'key', name='uq_onboarding_items_section_key'),
    )
    op.create_index('idx_onboarding_items_section', 'onboarding_items', ['section_id', 'position'])

    op.create_table(
        'onboarding_progress',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='todo'),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('updated_by_client_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['onboarding_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by_client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('company_id', 'item_id', name='uq_onboarding_progress_company_item'),
        # 'blocked' nao e gravado: e derivado das dependencias em tempo de
        # leitura. Fica no CHECK para permitir bloqueio manual no futuro.
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'done', 'blocked', 'skipped')",
            name='chk_onboarding_progress_status',
        ),
    )
    op.create_index('idx_onboarding_progress_company', 'onboarding_progress', ['company_id'])

    op.create_table(
        'onboarding_answers',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('field_key', sa.String(length=120), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['onboarding_items.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('company_id', 'field_key', name='uq_onboarding_answers_company_field'),
    )
    op.create_index('idx_onboarding_answers_company', 'onboarding_answers', ['company_id'])


def downgrade() -> None:
    op.drop_table('onboarding_answers')
    op.drop_table('onboarding_progress')
    op.drop_table('onboarding_items')
    op.drop_table('onboarding_sections')
    op.drop_table('onboarding_templates')
    op.drop_table('platform_audit_log')
    op.execute('DROP INDEX IF EXISTS idx_clients_platform_role')
    op.drop_constraint('chk_clients_platform_role', 'clients', type_='check')
    op.drop_column('clients', 'platform_role')
