"""add dispatch guide

Revision ID: d8f1a3c5e7b9
Revises: c7e9a1b3d5f7
Create Date: 2026-07-29 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d8f1a3c5e7b9"
down_revision: Union[str, None] = "c7e9a1b3d5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dispatches", sa.Column("guide_number", sa.String(100)))
    op.execute(
        sa.text(
            """
            UPDATE inventory_positions AS position
            SET invoiced_not_dispatched = COALESCE((
                SELECT SUM(
                    GREATEST(
                        invoice_line.quantity - COALESCE((
                            SELECT SUM(
                                dispatch_line.dispatched_quantity
                                + dispatch_line.missing_quantity
                            )
                            FROM dispatch_lines AS dispatch_line
                            JOIN dispatches AS dispatch
                              ON dispatch.id = dispatch_line.dispatch_id
                            WHERE dispatch.invoice_id = invoice.id
                              AND dispatch_line.invoice_line_id = invoice_line.id
                        ), 0),
                        0
                    )
                )
                FROM invoice_lines AS invoice_line
                JOIN invoices AS invoice ON invoice.id = invoice_line.invoice_id
                WHERE invoice_line.product_id = position.product_id
                  AND invoice.administrative_status = 'confirmed'
            ), 0)
            """
        )
    )


def downgrade() -> None:
    op.drop_column("dispatches", "guide_number")
