"""add document processing jobs

Revision ID: bf4a6c8d0e13
Revises: ae3f5b7c9d12
Create Date: 2026-07-28 16:40:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "bf4a6c8d0e13"
down_revision: Union[str, None] = "ae3f5b7c9d12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("temporary_path", sa.String(length=500), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.BigInteger(), nullable=False),
        sa.Column("requires_ocr", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress", sa.BigInteger(), nullable=False),
        sa.Column("extraction_method", sa.String(length=80), nullable=True),
        sa.Column(
            "result",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("attempt", sa.BigInteger(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column(
            "memory_metrics",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("kind", "user_id", "sha256", "status", "created_at"):
        op.create_index(
            f"ix_document_processing_jobs_{column}",
            "document_processing_jobs",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("document_processing_jobs")
