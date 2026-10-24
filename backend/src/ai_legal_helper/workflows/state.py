# -*- coding: utf-8 -*-
"""
모듈명: state.py

[모듈 개요]
LangGraph 워크플로우에서 노드 간 전파되는 전역 상태(State) 스키마를 정의한다.

[주요 기능]
1. 사용자 질문, 분류 범주, 실행 계획 상태 유지
2. 병렬 에이전트들의 실행 결과 및 RAG 검색 문서 저장
3. 초안 답변 및 법률검증 Agent(Verification)의 검증 결과 기록
4. 무한 재검토 루프 방지를 위한 revision_count 추적
5. 최종 답변 및 사용자 경고 상태 관리

[주의사항]
- P1.2 버전과의 호환성을 위해 기존 필드(categories, plan, results)를 유지한다.
- MessagesState를 상속하여 LangChain의 `messages` 이력 관리 기능을 자동 적용한다.
"""
from typing import Dict, List, Any, Optional
from langgraph.graph import MessagesState
import operator
from typing import Annotated

class LegalState(MessagesState):
    """법률 상담 LangGraph 파이프라인의 전역 상태 객체.
    
    Supervisor, 병렬 분석 에이전트, Verifier Agent, HILT 법령 원문 검색,
    그리고 최종 고객 응답 처분(final_disposition) 상태를 관리한다.
    
    Attributes:
        final_disposition: 최종 응답 처분 정책 ('DELIVERED', 'CAUTIONARY', 'WITHHELD').
            - DELIVERED: Verifier PASS 통과 완료
            - CAUTIONARY: 핵심 법리 확보 및 주의 안내/조건부 확정 (REVISE 후 finalize)
            - WITHHELD: 근거 부족 또는 중대 결함으로 확정 조언 유보 (insufficient)
    """
    # Existing fields for compatibility
    question: str
    categories: List[str]
    plan: List[str]
    results: Dict[str, str]

    # New fields for P2.1
    request_id: Optional[str]
    trace_id: Optional[str]
    selected_agents: List[str]
    analysis_plan: List[str]
    agent_results: Dict[str, str]
    retrieved_sources: List[Dict[str, Any]]
    draft_answer: str
    verification_result: Dict[str, Any]
    revision_count: int
    cited_sources: Optional[List[Dict[str, Any]]] = None
    final_answer: str
    warnings: List[str]
    case_context: Optional[str]

    # P2.4: Evidence GraphRAG 결과 (PostgreSQL 대조 검증을 통과한 경로만 valid_paths 에 저장)
    # {available, valid_paths, invalid_count, evidence_gaps, contradictions}
    graph_evidence: Optional[Dict[str, Any]]

    # P4.1: Verifier-Guided HILT 법령 원문 검색 필드
    approval_request: Optional[Dict[str, Any]]
    approval_status: Optional[str]  # NONE, PENDING, APPROVED, REJECTED, EXPIRED
    statute_search_results: Optional[List[Dict[str, Any]]]
    hilt_executed: Optional[bool]

    # Router v2.0 분류 상태 관리 필드
    router_status: Optional[str] = None
    router_reason: Optional[str] = None
    router_error_code: Optional[str] = None

    # P0 개선: 최종 고객 응답 처분 상태 ('DELIVERED', 'CAUTIONARY', 'WITHHELD')
    final_disposition: Optional[str]
    # Phase 1: Context-Aware Multi-turn Conversation Fields
    conversation_id: Optional[str] = None
    conversation_context: Optional[Dict[str, Any]] = None
    turn_index: Optional[int] = 1
    # Phase 2: Adaptive Workflow Fields
    intent: Optional[str] = None
    resolved_query: Optional[str] = None
    intent_decision: Optional[Dict[str, Any]] = None

    # Issue-Level Verification & Evidence-Grounded Consultation v1.0
    case_evidence_briefing: Optional[Dict[str, Any]] = None
    case_evidence_sources: Optional[List[Dict[str, Any]]] = None
    issue_tasks: Optional[List[Dict[str, Any]]] = None
    issue_results: Optional[List[Dict[str, Any]]] = None

