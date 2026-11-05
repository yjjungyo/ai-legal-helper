# -*- coding: utf-8 -*-
"""P9 공식 법령 전체 버전 인덱싱 작업 기록.

- 동일 법령 ID/MST에 대해 한 개의 영속 작업만 생성한다.
- P4에서 사용자가 승인한 공식 조회의 전체 XML만 받아 별도 worker에서 처리한다.
- 상담 요청 스레드에서 Chroma 임베딩하지 않는다.
"""
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, ForeignKey, Index
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
    law_type = Column(String(80))
    promulgation_date = Column(String(10))
    promulgation_number = Column(String(80))
    list_effective_date = Column(String(10), nullable=False)
    status = Column(String(24), nullable=False, default="PENDING", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    error_code = Column(String(100))
    chunk_count = Column(Integer, nullable=False, default=0)
    lease_owner = Column(String(64))
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime)


class LawHistorySnapshot(Base):
    """공식 eflaw 연혁 조회의 완전성/시점. 최신성 자체가 법률 적용 확정은 아니다."""
    __tablename__ = "law_history_snapshots"
    __table_args__ = (
        Index("ix_law_history_snapshots_law_checked", "law_id", "checked_at"),
    )

    id = Column(String(36), primary_key=True)
    law_id = Column(String(64), nullable=False)
    checked_at = Column(DateTime, nullable=False)
    checked_through = Column(DateTime)
    source_target = Column(String(20), nullable=False, default="eflaw")
    completeness_status = Column(String(24), nullable=False)
    pages_fetched = Column(Integer, nullable=False, default=0)
    official_version_count = Column(Integer)
    error_code = Column(String(100))
    fingerprint = Column(String(64))


class LawVersionIndex(Base):
    """공식 MST의 원문/Chroma 수록 상태; 기존 작업 큐와 별도 커버리지 인덱스."""
    __tablename__ = "law_version_index"
    __table_args__ = (
        UniqueConstraint("law_id", "mst", name="uq_law_version_index_law_mst"),
        Index("ix_law_version_index_law_effective", "law_id", "list_effective_date"),
    )

    id = Column(String(36), primary_key=True)
    law_id = Column(String(64), nullable=False)
    mst = Column(String(80), nullable=False)
    promulgation_date = Column(String(10))
    list_effective_date = Column(String(10), nullable=False)
    history_code = Column(String(30))
    source_snapshot_id = Column(String(36), ForeignKey("law_history_snapshots.id"))
    official_xml_hash = Column(String(64))
    xml_identity_status = Column(String(32), nullable=False, default="UNCONFIRMED")
    index_status = Column(String(24), nullable=False, default="DISCOVERED")
    indexed_at = Column(DateTime)
    chunk_count = Column(Integer, nullable=False, default=0)


class LawArticleCoverage(Base):
    """실제로 저장된 조문/부칙의 MST별 청크 커버리지."""
    __tablename__ = "law_article_coverage"
    __table_args__ = (
        UniqueConstraint("law_id", "mst", "vector_id",
                         name="uq_law_article_coverage_identity"),
        Index("ix_law_article_coverage_lookup", "law_id", "mst", "article_id"),
    )

    id = Column(String(36), primary_key=True)
    law_id = Column(String(64), nullable=False)
    mst = Column(String(80), nullable=False)
    article_id = Column(String(80), nullable=False)
    content_hash = Column(String(64), nullable=False)
    vector_id = Column(String(300), nullable=False)
    article_effective_date = Column(String(10))
    effective_date_basis = Column(String(64))
    effective_to = Column(String(10))
    applicability_review_status = Column(String(32), nullable=False, default="UNCONFIRMED")
    indexed_at = Column(DateTime, nullable=False)


class LawVersionEffectiveBranch(Base):
    """Official history may list multiple effective dates for one MST."""
    __tablename__ = "law_version_effective_branches"
    __table_args__ = (
        UniqueConstraint("source_snapshot_id", "law_id", "mst", "effective_date",
                         name="uq_law_version_effective_branch"),
        Index("ix_law_version_effective_branch_snapshot", "source_snapshot_id"),
    )

    id = Column(String(36), primary_key=True)
    law_id = Column(String(64), nullable=False)
    mst = Column(String(80), nullable=False)
    effective_date = Column(String(10), nullable=False)
    promulgation_date = Column(String(10))
    history_code = Column(String(30))
    source_snapshot_id = Column(String(36), ForeignKey("law_history_snapshots.id"),
                                nullable=False)


class LawArticleVersion(Base):
    """Article text/version evidence, separate from vector coverage."""
    __tablename__ = "law_article_versions"
    __table_args__ = (
        UniqueConstraint("law_id", "mst", "article_id", "content_hash",
                         name="uq_law_article_version_identity"),
        Index("ix_law_article_version_effective", "law_id", "article_id",
              "effective_from"),
    )

    id = Column(String(36), primary_key=True)
    law_id = Column(String(64), nullable=False)
    mst = Column(String(80), nullable=False)
    article_id = Column(String(80), nullable=False)
    content_hash = Column(String(64), nullable=False)
    effective_from = Column(String(10))
    effective_to = Column(String(10))
    effective_date_basis = Column(String(64))
    effective_date_status = Column(String(32), nullable=False, default="UNCONFIRMED")
    source_vector_id = Column(String(300))
    indexed_at = Column(DateTime, nullable=False)


class LawTransitionRule(Base):
    """Source-grounded addendum rules; no automated legal applicability claim."""
    __tablename__ = "law_transition_rules"
    __table_args__ = (
        UniqueConstraint("law_id", "mst", "source_vector_id",
                         name="uq_law_transition_rule_identity"),
        Index("ix_law_transition_rule_lookup", "law_id", "mst"),
    )

    id = Column(String(36), primary_key=True)
    law_id = Column(String(64), nullable=False)
    mst = Column(String(80), nullable=False)
    rule_hash = Column(String(64), nullable=False)
    rule_text = Column(Text, nullable=False)
    promulgation_date = Column(String(10))
    promulgation_number = Column(String(80))
    rule_type = Column(String(32), nullable=False, default="UNCLASSIFIED")
    applicability_status = Column(String(32), nullable=False, default="REVIEW_REQUIRED")
    source_vector_id = Column(String(300))
    indexed_at = Column(DateTime, nullable=False)
