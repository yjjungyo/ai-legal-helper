# -*- coding: utf-8 -*-
"""P12-1: official law history snapshot and per-version/article index coverage.

Revision ID: b8d2e6f91034
Revises: a4c9f5d71092

No backfill or external calls. Existing catalog and job tables remain unchanged.
"""
from alembic import op
import sqlalchemy as sa

revision = "b8d2e6f91034"
down_revision = "a4c9f5d71092"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "law_history_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("law_id", sa.String(64), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("checked_through", sa.DateTime()),
        sa.Column("source_target", sa.String(20), nullable=False),
        sa.Column("completeness_status", sa.String(24), nullable=False),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("official_version_count", sa.Integer()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("fingerprint", sa.String(64)),
    )
    op.create_index("ix_law_history_snapshots_law_checked",
                    "law_history_snapshots", ["law_id", "checked_at"])
    op.create_table(
        "law_version_index",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("law_id", sa.String(64), nullable=False),
        sa.Column("mst", sa.String(80), nullable=False),
        sa.Column("promulgation_date", sa.String(10)),
        sa.Column("list_effective_date", sa.String(10), nullable=False),
        sa.Column("history_code", sa.String(30)),
        sa.Column("source_snapshot_id", sa.String(36),
                  sa.ForeignKey("law_history_snapshots.id")),
        sa.Column("official_xml_hash", sa.String(64)),
        sa.Column("xml_identity_status", sa.String(32), nullable=False),
        sa.Column("index_status", sa.String(24), nullable=False),
        sa.Column("indexed_at", sa.DateTime()),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("law_id", "mst", name="uq_law_version_index_law_mst"),
    )
    op.create_index("ix_law_version_index_law_effective",
                    "law_version_index", ["law_id", "list_effective_date"])
    op.create_table(
        "law_article_coverage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("law_id", sa.String(64), nullable=False),
        sa.Column("mst", sa.String(80), nullable=False),
        sa.Column("article_id", sa.String(80), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("vector_id", sa.String(300), nullable=False),
        sa.Column("article_effective_date", sa.String(10)),
        sa.Column("effective_date_basis", sa.String(64)),
        sa.Column("effective_to", sa.String(10)),
        sa.Column("applicability_review_status", sa.String(32), nullable=False),
        sa.Column("indexed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("law_id", "mst", "vector_id",
                            name="uq_law_article_coverage_identity"),
    )
    op.create_index("ix_law_article_coverage_lookup",
                    "law_article_coverage", ["law_id", "mst", "article_id"])


def downgrade():
    op.drop_index("ix_law_article_coverage_lookup", table_name="law_article_coverage")
    op.drop_table("law_article_coverage")
    op.drop_index("ix_law_version_index_law_effective", table_name="law_version_index")
    op.drop_table("law_version_index")
    op.drop_index("ix_law_history_snapshots_law_checked", table_name="law_history_snapshots")
    op.drop_table("law_history_snapshots")
