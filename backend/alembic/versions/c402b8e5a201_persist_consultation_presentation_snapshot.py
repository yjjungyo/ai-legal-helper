"""persist verified consultation presentation snapshots

Revision ID: c402b8e5a201
Revises: a73ae746b0c0

Existing consultations are not backfilled: historic regeneration does not prove
what was shown at the original consultation time.
"""
from alembic import op
import sqlalchemy as sa

revision = "c402b8e5a201"
down_revision = "a73ae746b0c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("consultations", sa.Column("presentation_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("consultations", "presentation_snapshot")
