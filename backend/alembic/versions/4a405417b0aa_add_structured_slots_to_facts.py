# -*- coding: utf-8 -*-
"""add_structured_slots_to_facts

Revision ID: 4a405417b0aa
Revises: d3f5a9b01036
Create Date: 2026-11-06 10:53:54.301962

[마이그레이션 개요]
승인된 공식 사실(Fact)의 법률적 의미 속성(Event, Role, Modality, Speech-act)을
영속화하기 위해 facts 테이블에 구조화 비교 슬롯 정보(subject_key, predicate_key,
scope, temporal_context, structured_slots) 컬럼을 추가한다.
이를 통해 후속 상충 판정, 타임라인, 상담, GraphRAG 동기화 시 원문을 재해석하지 않고
승인된 의미 데이터를 LLM 호출 없이 즉시 재사용할 수 있도록 보장한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a405417b0aa'
down_revision: Union[str, Sequence[str], None] = 'd3f5a9b01036'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """스키마 업그레이드: facts 테이블에 구조화 의미 데이터 컬럼 추가 및 기본값 백필."""
    op.add_column("facts", sa.Column("subject_key", sa.String(), nullable=True))
    op.add_column("facts", sa.Column("predicate_key", sa.String(), nullable=True))
    op.add_column(
        "facts",
        sa.Column("scope", sa.String(), nullable=True, server_default="CASE_GLOBAL"),
    )
    op.add_column("facts", sa.Column("temporal_context", sa.String(), nullable=True))
    op.add_column("facts", sa.Column("structured_slots", sa.JSON(), nullable=True))

    op.execute(
        "UPDATE facts SET scope = 'CASE_GLOBAL' WHERE scope IS NULL;"
    )


def downgrade() -> None:
    """스키마 롤백: 추가된 구조화 컬럼 제거."""
    op.drop_column("facts", "structured_slots")
    op.drop_column("facts", "temporal_context")
    op.drop_column("facts", "scope")
    op.drop_column("facts", "predicate_key")
    op.drop_column("facts", "subject_key")
