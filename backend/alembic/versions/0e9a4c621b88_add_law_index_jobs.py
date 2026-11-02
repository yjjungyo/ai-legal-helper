# -*- coding: utf-8 -*-
"""P9 approved legal version indexing jobs; existing Chroma and case tables untouched.

Revision ID: 0e9a4c621b88
Revises: 90d4e30c2a71
"""
from alembic import op
import sqlalchemy as sa

revision = "0e9a4c621b88"
down_revision = "90d4e30c2a71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "law_index_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("law_id", sa.String(length=64), nullable=False),
        sa.Column("law_name", sa.String(length=500), nullable=False),
        sa.Column("law_type", sa.String(length=80), nullable=True),
        sa.Column("version_id", sa.String(length=80), nullable=False),
        sa.Column("law_effective_date", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("indexed_chunk_count", sa.Integer(), nullable=False),
        sa.Column("indexed_content_hash", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "law_id", "version_id", "law_effective_date",
            name="uq_law_index_job_version",
        ),
    )
    op.create_index("ix_law_index_jobs_law_id", "law_index_jobs", ["law_id"])
    op.create_index("ix_law_index_jobs_status", "law_index_jobs", ["status"])


def downgrade() -> None:
    """삭제성 롤백: P9 작업 이력을 잃을 수 있으므로 운영에서는 사전 백업 필요."""
    op.drop_index("ix_law_index_jobs_status", table_name="law_index_jobs")
    op.drop_index("ix_law_index_jobs_law_id", table_name="law_index_jobs")
    op.drop_table("law_index_jobs")
