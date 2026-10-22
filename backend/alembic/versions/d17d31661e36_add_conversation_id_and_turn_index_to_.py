# -*- coding: utf-8 -*-
"""add_conversation_id_and_turn_index_to_consultations

Revision ID: d17d31661e36
Revises: 32499b33ab28
Create Date: 2026-10-22 20:09:19.166489

[마이그레이션 개요]
법률 상담(consultations) 테이블에 연속된 대화 세션을 그룹화하기 위한
`conversation_id`와 대화 내 턴 순서를 나타내는 `turn_index` 컬럼을 추가한다.
기존에 생성된 상담 레코드들의 경우 request_id 값을 conversation_id로 1회 백필하여
하위 호환성과 데이터 연속성을 보존한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd17d31661e36'
down_revision: Union[str, Sequence[str], None] = '32499b33ab28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """스키마 업그레이드: consultations 테이블에 conversation_id 및 turn_index 추가 및 인덱스 생성."""
    # 1. 컬럼 추가
    op.add_column('consultations', sa.Column('conversation_id', sa.String(length=100), nullable=True))
    op.add_column('consultations', sa.Column('turn_index', sa.Integer(), nullable=False, server_default='1'))
    
    # 2. 빠른 대화별 히스토리 조회를 위한 인덱스 생성
    op.create_index(op.f('ix_consultations_conversation_id'), 'consultations', ['conversation_id'], unique=False)
    
    # 3. 기존 상담 레코드 하위 호환성을 위한 데이터 백필
    op.execute("UPDATE consultations SET conversation_id = request_id WHERE conversation_id IS NULL;")


def downgrade() -> None:
    """스키마 롤백: 인덱스 및 신규 컬럼 제거."""
    op.drop_index(op.f('ix_consultations_conversation_id'), table_name='consultations')
    op.drop_column('consultations', 'turn_index')
    op.drop_column('consultations', 'conversation_id')
