from alembic import op
import sqlalchemy as sa

revision = "c2e4a8f91035"
down_revision = "b8d2e6f91034"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("law_version_effective_branches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("law_id", sa.String(64), nullable=False),
        sa.Column("mst", sa.String(80), nullable=False),
        sa.Column("effective_date", sa.String(10), nullable=False),
        sa.Column("promulgation_date", sa.String(10)),
        sa.Column("history_code", sa.String(30)),
        sa.Column("source_snapshot_id", sa.String(36), sa.ForeignKey("law_history_snapshots.id"), nullable=False),
        sa.UniqueConstraint("source_snapshot_id", "law_id", "mst", "effective_date", name="uq_law_version_effective_branch"))
    op.create_index("ix_law_version_effective_branch_snapshot",
        "law_version_effective_branches", ["source_snapshot_id"])

def downgrade():
    op.drop_index("ix_law_version_effective_branch_snapshot", table_name="law_version_effective_branches")
    op.drop_table("law_version_effective_branches")
