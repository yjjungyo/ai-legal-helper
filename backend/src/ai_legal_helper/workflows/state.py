# -*- coding: utf-8 -*-
"""
모듈명: state.py

[모듈 개요]
LangGraph 워크플로우에서 노드 간 전파되는 전역 상태(State) 스키마를 정의한다.

[주요 기능]
1. 사용자 질문, 분류 범주, 실행 계획 상태 유지
2. 병렬 에이전트들의 실행 결과 및 RAG 검색 문서 저장
3. 초안 답변 및 수석 검증관(Verification)의 검증 결과 기록
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
    
    기존 단일 흐름 파이프라인 상태에서, P2.1 Supervisor 도입에 맞춰
    검증 결과와 재검토 횟수 등을 추가로 관리하도록 확장되었다.
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
    revision_count: Annotated[int, operator.add]
    final_answer: str
    warnings: List[str]
    case_context: Optional[str]

    # P2.4: Evidence GraphRAG 결과 (PostgreSQL 대조 검증을 통과한 경로만 valid_paths 에 저장)
    # {available, valid_paths, invalid_count, evidence_gaps, contradictions}
    graph_evidence: Optional[Dict[str, Any]]
