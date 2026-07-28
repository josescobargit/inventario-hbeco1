"""add supplier invoice entries

Revision ID: ae3f5b7c9d12
Revises: 9d2e4f6a8b10
Create Date: 2026-07-28 15:10:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ae3f5b7c9d12"
down_revision: Union[str, None] = "9d2e4f6a8b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "supplier_invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_ruc", sa.String(length=13), nullable=False),
        sa.Column("supplier_name", sa.String(length=200), nullable=False),
        sa.Column("invoice_number", sa.String(length=17), nullable=False),
        sa.Column("issued_at", sa.Date(), nullable=False),
        sa.Column("authorization_number", sa.String(length=60), nullable=True),
        sa.Column("buyer_name", sa.String(length=200), nullable=True),
        sa.Column("buyer_ruc", sa.String(length=13), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("tax", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("total", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("extraction_method", sa.String(length=80), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("registered_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("inventory_applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inventory_reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["registered_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supplier_ruc",
            "invoice_number",
            name="uq_supplier_invoice_ruc_number",
        ),
        sa.UniqueConstraint("authorization_number"),
    )
    for column in (
        "supplier_ruc",
        "supplier_name",
        "invoice_number",
        "issued_at",
        "file_sha256",
        "status",
        "registered_by_user_id",
    ):
        op.create_index(
            f"ix_supplier_invoices_{column}",
            "supplier_invoices",
            [column],
            unique=False,
        )
    op.create_table(
        "supplier_invoice_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_code", sa.String(length=100), nullable=True),
        sa.Column("barcode", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column("discount", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("line_total", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["supplier_invoice_id"], ["supplier_invoices.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supplier_invoice_id",
            "line_number",
            name="uq_supplier_invoice_line_number",
        ),
    )
    op.create_index(
        "ix_supplier_invoice_lines_product_id",
        "supplier_invoice_lines",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        "ix_supplier_invoice_lines_supplier_invoice_id",
        "supplier_invoice_lines",
        ["supplier_invoice_id"],
        unique=False,
    )
    op.create_table(
        "supplier_product_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_ruc", sa.String(length=13), nullable=False),
        sa.Column("supplier_code", sa.String(length=100), nullable=True),
        sa.Column("barcode", sa.String(length=100), nullable=True),
        sa.Column("normalized_description", sa.String(length=300), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "supplier_ruc", "barcode", name="uq_supplier_alias_barcode"
        ),
        sa.UniqueConstraint(
            "supplier_ruc", "supplier_code", name="uq_supplier_alias_code"
        ),
    )
    op.create_index(
        "ix_supplier_product_aliases_product_id",
        "supplier_product_aliases",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        "ix_supplier_product_aliases_supplier_ruc",
        "supplier_product_aliases",
        ["supplier_ruc"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("supplier_product_aliases")
    op.drop_table("supplier_invoice_lines")
    op.drop_table("supplier_invoices")
