"""restaura tabelas e colunas ausentes na edicao publica

A edicao publica gerou o schema sem 16 tabelas e 5 colunas que o SQL cru da
aplicacao le e escreve. Cada objeto abaixo foi reconstruido a partir de:

- a familia irma equivalente que sobreviveu no schema (``pos_consulta_*`` e o
  espelho de ``pos_venda_*``, e ``pos_consulta_executions`` e o molde das tres
  tabelas de execucao);
- os ``INSERT``/``ON CONFLICT`` do proprio codigo, que fixam colunas e chaves;
- o modelo SQLAlchemy existente, quando havia (``referral_history``).

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EXECUTION_STATUSES = ['SCHEDULED', 'PROCESSING', 'SUCCESS', 'FAILED', 'CANCELED']


def _execution_table(name: str, owner_column: str, sequence_column: str,
                     step_column: str, extra: list | None = None) -> None:
    """Cria uma tabela de execucao no mesmo formato de pos_consulta_executions."""
    columns = [
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(owner_column, sa.BigInteger(), nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column(sequence_column, sa.Integer(), nullable=False),
        sa.Column(step_column, sa.Integer(), nullable=True),
        sa.Column('step_number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('scheduled_for', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
    ]
    columns.extend(extra or [])
    columns.extend([
        sa.CheckConstraint(
            "status IN ('SCHEDULED','PROCESSING','SUCCESS','FAILED','CANCELED')",
            name=f'chk_{name}_status',
        ),
        sa.UniqueConstraint(owner_column, sequence_column, step_column, name=f'uq_{name}'),
        sa.PrimaryKeyConstraint('id'),
    ])
    op.create_table(name, *columns)
    op.create_index(f'idx_{name}_status', name, ['status', 'scheduled_for'])
    op.create_index(f'idx_{name}_company', name, ['company_id'])


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Auditoria de webhooks. Fica no caminho das mensagens recebidas do
    # WhatsApp, entao e a primeira a importar.
    # ------------------------------------------------------------------
    op.create_table(
        'webhook_audit',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=True),
        sa.Column('instance_id', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=32), nullable=True),
        sa.Column('message_id', sa.String(length=255), nullable=True),
        sa.Column('message_type', sa.String(length=64), nullable=True),
        sa.Column('message_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='received'),
        sa.Column('processing_status', sa.String(length=32), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('processed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_webhook_audit_company_created', 'webhook_audit', ['company_id', 'created_at'])
    op.create_index('idx_webhook_audit_message', 'webhook_audit', ['message_id'])
    op.create_index('idx_webhook_audit_status', 'webhook_audit', ['status'])

    # ------------------------------------------------------------------
    # Tabelas de execucao: follow-up, confirmacao e no-show.
    # ------------------------------------------------------------------
    _execution_table(
        'follow_up_executions',
        owner_column='lead_id',
        sequence_column='follow_up_sequence_id',
        step_column='follow_up_step_id',
    )

    _execution_table(
        'confirmation_executions',
        owner_column='agendamento_id',
        sequence_column='confirmation_sequence_id',
        step_column='confirmation_step_id',
        extra=[
            # Guarda a data original para detectar remarcacao antes do envio.
            sa.Column('original_consulta_data', sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column('executed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        ],
    )

    _execution_table(
        'noshow_follow_up_executions',
        owner_column='lead_id',
        sequence_column='noshow_follow_up_sequence_id',
        step_column='noshow_follow_up_step_id',
    )

    # ------------------------------------------------------------------
    # Pos-venda: espelho exato da familia pos_consulta_*.
    # ------------------------------------------------------------------
    op.create_table(
        'pos_venda_sequences',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_pos_venda_sequences_company', 'pos_venda_sequences', ['company_id'])

    op.create_table(
        'pos_venda_steps',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('pos_venda_sequence_id', sa.Integer(), nullable=False),
        sa.Column('step_number', sa.Integer(), nullable=False),
        sa.Column('send_after', sa.Integer(), nullable=True),
        sa.Column('send_after_unit', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['pos_venda_sequence_id'], ['pos_venda_sequences.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_pos_venda_steps_sequence', 'pos_venda_steps', ['pos_venda_sequence_id'])

    op.create_table(
        'pos_venda_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('pos_venda_step_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['pos_venda_step_id'], ['pos_venda_steps.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_pos_venda_messages_step', 'pos_venda_messages', ['pos_venda_step_id'])

    op.create_table(
        'pos_venda_schedule_configs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('pos_venda_sequence_id', sa.Integer(), nullable=True),
        sa.Column('schedule_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pos_venda_sequence_id'], ['pos_venda_sequences.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_pos_venda_schedule_company', 'pos_venda_schedule_configs', ['company_id'])

    _execution_table(
        'pos_venda_executions',
        owner_column='venda_id',
        sequence_column='pos_venda_sequence_id',
        step_column='pos_venda_step_id',
        extra=[sa.Column('lead_id', sa.BigInteger(), nullable=True)],
    )

    # ------------------------------------------------------------------
    # Controle de fluxo (tela de Automacoes).
    # ------------------------------------------------------------------
    op.create_table(
        'contact_flow_control',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('contact_identifier', sa.String(length=255), nullable=False),
        sa.Column('identifier_type', sa.String(length=32), nullable=True),
        sa.Column('flow_type', sa.String(length=64), nullable=False),
        sa.Column('is_paused', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('pause_reason', sa.Text(), nullable=True),
        sa.Column('paused_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('paused_by', sa.Integer(), nullable=True),
        sa.Column('resumed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('resumed_by', sa.Integer(), nullable=True),
        sa.Column('expire_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        # Exigida pelo ON CONFLICT de routes/flow_control.py.
        sa.UniqueConstraint('company_id', 'contact_identifier', 'flow_type',
                            name='uq_contact_flow_control'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_contact_flow_control_expire', 'contact_flow_control', ['expire_at'])

    op.create_table(
        'contact_flow_control_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('contact_flow_control_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('performed_by', sa.Integer(), nullable=True),
        sa.Column('performed_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['contact_flow_control_id'], ['contact_flow_control.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_contact_flow_history_parent', 'contact_flow_control_history',
                    ['contact_flow_control_id'])

    op.create_table(
        'flow_control_states',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('flow_type', sa.String(length=64), nullable=False),
        sa.Column('is_paused', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('pause_reason', sa.Text(), nullable=True),
        sa.Column('paused_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('paused_by', sa.Integer(), nullable=True),
        sa.Column('resumed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('resumed_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('company_id', 'flow_type', name='uq_flow_control_states'),
        sa.PrimaryKeyConstraint('id'),
    )

    # ------------------------------------------------------------------
    # Auditoria de acoes em contatos.
    # ------------------------------------------------------------------
    op.create_table(
        'contact_actions_audit',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action_type', sa.String(length=64), nullable=False),
        sa.Column('action_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_contact_actions_audit_company', 'contact_actions_audit',
                    ['company_id', 'created_at'])
    op.create_index('idx_contact_actions_audit_contact', 'contact_actions_audit', ['contact_id'])

    # ------------------------------------------------------------------
    # Consumo de tokens de IA por empresa.
    # ------------------------------------------------------------------
    op.create_table(
        'tokens_input_usage',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('contact_phone', sa.String(length=32), nullable=True),
        sa.Column('function_name', sa.String(length=255), nullable=True),
        sa.Column('model_name', sa.String(length=128), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_tokens_input_usage_company', 'tokens_input_usage',
                    ['company_id', 'created_at'])

    # ------------------------------------------------------------------
    # Investimento em campanhas de anuncio, por mes de referencia.
    # ------------------------------------------------------------------
    op.create_table(
        'ad_campaign_investment',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('source_id', sa.String(length=255), nullable=False),
        sa.Column('investment', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
        sa.Column('reference_month', sa.String(length=7), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        # Exigida pelo ON CONFLICT de routes/ad_campaign_routes.py.
        sa.UniqueConstraint('company_id', 'source_id', 'reference_month',
                            name='uq_ad_campaign_investment'),
        sa.PrimaryKeyConstraint('id'),
    )

    # ------------------------------------------------------------------
    # Historico de indicacoes. Espelha backend/agents_sdk/models/referral_history.py.
    # ------------------------------------------------------------------
    op.create_table(
        'referral_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('lead_phone', sa.String(length=20), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('referrals_count', sa.Integer(), server_default='0'),
        sa.Column('referral_names', sa.Text(), nullable=True),
        sa.Column('last_referral_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['campaign_id'], ['referral_campaigns.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('lead_phone', 'company_id', 'campaign_id',
                            name='unique_lead_company_campaign'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_referral_history_lead_phone', 'referral_history', ['lead_phone'])
    op.create_index('ix_referral_history_company_id', 'referral_history', ['company_id'])
    op.create_index('ix_referral_history_last_referral_date', 'referral_history', ['last_referral_date'])

    # ------------------------------------------------------------------
    # Colunas ausentes em tabelas existentes.
    # ------------------------------------------------------------------
    op.add_column('contacts', sa.Column('archived', sa.Boolean(), nullable=False,
                                        server_default=sa.text('false')))
    op.add_column('contacts', sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('contacts', sa.Column('archived_by', sa.Integer(), nullable=True))
    op.add_column('contacts', sa.Column('archive_reason', sa.Text(), nullable=True))
    op.create_index('idx_contacts_company_archived', 'contacts', ['company_id', 'archived'])

    # O gerenciador de estado dos agentes le "SELECT current_step, state_data".
    op.add_column('conversation_state', sa.Column('current_step', sa.Integer(), nullable=False,
                                                  server_default='0'))


def downgrade() -> None:
    op.drop_column('conversation_state', 'current_step')
    op.drop_index('idx_contacts_company_archived', table_name='contacts')
    for col in ('archive_reason', 'archived_by', 'archived_at', 'archived'):
        op.drop_column('contacts', col)

    for table in (
        'referral_history',
        'ad_campaign_investment',
        'tokens_input_usage',
        'contact_actions_audit',
        'flow_control_states',
        'contact_flow_control_history',
        'contact_flow_control',
        'pos_venda_executions',
        'pos_venda_schedule_configs',
        'pos_venda_messages',
        'pos_venda_steps',
        'pos_venda_sequences',
        'noshow_follow_up_executions',
        'confirmation_executions',
        'follow_up_executions',
        'webhook_audit',
    ):
        op.drop_table(table)
