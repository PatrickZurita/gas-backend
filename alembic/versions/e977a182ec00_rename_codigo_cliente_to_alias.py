"""rename codigo_cliente to alias

Revision ID: e977a182ec00
Revises: d5015bf2df00
Create Date: 2025-12-29 11:10:38.135985

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e977a182ec00'
down_revision: Union[str, Sequence[str], None] = 'd5015bf2df00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column("clientes", "codigo_cliente", new_column_name="alias")
    op.execute("ALTER INDEX IF EXISTS ix_clientes_codigo_cliente RENAME TO ix_clientes_alias")


def downgrade():
    op.execute("ALTER INDEX IF EXISTS ix_clientes_alias RENAME TO ix_clientes_codigo_cliente")
    op.alter_column("clientes", "alias", new_column_name="codigo_cliente")
