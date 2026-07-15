"""add low stock units setting

Revision ID: f7a9b2c3d4e5
Revises: e4f2d8c1a9b0
Create Date: 2026-07-14 18:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a9b2c3d4e5"
down_revision: Union[str, None] = "e4f2d8c1a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE app_settings
            SET value = jsonb_set(value, '{low_stock_threshold_units}', '0'::jsonb, true)
            WHERE key = 'operational'
              AND NOT (value ? 'low_stock_threshold_units')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE app_settings
            SET value = value - 'low_stock_threshold_units'
            WHERE key = 'operational'
            """
        )
    )
