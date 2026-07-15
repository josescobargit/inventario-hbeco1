"""create delivery lines

Revision ID: c8b6a4d2e901
Revises: a71f0c8d921b
Create Date: 2026-07-08 22:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8b6a4d2e901"
down_revision: Union[str, None] = "a71f0c8d921b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "delivery_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_line_id", sa.Uuid(), nullable=False),
        sa.Column("delivered_quantity", sa.BigInteger(), nullable=False),
        sa.Column("rejected_quantity", sa.BigInteger(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "delivered_quantity >= 0", name=op.f("ck_delivery_lines_delivered_nonnegative")
        ),
        sa.CheckConstraint(
            "rejected_quantity >= 0", name=op.f("ck_delivery_lines_rejected_nonnegative")
        ),
        sa.CheckConstraint(
            "delivered_quantity + rejected_quantity > 0",
            name=op.f("ck_delivery_lines_reported_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["deliveries.id"],
            name=op.f("fk_delivery_lines_delivery_id_deliveries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_line_id"],
            ["invoice_lines.id"],
            name=op.f("fk_delivery_lines_invoice_line_id_invoice_lines"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_lines")),
    )
    op.create_index(
        op.f("ix_delivery_lines_delivery_id"),
        "delivery_lines",
        ["delivery_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_delivery_lines_invoice_line_id"),
        "delivery_lines",
        ["invoice_line_id"],
        unique=False,
    )
    op.execute(sa.text('ALTER TABLE public."delivery_lines" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text('REVOKE ALL ON TABLE public."delivery_lines" FROM PUBLIC'))
    op.execute(
        sa.text(
            """DO $$ BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN REVOKE ALL ON TABLE public."delivery_lines" FROM anon; END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN REVOKE ALL ON TABLE public."delivery_lines" FROM authenticated; END IF;
            END $$"""
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_delivery_lines_invoice_line_id"), table_name="delivery_lines")
    op.drop_index(op.f("ix_delivery_lines_delivery_id"), table_name="delivery_lines")
    op.drop_table("delivery_lines")
