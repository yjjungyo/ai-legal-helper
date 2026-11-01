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
from enum import Enum


class ConsultationStepStatus(str, Enum):
    """상담 단계별 세부 실행 상태 열거형 (P0-05)."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    FAILED = "FAILED"


class ConsultationStep(BaseModel):
    """상담 진행 단계 세부 정보 모델 (P0-05)."""
    step_id: str = Field(description="단계 식별자 (예: 'step_1' ~ 'step_6')")
    title: str = Field(description="단계 표제어 (예: '사건 정보와 이전 상담 맥락 확인')")
    status: ConsultationStepStatus = Field(default=ConsultationStepStatus.PENDING, description="진행 상태")
    started_at: Optional[str] = Field(default=None, description="시작 시각 (ISO)")
    completed_at: Optional[str] = Field(default=None, description="종료 시각 (ISO)")
    message: Optional[str] = Field(default=None, description="진행 상태 추가 안내 문구")


class ConsultationProgress(BaseModel):
    """상담 전체 6단계 진행 상태 모델 (P0-05)."""
    request_id: str = Field(description="상담 요청 식별자")
    current_step: Optional[str] = Field(default=None, description="현재 활성 단계 ID")
    steps: List[ConsultationStep] = Field(default_factory=list, description="6대 진행 단계 목록")
    updated_at: str = Field(description="마지막 갱신 시각 (ISO)")


def create_initial_progress(request_id: str, updated_at: str) -> ConsultationProgress:
    """초기 6단계 진행 상태 객체를 생성한다.

    Args:
        request_id: 대상 상담 요청 식별자.
        updated_at: 생성 시점의 KST ISO 일시 문자열.

    Returns:
        ConsultationProgress: step_1이 RUNNING 상태로 초기화된 6단계 진행 상태.
    """
    return ConsultationProgress(
        request_id=request_id,
        current_step="step_1",
        steps=[
            ConsultationStep(step_id="step_1", title="사건 정보와 이전 상담 맥락 확인", status=ConsultationStepStatus.RUNNING, started_at=updated_at),
            ConsultationStep(step_id="step_2", title="사실관계·타임라인·증거 조회", status=ConsultationStepStatus.PENDING),
            ConsultationStep(step_id="step_3", title="관련 법령 및 판례 검색", status=ConsultationStepStatus.PENDING),
            ConsultationStep(step_id="step_4", title="법률 쟁점별 분석", status=ConsultationStepStatus.PENDING),
            ConsultationStep(step_id="step_5", title="증거·법률 근거 검증", status=ConsultationStepStatus.PENDING),
            ConsultationStep(step_id="step_6", title="최종 상담 답변 작성", status=ConsultationStepStatus.PENDING),
        ],
        updated_at=updated_at,
    )


class ConsultationRequest(BaseModel):
    """법률 상담 요청 스키마."""
    question: str
    case_id: Optional[str] = None
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None  # 연속된 대화 식별자 (미전달 시 서버가 신규 생성)

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
    article_title: Optional[str] = None
    paragraph_no: Optional[str] = None
    part: Optional[str] = None
    chapter: Optional[str] = None
    section: Optional[str] = None
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
    evidence_label: Optional[str] = None
    label: Optional[str] = None
    filename: Optional[str] = None
    original_filename: Optional[str] = None
    document_name: Optional[str] = None
    file_name: Optional[str] = None
    paragraph_index: Optional[int] = None
    category: Optional[str] = None

    # 원자적 증거 접지(Grounding) 필드 (P0-2)
    claim_id: Optional[str] = None
    span_id: Optional[str] = None
    text_excerpt: Optional[str] = None

class ClaimReference(BaseModel):
    """주장에 대응하는 구체적 증거 문서, 추출 클레임 및 텍스트 발췌 참조 모델 (P0-2)."""
    evidence_id: str = Field(description="증거 문서 UUID")
    evidence_label: Optional[str] = Field(default=None, description="증거 표시 라벨 (예: 'E01')")
    claim_id: Optional[str] = Field(default=None, description="추출 주장 UUID")
    span_id: Optional[str] = Field(default=None, description="원문 발췌 위치 UUID")
    text_excerpt: Optional[str] = Field(default=None, description="원문 발췌 인용문")
    document_name: Optional[str] = Field(default=None, description="증거 원본 파일명")


class ClaimCitation(BaseModel):
    """답변 내 개별 명제/권고와 실제 증거 및 법률 출처 간의 원자적 접지(Grounding) 매핑 모델 (P0-2)."""
    citation_tag: str = Field(description="증거 인용 태그 (예: '[E01]', '[E01], [E03]')")
    claim_text: str = Field(description="인용된 사실 진술문 또는 법률 판단 문장")
    grounding_status: str = Field(default="SUPPORTED", description="근거 검증 상태 ('SUPPORTED', 'CONDITIONALLY_SUPPORTED', 'UNGROUNDED')")
    evidence_refs: List[ClaimReference] = Field(default_factory=list, description="연결된 증거 원문 발췌 목록")
    legal_refs: List[Dict[str, Any]] = Field(default_factory=list, description="연결된 법령 및 판례 조문 정보")
    explanation: Optional[str] = Field(default=None, description="접지 상세 설명 또는 전제 조건")

class UsageSummary(BaseModel):
    total_calls: int
    actual_calls: int
    estimated_calls: int
    unavailable_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    agent_usage: Dict[str, int] = {}

class PresentationBlock(BaseModel):
    """최종 답변 원문의 연속 구간. markdown은 검증된 answer의 정확한 부분 문자열이다."""
    block_id: str
    kind: str  # LEAD | SECTION | BODY
    start: int
    end: int
    markdown: str
    title: Optional[str] = None
    claim_refs: List[str] = Field(default_factory=list)
    source_refs: List[str] = Field(default_factory=list)


class PresentationClaim(BaseModel):
    """검증된 주장 중 답변에서 정확히 한 위치에 고정된 주장만 포함한다."""
    claim_id: str
    text: str
    start: int
    end: int
    claim_type: Optional[str] = None
    fact_status: Optional[str] = None
    grounding_status: str = "SUPPORTED"
    semantic_type: str = "OTHER"
    source_binding: str = "NOT_LINKED"
    source_refs: List[str] = Field(default_factory=list)


class PresentationSource(BaseModel):
    """원문 레지스트리에 존재하는 자료만 식별자로 표현하며 출처 내용을 재생성하지 않는다."""
    source_id: str
    source_type: Optional[str] = None
    display_name: str
    evidence_id: Optional[str] = None
    claim_id: Optional[str] = None
    span_id: Optional[str] = None
    document_name: Optional[str] = None
    statute_name: Optional[str] = None
    article: Optional[str] = None
    source_url: Optional[str] = None


class ConsultationPresentation(BaseModel):
    schema_version: str = "1.0"
    source_answer_sha256: str
    verification_binding: str  # HASH_MATCHED | STATUS_MATCHED
    direct_answer_block_id: Optional[str] = None
    blocks: List[PresentationBlock] = Field(default_factory=list)
    claims: List[PresentationClaim] = Field(default_factory=list)
    sources: List[PresentationSource] = Field(default_factory=list)


class ConsultationResponse(BaseModel):
    request_id: str
    conversation_id: Optional[str] = None  # 연속된 대화 식별자
    turn_index: Optional[int] = 1          # 대화 내 턴 순서 (1부터 시작)
    trace_id: str
    status: str
    # 3계층 상태 분리 (P1-05 Three-Tier Status Model)
    execution_status: Optional[str] = "COMPLETED"  # IN_PROGRESS | APPROVAL_REQUIRED | COMPLETED | ERROR
    verification_status: Optional[str] = None      # PASS | REVISE | INSUFFICIENT | UNVERIFIED
    answer_status: Optional[str] = None            # DELIVERED | WITHHELD | CAUTIONARY | REVISED
    routing_status: Optional[str] = None           # CLASSIFIED | NEEDS_CLARIFICATION | ROUTER_ERROR
    # Phase 2 Adaptive Workflow fields
    intent: Optional[str] = None                   # FOLLOWUP_ACTION, FOLLOWUP_QUESTION, NEW_LEGAL_ANALYSIS 등
    resolved_query: Optional[str] = None           # 대화 문맥이 결합되어 복원된 내부 검색 질의

    answer: Optional[str] = None
    # 검증 완료 답변의 손실 없는 화면용 구조. 기존 answer/sources는 하위 호환 유지.
    presentation: Optional[ConsultationPresentation] = None
    # 내부 보관: 기존 API 계약을 바꾸지 않도록 snapshot 전체는 응답 직렬화에서 제외
    presentation_snapshot: Optional[Dict[str, Any]] = Field(default=None, exclude=True)
    presentation_origin: Optional[str] = None  # FROZEN | LEGACY_REBUILT | INVALID_SNAPSHOT | UNAVAILABLE
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

    # Issue-Level Verification & Evidence Grounding fields (Section 15.2 & P0-2)
    issue_results: Optional[List[Dict[str, Any]]] = None
    verified_facts: Optional[List[Dict[str, Any]]] = None
    missing_evidence: Optional[List[Dict[str, Any]]] = None
    evidence_citations: Optional[List[Dict[str, Any]]] = None
    claim_citations: List[ClaimCitation] = Field(default_factory=list, description="답변 문장별 원자적 증거·법령 접지 인용 목록 (P0-2)")

    # P0-3 Multi-turn Case Delta & Determination Comparison
    case_delta: Optional[Dict[str, Any]] = Field(default=None, description="사건 사실·증거 변동 및 법률 판단 변경 비교 (P0-3)")

    # Case-Centric Chat UI v1.1 Progress field (P0-05)
    progress: Optional[ConsultationProgress] = None


class ApprovalDecisionRequest(BaseModel):
    """법령 검색 승인/거절 결정 요청 스키마."""
    approved: bool = Field(description="승인 여부 (True: 승인 후 공식 법령 원문 검색 진행, False: 거절 후 판단 유보)")
    reason: Optional[str] = Field(default=None, description="거절 또는 승인 사유 메모")



class ConversationSummary(BaseModel):
    """사건 내 개별 대화 세션의 요약 정보 스키마."""
    conversation_id: str
    case_id: Optional[str] = None
    first_question: str
    last_question: str
    last_answer: Optional[str] = None
    turns_count: int
    last_status: str
    last_answer_status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConversationDetail(BaseModel):
    """특정 대화 세션의 전체 질의응답 이력 스키마."""
    conversation_id: str
    case_id: Optional[str] = None
    turns: List[ConsultationResponse] = []
