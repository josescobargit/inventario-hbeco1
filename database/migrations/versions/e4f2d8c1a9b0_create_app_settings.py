"""create app settings

Revision ID: e4f2d8c1a9b0
Revises: c8b6a4d2e901
Create Date: 2026-07-14 13:05:00
"""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e4f2d8c1a9b0"
down_revision: Union[str, None] = "c8b6a4d2e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_OPERATIONAL_SETTINGS = {
    "warehouse_name": "Bodega principal",
    "low_stock_threshold_mode": "boxes",
    "low_stock_threshold_boxes": 1,
    "low_stock_threshold_units": 0,
    "report_default_days": 30,
    "allow_exception_invoices": True,
    "suggested_chains": ["Gerardo Ortiz", "Favorita", "Rosado", "Danec", "Tía"],
    "invoice_exception_note": "Usar excepción cuando la factura no corresponde a una OC normal o tiene otro fin operativo.",
}


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_app_settings_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )
    op.create_index(
        op.f("ix_app_settings_updated_by_user_id"),
        "app_settings",
        ["updated_by_user_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO app_settings (key, value, description, updated_at)
            VALUES (
              'operational',
              CAST(:settings_value AS jsonb),
              'Parámetros operativos generales del sistema',
              CURRENT_TIMESTAMP
            )
            ON CONFLICT (key) DO NOTHING
            """
        ).bindparams(
            settings_value=json.dumps(DEFAULT_OPERATIONAL_SETTINGS, ensure_ascii=False)
        )
    )
    op.execute(sa.text('ALTER TABLE public."app_settings" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('REVOKE ALL ON TABLE public."app_settings" FROM PUBLIC'))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN REVOKE ALL ON TABLE public."app_settings" FROM anon; END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN REVOKE ALL ON TABLE public."app_settings" FROM authenticated; END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_app_settings_updated_by_user_id"), table_name="app_settings")
    op.drop_table("app_settings")
