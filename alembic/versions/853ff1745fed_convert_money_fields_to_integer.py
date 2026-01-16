"""convert money fields to integer

Revision ID: 853ff1745fed
Revises: ad95b087863c
Create Date: 2026-01-16 11:54:19.177905

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '853ff1745fed'
down_revision: Union[str, Sequence[str], None] = 'ad95b087863c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "pedidos",
        "total_soles",
        type_=sa.Integer(),
        postgresql_using="total_soles::integer",
        existing_type=sa.Numeric(10, 2),
        existing_nullable=False,
    )

    op.alter_column(
        "pedidos",
        "saldo_pendiente",
        type_=sa.Integer(),
        postgresql_using="saldo_pendiente::integer",
        existing_type=sa.Numeric(10, 2),
        existing_nullable=False,
    )


def downgrade() -> None:
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