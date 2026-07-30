"""add_demanda_perdida_p1

Revision ID: e08d9a342efe
Revises: 45e86826b2b7
Create Date: 2026-07-30 00:00:00.000000

P1 #2 (MEJORAS_CAPTURA_DATA):
- tabla demanda_perdida: la llamada que NO se pudo atender. Decide el caso del
  2do courier. Tabla aparte a proposito: el estado PERDIDO en pedidos fue
  descartado (obligaria cliente/direccion fantasma y romperia reportes/stock).
- No toca pedidos, stock_jornadas ni movimientos_stock. Cero impacto en ventas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e08d9a342efe"
down_revision: Union[str, Sequence[str], None] = "45e86826b2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "demanda_perdida",
        sa.Column("id", sa.Integer(), primary_key=True),
        # fecha operativa (dia Lima); la fija el service con fecha_hoy_lima(),
        # server_default solo como fallback. Mismo patron que movimientos_stock.fecha.
        sa.Column(
            "fecha",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column("motivo", sa.String(length=20), nullable=False),
        sa.Column("zona_texto", sa.String(length=120), nullable=True),
        sa.Column(
            "cantidad_balones",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "peso_balon_kg",
            sa.Integer(),
            server_default=sa.text("10"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "motivo IN ('SIN_STOCK', 'FUERA_DE_ZONA', 'SATURADO', 'OTRO')",
            name="ck_demanda_perdida_motivo_valido",
        ),
        sa.CheckConstraint(
            "cantidad_balones >= 1",
            name="ck_demanda_perdida_cantidad_balones_ge_1",
        ),
        sa.CheckConstraint(
            "peso_balon_kg IN (10, 45)",
            name="ck_demanda_perdida_peso_balon_kg_valido",
        ),
    )
    op.create_index("ix_demanda_perdida_fecha", "demanda_perdida", ["fecha"])
    op.create_index("ix_demanda_perdida_motivo", "demanda_perdida", ["motivo"])
    op.create_index(
        "ix_demanda_perdida_created_at", "demanda_perdida", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_demanda_perdida_created_at", table_name="demanda_perdida")
    op.drop_index("ix_demanda_perdida_motivo", table_name="demanda_perdida")
    op.drop_index("ix_demanda_perdida_fecha", table_name="demanda_perdida")
    op.drop_table("demanda_perdida")
