"""Version document parsing and retain superseded extraction rows for audit.

Revision ID: c01a10e577f7
Revises: c01a10e577f6
"""

from alembic import op
import sqlalchemy as sa

revision = "c01a10e577f7"
down_revision = "c01a10e577f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "commercial_documents",
        sa.Column("parser_version", sa.String(40), nullable=True),
    )
    op.add_column(
        "commercial_records",
        sa.Column(
            "superseded", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade():
    op.drop_column("commercial_records", "superseded")
    op.drop_column("commercial_documents", "parser_version")
