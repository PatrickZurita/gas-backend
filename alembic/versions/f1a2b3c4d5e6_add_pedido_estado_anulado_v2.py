"""add_pedido_estado_anulado_v2

Revision ID: f1a2b3c4d5e6
Revises: c2f1a8e7d430
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "c2f1a8e7d430"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedidos",
        sa.Column(
            "estado",
            sa.String(length=20),
            server_default="ACTIVO",
            nullable=False,
        ),
    )
    op.add_column(
        "pedidos",
        sa.Column("anulado_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pedidos",
        sa.Column("anulado_motivo", sa.String(length=250), nullable=True),
    )
    op.add_column(
        "pedidos",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_check_constraint(
        "ck_pedidos_estado_valido",
        "pedidos",
        "estado IN ('ACTIVO', 'ANULADO')",
    )

    # Ampliar el enum de tipos de movimiento para permitir la reversa por
    # anulacion. PostgreSQL requiere recrear el CHECK constraint.
    op.drop_constraint(
        "ck_movimientos_stock_tipo_valido",
        "movimientos_stock",
        type_="check",
    )
    op.create_check_constraint(
        "ck_movimientos_stock_tipo_valido",
        "movimientos_stock",
        "tipo IN ('INICIO_DIA', 'ENTRADA', 'SALIDA_PEDIDO', 'AJUSTE', "
        "'REVERSA_ANULACION')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_movimientos_stock_tipo_valido",
        "movimientos_stock",
        type_="check",
    )
    op.create_check_constraint(
        "ck_movimientos_stock_tipo_valido",
        "movimientos_stock",
        "tipo IN ('INICIO_DIA', 'ENTRADA', 'SALIDA_PEDIDO', 'AJUSTE')",
    )

    op.drop_constraint("ck_pedidos_estado_valido", "pedidos", type_="check")
    op.drop_column("pedidos", "updated_at")
    op.drop_column("pedidos", "anulado_motivo")
    op.drop_column("pedidos", "anulado_at")
    op.drop_column("pedidos", "estado")
