"""add_metodo_pago_v26

Revision ID: b8c9d1e2f3a4
Revises: a7b8c9d0e1f2
Create Date: 2026-05-25 00:00:00.000000

V2.6:
- pedidos.metodo_pago (NULL, CHECK IN ('EFECTIVO', 'YAPE') o NULL)
  Solo aplica cuando pagado=True. NULL es valido (pedido sin pago materializado).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedidos",
        sa.Column("metodo_pago", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_pedidos_metodo_pago_valido",
        "pedidos",
        "metodo_pago IS NULL OR metodo_pago IN ('EFECTIVO', 'YAPE')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_pedidos_metodo_pago_valido", "pedidos", type_="check"
    )
    op.drop_column("pedidos", "metodo_pago")
