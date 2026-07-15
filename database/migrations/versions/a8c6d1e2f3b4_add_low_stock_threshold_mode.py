"""add low stock threshold mode

Revision ID: a8c6d1e2f3b4
Revises: f7a9b2c3d4e5
Create Date: 2026-07-14 19:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8c6d1e2f3b4"
down_revision: Union[str, None] = "f7a9b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE app_settings
            SET value = jsonb_set(value, '{low_stock_threshold_mode}', '"boxes"'::jsonb, true)
            WHERE key = 'operational'
              AND NOT (value ? 'low_stock_threshold_mode')
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE app_settings
            SET value = value - 'low_stock_threshold_mode'
            WHERE key = 'operational'
            """
        )
    )
