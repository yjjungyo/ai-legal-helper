# -*- coding: utf-8 -*-
"""add_structured_conflict_fields_to_evidence_claims

Revision ID: f7c8a912b304
Revises: d17d31661e36
Create Date: 2026-10-23 21:35:00.000000

[마이그레이션 개요]
Evidence Conflict Detection Engine v1.1의 P0-02 요구사항에 따라
`evidence_claims` 테이블에 구조화된 비교 슬롯 정보(`subject_key`, `predicate_key`,
`scope`, `temporal_context`, `structured_slots`)를 영속화하기 위한 컬럼을 추가한다.
기존 레코드에 대해서는 `claim_type = 'DOC_INFO'`인 경우 `scope = 'DOCUMENT_LOCAL'`,
그 외에는 `scope = 'CASE_GLOBAL'`로 호환 기본값을 백필한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7c8a912b304"
down_revision: Union[str, Sequence[str], None] = "d17d31661e36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """스키마 업그레이드: evidence_claims 테이블에 구조화 상충 비교 컬럼 추가 및 기본값 백필."""
    op.add_column("evidence_claims", sa.Column("subject_key", sa.String(), nullable=True))
    op.add_column("evidence_claims", sa.Column("predicate_key", sa.String(), nullable=True))
    op.add_column(
        "evidence_claims",
        sa.Column("scope", sa.String(), nullable=True, server_default="CASE_GLOBAL"),
    )
    op.add_column("evidence_claims", sa.Column("temporal_context", sa.String(), nullable=True))
    op.add_column("evidence_claims", sa.Column("structured_slots", sa.JSON(), nullable=True))

    # 기존 레코드 호환 백필
    op.execute(
        "UPDATE evidence_claims SET scope = 'DOCUMENT_LOCAL' "
        "WHERE claim_type IN ('DOC_INFO', 'DOCUMENT_INFO', '문서정보') AND (scope IS NULL OR scope = 'CASE_GLOBAL');"
    )
    op.execute(
        "UPDATE evidence_claims SET scope = 'CASE_GLOBAL' WHERE scope IS NULL;"
    )


def downgrade() -> None:
    """스키마 롤백: 추가된 구조화 컬럼 제거."""
    op.drop_column("evidence_claims", "structured_slots")
    op.drop_column("evidence_claims", "temporal_context")
    op.drop_column("evidence_claims", "scope")
    op.drop_column("evidence_claims", "predicate_key")
    op.drop_column("evidence_claims", "subject_key")
