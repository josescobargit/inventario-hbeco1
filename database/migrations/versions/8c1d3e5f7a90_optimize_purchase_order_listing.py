"""optimize purchase order listing and stop retaining new source binaries

Revision ID: 8c1d3e5f7a90
Revises: 7b9c2d4e6f80
Create Date: 2026-07-28 01:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "8c1d3e5f7a90"
down_revision: Union[str, None] = "7b9c2d4e6f80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "purchase_order_source_documents",
        "content",
        existing_type=sa.LargeBinary(),
        nullable=True,
    )
    op.create_index(
        "ix_purchase_orders_created_at_id",
        "purchase_orders",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_orders_order_date",
        "purchase_orders",
        ["order_date"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_orders_status_created_at",
        "purchase_orders",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_orders_chain_number_lookup",
        "purchase_orders",
        ["chain_name", "order_number"],
        unique=False,
    )
    op.create_index(
        "ix_purchase_order_lines_order_sort",
        "purchase_order_lines",
        ["purchase_order_id", "sort_order"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_movements_product_reference",
        "inventory_movements",
        ["product_id", "reference_type", "reference_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_movements_product_reference",
        table_name="inventory_movements",
    )
    op.drop_index("ix_purchase_order_lines_order_sort", table_name="purchase_order_lines")
    op.drop_index("ix_purchase_orders_chain_number_lookup", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_status_created_at", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_order_date", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_created_at_id", table_name="purchase_orders")
    op.alter_column(
        "purchase_order_source_documents",
        "content",
        existing_type=sa.LargeBinary(),
        nullable=False,
    )
