"""add_peso_balon_kg_and_fecha_index_v2

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-05-23 00:00:00.000000

V2.2 + V2.3 + V3:
- pedidos.peso_balon_kg (NOT NULL, default 10, CHECK IN (10, 45))
- movimientos_stock.peso_balon_kg (NULL, retrocompat)
- index ix_pedidos_fecha_entrega (idempotente)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedidos",
        sa.Column(
            "peso_balon_kg",
            sa.Integer(),
            server_default=sa.text("10"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_pedidos_peso_balon_kg_valido",
        "pedidos",
        "peso_balon_kg IN (10, 45)",
    )

    op.add_column(
        "movimientos_stock",
        sa.Column("peso_balon_kg", sa.Integer(), nullable=True),
    )

    # Soporte V3 historial por fecha: el endpoint ya existe pero el indice
    # explicito ayuda a /reportes/dia, /reportes/semana, /reportes/mes.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pedidos_fecha_entrega "
        "ON pedidos(fecha_entrega)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pedidos_fecha_entrega")
    op.drop_column("movimientos_stock", "peso_balon_kg")
    op.drop_constraint(
        "ck_pedidos_peso_balon_kg_valido", "pedidos", type_="check"
    )
    op.drop_column("pedidos", "peso_balon_kg")
