"""restore decimal soles and backfill centavos

Revision ID: c2f1a8e7d430
Revises: b4e8f6a2c901
Create Date: 2026-05-08 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2f1a8e7d430"
down_revision: Union[str, Sequence[str], None] = "b4e8f6a2c901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "pedidos",
        "total_soles",
        type_=sa.Numeric(10, 2),
        postgresql_using="total_soles::numeric(10,2)",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "pedidos",
        "saldo_pendiente",
        type_=sa.Numeric(10, 2),
        postgresql_using="saldo_pendiente::numeric(10,2)",
        existing_type=sa.Integer(),
        existing_nullable=False,
    )
    op.execute(
        """
        UPDATE pedidos
        SET
            monto_total_centavos = COALESCE(
                monto_total_centavos,
                (total_soles * 100)::integer
            ),
            monto_pendiente_centavos = COALESCE(
                monto_pendiente_centavos,
                (saldo_pendiente * 100)::integer
            )
        """
    )


def downgrade() -> None:
    op.alter_column(
        "pedidos",
        "saldo_pendiente",
        type_=sa.Integer(),
        postgresql_using="saldo_pendiente::integer",
        existing_type=sa.Numeric(10, 2),
        existing_nullable=False,
    )
    op.alter_column(
        "pedidos",
        "total_soles",
        type_=sa.Integer(),
        postgresql_using="total_soles::integer",
        existing_type=sa.Numeric(10, 2),
        existing_nullable=False,
    )
