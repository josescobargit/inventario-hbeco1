"""add purchase order source documents and customer aliases

Revision ID: 5a7c9e1d3f20
Revises: a8c6d1e2f3b4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5a7c9e1d3f20"
down_revision: Union[str, None] = "a8c6d1e2f3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "purchase_order_source_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("upload_token", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("extraction_method", sa.String(40), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("page_count", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_token"),
    )
    op.create_index(
        "ix_purchase_order_source_documents_upload_token",
        "purchase_order_source_documents",
        ["upload_token"],
        unique=True,
    )
    op.create_index(
        "ix_purchase_order_source_documents_sha256",
        "purchase_order_source_documents",
        ["sha256"],
    )
    op.create_table(
        "purchase_order_document_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["purchase_order_source_documents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_order_id", "document_id", name="uq_purchase_order_document"
        ),
    )
    op.create_index(
        "ix_purchase_order_document_links_purchase_order_id",
        "purchase_order_document_links",
        ["purchase_order_id"],
    )
    op.create_index(
        "ix_purchase_order_document_links_document_id",
        "purchase_order_document_links",
        ["document_id"],
    )
    op.create_table(
        "customer_product_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_name", sa.String(160), nullable=False),
        sa.Column("chain_name_normalized", sa.String(160), nullable=False),
        sa.Column("source_text", sa.String(300), nullable=False),
        sa.Column("source_text_normalized", sa.String(300), nullable=False),
        sa.Column("detected_code", sa.String(100), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chain_name_normalized",
            "source_text_normalized",
            name="uq_customer_product_alias",
        ),
    )
    op.create_index(
        "ix_customer_product_aliases_chain_name_normalized",
        "customer_product_aliases",
        ["chain_name_normalized"],
    )
    op.create_index(
        "ix_customer_product_aliases_source_text_normalized",
        "customer_product_aliases",
        ["source_text_normalized"],
    )
    for table_name in (
        "purchase_order_source_documents",
        "purchase_order_document_links",
        "customer_product_aliases",
    ):
        op.execute(
            sa.text(f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY')
        )
        op.execute(sa.text(f'REVOKE ALL ON TABLE public."{table_name}" FROM PUBLIC'))


def downgrade() -> None:
    op.drop_table("customer_product_aliases")
    op.drop_table("purchase_order_document_links")
    op.drop_table("purchase_order_source_documents")
