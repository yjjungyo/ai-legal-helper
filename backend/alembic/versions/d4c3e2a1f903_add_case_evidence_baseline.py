"""add case evidence baseline and reanalysis lineage to consultations

Revision ID: d4c3e2a1f903
Revises: c402b8e5a201
"""
from alembic import op
import sqlalchemy as sa

revision = "d4c3e2a1f903"
down_revision = "c402b8e5a201"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("consultations", sa.Column("case_evidence_manifest", sa.JSON(), nullable=True))
    op.add_column("consultations", sa.Column("reanalysis_of_request_id", sa.String(), nullable=True))
    op.create_index("ix_consultations_reanalysis_of_request_id", "consultations",
                    ["reanalysis_of_request_id"], unique=False)

def downgrade() -> None:
    op.drop_index("ix_consultations_reanalysis_of_request_id", table_name="consultations")
    op.drop_column("consultations", "reanalysis_of_request_id")
    op.drop_column("consultations", "case_evidence_manifest")
