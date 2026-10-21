"""
모듈명: consultation.py

[모듈 개요]
법률 상담 API의 요청(Request) 및 응답(Response) 데이터 스키마를 정의한다.

[주요 기능]
1. 프론트엔드와 통신하는 JSON 페이로드 구조 강제
2. 검증 결과(VerificationResult) 및 토큰 사용량 정보 포함

[주의사항]
- P2.1에서 Verification 관련 필드와 Agent별 토큰 사용량 필드가 추가됨.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class ConsultationRequest(BaseModel):
    """법률 상담 요청 스키마."""
    question: str
    case_id: Optional[str] = None
    session_id: Optional[str] = None

class Source(BaseModel):
    """법률 RAG 및 사건 증거 RAG 통합 표준 출처 응답 스키마.

    공통 필드와 유형별 필드(법령, 판례, 사건 증거, 일반 문서)를 모두 포함하며,
    실제 검색 데이터에서 확인되지 않은 필드는 None(null)으로 반환한다.
    """
    file: str = "?"
    page: Optional[str] = ""

    # 표준 공통 필드
    source_id: Optional[str] = None
    source_type: Optional[str] = None  # STATUTE | PRECEDENT | CASE_EVIDENCE | DOCUMENT
    document_id: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    retrieval_method: Optional[str] = None
    chunk_id: Optional[str] = None
    source_url: Optional[str] = None
    version_date: Optional[str] = None
    retrieved_at: Optional[str] = None

    # 법령(STATUTE) 추가 필드 (P1-02 보강)
    law_id: Optional[str] = None
    statute_name: Optional[str] = None
    article: Optional[str] = None
    promulgation_date: Optional[str] = None
    promulgation_number: Optional[str] = None
    effective_date: Optional[str] = None
    version_id: Optional[str] = None

    # 판례(PRECEDENT) 추가 필드
    court: Optional[str] = None
    case_number: Optional[str] = None
    decision_date: Optional[str] = None

    # 사건 증거(CASE_EVIDENCE) 및 일반 문서(DOCUMENT) 추가 필드
    evidence_id: Optional[str] = None
    filename: Optional[str] = None
    category: Optional[str] = None

class UsageSummary(BaseModel):
    total_calls: int
    actual_calls: int
    estimated_calls: int
    unavailable_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    agent_usage: Dict[str, int] = {}

class ConsultationResponse(BaseModel):
    request_id: str
    trace_id: str
    status: str
    # 3계층 상태 분리 (P1-05 Three-Tier Status Model)
    execution_status: Optional[str] = "COMPLETED"  # IN_PROGRESS | APPROVAL_REQUIRED | COMPLETED | ERROR
    verification_status: Optional[str] = None      # PASS | REVISE | INSUFFICIENT | UNVERIFIED
    answer_status: Optional[str] = None            # DELIVERED | WITHHELD | CAUTIONARY | REVISED
    routing_status: Optional[str] = None           # CLASSIFIED | NEEDS_CLARIFICATION | ROUTER_ERROR

    answer: Optional[str] = None
    sources: List[Source] = []
    elapsed_ms: Optional[float] = None
    usage_summary: Optional[UsageSummary] = None
    warnings: List[str] = []
    
    # New P2.1 fields
    verification_result: Optional[Dict[str, Any]] = None
    revision_count: int = 0
    selected_agents: List[str] = []
    
    # P3.3 History and Context fields
    question: Optional[str] = None
    case_id: Optional[str] = None
    created_at: Optional[str] = None

    # P4.1 HILT Statute Search Approval fields
    approval_request: Optional[Dict[str, Any]] = None


class ApprovalDecisionRequest(BaseModel):
    """법령 검색 승인/거절 결정 요청 스키마."""
    approved: bool = Field(description="승인 여부 (True: 승인 후 공식 법령 원문 검색 진행, False: 거절 후 판단 유보)")
    reason: Optional[str] = Field(default=None, description="거절 또는 승인 사유 메모")

