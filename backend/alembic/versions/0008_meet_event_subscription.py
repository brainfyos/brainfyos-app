"""Assinatura de eventos do Google Meet (Workspace Events)

Estado da assinatura mora em ``calendar_integrations``, e nao numa tabela
nova: ja existe exatamente uma integracao Google por empresa, e a assinatura e
uma propriedade dela. Uma tabela separada criaria um 1:1 para manter em
sincronia sem ganho nenhum.

Sem entidade nova para deduplicar eventos: a garantia real de idempotencia ja
esta em ``uq_meeting_transcript_external`` (migration 0007). Um evento
entregue duas vezes chega no mesmo transcript externo e o indice unico corta.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nome do recurso da assinatura no Google (``subscriptions/{id}``).
    op.add_column(
        'calendar_integrations',
        sa.Column('meet_subscription_name', sa.String(length=255), nullable=True),
    )
    # Assinaturas do Workspace Events expiram; renovamos antes disso.
    op.add_column(
        'calendar_integrations',
        sa.Column('meet_subscription_expires_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        'calendar_integrations',
        sa.Column(
            'meet_subscription_status',
            sa.String(length=20),
            nullable=False,
            server_default='inactive',
        ),
    )
    op.add_column(
        'calendar_integrations',
        sa.Column('meet_subscription_error', sa.Text(), nullable=True),
    )
    # Ultimo evento realmente recebido. E o sinal de que a assinatura esta
    # entregando de verdade -- 'active' sozinho so diz que o Google aceitou
    # criar, nao que a entrega funciona.
    op.add_column(
        'calendar_integrations',
        sa.Column('meet_last_event_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        'chk_calendar_meet_subscription_status',
        'calendar_integrations',
        "meet_subscription_status IN ('inactive', 'active', 'degraded', 'expired', 'failed')",
    )
    # Renovacao varre por status + expiracao; o indice evita varredura cheia
    # quando houver muitas empresas conectadas.
    op.create_index(
        'idx_calendar_meet_subscription',
        'calendar_integrations',
        ['meet_subscription_status', 'meet_subscription_expires_at'],
    )


def downgrade() -> None:
    op.drop_index('idx_calendar_meet_subscription', table_name='calendar_integrations')
    op.drop_constraint(
        'chk_calendar_meet_subscription_status', 'calendar_integrations', type_='check'
    )
    for column in (
        'meet_last_event_at',
        'meet_subscription_error',
        'meet_subscription_status',
        'meet_subscription_expires_at',
        'meet_subscription_name',
    ):
        op.drop_column('calendar_integrations', column)
