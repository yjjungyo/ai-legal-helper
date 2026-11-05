from alembic import op
import sqlalchemy as sa

revision = "d3f5a9b01036"
down_revision = "c2e4a8f91035"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("law_article_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("law_id", sa.String(64), nullable=False),
        sa.Column("mst", sa.String(80), nullable=False),
        sa.Column("article_id", sa.String(80), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("effective_from", sa.String(10)),
        sa.Column("effective_to", sa.String(10)),
        sa.Column("effective_date_basis", sa.String(64)),
        sa.Column("effective_date_status", sa.String(32), nullable=False),
        sa.Column("source_vector_id", sa.String(300)),
        sa.Column("indexed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("law_id", "mst", "article_id", "content_hash", name="uq_law_article_version_identity"))
    op.create_index("ix_law_article_version_effective", "law_article_versions", ["law_id", "article_id", "effective_from"])
    op.create_table("law_transition_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("law_id", sa.String(64), nullable=False),
        sa.Column("mst", sa.String(80), nullable=False),
        sa.Column("rule_hash", sa.String(64), nullable=False),
        sa.Column("rule_text", sa.Text(), nullable=False),
        sa.Column("promulgation_date", sa.String(10)),
        sa.Column("promulgation_number", sa.String(80)),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("applicability_status", sa.String(32), nullable=False),
        sa.Column("source_vector_id", sa.String(300)),
        sa.Column("indexed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("law_id", "mst", "rule_hash", name="uq_law_transition_rule_identity"))
    op.create_index("ix_law_transition_rule_lookup", "law_transition_rules", ["law_id", "mst"])

def downgrade():
    op.drop_index("ix_law_transition_rule_lookup", table_name="law_transition_rules")
    op.drop_table("law_transition_rules")
    op.drop_index("ix_law_article_version_effective", table_name="law_article_versions")
    op.drop_table("law_article_versions")
