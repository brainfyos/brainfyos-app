"""contacts: colunas de conversa e chave unica por empresa

A edicao publica criou ``contacts`` sem as colunas que o SQL cru da
aplicacao le e escreve, o que quebrava a listagem do Chat Ao Vivo com
``UndefinedColumn: column c.last_message_at does not exist``.

Alem disso, tres caminhos de ingestao de mensagens usam
``ON CONFLICT (client_id, company_id, phone)``, mas a tabela so tinha a
restricao ``(client_id, phone)``. O codigo trata explicitamente o caso de
"mesmo telefone em outra empresa" criando um novo registro, entao a chave
correta inclui ``company_id``.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('last_message_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('contacts', sa.Column('source_id', sa.String(length=255), nullable=True))
    op.add_column('contacts', sa.Column('thumbnail_url', sa.Text(), nullable=True))
    op.add_column('contacts', sa.Column('sender_lid', sa.String(length=255), nullable=True))
    op.add_column(
        'contacts',
        sa.Column('unread_count', sa.Integer(), server_default='0', nullable=False),
    )

    # Ordena a lista de conversas por atividade recente.
    op.create_index(
        'idx_contacts_company_last_message',
        'contacts',
        ['company_id', sa.text('last_message_at DESC NULLS LAST')],
    )

    # A chave anterior impedia o mesmo telefone em empresas diferentes do
    # mesmo cliente e nao casava com os ON CONFLICT da ingestao.
    op.drop_constraint('uq_contact_client_phone', 'contacts', type_='unique')
    op.create_unique_constraint(
        'uq_contact_client_company_phone',
        'contacts',
        ['client_id', 'company_id', 'phone'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_contact_client_company_phone', 'contacts', type_='unique')
    op.create_unique_constraint('uq_contact_client_phone', 'contacts', ['client_id', 'phone'])
    op.drop_index('idx_contacts_company_last_message', table_name='contacts')
    op.drop_column('contacts', 'unread_count')
    op.drop_column('contacts', 'sender_lid')
    op.drop_column('contacts', 'thumbnail_url')
    op.drop_column('contacts', 'source_id')
    op.drop_column('contacts', 'last_message_at')
