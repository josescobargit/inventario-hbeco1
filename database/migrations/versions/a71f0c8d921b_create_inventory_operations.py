"""create inventory operations

Revision ID: a71f0c8d921b
Revises: 8110e6de503e
Create Date: 2026-07-07 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a71f0c8d921b"
down_revision: Union[str, None] = "8110e6de503e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inventory_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("registered_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(length=20), nullable=False),
        sa.Column("responsible_name", sa.String(length=160), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_reference", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "operation_type IN ('entry','exit')",
            name=op.f("ck_inventory_operations_valid_type"),
        ),
        sa.ForeignKeyConstraint(
            ["registered_by_user_id"],
            ["users.id"],
            name=op.f("fk_inventory_operations_registered_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name=op.f("fk_inventory_operations_warehouse_id_warehouses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_operations")),
    )
    for column in (
        "document_reference",
        "occurred_at",
        "operation_type",
        "registered_by_user_id",
        "warehouse_id",
    ):
        op.create_index(
            op.f(f"ix_inventory_operations_{column}"),
            "inventory_operations",
            [column],
            unique=False,
        )
    op.create_table(
        "inventory_operation_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_inventory_operation_lines_quantity_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["inventory_operations.id"],
            name=op.f("fk_inventory_operation_lines_operation_id_inventory_operations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_inventory_operation_lines_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_operation_lines")),
        sa.UniqueConstraint("operation_id", "product_id", name="uq_operation_product"),
    )
    for column in ("operation_id", "product_id"):
        op.create_index(
            op.f(f"ix_inventory_operation_lines_{column}"),
            "inventory_operation_lines",
            [column],
            unique=False,
        )
    for table_name in ("inventory_operations", "inventory_operation_lines"):
        op.execute(
            sa.text(f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY')
        )
        op.execute(sa.text(f'REVOKE ALL ON TABLE public."{table_name}" FROM PUBLIC'))
        op.execute(
            sa.text(
                f"""DO $$ BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN REVOKE ALL ON TABLE public."{table_name}" FROM anon; END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN REVOKE ALL ON TABLE public."{table_name}" FROM authenticated; END IF;
            END $$"""
            )
        )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_inventory_operation_lines_product_id"),
        table_name="inventory_operation_lines",
    )
    op.drop_index(
        op.f("ix_inventory_operation_lines_operation_id"),
        table_name="inventory_operation_lines",
    )
    op.drop_table("inventory_operation_lines")
    for column in (
        "warehouse_id",
        "registered_by_user_id",
        "operation_type",
        "occurred_at",
        "document_reference",
    ):
        op.drop_index(
            op.f(f"ix_inventory_operations_{column}"),
            table_name="inventory_operations",
        )
    op.drop_table("inventory_operations")
