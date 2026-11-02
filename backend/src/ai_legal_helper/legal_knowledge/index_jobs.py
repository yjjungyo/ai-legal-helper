# -*- coding: utf-8 -*-
"""P9 공식 법령 전체 버전 인덱싱 작업 기록.

- 동일 법령 ID/MST에 대해 한 개의 영속 작업만 생성한다.
- P4에서 사용자가 승인한 공식 조회의 전체 XML만 받아 별도 worker에서 처리한다.
- 상담 요청 스레드에서 Chroma 임베딩하지 않는다.
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class OfficialLawIndexJob(Base):
    __tablename__ = "official_law_index_jobs"
    __table_args__ = (
        UniqueConstraint("law_id", "mst", name="uq_official_law_index_job_law_version"),
    )

    id = Column(String(36), primary_key=True)
    law_id = Column(String(64), nullable=False, index=True)
    law_name = Column(String(500), nullable=False)
    mst = Column(String(80), nullable=False)
    list_effective_date = Column(String(10), nullable=False)
    status = Column(String(24), nullable=False, default="PENDING", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    error_code = Column(String(100))
    chunk_count = Column(Integer, nullable=False, default=0)
    lease_owner = Column(String(64))
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime)
