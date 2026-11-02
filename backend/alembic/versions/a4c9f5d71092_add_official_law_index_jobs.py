# -*- coding: utf-8 -*-
"""P9 공식 법령 버전 인덱싱 Job 영속화. 기존 사건 테이블 및 컬렉션 불변.

Revision ID: a4c9f5d71092
Revises: 90d4e30c2a71
"""
from alembic import op
import sqlalchemy as sa

revision = "a4c9f5d71092"
down_revision = "90d4e30c2a71"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "official_law_index_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("law_id", sa.String(64), nullable=False),
        sa.Column("law_name", sa.String(500), nullable=False),
        sa.Column("mst", sa.String(80), nullable=False),
        sa.Column("law_type", sa.String(80)),
        sa.Column("promulgation_date", sa.String(10)),
        sa.Column("promulgation_number", sa.String(80)),
        sa.Column("list_effective_date", sa.String(10), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.UniqueConstraint("law_id", "mst",
                            name="uq_official_law_index_job_law_version"),
    )
    op.create_index("ix_official_law_index_jobs_law_id", "official_law_index_jobs", ["law_id"])
    op.create_index("ix_official_law_index_jobs_status", "official_law_index_jobs", ["status"])


def downgrade():
    # 운영 데이터가 누적된 테이블이므로 downgrade 실행 전에 반드시 백업.
    op.drop_index("ix_official_law_index_jobs_status", table_name="official_law_index_jobs")
    op.drop_index("ix_official_law_index_jobs_law_id", table_name="official_law_index_jobs")
    op.drop_table("official_law_index_jobs")
