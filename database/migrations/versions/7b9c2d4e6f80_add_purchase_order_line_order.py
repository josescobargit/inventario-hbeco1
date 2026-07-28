"""add purchase order line order

Revision ID: 7b9c2d4e6f80
Revises: 6d8e1a2b3c4f
Create Date: 2026-07-27 18:20:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7b9c2d4e6f80"
down_revision: Union[str, None] = "6d8e1a2b3c4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchase_order_lines",
        sa.Column(
            "sort_order",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.execute(
        """
        WITH ordered AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY purchase_order_id
                       ORDER BY id
                   ) - 1 AS position
            FROM purchase_order_lines
        )
        UPDATE purchase_order_lines AS line
        SET sort_order = ordered.position
        FROM ordered
        WHERE line.id = ordered.id
        """
    )
    op.alter_column("purchase_order_lines", "sort_order", server_default=None)


def downgrade() -> None:
    op.drop_column("purchase_order_lines", "sort_order")
