"""add invoice inventory audit fields and movement indexes

Revision ID: c7e9a1b3d5f7
Revises: bf4a6c8d0e13
Create Date: 2026-07-28 23:25:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c7e9a1b3d5f7"
down_revision: Union[str, None] = "bf4a6c8d0e13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("establishment_number", sa.String(3)))
    op.add_column("invoices", sa.Column("emission_point", sa.String(3)))
    op.add_column("invoices", sa.Column("sequential_number", sa.BigInteger()))
    op.add_column(
        "invoices",
        sa.Column(
            "inventory_status",
            sa.String(30),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "invoices",
        sa.Column(
            "inventory_discounted_quantity",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "invoices",
        sa.Column("inventory_movement_id", sa.Uuid(), nullable=True),
    )
    op.add_column("invoices", sa.Column("inventory_last_error", sa.Text()))
    op.add_column(
        "invoices",
        sa.Column(
            "inventory_attempts",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE invoices
            SET establishment_number = split_part(invoice_number, '-', 1),
                emission_point = split_part(invoice_number, '-', 2),
                sequential_number = CAST(split_part(invoice_number, '-', 3) AS BIGINT),
                inventory_discounted_quantity = GREATEST(
                    0,
                    COALESCE((
                        SELECT SUM(
                            COALESCE(
                                (movement.before_value ->> 'physical_confirmed')::BIGINT,
                                0
                            )
                            - COALESCE(
                                (movement.after_value ->> 'physical_confirmed')::BIGINT,
                                0
                            )
                        )
                        FROM inventory_movements AS movement
                        WHERE movement.reference_type = 'invoice'
                          AND movement.reference_id = invoices.id::TEXT
                    ), 0)
                ),
                inventory_movement_id = (
                    SELECT movement.id
                    FROM inventory_movements AS movement
                    WHERE movement.reference_type = 'invoice'
                      AND movement.reference_id = invoices.id::TEXT
                      AND (
                          movement.before_value ->> 'physical_confirmed'
                      ) IS DISTINCT FROM (
                          movement.after_value ->> 'physical_confirmed'
                      )
                    ORDER BY movement.occurred_at, movement.id
                    LIMIT 1
                ),
                inventory_attempts = CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM inventory_movements AS movement
                        WHERE movement.reference_type = 'invoice'
                          AND movement.reference_id = invoices.id::TEXT
                    ) THEN 1
                    ELSE 0
                END,
                inventory_status = CASE
                    WHEN administrative_status = 'cancelled'
                         AND inventory_reversed_at IS NOT NULL THEN 'reverted'
                    WHEN administrative_status = 'cancelled' THEN 'not_applicable'
                    WHEN COALESCE((
                        SELECT SUM(
                            COALESCE(
                                (movement.before_value ->> 'physical_confirmed')::BIGINT,
                                0
                            )
                            - COALESCE(
                                (movement.after_value ->> 'physical_confirmed')::BIGINT,
                                0
                            )
                        )
                        FROM inventory_movements AS movement
                        WHERE movement.reference_type = 'invoice'
                          AND movement.reference_id = invoices.id::TEXT
                    ), 0) = 0 THEN 'pending'
                    WHEN COALESCE((
                        SELECT SUM(
                            COALESCE(
                                (movement.before_value ->> 'physical_confirmed')::BIGINT,
                                0
                            )
                            - COALESCE(
                                (movement.after_value ->> 'physical_confirmed')::BIGINT,
                                0
                            )
                        )
                        FROM inventory_movements AS movement
                        WHERE movement.reference_type = 'invoice'
                          AND movement.reference_id = invoices.id::TEXT
                    ), 0) = COALESCE((
                        SELECT SUM(line.quantity)
                        FROM invoice_lines AS line
                        WHERE line.invoice_id = invoices.id
                    ), 0) THEN 'discounted'
                    WHEN COALESCE((
                        SELECT SUM(
                            COALESCE(
                                (movement.before_value ->> 'physical_confirmed')::BIGINT,
                                0
                            )
                            - COALESCE(
                                (movement.after_value ->> 'physical_confirmed')::BIGINT,
                                0
                            )
                        )
                        FROM inventory_movements AS movement
                        WHERE movement.reference_type = 'invoice'
                          AND movement.reference_id = invoices.id::TEXT
                    ), 0) > 0
                    AND COALESCE((
                        SELECT SUM(
                            COALESCE(
                                (movement.before_value ->> 'physical_confirmed')::BIGINT,
                                0
                            )
                            - COALESCE(
                                (movement.after_value ->> 'physical_confirmed')::BIGINT,
                                0
                            )
                        )
                        FROM inventory_movements AS movement
                        WHERE movement.reference_type = 'invoice'
                          AND movement.reference_id = invoices.id::TEXT
                    ), 0) < COALESCE((
                        SELECT SUM(line.quantity)
                        FROM invoice_lines AS line
                        WHERE line.invoice_id = invoices.id
                    ), 0) THEN 'partial'
                    ELSE 'error'
                END
            """
        )
    )
    op.alter_column("invoices", "establishment_number", nullable=False)
    op.alter_column("invoices", "emission_point", nullable=False)
    op.alter_column("invoices", "sequential_number", nullable=False)
    op.create_foreign_key(
        "fk_invoices_inventory_movement_id_inventory_movements",
        "invoices",
        "inventory_movements",
        ["inventory_movement_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for column in (
        "establishment_number",
        "emission_point",
        "sequential_number",
        "inventory_status",
        "inventory_movement_id",
    ):
        op.create_index(f"ix_invoices_{column}", "invoices", [column])
    op.create_index(
        "ix_invoices_sequence",
        "invoices",
        ["establishment_number", "emission_point", "sequential_number"],
    )

    op.add_column(
        "inventory_movements",
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="confirmed",
        ),
    )
    op.create_index(
        "ix_inventory_movements_status", "inventory_movements", ["status"]
    )
    op.create_index(
        "ix_inventory_movements_history",
        "inventory_movements",
        ["status", "occurred_at", "product_id"],
    )
    op.create_index(
        "ix_inventory_movements_product_ledger",
        "inventory_movements",
        ["product_id", "status", "occurred_at", "id"],
    )
    op.create_index(
        "ix_inventory_movements_invoice_origin",
        "inventory_movements",
        ["reference_type", "reference_id", "movement_type", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_movements_invoice_origin", table_name="inventory_movements"
    )
    op.drop_index(
        "ix_inventory_movements_product_ledger",
        table_name="inventory_movements",
    )
    op.drop_index("ix_inventory_movements_history", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_status", table_name="inventory_movements")
    op.drop_column("inventory_movements", "status")
    op.drop_index("ix_invoices_sequence", table_name="invoices")
    for column in (
        "inventory_movement_id",
        "inventory_status",
        "sequential_number",
        "emission_point",
        "establishment_number",
    ):
        op.drop_index(f"ix_invoices_{column}", table_name="invoices")
    op.drop_constraint(
        "fk_invoices_inventory_movement_id_inventory_movements",
        "invoices",
        type_="foreignkey",
    )
    for column in (
        "inventory_attempts",
        "inventory_last_error",
        "inventory_movement_id",
        "inventory_discounted_quantity",
        "inventory_status",
        "sequential_number",
        "emission_point",
        "establishment_number",
    ):
        op.drop_column("invoices", column)
