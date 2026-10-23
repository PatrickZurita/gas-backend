"""Private expiring geo results; no migration execution is implied.

Revision ID: 7e0a21b1c5d9
Revises: e08d9a342efe
"""

from alembic import op
import sqlalchemy as sa

revision = "7e0a21b1c5d9"
down_revision = "e08d9a342efe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resultados_geo_temporales",
        sa.Column("direccion_id", sa.Integer(), sa.ForeignKey("direcciones.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("texto_fingerprint", sa.String(64), nullable=False),
        sa.Column("estado", sa.String(24), nullable=False),
        sa.Column("precision", sa.String(8), nullable=True),
        sa.Column("h3_res9", sa.String(15), nullable=True),
        sa.Column("proveedor", sa.String(20), nullable=False),
        sa.Column("geocodificado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "estado IN ('OK', 'SIN_RESULTADO', 'RECHAZADO_BOUNDS', "
            "'RECHAZADO_PRECISION', 'PENDIENTE_DUENO')",
            name="ck_geo_temporal_estado",
        ),
        sa.CheckConstraint(
            "(estado = 'OK' AND precision IN ('HIGH', 'MEDIUM', 'LOW')) "
            "OR (estado <> 'OK' AND precision IS NULL)",
            name="ck_geo_temporal_precision",
        ),
        sa.CheckConstraint(
            "expira_en > geocodificado_en AND "
            "expira_en <= geocodificado_en + INTERVAL '29 days'",
            name="ck_geo_temporal_vencimiento",
        ),
    )
    op.create_index("ix_resultados_geo_temporales_expira_en", "resultados_geo_temporales", ["expira_en"])
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gas_readonly') THEN
            GRANT SELECT ON resultados_geo_temporales TO gas_readonly;
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_index("ix_resultados_geo_temporales_expira_en", table_name="resultados_geo_temporales")
    op.drop_table("resultados_geo_temporales")
