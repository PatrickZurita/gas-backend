"""add pedido product and centavos fields

Revision ID: b4e8f6a2c901
Revises: 9c3a7d1f4b20
Create Date: 2026-05-08 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4e8f6a2c901"
down_revision: Union[str, Sequence[str], None] = "9c3a7d1f4b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pedidos",
        sa.Column(
            "tipo_balon",
            sa.String(length=30),
            server_default="NORMAL",
            nullable=False,
        ),
    )
    op.add_column(
        "pedidos",
        sa.Column(
            "marca_balon",
            sa.String(length=30),
            server_default="PETROPERU",
            nullable=False,
        ),
    )
    op.add_column(
        "pedidos",
        sa.Column("precio_unitario_centavos", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pedidos",
        sa.Column("monto_total_centavos", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pedidos",
        sa.Column("monto_pendiente_centavos", sa.Integer(), nullable=True),
    )

    op.create_check_constraint(
        "ck_pedidos_tipo_balon_valido",
        "pedidos",
        "tipo_balon IN ('NORMAL', 'PREMIUM')",
    )
    op.create_check_constraint(
        "ck_pedidos_marca_balon_valida",
        "pedidos",
        "marca_balon IN ('SOLGAS', 'PETROPERU')",
    )
    op.create_check_constraint(
        "ck_pedidos_precio_unitario_centavos_ge_0",
        "pedidos",
        "precio_unitario_centavos IS NULL OR precio_unitario_centavos >= 0",
    )
    op.create_check_constraint(
        "ck_pedidos_monto_total_centavos_ge_0",
        "pedidos",
        "monto_total_centavos IS NULL OR monto_total_centavos >= 0",
    )
    op.create_check_constraint(
        "ck_pedidos_monto_pendiente_centavos_ge_0",
        "pedidos",
        "monto_pendiente_centavos IS NULL OR monto_pendiente_centavos >= 0",
    )
    op.create_index(
        "ix_pedidos_fecha_marca_tipo",
        "pedidos",
        ["fecha_entrega", "marca_balon", "tipo_balon"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pedidos_fecha_marca_tipo", table_name="pedidos")
    op.drop_constraint(
        "ck_pedidos_monto_pendiente_centavos_ge_0",
        "pedidos",
        type_="check",
    )
    op.drop_constraint(
        "ck_pedidos_monto_total_centavos_ge_0",
        "pedidos",
        type_="check",
    )
    op.drop_constraint(
        "ck_pedidos_precio_unitario_centavos_ge_0",
        "pedidos",
        type_="check",
    )
    op.drop_constraint("ck_pedidos_marca_balon_valida", "pedidos", type_="check")
    op.drop_constraint("ck_pedidos_tipo_balon_valido", "pedidos", type_="check")
    op.drop_column("pedidos", "monto_pendiente_centavos")
    op.drop_column("pedidos", "monto_total_centavos")
    op.drop_column("pedidos", "precio_unitario_centavos")
    op.drop_column("pedidos", "marca_balon")
    op.drop_column("pedidos", "tipo_balon")
