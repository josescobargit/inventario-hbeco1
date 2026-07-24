"""add purchase order source quantities

Revision ID: 9c2f7a1b4d60
Revises: 5a7c9e1d3f20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c2f7a1b4d60"
down_revision: Union[str, None] = "5a7c9e1d3f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column("secondary_reference", sa.String(100), nullable=True),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("local_name", sa.String(200), nullable=True),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column("original_quantity", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column("original_unit", sa.String(30), nullable=True),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column("units_per_box", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column("conversion_method", sa.String(40), nullable=True),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column(
            "conversion_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column("source_page", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column("source_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column("source_code", sa.String(100), nullable=True),
    )
    op.add_column(
        "purchase_order_lines",
        sa.Column("source_description", sa.String(300), nullable=True),
    )
    op.alter_column("purchase_order_lines", "conversion_confirmed", server_default=None)


def downgrade() -> None:
    for column in (
        "source_description",
        "source_code",
        "source_text",
        "source_page",
        "conversion_confirmed",
        "conversion_method",
        "units_per_box",
        "original_unit",
        "original_quantity",
    ):
        op.drop_column("purchase_order_lines", column)
    op.drop_column("purchase_orders", "local_name")
    op.drop_column("purchase_orders", "secondary_reference")
