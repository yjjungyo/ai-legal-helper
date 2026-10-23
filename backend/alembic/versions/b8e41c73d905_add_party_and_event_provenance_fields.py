# -*- coding: utf-8 -*-
"""add_party_and_event_provenance_fields

Revision ID: b8e41c73d905
Revises: f7c8a912b304
Create Date: 2026-10-23 22:30:00.000000

[마이그레이션 개요]
Evidence → Facts → Parties / Timeline 자동 생성 및 동기화 개선에 따라
`parties` 테이블과 `events` 테이블에 출처(`source_type`), 신뢰/검증 상태(`verification_status`),
이벤트 발생 성격(`occurrence_status`), 관련 Fact/Claim ID(`related_fact_ids`, `related_claim_ids`)
컬럼을 추가하고 기존 데이터의 호환 기본값을 백필한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8e41c73d905"
down_revision: Union[str, Sequence[str], None] = "f7c8a912b304"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """스키마 업그레이드: parties 및 events 테이블에 출처·추적 메타데이터 컬럼 추가."""
    op.add_column(
        "parties",
        sa.Column("source_type", sa.String(), nullable=True, server_default="MANUAL"),
    )
    op.add_column(
        "parties",
        sa.Column("verification_status", sa.String(), nullable=True, server_default="VERIFIED"),
    )
    op.add_column("parties", sa.Column("related_fact_ids", sa.JSON(), nullable=True))
    op.add_column("parties", sa.Column("related_claim_ids", sa.JSON(), nullable=True))

    op.add_column(
        "events",
        sa.Column("occurrence_status", sa.String(), nullable=True, server_default="ACTUAL"),
    )
    op.add_column(
        "events",
        sa.Column("source_type", sa.String(), nullable=True, server_default="MANUAL"),
    )

    op.execute("UPDATE parties SET source_type = 'MANUAL' WHERE source_type IS NULL;")
    op.execute("UPDATE parties SET verification_status = 'VERIFIED' WHERE verification_status IS NULL;")
    op.execute("UPDATE events SET occurrence_status = 'ACTUAL' WHERE occurrence_status IS NULL;")
    op.execute(
        "UPDATE events SET source_type = CASE "
        "WHEN related_fact_ids IS NOT NULL THEN 'EVIDENCE_DERIVED' "
        "ELSE 'MANUAL' END "
        "WHERE source_type IS NULL;"
    )


def downgrade() -> None:
    """스키마 롤백: parties 및 events 테이블에서 추가된 컬럼 제거."""
    op.drop_column("events", "source_type")
    op.drop_column("events", "occurrence_status")
    op.drop_column("parties", "related_claim_ids")
    op.drop_column("parties", "related_fact_ids")
    op.drop_column("parties", "verification_status")
    op.drop_column("parties", "source_type")
