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
    file: str
    page: str

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
