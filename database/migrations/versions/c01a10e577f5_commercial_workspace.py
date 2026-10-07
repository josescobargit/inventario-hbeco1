"""Commercial evidence, historical rows and product profiles.

Revision ID: c01a10e577f5
Revises: d8f1a3c5e7b9
"""

from alembic import op
import sqlalchemy as sa

revision = "c01a10e577f5"
down_revision = "d8f1a3c5e7b9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commercial_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("extracted_text", sa.Text()),
        sa.Column("method", sa.String(60), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "commercial_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("commercial_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("corrections", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "document_id", "row_number", name="uq_commercial_document_row"
        ),
    )
    op.create_index(
        "ix_commercial_records_document_id", "commercial_records", ["document_id"]
    )
    op.create_table(
        "commercial_product_profiles",
        sa.Column(
            "product_id",
            sa.Uuid(),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("ean14", sa.String(14)),
        sa.Column("presentation", sa.String(160)),
        sa.Column("content", sa.String(160)),
        sa.Column("line", sa.String(100)),
        sa.Column("aliases", sa.JSON(), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "commercial_documents",
            "commercial_records",
            "commercial_product_profiles",
        ):
            op.execute(sa.text(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC"))
            op.execute(
                sa.text(f"""DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    REVOKE ALL ON TABLE public.{table} FROM anon;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL ON TABLE public.{table} FROM authenticated;
                END IF;
            END $$;""")
            )


def downgrade():
    op.drop_table("commercial_product_profiles")
    op.drop_table("commercial_records")
    op.drop_table("commercial_documents")
