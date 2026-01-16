"""rename fecha_pedido to fecha_entrega and add created_at

Revision ID: ad95b087863c
Revises: 427c30065f29
Create Date: 2026-01-16 10:25:53.512454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad95b087863c'
down_revision: Union[str, Sequence[str], None] = '427c30065f29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "pedidos",
        "fecha_pedido",
        new_column_name="fecha_entrega",
        existing_type=sa.Date(),
        existing_nullable=False,
    )

    op.add_column(
        "pedidos",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.drop_index("ix_pedidos_fecha_pedido", table_name="pedidos")
    op.create_index("ix_pedidos_fecha_entrega", "pedidos", ["fecha_entrega"])
    op.create_index("ix_pedidos_created_at", "pedidos", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_pedidos_created_at", table_name="pedidos")
    op.drop_index("ix_pedidos_fecha_entrega", table_name="pedidos")

    op.create_index("ix_pedidos_fecha_pedido", "pedidos", ["fecha_pedido"])

    op.drop_column("pedidos", "created_at")

    op.alter_column(
        "pedidos",
        "fecha_entrega",
        new_column_name="fecha_pedido",
        existing_type=sa.Date(),
        existing_nullable=False,
    )