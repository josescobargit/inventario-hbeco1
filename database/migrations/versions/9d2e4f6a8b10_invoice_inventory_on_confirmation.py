"""apply inventory when an invoice is confirmed

Revision ID: 9d2e4f6a8b10
Revises: 8c1d3e5f7a90
Create Date: 2026-07-28 12:30:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9d2e4f6a8b10"
down_revision: Union[str, None] = "8c1d3e5f7a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("inventory_applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("inventory_reversed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "inventory_movements",
        sa.Column("purchase_order_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "inventory_movements",
        sa.Column("quantity", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_inventory_movements_purchase_order_id_purchase_orders",
        "inventory_movements",
        "purchase_orders",
        ["purchase_order_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_inventory_movements_purchase_order_id",
        "inventory_movements",
        ["purchase_order_id"],
        unique=False,
    )
    op.add_column(
        "returns",
        sa.Column("delivery_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_returns_delivery_id_deliveries",
        "returns",
        "deliveries",
        ["delivery_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_returns_delivery_id",
        "returns",
        ["delivery_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_returns_delivery_id", table_name="returns")
    op.drop_constraint(
        "fk_returns_delivery_id_deliveries",
        "returns",
        type_="foreignkey",
    )
    op.drop_column("returns", "delivery_id")
    op.drop_index(
        "ix_inventory_movements_purchase_order_id",
        table_name="inventory_movements",
    )
    op.drop_constraint(
        "fk_inventory_movements_purchase_order_id_purchase_orders",
        "inventory_movements",
        type_="foreignkey",
    )
    op.drop_column("inventory_movements", "quantity")
    op.drop_column("inventory_movements", "purchase_order_id")
    op.drop_column("invoices", "inventory_reversed_at")
    op.drop_column("invoices", "inventory_applied_at")
