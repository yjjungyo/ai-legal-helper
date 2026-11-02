# -*- coding: utf-8 -*-
"""Temporal Legal RAG P2: law catalog, official aliases, and sync audit tables.

Revision ID: 90d4e30c2a71
Revises: d4c3e2a1f903

[안전]
- 기존 사건/증거/법령 Vector 컬렉션을 수정하지 않는다.
- 저장되는 시행일은 목록 메타데이터이며 조문 법적 적용 여부에 사용하지 않는다.
- 기존 데이터를 자동 backfill 하지 않는다. 관리자가 별도 sync CLI를 명시 실행한다.
"""
from alembic import op
import sqlalchemy as sa

revision = "90d4e30c2a71"
down_revision = "d4c3e2a1f903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """공식 법령명 목록 조회와 증분 동기화 결과를 위한 별도 테이블만 생성."""
    op.create_table(
        "law_catalog",
        sa.Column("law_id", sa.String(length=64), primary_key=True),
        sa.Column("official_name", sa.String(length=500), nullable=False),
        sa.Column("name_key", sa.String(length=500), nullable=False),
        sa.Column("law_type", sa.String(length=80)),
        sa.Column("current_mst", sa.String(length=80)),
        sa.Column("short_name", sa.String(length=500)),
        sa.Column("promulgation_date", sa.String(length=10)),
        sa.Column("list_effective_date", sa.String(length=10)),
        sa.Column("promulgation_number", sa.String(length=80)),
        sa.Column("ministry_name", sa.String(length=200)),
        sa.Column("history_code", sa.String(length=30)),
        sa.Column("detail_url", sa.Text()),
        sa.Column("source_target", sa.String(length=20), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_law_catalog_name_key", "law_catalog", ["name_key"])

    op.create_table(
        "law_catalog_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("law_id", sa.String(length=64), sa.ForeignKey("law_catalog.law_id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias_name", sa.String(length=500), nullable=False),
        sa.Column("alias_key", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("law_id", "alias_key", name="uq_law_catalog_alias_law_key"),
    )
    op.create_index("ix_law_catalog_aliases_law_id", "law_catalog_aliases", ["law_id"])
    op.create_index("ix_law_catalog_aliases_alias_key", "law_catalog_aliases", ["alias_key"])

    op.create_table(
        "law_catalog_sync_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("query_text", sa.String(length=500)),
        sa.Column("total_expected", sa.Integer()),
        sa.Column("items_seen", sa.Integer(), nullable=False),
        sa.Column("pages_completed", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
    )


def downgrade() -> None:
    """P2 신규 테이블만 제거. 하향 마이그레이션은 축적된 카탈로그 데이터를 삭제하므로 주의."""
    op.drop_table("law_catalog_sync_runs")
    op.drop_index("ix_law_catalog_aliases_alias_key", table_name="law_catalog_aliases")
    op.drop_index("ix_law_catalog_aliases_law_id", table_name="law_catalog_aliases")
    op.drop_table("law_catalog_aliases")
    op.drop_index("ix_law_catalog_name_key", table_name="law_catalog")
    op.drop_table("law_catalog")
