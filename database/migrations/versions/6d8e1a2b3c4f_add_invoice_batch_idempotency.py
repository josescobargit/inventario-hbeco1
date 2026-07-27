"""add invoice batch and idempotency traceability

Revision ID: 6d8e1a2b3c4f
Revises: 9c2f7a1b4d60
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6d8e1a2b3c4f"
down_revision: Union[str, None] = "9c2f7a1b4d60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("idempotency_key", sa.String(100)))
    op.add_column("invoices", sa.Column("batch_id", sa.Uuid()))
    op.create_index(
        op.f("ix_invoices_idempotency_key"),
        "invoices",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(op.f("ix_invoices_batch_id"), "invoices", ["batch_id"])
    op.add_column(
        "inventory_movements", sa.Column("idempotency_key", sa.String(160))
    )
    op.add_column("inventory_movements", sa.Column("batch_id", sa.Uuid()))
    op.create_index(
        op.f("ix_inventory_movements_idempotency_key"),
        "inventory_movements",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        op.f("ix_inventory_movements_batch_id"),
        "inventory_movements",
        ["batch_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_inventory_movements_batch_id"),
        table_name="inventory_movements",
    )
    op.drop_index(
        op.f("ix_inventory_movements_idempotency_key"),
        table_name="inventory_movements",
    )
    op.drop_column("inventory_movements", "batch_id")
    op.drop_column("inventory_movements", "idempotency_key")
    op.drop_index(op.f("ix_invoices_batch_id"), table_name="invoices")
    op.drop_index(op.f("ix_invoices_idempotency_key"), table_name="invoices")
    op.drop_column("invoices", "batch_id")
    op.drop_column("invoices", "idempotency_key")
