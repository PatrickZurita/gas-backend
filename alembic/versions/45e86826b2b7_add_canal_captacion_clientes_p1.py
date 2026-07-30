"""add_canal_captacion_clientes_p1

Revision ID: 45e86826b2b7
Revises: b8c9d1e2f3a4
Create Date: 2026-07-30 00:00:00.000000

P1 #1 (MEJORAS_CAPTURA_DATA):
- clientes.canal_captacion (NULL, CHECK IN ('VOLANTE','FACEBOOK','RECOMENDACION',
  'CARTEL','ANTIGUO','OTRO') o NULL)
  Se pregunta UNA vez al crear el cliente. Legacy queda NULL (patron metodo_pago V2.6:
  no atribuir sin evidencia). Sin backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "45e86826b2b7"
down_revision: Union[str, Sequence[str], None] = "b8c9d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clientes",
        sa.Column("canal_captacion", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_clientes_canal_captacion_valido",
        "clientes",
        "canal_captacion IS NULL OR canal_captacion IN "
        "('VOLANTE', 'FACEBOOK', 'RECOMENDACION', 'CARTEL', 'ANTIGUO', 'OTRO')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_clientes_canal_captacion_valido", "clientes", type_="check"
    )
    op.drop_column("clientes", "canal_captacion")
