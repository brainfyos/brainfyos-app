"""contacts.human_mode: default no banco

O modelo declara ``human_mode = Column(Boolean, default=False, nullable=False)``,
mas ``default`` do SQLAlchemy so vale para inserts feitos pela ORM. Os tres
caminhos de ingestao de mensagens usam ``INSERT INTO contacts`` cru e nao
informam a coluna, entao todo contato novo vindo do WhatsApp falhava com
``NotNullViolation``. O default precisa existir no proprio banco.

false = contato em modo IA, que e o comportamento padrao da plataforma.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('contacts', 'human_mode', server_default=sa.text('false'))


def downgrade() -> None:
    op.alter_column('contacts', 'human_mode', server_default=None)
