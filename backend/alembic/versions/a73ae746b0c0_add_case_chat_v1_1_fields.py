"""add_case_chat_v1_1_fields

Revision ID: a73ae746b0c0
Revises: 7cd64ca60a97
Create Date: 2026-10-24 13:06:09.415381

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a73ae746b0c0'
down_revision: Union[str, Sequence[str], None] = '7cd64ca60a97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# -*- coding: utf-8 -*-
"""add_case_chat_v1_1_fields

Revision ID: a73ae746b0c0
Revises: 7cd64ca60a97
Create Date: 2026-10-24 13:06:09.415381

[마이그레이션 개요]
사건 중심 단일 대화(Case = One Persistent Conversation) v1.1 요구사항을 지원하기 위해:
1. `cases` 테이블에 사건 대표 대화 식별자인 `primary_conversation_id` 컬럼 및 인덱스 추가.
2. `consultations` 테이블에 LangGraph 6단계 실시간 진행 상태 영속화를 위한 `progress` JSON 컬럼 추가.
3. 기존 등록된 사건들의 기존 상담 이력을 조사하여 최초 `conversation_id`를 대표 대화 ID로 백필.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a73ae746b0c0'
down_revision: Union[str, Sequence[str], None] = '7cd64ca60a97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """스키마 업그레이드: cases.primary_conversation_id 및 consultations.progress 추가 및 데이터 백필."""
    # 1. cases 테이블에 primary_conversation_id 추가
    op.add_column('cases', sa.Column('primary_conversation_id', sa.String(length=100), nullable=True))
    op.create_index(op.f('ix_cases_primary_conversation_id'), 'cases', ['primary_conversation_id'], unique=False)

    # 2. consultations 테이블에 progress (JSON) 추가
    op.add_column('consultations', sa.Column('progress', sa.JSON(), nullable=True))

    # 3. 기존 사건들의 대표 대화 세션 ID 백필
    # 각 사건별로 가장 오래된 consultation 레코드의 conversation_id를 가져와 설정
    op.execute("""
        UPDATE cases c
        SET primary_conversation_id = sub.conv_id
        FROM (
            SELECT DISTINCT ON (case_id) case_id, conversation_id AS conv_id
            FROM consultations
            WHERE case_id IS NOT NULL AND conversation_id IS NOT NULL
            ORDER BY case_id, created_at ASC
        ) sub
        WHERE c.id = sub.case_id AND c.primary_conversation_id IS NULL;
    """)


def downgrade() -> None:
    """스키마 롤백: 추가된 컬럼 및 인덱스 제거."""
    op.drop_column('consultations', 'progress')
    op.drop_index(op.f('ix_cases_primary_conversation_id'), table_name='cases')
    op.drop_column('cases', 'primary_conversation_id')

