"""add stock jornadas and movements

Revision ID: 9c3a7d1f4b20
Revises: 853ff1745fed
Create Date: 2026-05-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c3a7d1f4b20"
down_revision: Union[str, Sequence[str], None] = "853ff1745fed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_jornadas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("stock_inicial", sa.Integer(), nullable=False),
        sa.Column("stock_actual", sa.Integer(), nullable=False),
        sa.Column("stock_final_fisico", sa.Integer(), nullable=True),
        sa.Column("cerrado", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stock_final_fisico IS NULL OR stock_final_fisico >= 0",
            name="ck_stock_jornadas_final_ge_0",
        ),
        sa.CheckConstraint(
            "stock_inicial >= 0",
            name="ck_stock_jornadas_inicial_ge_0",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_stock_jornadas_fecha"),
        "stock_jornadas",
        ["fecha"],
        unique=True,
    )

    op.create_table(
        "movimientos_stock",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_jornada_id", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("cantidad_delta", sa.Integer(), nullable=False),
        sa.Column("stock_resultante", sa.Integer(), nullable=False),
        sa.Column("pedido_id", sa.Integer(), nullable=True),
        sa.Column("marca_balon", sa.String(length=30), nullable=True),
        sa.Column("tipo_balon", sa.String(length=30), nullable=True),
        sa.Column("observacion", sa.String(length=250), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tipo IN ('INICIO_DIA', 'ENTRADA', 'SALIDA_PEDIDO', 'AJUSTE')",
            name="ck_movimientos_stock_tipo_valido",
        ),
        sa.ForeignKeyConstraint(
            ["pedido_id"],
            ["pedidos.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["stock_jornada_id"],
            ["stock_jornadas.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_movimientos_stock_created_at"),
        "movimientos_stock",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_movimientos_stock_fecha"),
        "movimientos_stock",
        ["fecha"],
        unique=False,
    )
    op.create_index(
        op.f("ix_movimientos_stock_pedido_id"),
        "movimientos_stock",
        ["pedido_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_movimientos_stock_stock_jornada_id"),
        "movimientos_stock",
        ["stock_jornada_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_movimientos_stock_tipo"),
        "movimientos_stock",
        ["tipo"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_movimientos_stock_tipo"), table_name="movimientos_stock")
    op.drop_index(
        op.f("ix_movimientos_stock_stock_jornada_id"),
        table_name="movimientos_stock",
    )
    op.drop_index(
        op.f("ix_movimientos_stock_pedido_id"),
        table_name="movimientos_stock",
    )
    op.drop_index(op.f("ix_movimientos_stock_fecha"), table_name="movimientos_stock")
    op.drop_index(
        op.f("ix_movimientos_stock_created_at"),
        table_name="movimientos_stock",
    )
    op.drop_table("movimientos_stock")
    op.drop_index(op.f("ix_stock_jornadas_fecha"), table_name="stock_jornadas")
    op.drop_table("stock_jornadas")
