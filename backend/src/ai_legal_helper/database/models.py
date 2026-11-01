# -*- coding: utf-8 -*-
"""
Case Intelligence 데이터베이스 모델 (Database Models)

이 모듈은 사건, 당사자, 사실관계, 이벤트(타임라인), 법률 쟁점 등 
사건의 맥락을 영구적으로 저장하기 위한 SQLAlchemy ORM 모델들을 정의한다.
각 엔터티는 외래 키(Foreign Key)를 통해 `Case` 객체와 관계를 맺는다.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey, JSON, Boolean, desc, UniqueConstraint
from sqlalchemy.orm import relationship

from ai_legal_helper.database.session import Base
from ai_legal_helper.utils.datetime_utils import get_kst_now

def generate_uuid() -> str:
    """고유 식별자(UUID4)를 문자열 형태로 생성한다."""
    return str(uuid.uuid4())

class User(Base):
    """사용자(User) 모델"""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    status = Column(String, default="ACTIVE")
    created_at = Column(DateTime, default=get_kst_now)
    updated_at = Column(DateTime, default=get_kst_now, onupdate=get_kst_now)
    
    cases = relationship("Case", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")

class UserSession(Base):
    """사용자 세션(UserSession) 모델"""
    __tablename__ = "user_sessions"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    session_token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=get_kst_now)
    
    user = relationship("User", back_populates="sessions")

class AuditLog(Base):
    """감사 로그(AuditLog) 모델"""
    __tablename__ = "audit_logs"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    actor_user_id = Column(String, nullable=True) # ForeignKey("users.id") 생략 가능
    case_id = Column(String, nullable=True)
    event_type = Column(String, nullable=False)
    resource_type = Column(String, nullable=False)
    resource_id = Column(String, nullable=True)
    result = Column(String, nullable=False)
    created_at = Column(DateTime, default=get_kst_now)

class Case(Base):
    """
    사건(Case) 모델
    
    법률 상담의 단일 사건 단위를 나타내며, 관련된 당사자, 사실관계 등을 소유하는 최상위 엔터티이다.
    """
    __tablename__ = "cases"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True) # 마이그레이션 후 Not Null 고려
    title = Column(String, nullable=False, default="새 사건")
    case_type = Column(String, nullable=True)  # 예: "주택임대차"
    description = Column(Text, nullable=True)
    status = Column(String, default="OPEN")  # OPEN, IN_PROGRESS, CLOSED
    primary_conversation_id = Column(String(100), nullable=True, index=True)  # 사건 대표 대화 식별자 (Case = One Persistent Conversation)
    version = Column(Integer, default=1)  # 업데이트 발생 시 증가
    created_at = Column(DateTime, default=get_kst_now)
    updated_at = Column(DateTime, default=get_kst_now, onupdate=get_kst_now)

    __mapper_args__ = {
        "version_id_col": version
    }

    # 연관 관계
    user = relationship("User", back_populates="cases")
    parties = relationship("Party", back_populates="case", cascade="all, delete-orphan")
    facts = relationship("Fact", back_populates="case", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="case", cascade="all, delete-orphan")
    legal_issues = relationship("LegalIssue", back_populates="case", cascade="all, delete-orphan")
    revisions = relationship("CaseRevision", back_populates="case", cascade="all, delete-orphan")
    evidences = relationship("EvidenceDocument", back_populates="case", cascade="all, delete-orphan")
    claims = relationship("EvidenceClaim", back_populates="case", cascade="all, delete-orphan")
    legal_actions = relationship("LegalAction", back_populates="case", cascade="all, delete-orphan")
    action_revisions = relationship("ActionRevision", back_populates="case", cascade="all, delete-orphan")
    legal_documents = relationship("LegalDocument", back_populates="case", cascade="all, delete-orphan")
    consultations = relationship("ConsultationRecord", back_populates="case", cascade="all, delete-orphan", order_by="desc(ConsultationRecord.created_at)")
    evidence_assessments = relationship("EvidenceAssessment", back_populates="case", cascade="all, delete-orphan")
    fact_adjudications = relationship("FactAdjudication", back_populates="case", cascade="all, delete-orphan")
    evidence_gaps = relationship("EvidenceGap", back_populates="case", cascade="all, delete-orphan")
    comparison_audits = relationship("FactComparisonAudit", back_populates="case", cascade="all, delete-orphan")

class Party(Base):
    """
    사건 당사자(Party) 모델
    
    사건에 연루된 인물이나 단체(임대인, 임차인, 원고, 피고 등)를 나타낸다.
    수동 등록(MANUAL)과 증거/진술 파생(EVIDENCE_DERIVED, STATEMENT_EXTRACTED) 출처 및
    근거 Fact/Claim ID 목록을 함께 관리하여 증거 수정·반려 시 정합성을 보장한다.
    """
    __tablename__ = "parties"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=True)  # 임차인, 임대인, 원고, 피고 등
    party_relationship = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    source_type = Column(String, default="MANUAL", nullable=True)  # MANUAL, STATEMENT_EXTRACTED, EVIDENCE_DERIVED
    verification_status = Column(String, default="VERIFIED", nullable=True)  # VERIFIED, DOCUMENT_VERIFIED, PARTY_ASSERTED, UNVERIFIED
    related_fact_ids = Column(JSON, nullable=True)  # 연관된 Fact ID 목록
    related_claim_ids = Column(JSON, nullable=True)  # 연관된 EvidenceClaim ID 목록

    case = relationship("Case", back_populates="parties")

class Fact(Base):
    """
    사실관계(Fact) 모델
    
    사건에 포함된 개별 사실이나 주장을 저장한다. AI를 통해 문장에서 개별 사실로 분리된다.
    """
    __tablename__ = "facts"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    statement = Column(Text, nullable=False)
    fact_type = Column(String, nullable=True)  # 날짜, 금액, 행위 등
    confidence = Column(Float, nullable=True)  # AI 추출 신뢰도
    source_type = Column(String, default="USER_CLAIM")  # USER_CLAIM, DOCUMENT_SUPPORTED, AI_INFERENCE 등
    source_ref = Column(Text, nullable=True)  # 원문 참조 (보안상 원문 그대로 저장 주의, 비식별화 권장)
    occurred_at = Column(String, nullable=True)  # 발생 시점 명시 (문자열)
    verification_status = Column(String, default="UNVERIFIED")  # UNVERIFIED, VERIFIED, DISPUTED
    created_at = Column(DateTime, default=get_kst_now)

    case = relationship("Case", back_populates="facts")
    adjudications = relationship("FactAdjudication", back_populates="fact", cascade="all, delete-orphan")
    gaps = relationship("EvidenceGap", back_populates="fact")

class Event(Base):
    """
    타임라인 이벤트(Event) 모델
    
    시간순으로 정렬 가능한 사건의 전개 단위를 나타낸다. 추출된 사실관계 중 
    날짜 정보가 있는 것들이 모여 이벤트를 구성하며, 실제 발생(ACTUAL)과
    예정/기일(SCHEDULED), 요청 기한(REQUESTED) 및 출처(source_type)를 구분한다.
    """
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    event_date = Column(String, nullable=True)  # YYYY-MM-DD 또는 대략적 시기
    date_precision = Column(String, default="EXACT")  # EXACT, APPROXIMATE, UNKNOWN
    event_type = Column(String, nullable=True)  # 계약 체결, 계약 시작, 계약 종료, 지급기일, 통지 발송 등
    occurrence_status = Column(String, default="ACTUAL", nullable=True)  # ACTUAL, SCHEDULED, REQUESTED, NEEDS_VERIFICATION
    source_type = Column(String, default="MANUAL", nullable=True)  # MANUAL, STATEMENT_EXTRACTED, EVIDENCE_DERIVED
    related_fact_ids = Column(JSON, nullable=True)  # 연관된 Fact ID 목록
    created_at = Column(DateTime, default=get_kst_now)

    case = relationship("Case", back_populates="events")

class LegalIssue(Base):
    """
    법률 쟁점(LegalIssue) 모델
    
    확정된 사실관계를 기반으로 AI가 도출해낸, 검토가 필요한 법률적 쟁점을 의미한다.
    """
    __tablename__ = "legal_issues"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    related_fact_ids = Column(JSON, nullable=True)  # 연관 Fact ID
    status = Column(String, default="OPEN")  # OPEN, RESOLVED
    created_at = Column(DateTime, default=get_kst_now)

    case = relationship("Case", back_populates="legal_issues")

class CaseRevision(Base):
    """
    사건 변경 이력(CaseRevision) 모델
    
    사용자 진술 추가 등으로 사건 맥락이 업데이트되었을 때의 변경 로그를 남긴다.
    """
    __tablename__ = "case_revisions"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    change_type = Column(String, nullable=False)  # FACTS_ADDED, ISSUE_RESOLVED 등
    change_summary = Column(Text, nullable=True)
    changed_entity_ids = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=get_kst_now)

    case = relationship("Case", back_populates="revisions")


class EvidenceDocument(Base):
    """
    증거 문서(EvidenceDocument) 모델
    
    업로드된 파일의 메타데이터와 안전한 저장소 위치를 관리한다.
    """
    __tablename__ = "evidence_documents"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    original_filename = Column(String, nullable=False)
    safe_storage_key = Column(String, nullable=False)
    media_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False)
    status = Column(String, default="UPLOADED")  # UPLOADED, EXTRACTING, REVIEW_REQUIRED, APPROVED, FAILED, EXTRACTION_UNAVAILABLE
    source_kind = Column(String, nullable=True)  # Contract, Conversation, Notice, etc.
    metadata_json = Column(JSON, nullable=True)
    uploaded_at = Column(DateTime, default=get_kst_now)
    extracted_at = Column(DateTime, nullable=True)
    extraction_version = Column(String, nullable=True)
    error_code = Column(String, nullable=True)

    case = relationship("Case", back_populates="evidences")
    spans = relationship("EvidenceSpan", back_populates="document", cascade="all, delete-orphan")
    claims = relationship("EvidenceClaim", back_populates="document", cascade="all, delete-orphan")
    assessments = relationship("EvidenceAssessment", back_populates="document", cascade="all, delete-orphan")

class EvidenceSpan(Base):
    """
    증거 발췌(EvidenceSpan) 모델
    
    증거 문서 내에서의 특정 텍스트 위치나 구역(페이지, 문단, 문자 오프셋)을 지정한다.
    """
    __tablename__ = "evidence_spans"

    id = Column(String, primary_key=True, default=generate_uuid)
    evidence_id = Column(String, ForeignKey("evidence_documents.id", ondelete="CASCADE"), nullable=False)
    page_number = Column(Integer, nullable=True)
    paragraph_index = Column(Integer, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    text_excerpt = Column(Text, nullable=False)
    extractor_version = Column(String, nullable=True)
    location_quality = Column(String, default="EXACT")  # EXACT, APPROXIMATE, UNKNOWN
    created_at = Column(DateTime, default=get_kst_now)

    document = relationship("EvidenceDocument", back_populates="spans")
    claim_links = relationship("EvidenceClaim", secondary="evidence_span_claim_links", back_populates="spans")

class EvidenceClaim(Base):
    """
    추출 사실 후보(EvidenceClaim) 모델
    
    AI가 문서에서 추출한 사실관계 명제나 당사자 주장의 후보.
    사용자의 승인(REVIEW_STATUS)을 얻으면 공식 Fact로 편입된다.
    """
    __tablename__ = "evidence_claims"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    evidence_id = Column(String, ForeignKey("evidence_documents.id", ondelete="CASCADE"), nullable=False)
    statement = Column(Text, nullable=False)
    claim_type = Column(String, nullable=True)
    assertion_status = Column(String, default="AI_INFERENCE")  # DOCUMENT_STATES, PARTY_ALLEGES, AI_INFERENCE, UNCERTAIN
    confidence = Column(Float, nullable=True)
    review_status = Column(String, default="PENDING")  # PENDING, APPROVED, EDITED, REJECTED
    extractor_model = Column(String, nullable=True)
    subject_key = Column(String, nullable=True)  # 비교 대상 주체·계약·항목 키
    predicate_key = Column(String, nullable=True)  # 비교 대상 속성·행위 의미 키
    scope = Column(String, default="CASE_GLOBAL", nullable=True)  # DOCUMENT_LOCAL, CASE_GLOBAL
    temporal_context = Column(String, nullable=True)  # 적용 시점·기간·이벤트 역할
    structured_slots = Column(JSON, nullable=True)  # 정규화된 금액·날짜 역할 및 상충 판정 메타데이터
    created_at = Column(DateTime, default=get_kst_now)

    case = relationship("Case", back_populates="claims")
    document = relationship("EvidenceDocument", back_populates="claims")
    spans = relationship("EvidenceSpan", secondary="evidence_span_claim_links", back_populates="claim_links")
    assessments = relationship("EvidenceAssessment", back_populates="claim", cascade="all, delete-orphan")
    adjudications = relationship("FactAdjudication", back_populates="claim")
    gaps = relationship("EvidenceGap", back_populates="claim")

class EvidenceSpanClaimLink(Base):
    """
    Claim과 Span을 다대다로 연결 (EvidenceSpanClaimLink)
    """
    __tablename__ = "evidence_span_claim_links"

    claim_id = Column(String, ForeignKey("evidence_claims.id", ondelete="CASCADE"), primary_key=True)
    span_id = Column(String, ForeignKey("evidence_spans.id", ondelete="CASCADE"), primary_key=True)

class EvidenceLink(Base):
    """
    증거 연결(EvidenceLink) 모델
    
    승인된 Claim/Span이 공식 Fact, Event, LegalIssue를 지지(SUPPORTS), 모순(CONTRADICTS)하는지 기록한다.
    """
    __tablename__ = "evidence_links"

    id = Column(String, primary_key=True, default=generate_uuid)
    evidence_id = Column(String, ForeignKey("evidence_documents.id", ondelete="CASCADE"), nullable=False)
    span_id = Column(String, ForeignKey("evidence_spans.id", ondelete="CASCADE"), nullable=True)
    claim_id = Column(String, ForeignKey("evidence_claims.id", ondelete="CASCADE"), nullable=True)
    
    # 연결 대상 (사실, 이벤트, 쟁점 중 하나)
    target_type = Column(String, nullable=False)  # FACT, EVENT, LEGAL_ISSUE
    target_id = Column(String, nullable=False)
    
    link_type = Column(String, default="SUPPORTS")  # SUPPORTS, CONTRADICTS, CONTEXT, UNCERTAIN
    created_at = Column(DateTime, default=get_kst_now)

class EvidenceReview(Base):
    """
    증거 검토 이력(EvidenceReview) 모델
    
    사용자의 Claim 승인/수정/거절 이력을 기록한다.
    """
    __tablename__ = "evidence_reviews"

    id = Column(String, primary_key=True, default=generate_uuid)
    claim_id = Column(String, ForeignKey("evidence_claims.id", ondelete="CASCADE"), nullable=False)
    case_revision_id = Column(String, ForeignKey("case_revisions.id", ondelete="SET NULL"), nullable=True)
    
    previous_review_status = Column(String, nullable=True)
    new_review_status = Column(String, nullable=False)
    previous_statement = Column(Text, nullable=True)
    new_statement = Column(Text, nullable=True)
    
    review_reason = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, default=get_kst_now)

class GraphSyncTask(Base):
    """
    그래프 동기화 작업(GraphSyncTask) 모델
    
    PostgreSQL 데이터 변경 시 Neo4j 동기화 이벤트를 추적하고 
    실패 시 재시도하기 위한 Outbox 패턴을 구현한다.
    """
    __tablename__ = "graph_sync_tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, nullable=False, index=True)
    status = Column(String, default="PENDING", index=True)  # PENDING, PROCESSING, COMPLETED, FAILED
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=get_kst_now)
    updated_at = Column(DateTime, default=get_kst_now, onupdate=get_kst_now)

class LegalAction(Base):
    """
    법률 행동(LegalAction) 모델
    
    분석을 통해 제안된 행동 계획의 단일 항목을 나타낸다.
    """
    __tablename__ = "legal_actions"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String, nullable=False)  # NOTICE, DEMAND, LAWSUIT, REVIEW 등
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(String, default="MEDIUM")  # HIGH, MEDIUM, LOW
    status = Column(String, default="RECOMMENDED")  # RECOMMENDED, IN_PROGRESS, COMPLETED, DISCARDED, BLOCKED
    rationale = Column(Text, nullable=True)
    risk_level = Column(String, default="NONE")  # HIGH, LOW, NONE
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=get_kst_now)
    updated_at = Column(DateTime, default=get_kst_now, onupdate=get_kst_now)

    case = relationship("Case", back_populates="legal_actions")
    requirements = relationship("ActionRequirement", back_populates="action", cascade="all, delete-orphan")
    deadlines = relationship("ActionDeadline", back_populates="action", cascade="all, delete-orphan")
    dependencies_out = relationship("ActionDependency", foreign_keys="[ActionDependency.action_id]", back_populates="action", cascade="all, delete-orphan")
    dependencies_in = relationship("ActionDependency", foreign_keys="[ActionDependency.depends_on_action_id]", back_populates="depends_on_action", cascade="all, delete-orphan")


class ActionRequirement(Base):
    """
    행동 요건(ActionRequirement) 모델
    
    특정 행동을 취하기 위해 필요한 선행 조건, 사실, 증거.
    """
    __tablename__ = "action_requirements"

    id = Column(String, primary_key=True, default=generate_uuid)
    action_id = Column(String, ForeignKey("legal_actions.id", ondelete="CASCADE"), nullable=False)
    requirement_type = Column(String, nullable=False)  # FACT_CONFIRMATION, EVIDENCE_REQUIRED, LEGAL_CONDITION
    description = Column(Text, nullable=True)
    satisfaction_status = Column(String, default="UNKNOWN")  # SATISFIED, UNSATISFIED, UNKNOWN
    supporting_evidence_ids = Column(JSON, nullable=True)
    legal_source_ids = Column(JSON, nullable=True)

    action = relationship("LegalAction", back_populates="requirements")


class ActionDependency(Base):
    """
    행동 간 의존성(ActionDependency) 모델
    """
    __tablename__ = "action_dependencies"

    id = Column(String, primary_key=True, default=generate_uuid)
    action_id = Column(String, ForeignKey("legal_actions.id", ondelete="CASCADE"), nullable=False)
    depends_on_action_id = Column(String, ForeignKey("legal_actions.id", ondelete="CASCADE"), nullable=False)
    dependency_type = Column(String, default="PREREQUISITE")  # PREREQUISITE, OPTIONAL_PRECURSOR

    action = relationship("LegalAction", foreign_keys=[action_id], back_populates="dependencies_out")
    depends_on_action = relationship("LegalAction", foreign_keys=[depends_on_action_id], back_populates="dependencies_in")


class ActionDeadline(Base):
    """
    행동 기한(ActionDeadline) 모델
    """
    __tablename__ = "action_deadlines"

    id = Column(String, primary_key=True, default=generate_uuid)
    action_id = Column(String, ForeignKey("legal_actions.id", ondelete="CASCADE"), nullable=False)
    deadline_type = Column(String, default="UNKNOWN")  # LEGAL_DEADLINE, RECOMMENDED_DATE, UNKNOWN
    deadline_date = Column(DateTime, nullable=True)
    calculation_basis = Column(Text, nullable=True)
    legal_source_ids = Column(JSON, nullable=True)
    verification_status = Column(String, default="UNVERIFIED")  # VERIFIED, UNVERIFIED

    action = relationship("LegalAction", back_populates="deadlines")


class ActionRevision(Base):
    """
    행동 계획 변경 이력(ActionRevision) 모델
    """
    __tablename__ = "action_revisions"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    case_revision_id = Column(String, ForeignKey("case_revisions.id", ondelete="SET NULL"), nullable=True)
    action_plan_version = Column(Integer, nullable=False, default=1)
    change_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=get_kst_now)

    case = relationship("Case", back_populates="action_revisions")
    case_revision = relationship("CaseRevision")

class LegalDocument(Base):
    """
    법률 문서(LegalDocument) 모델
    """
    __tablename__ = "legal_documents"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    action_id = Column(String, ForeignKey("legal_actions.id", ondelete="SET NULL"), nullable=True)
    document_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    status = Column(String, default="DRAFT")  # DRAFT, PENDING_REVIEW, APPROVED, REJECTED, EXPORTED
    current_revision_id = Column(String, ForeignKey("document_revisions.id", name="fk_legal_doc_curr_rev", ondelete="SET NULL", use_alter=True), nullable=True)
    created_at = Column(DateTime, default=get_kst_now)
    updated_at = Column(DateTime, default=get_kst_now, onupdate=get_kst_now)

    case = relationship("Case", back_populates="legal_documents")
    action = relationship("LegalAction")
    revisions = relationship("DocumentRevision", back_populates="document", cascade="all, delete-orphan", foreign_keys="[DocumentRevision.document_id]")

class DocumentRevision(Base):
    """
    문서 버전(DocumentRevision) 모델
    """
    __tablename__ = "document_revisions"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_id = Column(String, ForeignKey("legal_documents.id", ondelete="CASCADE"), nullable=False)
    revision_number = Column(Integer, nullable=False)
    content = Column(Text, nullable=True)
    structured_content = Column(JSON, nullable=True)
    generation_context_version = Column(Integer, nullable=True)
    verification_status = Column(String, default="UNVERIFIED")  # UNVERIFIED, PASS, WARNING, FAIL, NEEDS_USER_CONFIRMATION
    created_at = Column(DateTime, default=get_kst_now)

    document = relationship("LegalDocument", back_populates="revisions", foreign_keys=[document_id])
    source_links = relationship("DocumentSourceLink", back_populates="revision", cascade="all, delete-orphan")
    reviews = relationship("DocumentReview", back_populates="revision", cascade="all, delete-orphan")
    exports = relationship("DocumentExport", back_populates="revision", cascade="all, delete-orphan")

class DocumentSourceLink(Base):
    """
    문서 생성 근거(DocumentSourceLink) 모델
    """
    __tablename__ = "document_source_links"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_revision_id = Column(String, ForeignKey("document_revisions.id", ondelete="CASCADE"), nullable=False)
    section_id = Column(String, nullable=True)
    source_type = Column(String, nullable=False)  # FACT, EVIDENCE, LEGAL_ISSUE
    source_id = Column(String, nullable=False)
    evidence_span_id = Column(String, nullable=True)
    verification_status = Column(String, default="UNVERIFIED")

    revision = relationship("DocumentRevision", back_populates="source_links")

class DocumentReview(Base):
    """
    문서 검토(DocumentReview) 모델
    """
    __tablename__ = "document_reviews"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_revision_id = Column(String, ForeignKey("document_revisions.id", ondelete="CASCADE"), nullable=False)
    review_status = Column(String, nullable=False)  # APPROVED, REJECTED, CHANGES_REQUESTED
    review_comment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, default=get_kst_now)

    revision = relationship("DocumentRevision", back_populates="reviews")

class DocumentExport(Base):
    """
    문서 출력(DocumentExport) 모델
    """
    __tablename__ = "document_exports"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_revision_id = Column(String, ForeignKey("document_revisions.id", ondelete="CASCADE"), nullable=False)
    file_format = Column(String, nullable=False)  # DOCX, PDF
    file_path = Column(String, nullable=False)
    checksum = Column(String, nullable=True)
    created_at = Column(DateTime, default=get_kst_now)

    revision = relationship("DocumentRevision", back_populates="exports")


class ConsultationRecord(Base):
    """
    법률 상담 기록(ConsultationRecord) 모델
    
    사건(Case) 또는 사용자(User) 단위로 진행된 법률 상담 요청 및 AI 답변 결과를 영구 저장한다.
    새로고침 또는 다른 화면 이동 후 복귀 시에도 상담 대화 이력이 유지되도록 한다.
    동일 대화 세션 내에서 다중 프로세스/스레드 간 턴 번호 중복을 방지하기 위해
    (conversation_id, turn_index) 고유 복합 제약조건을 DB 수준에서 보장한다.
    """
    __tablename__ = "consultations"
    __table_args__ = (
        UniqueConstraint("conversation_id", "turn_index", name="uq_consultations_conversation_turn"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    request_id = Column(String, unique=True, index=True, nullable=False)
    conversation_id = Column(String(100), index=True, nullable=True)
    turn_index = Column(Integer, default=1, nullable=False)
    trace_id = Column(String, nullable=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    status = Column(String, default="IN_PROGRESS")  # IN_PROGRESS, APPROVAL_REQUIRED, SUCCESS, ERROR, REJECTED
    execution_status = Column(String(50), default="IN_PROGRESS", nullable=True)  # IN_PROGRESS, APPROVAL_REQUIRED, COMPLETED, ERROR
    verification_status = Column(String(50), nullable=True)  # PASS, REVISE, INSUFFICIENT, UNVERIFIED
    answer_status = Column(String(50), default="WITHHELD", nullable=True)  # DELIVERED, WITHHELD, CAUTIONARY, REVISED
    routing_status = Column(String(50), nullable=True)  # CLASSIFIED, NEEDS_CLARIFICATION, ROUTER_ERROR
    approval_request = Column(JSON, nullable=True)
    sources = Column(JSON, nullable=True)
    verification_result = Column(JSON, nullable=True)
    # P4.2: immutable-at-application-level structured result snapshot (NULL for historical rows)
    presentation_snapshot = Column(JSON, nullable=True)
    # P4.3: consultation-start case evidence fingerprint and explicit reanalysis lineage
    case_evidence_manifest = Column(JSON, nullable=True)
    reanalysis_of_request_id = Column(String, nullable=True, index=True)
    warnings = Column(JSON, nullable=True)
    selected_agents = Column(JSON, nullable=True)
    progress = Column(JSON, nullable=True)  # LangGraph 6단계 실시간 진행 상태 (ConsultationProgress)
    elapsed_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=get_kst_now)
    updated_at = Column(DateTime, default=get_kst_now, onupdate=get_kst_now)

    case = relationship("Case", back_populates="consultations")
    user = relationship("User")


class EvidenceAssessment(Base):
    """
    증거 신뢰성 평가(EvidenceAssessment) 모델
    
    개별 증거 문서와 추출된 사실 명제 간의 7대 차원(출처진정성, 직접성, 관련성,
    완전성, 시점적합성, 상호보강성, 출처품질) 신뢰도를 평가하여 기록한다.
    """
    __tablename__ = "evidence_assessments"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = Column(String, ForeignKey("evidence_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id = Column(String, ForeignKey("evidence_claims.id", ondelete="CASCADE"), nullable=True, index=True)
    proposition_hash = Column(String, nullable=True, index=True)
    source_authenticity = Column(String, nullable=False, default="UNVERIFIED")
    directness = Column(String, nullable=False, default="INDIRECT_CIRCUMSTANTIAL")
    relevance = Column(String, nullable=False, default="DIRECTLY_RELEVANT")
    completeness = Column(String, nullable=False, default="COMPLETE")
    temporal_applicability = Column(String, nullable=False, default="CONTEMPORANEOUS")
    corroboration = Column(String, nullable=False, default="UNCORROBORATED")
    provenance_quality = Column(String, nullable=False, default="MEDIUM")
    assessment_status = Column(String, nullable=False, default="PROVISIONAL")
    reliability_score = Column(Float, nullable=False, default=0.5)
    proof_scope = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=get_kst_now)
    updated_at = Column(DateTime, default=get_kst_now, onupdate=get_kst_now)

    case = relationship("Case", back_populates="evidence_assessments")
    document = relationship("EvidenceDocument", back_populates="assessments")
    claim = relationship("EvidenceClaim", back_populates="assessments")


class FactAdjudication(Base):
    """
    사실 확정 및 심리 결과(FactAdjudication) 모델
    
    개별 사실 명제에 대한 증거 지원 여부, 타 증거와의 보강/대립 관계,
    최종 확정 상태(EVIDENCE_SUPPORTED, CORROBORATED, PARTY_ALLEGED,
    EVIDENCE_INCOMPLETE, GENUINELY_DISPUTED)를 기록한다.
    """
    __tablename__ = "fact_adjudications"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    fact_id = Column(String, ForeignKey("facts.id", ondelete="CASCADE"), nullable=True, index=True)
    claim_id = Column(String, ForeignKey("evidence_claims.id", ondelete="SET NULL"), nullable=True, index=True)
    adjudication_status = Column(String, nullable=False, default="EVIDENCE_SUPPORTED")
    primary_relation = Column(String, nullable=False, default="SUPPORTS")
    confidence = Column(Float, nullable=False, default=1.0)
    adjudication_basis = Column(Text, nullable=True)
    supporting_evidence_ids = Column(JSON, nullable=True)
    contradicting_evidence_ids = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=get_kst_now)
    updated_at = Column(DateTime, default=get_kst_now, onupdate=get_kst_now)

    case = relationship("Case", back_populates="fact_adjudications")
    fact = relationship("Fact", back_populates="adjudications")
    claim = relationship("EvidenceClaim", back_populates="adjudications")


class EvidenceGap(Base):
    """
    증거 공백 및 보완 추천(EvidenceGap) 모델
    
    사실관계의 미확인, 자료 미제출 등 필수 증거의 결함을 추적하고,
    권장되는 보완 서류와 행동 지침을 사용자에게 제공한다.
    """
    __tablename__ = "evidence_gaps"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id = Column(String, ForeignKey("evidence_claims.id", ondelete="SET NULL"), nullable=True, index=True)
    fact_id = Column(String, ForeignKey("facts.id", ondelete="SET NULL"), nullable=True, index=True)
    gap_type = Column(String, nullable=False, index=True)
    target_proposition = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    recommended_document_types = Column(JSON, nullable=True)
    recommended_action = Column(Text, nullable=True)
    priority = Column(String, nullable=False, default="MEDIUM")
    is_resolved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=get_kst_now)
    updated_at = Column(DateTime, default=get_kst_now, onupdate=get_kst_now)

    case = relationship("Case", back_populates="evidence_gaps")
    claim = relationship("EvidenceClaim", back_populates="gaps")
    fact = relationship("Fact", back_populates="gaps")


class FactComparisonAudit(Base):
    """
    사실 비교 및 상충 검증 감사 이력(FactComparisonAudit) 모델
    
    Claim과 Fact 간의 Comparability Gate 검증 결과 및
    판정 근거(차원별 일치/불일치)를 영구 감사 로그로 보관한다.
    """
    __tablename__ = "fact_comparison_audits"

    id = Column(String, primary_key=True, default=generate_uuid)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id = Column(String, ForeignKey("evidence_claims.id", ondelete="SET NULL"), nullable=True, index=True)
    fact_id = Column(String, ForeignKey("facts.id", ondelete="SET NULL"), nullable=True, index=True)
    is_comparable = Column(Boolean, nullable=False, default=False)
    comparability_reason = Column(String, nullable=True)
    relation = Column(String, nullable=True)
    audit_details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=get_kst_now)

    case = relationship("Case", back_populates="comparison_audits")

