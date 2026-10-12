"""Complete backend-only access for preceding document/invoice tables.

Revision ID: c01a10e577f6
Revises: c01a10e577f5
"""

from alembic import op
import sqlalchemy as sa

revision = "c01a10e577f6"
down_revision = "c01a10e577f5"
branch_labels = None
depends_on = None

TABLES = (
    "document_processing_jobs",
    "supplier_invoices",
    "supplier_invoice_lines",
    "supplier_product_aliases",
)


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
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
    # Access protections remain enabled when rolling back the feature.
    pass
