# -*- coding: utf-8 -*-
"""
모듈명: legal_workflow.py

[모듈 개요]
법률 상담 과정에서 여러 전문 Agent의 실행을 관리하는 Supervisor 워크플로우를 정의한다.

[주요 기능]
1. 사용자 질문 라우팅 및 계획 수립
2. 전문 Agent 병렬 실행
3. 종합 답변(Synthesize) 생성
4. 법률검증 Agent(Verification)를 통한 Grounding 체크
5. 검증 결과에 따른 재검토 및 최종 상태(PASS/REVISE/INSUFFICIENT) 결정

[처리 흐름]
등록 문서가 있는 사건: 원문 준비 → 법률 자료 검색 → 단일 답변 작성 → 질문·원문 검증
  → 누락 법령 승인 검색 또는 최대 두 번 재작성 → 통과한 동일 답변 확정 / 판단 유보

등록 문서가 없는 일반 상담:
사용자 질문
  → Supervisor Initialize
  → Route (분야 판별)
  → Plan (도구/계획 수립)
  → Run Agents (전문 에이전트 실행)
  → Synthesize (초안 작성)
  → Verification (근거 대조 검증)
  → [PASS] Finalize
  → [REVISE] Revise (재검토 1회 제한)
  → [INSUFFICIENT] Insufficient (근거 부족 알림)
  → 최종 응답

[주요 의존성]
- LangGraph: 상태 머신 관리
- LangChain: 메시지 및 LLM 통신
- ai_legal_helper.agents.verification: 검증 담당 에이전트
- ai_legal_helper.observability: Trace Context 및 로깅

[주의사항]
- 문서 상담 재작성은 공식 검색 후 재분석을 포함해 총 두 번, 기존 일반 상담은 한 번으로 제한한다.
- 비동기 `run_agents_node` 호출 시 ContextVar의 복제 동작을 위해 파이썬 내장 `asyncio.to_thread`를 사용한다.
"""
from typing import Dict, List, Any, Optional
from ai_legal_helper.agents.intent_analyzer import analyze_consultation_intent, ConsultationIntent
import os
import uuid
import sys
import asyncio
import re
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, AIMessage
from ai_legal_helper.case_intelligence.consultation_semantics import is_evidence_review_request
from langgraph.types import interrupt, Command, Send
from langgraph.checkpoint.memory import MemorySaver
try:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
except ImportError:
    AsyncPostgresSaver = None  # type: ignore
import operator
from typing import Annotated

from ai_legal_helper.workflows.state import LegalState
from ai_legal_helper.workflows.document_consultation import (
    DOCUMENT_MODE, generate_answer, verify_answer, next_verification_step, finish_answer,
)
from ai_legal_helper.agents.router import route_categories
from ai_legal_helper.agents.planner import plan_tools
from ai_legal_helper.agents.specialist import run_specialist_agent
from ai_legal_helper.agents.synthesizer import synthesize
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.observability.context import set_node_name

logger = get_logger(__name__)

_memory_checkpointer_instance = None


def get_postgres_conn_string() -> str:
    """PostgreSQL 비동기 접속을 위한 표준 연결 문자열을 반환한다."""
    from ai_legal_helper.database.session import SQLALCHEMY_DATABASE_URL
    url = SQLALCHEMY_DATABASE_URL
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


async def init_checkpointer():
    """애플리케이션 시작 시 PostgreSQL 체크포인트 테이블을 자동 초기화(setup)한다."""
    checkpointer_type = os.getenv("CHECKPOINTER_TYPE", "postgres").lower()
    if checkpointer_type == "memory":
        logger.info("[체크포인터] 메모리 기반 체크포인터(MemorySaver) 사용 (초기화 생략)")
        return

    conn_string = get_postgres_conn_string()
    try:
        async with AsyncPostgresSaver.from_conn_string(conn_string) as saver:
            await saver.setup()
        logger.info("[체크포인터] PostgreSQL 체크포인트 테이블 초기화 완료")
    except Exception as e:
        logger.error(f"[체크포인터] PostgreSQL 체크포인터 초기화 실패: {e}")
        raise


def get_memory_checkpointer() -> MemorySaver:
    """테스트 또는 격리 환경을 위한 메모리 기반 체크포인터 싱글톤 인스턴스를 반환한다."""
    global _memory_checkpointer_instance
    if _memory_checkpointer_instance is None:
        _memory_checkpointer_instance = MemorySaver()
    return _memory_checkpointer_instance


def get_checkpointer():
    """LangGraph 체크포인터를 획득한다.

    기본값은 PostgreSQL 기반 영속 체크포인터(AsyncPostgresSaver)를 사용하며,
    동기 그래프 컴파일 시에는 기본 메모리 인스턴스를 제공하고,
    비동기 런타임(run_legal_consultation)에서 AsyncPostgresSaver를 주입한다.

    Returns:
        BaseCheckpointSaver: 체크포인터 인스턴스.
    """
    checkpointer_type = os.getenv("CHECKPOINTER_TYPE", "postgres").lower()
    if checkpointer_type == "memory":
        return get_memory_checkpointer()
    return get_memory_checkpointer()


def _brief_history(messages: List[Any], max_chars: int = 1000) -> str:
    if not messages:
        return "(이전 대화 없음)"
    parts = []
    for m in messages[:-1][-5:]:
        role = "사용자" if isinstance(m, HumanMessage) else "도우미"
        text = m.content if isinstance(m.content, str) else str(m.content)
        text = text.replace("\n", " ")
        if len(text) > 160:
            text = text[:160] + f"...(+{len(text)-160})"
        parts.append(f"{role}: {text}")
    s = " / ".join(parts)
    return s[:max_chars] + ("... (trunc)" if len(s) > max_chars else "")

@trace
def supervisor_initialize_node(state: LegalState) -> Dict:
    """현재 사건 브리핑을 읽고 문서 원문 유무에 따라 답변 경로를 초기화한다.

    Args:
        state: 현재 사용자 메시지와 대화·사건 식별 상태.

    Returns:
        원본 질문, 현재 사건의 원문 브리핑, 답변 모드 및 초기 검증·검색 상태.
    """
    set_node_name("supervisor_initialize")
    q = None
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            q = m.content if isinstance(m.content, str) else str(m.content)
            break
    
    from ai_legal_helper.observability.context import get_request_id, get_trace_id, get_case_id
    from ai_legal_helper.database.session import SessionLocal
    from ai_legal_helper.database.models import Case, Fact, Event, EvidenceDocument, EvidenceClaim

    req_id = get_request_id() or "unknown_req"
    trace_id = get_trace_id() or "unknown_trace"
    
    conv_id = state.get("conversation_id")
    conv_ctx = state.get("conversation_context")
    turn_idx = state.get("turn_index") or 1

    # 사건 ID 복원: 컨텍스트 변수, 상태, 또는 대화 맥락 객체/딕셔너리에서 순차 탐색
    case_id = (
        get_case_id()
        or state.get("case_id")
        or (conv_ctx.get("case_id") if isinstance(conv_ctx, dict) else getattr(conv_ctx, "case_id", None))
    )
    if case_id:
        from ai_legal_helper.observability.context import set_case_id
        set_case_id(case_id)

    case_context = ""
    # 사건이 지정되지 않은 일반 상담에서는 GraphRAG 를 사용하지 않는다.
    graph_evidence: Dict[str, Any] = {
        "available": False,
        "search_mode": "NONE",
        "valid_paths": [],
        "structured_matches": [],
        "sources": [],
        "invalid_count": 0,
        "evidence_gaps": [],
        "contradictions": [],
    }
    briefing_dict = None
    case_evidence_sources = []
    issue_tasks_dict = []

    if case_id:
        db = SessionLocal()
        try:
            case = db.query(Case).filter(Case.id == case_id).first()
            if case:
                from ai_legal_helper.case_intelligence.case_briefing import build_case_evidence_briefing
                from ai_legal_helper.workflows.issue_planner import plan_legal_issues

                briefing_obj = build_case_evidence_briefing(db, case_id, q or "")
                issue_tasks_obj = plan_legal_issues(q or "", briefing_obj)

                briefing_dict = briefing_obj.model_dump()
                issue_tasks_dict = [t.model_dump() for t in issue_tasks_obj]
                case_evidence_sources = list(briefing_obj.source_registry.values())

                # 정규화된 사건 증거 브리핑 텍스트를 case_context 기본값으로 사용
                case_context = briefing_obj.formatted_summary
                
                # [Structured Evidence GraphRAG v2.0 통합]
                # PostgreSQL 구조화 증거 검색 + Neo4j 그래프 관계 탐색 → PostgreSQL 대조 검증 → 컨텍스트 추가.
                # Neo4j 장애/미구성 시에도 PostgreSQL 기반 사건 증거 검색 결과를 그대로 활용한다.
                graph_evidence = _collect_graph_evidence(db, case_id, q or "")
                graph_text = graph_evidence.pop("context_text", "")
                if graph_text:
                    case_context += "\n\n" + graph_text
                    
        except Exception as e:
            logger.warning(f"[INIT] 사건 증거 브리핑 구축 중 예외: {e}")
        finally:
            db.close()
            
    # 대화 맥락이 존재하는 경우 case_context 전두부에 대화 이력 요약 결합
    if conv_ctx:
        try:
            from ai_legal_helper.workflows.conversation_context import ConversationContext
            c_obj = ConversationContext(**conv_ctx) if isinstance(conv_ctx, dict) else conv_ctx
            conv_summary_text = c_obj.format_context_for_prompt(max_turns=3)
            if conv_summary_text and "(이전 상담 대화 없음" not in conv_summary_text:
                case_context = f"{conv_summary_text}\n\n{case_context}" if case_context else conv_summary_text
        except Exception as e:
            logger.warning(f"[INIT] 대화 맥락 포맷팅 중 예외: {e}")

    return {
        "request_id": req_id,
        "trace_id": trace_id,
        "conversation_id": conv_id,
        "conversation_context": conv_ctx,
        "turn_index": turn_idx,
        "question": q or "(질문 미확인)",
        # 등록 문서가 있는 사건은 파생 Fact 기반 다중 작성 대신 원문 작성 경로로 보낸다.
        "answer_mode": DOCUMENT_MODE if briefing_dict and briefing_dict.get("source_documents") else None,
        "answer_generation_error": None,
        "answer_source_manifest": None,
        "revision_count": 0,
        "warnings": [],
        "retrieved_sources": [],
        "case_context": case_context,
        "graph_evidence": graph_evidence,
        "case_evidence_briefing": briefing_dict,
        "case_evidence_sources": case_evidence_sources,
        "issue_tasks": issue_tasks_dict,
        "issue_results": [],
        "approval_request": None,
        "approval_status": "NONE",
        "approved_statute_laws": [],
        "statute_search_results": [],
        "statute_search_count": 0,
        "statute_search_history": [],
        "hilt_executed": False,
        "preserved_points": [],
    }


def _collect_graph_evidence(db, case_id: str, question: str) -> Dict[str, Any]:
    """PostgreSQL 구조화 증거 검색 + Neo4j 사건 그래프 탐색을 수행하고 코드 레벨로 검증한다.

    Args:
        db: SQLAlchemy 세션(PostgreSQL 증거 검색 및 그래프 경로 검증용).
        case_id: 사건 ID.
        question: 사용자 질문 또는 resolved_query(키워드 및 엔티티 추출 대상).

    Returns:
        {available, search_mode, valid_paths, structured_matches, sources,
         invalid_count, evidence_gaps, contradictions, context_text}
        context_text 는 호출자가 꺼내 쓴 뒤 state 에서는 제거한다(중복 저장 방지).

    Notes:
        어떤 예외도 전파하지 않는다. GraphRAG 는 보조 근거이므로 실패해도 상담은 계속된다.
    """
    empty = {
        "available": False,
        "search_mode": "NONE",
        "valid_paths": [],
        "structured_matches": [],
        "sources": [],
        "invalid_count": 0,
        "evidence_gaps": [],
        "contradictions": [],
        "context_text": "",
    }
    try:
        from ai_legal_helper.database.neo4j import get_neo4j_driver
        from ai_legal_helper.rag.graph_rag import (
            GraphRAGRetriever,
            validate_graph_paths,
            format_graph_context,
            graph_paths_to_sources,
            evidence_hits_to_sources,
            filter_verified_graph_contradictions,
        )
        driver = get_neo4j_driver()
        # Neo4j 드라이버가 None이더라도 search_hybrid 내부에서 PostgreSQL 구조화 증거 폴백을 수행한다.
        result = GraphRAGRetriever(driver).search_hybrid(case_id, question, db=db)
        # 검색 인덱스나 과거 그래프의 CONTRADICTS 관계를 법률 상담 근거로 그대로 사용하지 않는다.
        result["contradictions"] = filter_verified_graph_contradictions(
            db, case_id, result.get("contradictions", []),
        )
        checked = (
            validate_graph_paths(db, case_id, result.get("traversal_paths", []))
            if result.get("traversal_paths")
            else {"valid": [], "invalid": [], "checked": 0}
        )
        if checked["invalid"]:
            # 원문 대신 ID/사유만 기록 (개인정보 보호)
            logger.warning(f"[GRAPH_RAG] 검증 실패 경로 {len(checked['invalid'])}건 제외")

        structured_matches = result.get("structured_matches", [])
        ev_sources: List[Dict[str, Any]] = []
        seen_src_ids = set()
        for s in graph_paths_to_sources(checked["valid"]) + evidence_hits_to_sources(structured_matches):
            sid = s.get("source_id")
            if sid and sid not in seen_src_ids:
                seen_src_ids.add(sid)
                ev_sources.append(s)

        return {
            "available": result.get("available", False),
            "search_mode": result.get("search_mode", "POSTGRESQL_ONLY"),
            "valid_paths": checked["valid"],
            "structured_matches": structured_matches,
            "sources": ev_sources,
            "invalid_count": len(checked["invalid"]),
            "evidence_gaps": result.get("evidence_gaps", []),
            "contradictions": result.get("contradictions", []),
            "context_text": format_graph_context(result, checked["valid"]),
        }
    except Exception as e:
        logger.error(f"GraphRAG 검색 실패: {type(e).__name__}")
        return empty

@trace
def route_node(state: LegalState) -> Dict:
    """Router v2.0: 사용자 질문과 사건 맥락을 바탕으로 Specialist 분야를 선정하고 상태를 기록한다."""
    set_node_name("route")
    from ai_legal_helper.agents.router import route_categories_detailed

    q = state.get("resolved_query") or state.get("question", "(질문 미확인)")
    # 원문 작성 경로에서 분류는 검색 분야 선택 용도다. 이전 AI 판단을 분류 근거로 전달하지 않는다.
    case_ctx = ((state.get("case_evidence_briefing") or {}).get("case_type") or "") if state.get("answer_mode") == DOCUMENT_MODE else (state.get("case_context") or "")
    decision = route_categories_detailed(question=q, case_context=case_ctx)

    logger.debug(
        f"[분야 판별 결과] 상태={decision.status.value}, 선정 분야={decision.categories}, 사유={decision.reason}"
    )
    return {
        "categories": decision.categories,
        "selected_agents": decision.categories,
        "router_status": decision.status.value,
        "router_reason": decision.reason,
        "router_error_code": decision.error_code,
    }


def route_condition(state: LegalState) -> str:
    """Router 분류 상태에 따라 LangGraph 실행 경로를 분기한다.

    - CLASSIFIED: 정상 분류되었으므로 전문 에이전트 계획 수립('plan')으로 전이.
    - NEEDS_CLARIFICATION: 정보 부족으로 판단 보류 안내 노드('routing_exit')로 전이.
    - ROUTER_ERROR: 기술적 오류로 시스템 오류 안내 노드('routing_exit')로 전이.
    """
    from ai_legal_helper.agents.router import RouterStatus
    # 문서 질문의 답변 가능 여부는 분야 분류가 아니라 원문 작성 후 검증에서 결정한다.
    if state.get("answer_mode") == DOCUMENT_MODE:
        return "plan"
    status = state.get("router_status")
    if status == RouterStatus.CLASSIFIED.value or (not status and state.get("categories")):
        return "plan"
    return "routing_exit"


@trace
def routing_exit_node(state: LegalState) -> Dict:
    """Router에서 정보 부족(NEEDS_CLARIFICATION) 또는 오류(ROUTER_ERROR)로 종료할 때
    고객용 최종 안내 메시지를 생성하고 파이프라인을 안전하게 종료한다.

    [원칙]
    1. 전문 분석 Agent, Synthesizer, Verifier를 일체 실행하지 않는다.
    2. Verifier를 실행하지 않았으므로 verification_result를 생성하거나 PASS로 설정하지 않는다.
    3. 출처(sources, cited_sources)는 빈 배열로 반환한다.
    4. final_disposition은 'WITHHELD'로 설정한다.
    """
    set_node_name("routing_exit")
    from ai_legal_helper.agents.router import RouterStatus

    r_status = state.get("router_status") or RouterStatus.NEEDS_CLARIFICATION.value

    if r_status == RouterStatus.ROUTER_ERROR.value:
        final_answer = (
            "[안내: 일시적 시스템 오류]\n\n"
            "법률 분야를 확인하는 과정에서 일시적인 문제가 발생했습니다. 잠시 후 다시 시도해 주세요."
        )
        warnings = ["법률 분야 분류 중 시스템 오류가 발생했습니다."]
    else:  # NEEDS_CLARIFICATION
        clarification_msg = (
            "입력해주신 질문과 사건 맥락만으로는 구체적인 법률 분야를 판단하기 어렵습니다.\n\n"
            "정확하고 신뢰할 수 있는 법률 상담을 위해 다음 사항을 조금 더 자세히 알려주세요:\n"
            "1. 구체적으로 어떤 사건이나 분쟁이 발생했는지\n"
            "2. 상대방과 어떤 관계(임대인-임차인, 고용주-근로자, 개인 간 금전 거래 등)인지\n"
            "3. 법률적으로 어떤 해결이나 조치(손해배상 청구, 고소, 계약 해지, 대금 반환 등)를 원하시는지"
        )
        final_answer = f"[안내: 추가 정보 필요]\n\n{clarification_msg}"
        warnings = []

    return {
        "final_answer": final_answer,
        "answer": final_answer,
        "final_disposition": "WITHHELD",
        "verification_status": "UNVERIFIED",
        "verification_result": {},
        "categories": [],
        "selected_agents": [],
        "sources": [],
        "cited_sources": [],
        "retrieved_sources": [],
        "warnings": warnings,
        "messages": [AIMessage(content=final_answer)],
    }

@trace
def plan_node(state: LegalState) -> Dict:
    set_node_name("plan")
    cats = state.get("categories", [])
    plan = plan_tools(cats)
    logger.debug(f"[쟁점 계획 결과] 선정 도구={plan}")
    return {"plan": plan, "analysis_plan": plan}

@trace
async def run_agents_node(state: LegalState) -> Dict:
    """문서 사건은 법률 자료만 검색하고, 일반 상담은 기존 전문 에이전트를 실행한다.

    Args:
        state: 현재 질문, 사건 원문 및 검색할 법률 분야.

    Returns:
        검색 출처와 실행 결과. 문서 사건에서는 전문 에이전트 답변을 생성하지 않는다.
    """
    set_node_name("run_agents")
    if state.get("answer_mode") == DOCUMENT_MODE:
        from ai_legal_helper.rag.retrieval import retrieve_with_status
        from ai_legal_helper.rag.source_schema import build_source_from_chroma_doc

        sources = []
        retrieval_warnings = []
        for category in (state.get("categories") or [None])[:2]:
            try:
                retrieved = await asyncio.to_thread(
                    retrieve_with_status, query=state.get("question", ""), category=category, k=6,
                )
                sources.extend(build_source_from_chroma_doc(
                    doc, category=category, retrieval_method="CHROMA_VECTOR",
                ) for doc in retrieved.documents)
                if retrieved.error_detail:
                    retrieval_warnings.append("관련 법률 자료 검색 일부를 완료하지 못했습니다.")
            except Exception as exc:
                logger.warning("문서 상담 법률 검색 실패: %s", type(exc).__name__)
                retrieval_warnings.append("관련 법률 자료 검색을 완료하지 못했습니다.")
        return {"results": {}, "agent_results": {}, "retrieved_sources": sources,
                "warnings": list(dict.fromkeys((state.get("warnings") or []) + retrieval_warnings))}
    cats = state.get("categories", [])
    q = state.get("resolved_query") or state.get("question", "")
    brief = _brief_history(state.get("messages", []))
    
    case_ctx = state.get("case_context")
    if case_ctx:
        brief = f"{case_ctx}\n\n[이전 대화 요약]\n{brief}"

    results: Dict[str, str] = {}
    all_sources: list[dict] = []
    
    if not cats:
        return {"results": results, "agent_results": results, "retrieved_sources": all_sources}

    async def _run_agent_with_ctx(c: str) -> tuple[str, str, list]:
        return await asyncio.to_thread(run_specialist_agent, c, q, brief)

    # [P0-05/Gate 3] 전문 에이전트 다중 호출 병목 최적화: 핵심 최대 2개 전문 에이전트로 집중
    selected_cats = cats[:2] if len(cats) > 2 else cats
    tasks = [_run_agent_with_ctx(c) for c in selected_cats]
    responses = await asyncio.gather(*tasks)
    
    for cat, text, sources in responses:
        results[cat] = text
        all_sources.extend(sources)

    logger.debug(f"[전문 에이전트 분석 완료] 분석 완료 분야={list(results.keys())}")
    return {"results": results, "agent_results": results, "retrieved_sources": all_sources}

@trace
def synthesize_node(state: LegalState) -> Dict:
    """문서 원문 또는 기존 전문 분석으로 초안을 작성한다.

    Args:
        state: 질문, 원문 출처 또는 기존 전문 분석 결과.

    Returns:
        사용자 이력에 아직 추가하지 않은 초안과 원문 작성 명세.
    """
    set_node_name("synthesize")
    if state.get("answer_mode") == DOCUMENT_MODE:
        return generate_answer(state)
    intent_val = state.get("intent")
    msgs = synthesize(
        state.get("messages", []),
        state.get("results", {}),
        intent=intent_val,
        case_evidence_briefing=state.get("case_evidence_briefing"),
        issue_tasks=state.get("issue_tasks"),
        source_registry={s.get("evidence_label", s.get("source_id")): s for s in (state.get("case_evidence_sources") or []) if s},
    )
    draft = msgs[-1].content
    # don't append to messages yet, just save to draft_answer
    return {"draft_answer": draft}

@trace
def verification_node(state: LegalState) -> Dict:
    """초안 답변을 법령 출처 + 검증된 증거 그래프 경로와 대조하여 검증한다.

    [P2.4 확장]
    1. 법령 RAG 출처(retrieved_sources)에 그래프 근거(GRAPH:*)를 합쳐 LLM 검증에 제공한다.
    2. 그래프 근거를 PostgreSQL 과 다시 대조한다(코드 레벨 검증). 상담 도중 증거가
       반려·삭제되었을 수 있기 때문이다. 결과는 verification_result.graph_checks 에 기록한다.
    3. 무효 근거가 발견되면 경고를 추가하고, PASS 였더라도 REVISE 로 강등하여
       해당 근거 의존 문장을 제거하도록 지시한다.
    4. 증거 공백/상충은 상태를 바꾸지 않고 사용자 경고로만 노출한다
       (증거 부족은 법령 답변의 오류가 아니라 사건 정보의 한계이기 때문).
    """
    set_node_name("verification")
    if state.get("answer_mode") == DOCUMENT_MODE:
        return verify_answer(state)
    from ai_legal_helper.agents.verification import run_verification
    from ai_legal_helper.rag.graph_rag import (
        graph_paths_to_sources,
        evidence_hits_to_sources,
        validate_graph_paths,
    )
    from ai_legal_helper.observability.context import get_case_id

    q = state.get("question", "")
    draft = state.get("draft_answer", "")
    sources = list(state.get("retrieved_sources", []))
    graph_ev = state.get("graph_evidence") or {}
    graph_paths = graph_ev.get("valid_paths", [])
    structured_matches = graph_ev.get("structured_matches", [])

    graph_checks = {"available": bool(graph_ev.get("available")), "checked": 0,
                    "valid": 0, "invalid": []}
    case_id = get_case_id()
    if graph_paths and case_id:
        from ai_legal_helper.database.session import SessionLocal
        db = SessionLocal()
        try:
            rechecked = validate_graph_paths(db, case_id, graph_paths)
        except Exception as e:
            logger.warning(f"[VERIFICATION] 그래프 근거 재검증 실패: {type(e).__name__}")
            rechecked = {"valid": [], "invalid": [], "checked": 0}
        finally:
            db.close()
        graph_paths = rechecked["valid"]
        graph_checks.update(checked=rechecked["checked"], valid=len(rechecked["valid"]),
                            invalid=[{"claim_id": i["path"].get("claim_id"), "reasons": i["reasons"]}
                                     for i in rechecked["invalid"]])

    extra_sources = list(graph_paths_to_sources(graph_paths))
    if structured_matches:
        extra_sources.extend(evidence_hits_to_sources(structured_matches[:10]))

    existing_source_ids = {s.get("source_id") for s in sources if s.get("source_id")}
    dedup_extra_sources = []
    for es in extra_sources:
        sid = es.get("source_id")
        if sid and sid not in existing_source_ids:
            existing_source_ids.add(sid)
            dedup_extra_sources.append(es)

    combined_sources = sources + dedup_extra_sources
    result = run_verification(q, draft, combined_sources,
                              state.get("case_context", ""))

    warnings = list(result.get("warnings", []))
    if graph_checks["invalid"]:
        warnings.append(f"사건 증거 {len(graph_checks['invalid'])}건이 더 이상 유효하지 않아 근거에서 제외되었습니다.")
        if result.get("status") == "PASS":
            result["status"] = "REVISE"
            result.setdefault("revision_instructions", []).append(
                "더 이상 유효하지 않은 사건 증거(반려/삭제)에 의존한 문장을 제거하세요.")
    if graph_ev.get("evidence_gaps"):
        warnings.append(f"승인된 증거가 연결되지 않은 사실/쟁점이 {len(graph_ev['evidence_gaps'])}건 있습니다.")
    if graph_ev.get("contradictions"):
        from ai_legal_helper.rag.graph_rag import extract_keywords

        contra_list = graph_ev["contradictions"]
        warnings.append(f"상충하는 증거가 존재하는 항목이 {len(contra_list)}건 있습니다.")

        # [P1-03] 질문과 직접 관련된 핵심 Fact에 CONTRADICTION이 존재하는지 판별
        q_kws = [k for k in extract_keywords(q) if len(k) >= 2]
        draft_kws = [k for k in extract_keywords(draft) if len(k) >= 2]
        core_contradictions = []
        for c in contra_list:
            c_text = " ".join(
                str(c.get(field) or "")
                for field in ("target_content", "claim_statement", "contradicting_statement", "explanation")
            ).lower()
            if (q_kws and any(k in c_text for k in q_kws)) or (
                not q_kws and draft_kws and any(k in c_text for k in draft_kws)
            ):
                core_contradictions.append(c)

        if core_contradictions:
            caveat_markers = (
                "상충", "모순", "불일치", "다툼", "확인 필요", "확인이 필요",
                "나뉘", "따라 달라", "전제로", "만약", "일치하지 않",
            )
            draft_acknowledges = any(m in draft for m in caveat_markers)
            result["conflict_acknowledged"] = draft_acknowledges
            if result.get("reason_code") in (None, "NONE", ""):
                result["reason_code"] = "EVIDENCE_CONFLICT"

            if not draft_acknowledges:
                # 단정적 법률 결론을 차단하고 수정 또는 보류(WITHHELD) 유도
                result["status"] = "REVISE"
                result["reason_code"] = "EVIDENCE_CONFLICT"
                contra_summaries = [
                    f"사실 '{c.get('target_content') or ''}'에 대해 상충하는 증거 주장이 존재함"
                    for c in core_contradictions[:3]
                ]
                result.setdefault("contradictions", []).extend(contra_summaries)
                result.setdefault("revision_instructions", []).append(
                    "질문과 관련된 핵심 사실관계에 대해 제출된 증거 간 상충(CONTRADICTION)이 존재합니다. "
                    "어느 한쪽 사실만 확정된 것으로 단정하지 말고, 증거 간 상충 내용과 사실관계 확인에 따른 조건부 법률 효과를 명시하세요."
                )
            elif result.get("status") == "PASS":
                # 상충 사실을 명시하고 조건부로 설명한 경우 CAUTIONARY 처분이 되도록 REVISE 상태 부여
                result["status"] = "REVISE"

    result["warnings"] = warnings
    result["graph_checks"] = graph_checks

    # Source Registry에서 검증 통과된 표준 출처 목록 보존
    verified_sources = result.get("citation_audit", {}).get("verified_sources", combined_sources)

    # Langfuse 정량적 검증 평가 점수(Score) 기록
    try:
        from ai_legal_helper.observability.langfuse_client import log_score
        from ai_legal_helper.observability.context import get_trace_id
        t_id = get_trace_id()
        audit = result.get("citation_audit", {})
        status_score = 1.0 if result.get("status") == "PASS" else (0.5 if result.get("status") == "REVISE" else 0.0)
        log_score(t_id, "verification_status", status_score, comment=result.get("status"))
        if "citation_existence_rate" in audit:
            log_score(t_id, "citation_existence_rate", float(audit["citation_existence_rate"]))
        if "citation_support_rate" in audit:
            log_score(t_id, "citation_support_rate", float(audit["citation_support_rate"]))
    except Exception as ex:
        logger.debug(f"Langfuse 검증 점수 기록 실패: {ex}")

    # 쟁점별 독립 검증 실행 (P0-04, P0-09)
    issue_tasks_raw = state.get("issue_tasks") or []
    briefing_raw = state.get("case_evidence_briefing") or {}

    issue_results_list = []
    if issue_tasks_raw and briefing_raw:
        try:
            from ai_legal_helper.workflows.issue_planner import LegalIssueTask
            from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
            from ai_legal_helper.agents.issue_verifier import verify_all_issues

            tasks_objs = [LegalIssueTask(**it) for it in issue_tasks_raw]
            briefing_obj = CaseEvidenceBriefing(**briefing_raw)
            issue_res_objs = verify_all_issues(tasks_objs, draft, briefing_obj, combined_sources)
            issue_results_list = [r.model_dump() for r in issue_res_objs]
            result["issue_results"] = issue_results_list

            # 쟁점별 검증에서 식별된 누락 법령/조문 정보를 Tier 2 candidate_laws 및 missing_issues에 반영
            from ai_legal_helper.agents.issue_verifier import _STATUTE_REGEX
            sync_candidate_laws = set(result.get("candidate_laws", []) or [])
            sync_missing_issues = list(result.get("missing_issues", []) or [])
            for ir in issue_res_objs:
                for ms in (getattr(ir, "missing_statutes", None) or []):
                    m_stat = _STATUTE_REGEX.search(ms)
                    if m_stat:
                        sync_candidate_laws.add(m_stat.group(1))
                    if ms not in sync_missing_issues:
                        sync_missing_issues.append(ms)
            if sync_candidate_laws:
                result["candidate_laws"] = list(sync_candidate_laws)
            if sync_missing_issues:
                result["missing_issues"] = sync_missing_issues

            # Langfuse v2 관측성 지표 기록 (Section 16, P1-03)
            try:
                from ai_legal_helper.observability.context import get_current_span_id
                from ai_legal_helper.observability.langfuse_client import update_span

                cur_span = get_current_span_id()
                if cur_span:
                    candidate_cnt = sum(len(it.get("candidate_statutes", [])) for it in issue_tasks_raw)
                    verified_cnt = sum(len(r.get("supported_statute_ids", [])) for r in issue_results_list)
                    unsupported_cnt = sum(len(r.get("unsupported_claims", [])) for r in issue_results_list)
                    update_span(cur_span, {
                        "candidate_statute_count": candidate_cnt,
                        "retrieved_statute_count": len(combined_sources),
                        "verified_statute_count": verified_cnt,
                        "unsupported_legal_claim_count": unsupported_cnt,
                        "issue_count": len(issue_results_list),
                    })
            except Exception as span_e:
                logger.debug(f"[VERIFY] span update 무시: {span_e}")
        except Exception as e:
            logger.warning(f"[VERIFICATION] 쟁점별 검증 중 예외 발생: {e}")

    # [P0-VER-01] 검색된 원본 출처(combined_sources)가 본문 인용 매칭 실패 등으로 유실되지 않도록 보존한다.
    # retrieved_sources는 검색된 전체 출처를 유지하고, 본문에서 검증된 인용 출처는 verified_sources로 분리 관리한다.
    preserved_retrieved_sources = combined_sources if combined_sources else verified_sources

    return {
        "verification_result": result,
        "retrieved_sources": preserved_retrieved_sources,
        "verified_sources": verified_sources,
        "issue_results": issue_results_list,
    }

def verification_condition(state: LegalState) -> str:
    """법률 답변의 검증 결과에 따라 다음 실행 단계(Node)를 결정한다.

    등록 문서가 있는 사건은 질문 충족 검증을 포함한 별도 원문 정책을 우선 적용한다.
    아래 쟁점별 조건부 확정 정책은 문서 원문이 없는 기존 일반 상담에만 적용한다.

    1. 검증 통과(PASS): 최종 답변 확정(`finalize`).
    2. 법령 근거 부족(LEGAL_SOURCE_MISSING / LEGAL_SOURCE_INSUFFICIENT) 및 후보 법령 존재 시:
       사용자 승인을 구하는 HILT 노드(`statute_search_approval`)로 라우팅한다.
    3. 최초 검증 실패 시(REVISE 또는 일반 INSUFFICIENT): 1회에 한해 적응형 보강 검색(`revise`).
    4. HILT 공식 법령 검색이 이미 수행된 경우:
       허위 인용(가짜 출처)이 없다면 미검증 폐기하지 않고 실무 권고사항을 보존하여 `finalize`한다.
    5. 근거 부족(INSUFFICIENT, 증거 부족 등): 안내 및 안전 종료(`insufficient`).

    Args:
        state: 현재 LangGraph 워크플로우 상태.

    Returns:
        str: 다음 실행할 노드 이름 ('finalize', 'statute_search_approval', 'revise', 'insufficient').
    """
    if state.get("answer_mode") == DOCUMENT_MODE:
        return next_verification_step(state)
    ver_res = state.get("verification_result", {}) or {}
    status = ver_res.get("status", "PASS")
    reason_code = ver_res.get("reason_code", "NONE")
    candidate_laws = ver_res.get("candidate_laws", [])
    hilt_executed = state.get("hilt_executed", False)
    revision_count = state.get("revision_count", 0)

    # 쟁점별 검증 결과가 존재하는 경우 쟁점 기반 최종 처분 정책 우선 적용 (Section 8, P0-05)
    issue_results_raw = ver_res.get("issue_results") or state.get("issue_results") or []
    if issue_results_raw:
        from ai_legal_helper.agents.issue_verifier import IssueVerificationResult
        from ai_legal_helper.workflows.final_disposition import determine_final_disposition

        issue_res_objs = [IssueVerificationResult(**ir) for ir in issue_results_raw]
        disposition, disp_reason = determine_final_disposition(issue_res_objs)
        logger.info(f"[DISPOSITION] 쟁점 기반 처분 결정: {disposition} ({disp_reason})")

        # 후보 법령이 존재하고 아직 HILT를 실행하지 않은 경우:
        # 쟁점 중 법령 누락이 있거나 법령 근거 부족 시 사용자 승인을 구하는 HILT 노드로 우선 라우팅
        any_statute_missing = any(
            (getattr(ir, "missing_statutes", None) or getattr(ir, "missing_legal_sources", None))
            for ir in issue_res_objs
        )
        if not hilt_executed and candidate_laws and (any_statute_missing or reason_code in ("LEGAL_SOURCE_MISSING", "LEGAL_SOURCE_INSUFFICIENT")):
            # [P0-VER-01] 이미 검색된 출처(retrieved_sources)에 후보 법령이 확보되어 있는지 검증하여 불필요한 외부 검색 차단
            retrieved_statute_names = {
                s.get("statute_name") or s.get("title") or ""
                for s in state.get("retrieved_sources", [])
                if isinstance(s, dict)
            }
            truly_missing_laws = [
                law for law in candidate_laws
                if not any(law in r_name for r_name in retrieved_statute_names if r_name)
            ]
            if truly_missing_laws:
                logger.info(f"[DISPOSITION] 미확보 후보 법령({truly_missing_laws}) 검증을 위해 HILT 법령 검색 승인 요청 노드로 분기합니다.")
                return "statute_search_approval"

        if disposition in ("DELIVERED", "CAUTIONARY"):
            return "finalize"
        elif disposition == "WITHHELD":
            # [P0-VER-01] 전체 법률 검증(status)이 이미 PASS이거나,
            # 핵심 법률 주장이 검색 출처에 의해 온전히 뒷받침되고 결함(허위/미검증 인용 등)이 없는 경우:
            # 사건 사실관계가 없는 일반 법령 질의이므로 사건 증거 부재를 이유로 답변을 폐기하지 않고 finalize로 라우팅한다.
            audit = ver_res.get("citation_audit", {}) or {}
            claims = ver_res.get("claims", []) or []
            has_unsupported_core = any(
                c.get("grounding_status") == "UNSUPPORTED" and c.get("claim_type") in ("LEGAL_RULE", "LEGAL_APPLICATION")
                for c in claims
            )
            has_supported_core = any(
                c.get("grounding_status") == "SUPPORTED" and c.get("claim_type") in ("LEGAL_RULE", "LEGAL_APPLICATION")
                for c in claims
            )
            is_legally_sound = (
                status == "PASS" or (
                    has_supported_core
                    and not has_unsupported_core
                    and not audit.get("unverified_citations")
                    and not audit.get("unsupported_citations")
                    and reason_code not in ("LEGAL_SOURCE_MISSING", "CITATION_INVALID", "EVIDENCE_CONFLICT", "VERIFICATION_ERROR")
                )
            )
            if is_legally_sound:
                logger.info("[DISPOSITION] 쟁점 사실관계 증거는 미확보(NEEDS_EVIDENCE)이나 핵심 법리가 출처에 의해 정상 뒷받침되므로 finalize로 확정합니다.")
                return "finalize"
            # 1회 재검토 가능하면 revise 시도
            if revision_count < 1 and not hilt_executed:
                return "revise"
            return "insufficient"

    # 1. 모든 필수 검증을 통과했다면 최종 확정 (HILT 여부와 무관하게 PASS일 때만 확정)
    if status == "PASS":
        return "finalize"

    # 2. 법률 근거 부족(LEGAL_SOURCE_MISSING / LEGAL_SOURCE_INSUFFICIENT)이 원인이고 후보 법령이 식별된 경우에만 HILT 법령 검색 승인 요청 (1회 한정)
    #    주의: CASE_EVIDENCE_MISSING, EVIDENCE_CONFLICT 등 사실관계 문제는 법령 검색으로 오분기 금지
    #    [P0-VER-01] 이미 검색된 출처(retrieved_sources)에 후보 법령이 이미 확보되어 있다면 외부 추가 검색 불필요
    if not hilt_executed and candidate_laws and reason_code in ("LEGAL_SOURCE_MISSING", "LEGAL_SOURCE_INSUFFICIENT"):
        retrieved_statute_names = {
            s.get("statute_name") or s.get("title") or ""
            for s in state.get("retrieved_sources", [])
            if isinstance(s, dict)
        }
        truly_missing_laws = [
            law for law in candidate_laws
            if not any(law in r_name for r_name in retrieved_statute_names if r_name)
        ]
        if truly_missing_laws:
            return "statute_search_approval"

    # 3. 최초 검증 실패 시(REVISE 또는 일반 작성오류) 1회에 한해 적응형 보강 검색(revise) 시도
    #    단, 핵심 증거 상충(EVIDENCE_CONFLICT)이 존재하더라도 초안이 이미 상충을 명시하고 조건부 답변을 작성한 경우에는
    #    불필요한 재작성 없이 즉시 조건부 확정(finalize -> CAUTIONARY)으로 라우팅한다.
    if reason_code == "EVIDENCE_CONFLICT" and ver_res.get("conflict_acknowledged") and status == "REVISE":
        return "finalize"

    if revision_count < 1 and not hilt_executed:
        if status == "REVISE" or (status == "INSUFFICIENT" and reason_code in ("ANSWER_REVISION_REQUIRED", "NONE")):
            return "revise"

    # 4. HILT 실행 후 또는 재검토 한도(1회) 도달 후:
    #    - REVISE 상태이더라도 중대 결함(법률 근거 부재, 허위/미검증 인용, 증거 모순, 시스템 오류)이 존재하거나
    #      핵심 법률 주장(LEGAL_RULE, LEGAL_APPLICATION) 중 미뒷받침(UNSUPPORTED) 주장이 있는 경우
    #      고객에게 미검증 주장을 전달하지 않고 insufficient_node(WITHHELD)로 안전 종료한다 (P0-1, P0-2).
    #    - 법률적 핵심 뼈대가 검증된 출처에 의해 뒷받침되고 사실관계 입증 주의사항(CASE_EVIDENCE_MISSING)이나
    #      경미한 문구 보완만 남아있는 경우에만 finalize_node로 라우팅하여 조건부 답변(CAUTIONARY)을 제공한다.
    if status == "REVISE":
        # 1. 허위/미검증 인용 라벨 잔존 시 전달 차단 (Section 7, Section 12)
        audit = ver_res.get("citation_audit", {}) or {}
        if audit.get("unverified_citations"):
            logger.info("[GATING] REVISE 상태이나 허위/미검증 인용 감지로 finalize 차단 -> insufficient(WITHHELD)")
            return "insufficient"

        # 2. 쟁점 기반 부분 답변(Issue-Level Partial Answer) 평가 (P0-1)
        #    - 단위 쟁점 중 검증 완료(VERIFIED) 또는 조건부(CONDITIONAL) 쟁점이 1건 이상 존재하고 사건 브리핑이 있는 경우:
        #      전체 답변을 일괄 WITHHELD로 폐기하지 않고 assemble_grounded_answer를 통해
        #      검증된 쟁점과 확인된 사실만을 조립하여 조건부 답변(CAUTIONARY)을 제공한다.
        issue_results = ver_res.get("issue_results") or state.get("issue_results") or []
        briefing_raw = state.get("case_evidence_briefing")
        verified_count = sum(1 for r in issue_results if (r.get("status") == "VERIFIED" if isinstance(r, dict) else getattr(r, "status", None) == "VERIFIED"))
        conditional_count = sum(1 for r in issue_results if (r.get("status") == "CONDITIONAL" if isinstance(r, dict) else getattr(r, "status", None) == "CONDITIONAL"))

        if (verified_count > 0 or conditional_count > 0) and briefing_raw:
            logger.info(
                f"[GATING] REVISE 상태이나 검증된 쟁점(VERIFIED={verified_count}, CONDITIONAL={conditional_count}) 존재 "
                f"-> assemble_grounded_answer 부분 답변 생성을 위해 finalize_node로 라우팅 (P0-1)"
            )
            return "finalize"

        # 3. 사건 브리핑이 없거나 검증 가능한 쟁점이 전무한 일반 상담의 경우 안전 게이팅 적용
        # A) 중대 결함 사유(법령 미확보, 증거 상충, 시스템 오류) 존재 시 전달 차단
        if reason_code in ("LEGAL_SOURCE_MISSING", "CITATION_INVALID", "EVIDENCE_CONFLICT", "VERIFICATION_ERROR"):
            logger.info(f"[GATING] REVISE 상태이나 중대 결함({reason_code})으로 finalize 차단 -> insufficient(WITHHELD)")
            return "insufficient"

        # B) 핵심 법률 주장 중 미뒷받침(UNSUPPORTED) 주장 존재 시 전달 차단
        claims = ver_res.get("claims", []) or []
        unsupported_legal_claims = [
            c for c in claims
            if c.get("grounding_status") == "UNSUPPORTED" and c.get("claim_type") in ("LEGAL_RULE", "LEGAL_APPLICATION")
        ]
        if unsupported_legal_claims:
            logger.info(f"[GATING] REVISE 상태이나 미뒷받침 법률 주장 {len(unsupported_legal_claims)}건 존재로 finalize 차단 -> insufficient(WITHHELD)")
            return "insufficient"

        # D) 핵심 법리는 확보되었고 사실관계 입증 주의(CASE_EVIDENCE_MISSING) 또는 경미한 문구 보완인 경우에만 조건부 확정(CAUTIONARY)
        return "finalize"

    return "insufficient" 


@trace
def revise_node(state: LegalState) -> Dict:
    """검증 실패 시 보강 검색(Adaptive Re-Retrieval)과 출처/맥락 주입을 통해 초안 답변을 수정한다.

    1. `missing_issues`, `revision_instructions`, `contradictions`를 결합한 확장 질의로 카테고리별 RAG 재검색을 수행한다.
    2. 신규 검색된 문서를 표준 Source 스키마(`build_source_from_chroma_doc`)로 변환하여 기존 `retrieved_sources`에 병합한다.
    3. 실제 검색된 출처 목록(`retrieved_sources`)과 사건 맥락(`case_context`)을 수정 프롬프트에 함께 전달하여
       허위 출처 없이 근거에 부합하는 수정 답변을 생성한다.

    Args:
        state: 현재 LangGraph 워크플로우 상태.

    Returns:
        Dict: 수정된 `draft_answer`, 보강된 `retrieved_sources`, 증가된 `revision_count`.
    """
    set_node_name("revise")
    if state.get("answer_mode") == DOCUMENT_MODE:
        return generate_answer(state, repair=True)
    from ai_legal_helper.llm.gateway import get_llm
    from ai_legal_helper.rag.retrieval import retrieve
    from ai_legal_helper.rag.source_schema import build_source_from_chroma_doc
    from langchain_core.prompts import PromptTemplate

    ver_res = state.get("verification_result", {}) or {}
    instructions = ver_res.get("revision_instructions", [])
    missing_issues = ver_res.get("missing_issues", [])
    contradictions = ver_res.get("contradictions", [])
    draft = state.get("draft_answer", "")
    question = state.get("question", "")
    case_ctx = state.get("case_context", "") or "(사건 맥락 없음)"
    categories = state.get("categories", []) or []
    merged_sources = list(state.get("retrieved_sources", []) or [])
    existing_ids = {s.get("source_id") for s in merged_sources if s.get("source_id")}

    # 1. Adaptive Re-Retrieval (보강 검색 질의 생성 및 추가 RAG 검색 수행)
    re_query_parts = [question] + list(missing_issues) + list(instructions)
    re_query = " ".join([p for p in re_query_parts if p]).strip()
    if re_query and categories:
        for cat in categories:
            try:
                docs = retrieve(query=re_query[:300], category=cat, k=3)
                for doc in docs or []:
                    std_src = build_source_from_chroma_doc(
                        doc,
                        category=cat,
                        retrieval_method="CHROMA_VECTOR_REVISED",
                    )
                    sid = std_src.get("source_id")
                    if sid and sid not in existing_ids:
                        existing_ids.add(sid)
                        merged_sources.append(std_src)
            except Exception as e:
                logger.warning(f"[NODE:revise] 보강 RAG 검색 실패(cat={cat}): {e}")

    # 2. 실제 검색된 출처 포맷팅
    sources_text = ""
    for s in merged_sources[:15]:
        fname = s.get("filename") or s.get("file_name") or s.get("source_id") or "UNKNOWN"
        page = s.get("page") or "1"
        sources_text += f"- ({fname}, p.{page}): {str(s.get('content', ''))[:300]}\n"
    if not sources_text.strip():
        sources_text = "(검색된 출처 없음 - 특정 파일명을 인용하지 마세요)"

    inst_text = "\n- ".join(instructions) if instructions else "답변을 실제 검색된 출처와 사건 맥락에 맞게 수정하세요."
    contra_text = "\n- ".join(contradictions) if contradictions else "특이사항 없음"

    prompt = PromptTemplate.from_template(
        "당신은 법률 답변 수정 전문가입니다.\n"
        "기존 답변에 법률적 근거 부족, 미검증 허위 인용, 또는 핵심 쟁점 누락이 지적되었습니다.\n\n"
        "[수정 지침]\n- {instructions}\n\n"
        "[감지된 모순 및 문제점]\n- {contradictions}\n\n"
        "[사건 맥락]\n{case_context}\n\n"
        "[실제 검색된 출처 목록]\n{sources_text}\n\n"
        "[기존 답변 초안]\n{draft}\n\n"
        "[작성 규칙]\n"
        "1. 반드시 위 수정 지침과 [실제 검색된 출처 목록], [사건 맥락]에 명시된 사실만 반영하여 답변을 다시 작성하세요.\n"
        "2. [실제 검색된 출처 목록]에 없는 파일명이나 판례 사건번호는 절대 인용하지 마세요.\n"
        "3. 만약 사안이 특별법(근로기준법, 상가임대차법, 주택임대차보호법 등)의 적용 대상이나 검색된 출처에 해당 특별법 조문이 없다면, 일반 민법 규정만 단정적으로 적용하지 마시고 관련 특별법 근거 자료가 부족함을 명확히 명시하세요.\n"
        "4. 마크다운 특수문자(#, ##, ###, **, *, ---, > 등)를 절대 사용하지 마세요. 화면에 그대로 노출되므로 [제목], 번호(1., 2.), 불릿(- )으로 정돈된 플레인 텍스트로만 작성하세요."
    )
    llm = get_llm(temperature=0.0)
    res = (prompt | llm).invoke({
        "instructions": inst_text,
        "contradictions": contra_text,
        "case_context": case_ctx,
        "sources_text": sources_text,
        "draft": draft,
    })

    from ai_legal_helper.utils.text_formatter import clean_markdown_formatting
    raw_content = res.content if hasattr(res, "content") else str(res)
    cleaned_draft = clean_markdown_formatting(raw_content)

    return {
        "draft_answer": cleaned_draft,
        "retrieved_sources": merged_sources,
        "revision_count": state.get("revision_count", 0) + 1,
    }

@trace
def insufficient_node(state: LegalState) -> Dict:
    """근거 부족(INSUFFICIENT) 또는 판단 유보 시 고객에게 안전한 가이드와 불확실한 사항을 안내한다.

    [P0-02 & P0-1 & P0-2 원칙]
    1. 미검증 초안은 내부 감사용(internal_draft)으로만 보존하고 고객용 final_answer에서는 완전 배제한다.
    2. Verifier 내부 감수용 디버그 표현('표현상 긴장', '다소 넓다', 'X건 미연결', '초안은' 등)이나
       개발자용 모순/경고 배열을 고객 답변에 날것(raw)으로 노출하지 않고, 고객이 이해 가능한 법률 가이드로 정제한다.
    3. 내부 검증 데이터(contradictions, warnings, claims 등)는 Tier 2 검증 결과(verification_result)에 온전히 보존한다.
    4. final_disposition은 항상 'WITHHELD'로 확정하여 answer_status 불일치를 원천 차단한다.
    """
    set_node_name("insufficient")
    if state.get("answer_mode") == DOCUMENT_MODE:
        return finish_answer(state)
    from ai_legal_helper.agents.verification import sanitize_unverified_citations
    from ai_legal_helper.utils.text_formatter import clean_markdown_formatting

    raw_draft = state.get("draft_answer", "")
    sanitized_draft = sanitize_unverified_citations(
        raw_draft,
        state.get("retrieved_sources", []),
        case_context=state.get("case_context", ""),
    )

    ver_res = state.get("verification_result", {}) or {}
    missing_issues = ver_res.get("missing_issues", []) or []
    missing_laws = ver_res.get("candidate_laws", []) or []
    reason_code = ver_res.get("reason_code", "LEGAL_SOURCE_MISSING")

    # 고객용 판단 유보 안내문 (내부 시스템 용어 WITHHELD, INSUFFICIENT 완전 배제 및 사건 맥락 동적 구성)
    parts = []
    parts.append("[안내: 추가 법률 검토 및 객관적 사실 확인 필요]\n")

    q_text = state.get("question", "")
    case_ctx_text = state.get("case_context", "")

    # 부족 사유별 동적 원인 설명
    if reason_code in ("LEGAL_SOURCE_MISSING", "LEGAL_SOURCE_INSUFFICIENT"):
        lead_reason = "질문하신 사안의 권리 관계를 확정하기 위해 공식 법령 조문 또는 관련 판례 법리의 추가적인 확인 및 검토가 필요한 상태입니다."
    elif reason_code == "CASE_EVIDENCE_MISSING":
        lead_reason = "법률적 권리를 확정적으로 행사하기 위해 필수적인 구체적 사실관계(일자, 통지 도달 여부 등)나 객관적 입증 증빙이 아직 충분히 확인되지 않았습니다."
    elif reason_code == "EVIDENCE_CONFLICT":
        lead_reason = "현재 진술하신 사실관계와 제출된 자료 또는 법적 요건 간에 불일치나 상충이 감지되어 사실관계의 정리가 우선적으로 요구됩니다."
    else:
        lead_reason = "정확하고 신뢰할 수 있는 법적 조언을 위해 관련 법령 근거 및 객관적 증빙의 추가 확인이 필요합니다."
    parts.append(f"{lead_reason}\n의뢰인의 권리 보호를 위해 성급한 단정 대신 확인이 필요한 사항과 안전한 대처 방안을 안내해 드립니다.\n")

    # 1. 확인 및 보강이 필요한 핵심 쟁점 및 법령
    if missing_laws or missing_issues:
        parts.append("[1. 확인 및 보강이 필요한 핵심 쟁점 및 법령]")
        for law in missing_laws:
            parts.append(f"- 관련 법령: {law}")
        for issue in missing_issues:
            cleaned_issue = issue
            for bad_word in ["초안은 ", "초안이 ", "초안의 ", "초안을 ", "초안 ", "draft ", "Draft "]:
                cleaned_issue = cleaned_issue.replace(bad_word, "사안의 검토 ")
            parts.append(f"- 핵심 쟁점: {cleaned_issue}")
        parts.append("")

    # 2. 사실관계 및 입증 리스크 동적 안내 (사건 분야별 맞춤형 서류 안내)
    parts.append("[2. 사실관계 및 입증 리스크 안내]")
    # [P0-VER-01] 질문 텍스트(q_text)의 도메인을 최우선으로 고려한다.
    # 질문에 특정 도메인(임대차/노동/계약 등) 키워드가 없는데 이전 사건 세션의 case_ctx_text에만 존재하는 경우,
    # 이전 사건 컨텍스트로 인해 현재 질문과 무관한 안내문(예: 미성년자 질문에 임대차 안내)이 출력되는 오염을 방지한다.
    q_housing = any(k in q_text for k in ["전세", "보증금", "임대", "임차", "월세"])
    q_labor = any(k in q_text for k in ["근로", "해고", "임금", "퇴직금", "노동", "출근"])
    q_contract = any(k in q_text for k in ["계약", "대금", "채무", "빌려", "손해배상", "차용"])

    ctx_housing = any(k in case_ctx_text for k in ["전세", "보증금", "임대", "임차", "월세"])
    ctx_labor = any(k in case_ctx_text for k in ["근로", "해고", "임금", "퇴직금", "노동", "출근"])
    ctx_contract = any(k in case_ctx_text for k in ["계약", "대금", "채무", "빌려", "손해배상", "차용"])

    is_housing = q_housing or (ctx_housing and not (q_labor or q_contract) and any(k in q_text for k in ["부동산", "집", "방", "이사"]))
    is_labor = q_labor or (ctx_labor and not (q_housing or q_contract) and any(k in q_text for k in ["회사", "직장", "사장"]))
    is_contract = q_contract or (ctx_contract and not (q_housing or q_labor))

    if is_housing:
        parts.append("- 법률상 권리 주장은 임대차계약서, 보증금 이체 영수증, 계약 해지 또는 갱신 거절 통지 도달 증빙(내용증명, 문자/카카오톡 등)에 기초해야 합니다.")
    elif is_labor:
        parts.append("- 노동 관계상 권리 주장은 근로계약서, 급여명세서 및 입금내역, 출퇴근 기록, 서면 해고 통지서 등 객관적 증빙에 기초해야 합니다.")
    elif is_contract:
        parts.append("- 계약 및 금전 청구는 계약서 또는 차용증, 금융 거래 내역, 약정 해제 통지 내역 등 객관적 증빙에 기초해야 합니다.")
    else:
        parts.append("- 법률상 권리 주장은 당사자 간의 계약 서면, 의사표시 도달 증빙, 금융 거래 내역 등 객관적 입증 자료에 기초해야 합니다.")
    parts.append("- 객관적 증빙 없이 구두 주장만으로 법적 절차를 섣불리 진행할 경우 입증 부족으로 인한 불이익이 발생할 수 있습니다.\n")

    # 3. 안전한 후속 행동 가이드
    parts.append("[3. 안전한 후속 행동 가이드]")
    parts.append(
        "- 미검증 법률 판단에 의존한 일방적 법적 조치는 불측의 손해를 초래할 수 있으므로, 관련 서류 및 객관적 입증 자료를 지참하여 "
        "대한법률구조공단(국번없이 132) 또는 변호사 등 법률전문가의 정밀 대면 상담을 받으시기 바랍니다."
    )

    briefing_raw = state.get("case_evidence_briefing")
    issue_results_raw = ver_res.get("issue_results") or state.get("issue_results") or []

    # [P0-VER-01] 현재 질문(q_text)이 사건 브리핑과 실질적으로 연관된 경우에만 사건 브리핑 기반 동적 안내를 수행한다.
    # 사건과 무관한 일반 법령 질문(예: 미성년자 재산 처분 등)인 경우 이전 사건의 임대차 증거/쟁점 템플릿으로 오염되지 않도록 차단한다.
    is_question_related_to_case = bool(
        q_housing or q_labor or q_contract or not briefing_raw or
        any(k in q_text for k in ["사건", "내 사건", "증거", "서류", "진행", "소송"])
    )

    if briefing_raw and is_question_related_to_case and issue_results_raw:
        from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
        from ai_legal_helper.agents.issue_verifier import IssueVerificationResult
        from ai_legal_helper.workflows.final_disposition import build_dynamic_withheld_answer

        briefing_obj = CaseEvidenceBriefing(**briefing_raw)
        issue_res_objs = [IssueVerificationResult(**ir) for ir in issue_results_raw]
        final = build_dynamic_withheld_answer(issue_res_objs, briefing_obj, reason_code)
        # 본문에 실제로 인용되거나 제시된 증거만 선별
        preserved_sources = [
            ces for lbl, ces in briefing_obj.source_registry.items()
            if f"[{lbl}]" in final or f"[{lbl}_" in final or (ces.get("file_name") and ces.get("file_name") in final)
        ]
        if not preserved_sources:
            preserved_sources = list(briefing_obj.source_registry.values())[:3]
    else:
        final = clean_markdown_formatting("\n".join(parts))
        preserved_sources = []

    warnings = list(state.get("warnings", []) or []) + ["답변의 근거가 부족하여 INSUFFICIENT(WITHHELD) 처리되었습니다."]

    return {
        "final_answer": final,
        "internal_draft": sanitized_draft,
        "final_disposition": "WITHHELD",
        "verification_failure_reason": ver_res.get("explanation") or reason_code,
        "missing_evidence": missing_issues,
        "unresolved_issues": ver_res.get("missing_legal_issues", []),
        "warnings": warnings,
        "sources": preserved_sources,
        "cited_sources": preserved_sources,
        "messages": [AIMessage(content=final)],
        "issue_results": issue_results_raw,
    }


@trace
def finalize_node(state: LegalState) -> Dict:
    """문서 사건은 검증한 초안을 그대로 반환하고 일반 상담은 기존 출력 처리를 적용한다."""
    set_node_name("finalize")
    if state.get("answer_mode") == DOCUMENT_MODE:
        return finish_answer(state)
    from ai_legal_helper.agents.verification import sanitize_unverified_citations, audit_citations_and_claims
    from ai_legal_helper.utils.text_formatter import clean_markdown_formatting

    ver_res = state.get("verification_result", {}) or {}
    ver_status = ver_res.get("status", "PASS")
    warnings = list(state.get("warnings", []) or [])
    ver_warnings = ver_res.get("warnings", []) or []
    for w in ver_warnings:
        if w not in warnings:
            warnings.append(w)

    final_disp = "DELIVERED" if ver_status == "PASS" else "CAUTIONARY"

    briefing_raw = state.get("case_evidence_briefing")
    issue_results_raw = ver_res.get("issue_results") or state.get("issue_results") or []
    case_delta = None

    # [P0-VER-01] 질문이 사건 브리핑과 실질적으로 연관된 경우에만 assemble_grounded_answer로 사건 쟁점을 조립한다.
    # 사건과 무관한 일반 법령 질문(미성년자 재산처분 등)은 draft_answer의 정제본을 그대로 사용하여 사건 오염을 방지한다.
    q_text = state.get("question", "")
    q_housing = any(k in q_text for k in ["전세", "보증금", "임대", "임차", "월세"])
    q_labor = any(k in q_text for k in ["근로", "해고", "임금", "퇴직금", "노동", "출근"])
    q_contract = any(k in q_text for k in ["계약", "대금", "채무", "빌려", "손해배상", "차용"])
    is_case_relevant = bool(
        q_housing or q_labor or q_contract or not briefing_raw or
        any(k in q_text for k in ["사건", "내 사건", "증거", "서류", "진행", "소송"])
    )

    if briefing_raw and is_case_relevant and (issue_results_raw or is_evidence_review_request(q_text)):
        from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
        from ai_legal_helper.agents.issue_verifier import IssueVerificationResult
        from ai_legal_helper.workflows.final_disposition import (
            assemble_grounded_answer,
            determine_final_disposition,
            detect_case_delta,
            reconcile_issue_results,
        )

        briefing_obj = CaseEvidenceBriefing(**briefing_raw)
        issue_res_objs = reconcile_issue_results([IssueVerificationResult(**ir) for ir in issue_results_raw])
        issue_results_raw = [result.model_dump() for result in issue_res_objs]
        ver_res["issue_results"] = issue_results_raw
        calc_disp, _ = determine_final_disposition(issue_res_objs)
        # 전체 초안의 PASS가 쟁점별 미확인 상태를 덮어쓰지 않도록 최종 처분을 보존한다.
        final_disp = calc_disp if ver_status == "PASS" or calc_disp == "WITHHELD" else "CAUTIONARY"

        case_delta = detect_case_delta(
            briefing=briefing_obj,
            conv_context=state.get("conversation_context"),
            current_question=state.get("question", ""),
            resolved_query=state.get("resolved_query", ""),
        )

        final = assemble_grounded_answer(
            issue_res_objs,
            briefing_obj,
            state.get("draft_answer", ""),
            final_disp,
            conv_context=state.get("conversation_context"),
            current_question=state.get("question", ""),
            case_delta=case_delta,
        )
    else:
        sanitized = sanitize_unverified_citations(
            state.get("draft_answer", ""),
            state.get("retrieved_sources", []),
            case_context=state.get("case_context", ""),
        )
        final = clean_markdown_formatting(sanitized)

    # [P0-03] 최종 확정된 답변(final)에 기반하여 실제 인용·검증된 출처(cited_sources)를 최종 산출
    final_audit = audit_citations_and_claims(
        final,
        state.get("retrieved_sources", []),
        case_context=state.get("case_context", ""),
    )
    cited_sources = final_audit.get("cited_sources") or final_audit.get("verified_sources", [])

    # Case Evidence Sources 중 최종 확정된 답변 본문(final)에 실제로 인용된 증거만 선별 (P0-10)
    claim_citations_data = []
    if briefing_raw and is_case_relevant:
        from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
        briefing_obj = CaseEvidenceBriefing(**briefing_raw)
        if issue_results_raw and "issue_res_objs" in locals():
            from ai_legal_helper.workflows.final_disposition import build_claim_citations
            claim_citations_data = build_claim_citations(
                issue_results=issue_res_objs,
                briefing=briefing_obj,
                final_answer=final,
                retrieved_sources=state.get("retrieved_sources", []),
            )

        all_sources = list(cited_sources)
        seen_keys = {
            s.get("source_id") or s.get("evidence_id") or s.get("file") or s.get("evidence_label")
            for s in all_sources
            if isinstance(s, dict)
        }
        # None 제거
        seen_keys.discard(None)
        for ev_label, ces in briefing_obj.source_registry.items():
            if not isinstance(ces, dict):
                continue
            doc_name = ces.get("document_name") or ces.get("file_name") or ces.get("file") or ""
            is_cited_in_final = (
                f"[{ev_label}]" in final
                or f"[{ev_label}_" in final
                or f"[{ev_label}:" in final
                or (doc_name and doc_name in final)
            )
            if is_cited_in_final:
                k = ces.get("evidence_id") or ces.get("source_id") or ces.get("evidence_label") or ev_label
                if k and k not in seen_keys:
                    all_sources.append(ces)
                    seen_keys.add(k)
        cited_sources = all_sources

    ver_res["claim_citations"] = claim_citations_data
    if case_delta:
        ver_res["case_delta"] = case_delta

    return {
        "final_answer": final,
        "answer": final,
        "sources": cited_sources,
        "cited_sources": cited_sources,
        "claim_citations": claim_citations_data,
        "case_delta": case_delta,
        "warnings": warnings,
        "final_disposition": final_disp,
        "messages": [AIMessage(content=final)],
        "issue_results": issue_results_raw,
        "verification_result": ver_res,
    }


def _format_client_approval_explanation(
    raw_explanation: str,
    candidate_laws: List[str],
    missing_issues: List[str],
) -> str:
    """고객(의뢰인) 화면에 노출될 법령 추가 검색 승인 요청 사유를 정제하고 표준화한다.

    내부 시스템 감수용 단어('초안', 'draft' 등)가 포함되어 있을 경우 이를 고객 친화적인
    전문 법률 안내 문구로 자동 치환/정제하여 전문성과 신뢰성을 보장한다.

    Args:
        raw_explanation: Verifier Agent가 생성한 원시 사유 텍스트
        candidate_laws: 검색 후보 법령 목록
        missing_issues: 확인 필요한 법률 쟁점 목록

    Returns:
        str: 고객 화면에 노출하기에 적합하도록 정제된 승인 사유 안내문
    """
    laws_str = f"({', '.join(candidate_laws)})" if candidate_laws else ""
    if not raw_explanation:
        return f"질문하신 사안의 법률 쟁점을 정확히 검토하기 위해 공식 법령{laws_str} 조문 원문의 추가 확인이 필요합니다."

    cleaned = raw_explanation.strip()

    # '초안', 'draft' 등 내부 시스템 감수 용어 치환
    cleaned = re.sub(r'초안은\s*', '질문하신 사안의 법률 검토에 있어 ', cleaned)
    cleaned = re.sub(r'초안이\s*', '해당 사안에서 ', cleaned)
    cleaned = re.sub(r'초안을\s*그대로\s*확정하기보다[,\s]*', '확정적인 법률 판단을 내리기 전에 ', cleaned)
    cleaned = re.sub(r'초안을\s*', '의견서를 ', cleaned)
    cleaned = re.sub(r'초안의\s*', '검토 내용의 ', cleaned)
    cleaned = re.sub(r'초안\s*', '법률 검토 ', cleaned)
    cleaned = re.sub(r'\b[Dd]raft\b', '법률 검토', cleaned)

    # 서두가 질문 맥락 없이 시작하는 경우 고객 친화적 서두 보강
    if not (cleaned.startswith("질문") or cleaned.startswith("의뢰인")):
        lead = f"질문하신 사안에 대해 정확하고 신뢰할 수 있는 법적 판단을 제공하기 위해 공식 법령{laws_str} 조문의 확인이 필요합니다. "
        cleaned = lead + cleaned

    return cleaned


@trace
def statute_search_approval_node(state: LegalState) -> Dict:
    """법령 원문 검색 승인을 위한 HILT(Human-in-the-Loop) 노드.

    Verifier가 법률 근거 부족(LEGAL_SOURCE_MISSING / LEGAL_SOURCE_INSUFFICIENT)을 감지했을 때
    공식 법령 원문 검색 진행 여부를 사용자에게 질의하며 그래프 실행을 일시 중단(interrupt)한다.

    Args:
        state: 현재 LangGraph 워크플로우 상태.

    Returns:
        Dict: 승인 요청 정보(`approval_request`), 승인 상태(`approval_status`), HILT 실행 여부(`hilt_executed`).
    """
    set_node_name("statute_search_approval")
    from ai_legal_helper.observability.context import get_case_id, get_trace_id, get_request_id

    ver_res = state.get("verification_result", {}) or {}
    candidate_laws = ver_res.get("candidate_laws", [])
    missing_issues = ver_res.get("missing_legal_issues", []) or ver_res.get("missing_issues", [])
    reason_code = ver_res.get("reason_code", "LEGAL_SOURCE_MISSING")
    explanation_raw = ver_res.get("explanation", "현재 검색된 법률 자료만으로는 해당 쟁점을 충분히 검증할 수 없습니다.")
    explanation = _format_client_approval_explanation(explanation_raw, candidate_laws, missing_issues)

    case_id = state.get("case_id") or get_case_id() or "GENERAL_CONSULTATION"
    req_id = state.get("request_id") or get_request_id() or str(uuid.uuid4())
    trace_id = state.get("trace_id") or get_trace_id() or str(uuid.uuid4())
    approval_req_id = f"APPR-{str(uuid.uuid4())[:8]}"

    approval_payload = {
        "type": "STATUTE_SEARCH_APPROVAL",
        "case_id": case_id,
        "thread_id": req_id,
        "trace_id": trace_id,
        "approval_request_id": approval_req_id,
        "reason": reason_code,
        "explanation": explanation,
        "missing_issue": ", ".join(missing_issues) if missing_issues else "관련 법령 조문 확인 필요",
        "missing_legal_issues": missing_issues,
        "candidate_laws": candidate_laws,
        "search_scope": "공식 법령 원문 (국가법령정보공동활용 open.law.go.kr)",
        "approval_required": True,
    }

    # LangGraph 표준 interrupt 호출: 그래프 일시 중단 및 외부 승인 대기
    decision = interrupt(approval_payload)

    # Resume 시 수신된 사용자 결정 파싱
    approved = False
    user_reason = None
    if isinstance(decision, dict):
        approved = bool(decision.get("approved", False))
        user_reason = decision.get("reason")
    elif isinstance(decision, bool):
        approved = decision

    from ai_legal_helper.workflows.document_search import law_names

    raw_law_refs = list(candidate_laws or []) + [
        r.get("law_name", "")
        for r in (ver_res.get("legal_search_requests") or [])
        if isinstance(r, dict) and r.get("law_name")
    ]
    approved_laws = law_names(raw_law_refs) if approved else []

    logger.info(f"[공식 법령 검색 승인 결과] 승인여부={approved}, 사유={user_reason}")
    return {
        "approval_request": approval_payload,
        "approval_status": "APPROVED" if approved else "REJECTED",
        "approved_statute_laws": approved_laws,
        "hilt_executed": True,
    }


def statute_search_approval_condition(state: LegalState) -> str:
    """사용자의 법령 검색 승인 여부에 따라 분기한다.

    Args:
        state: 현재 LangGraph 워크플로우 상태.

    Returns:
        str: 'execute_statute_search' (승인 시) 또는 'insufficient' (거절 시).
    """
    status = state.get("approval_status")
    if status == "APPROVED":
        return "execute_statute_search"
    return "insufficient"


@trace
def execute_statute_search_node(state: LegalState) -> Dict:
    """사용자 승인 후 공식 법령 원문 검색 API(open.law.go.kr)를 호출하여 관련 조문을 조회한다.

    특별법 우선의 원칙(주택임대차보호법, 상가임대차법, 근로기준법 등)에 따라 후보 법령을 정렬하고
    법률검증 Agent의 핵심 쟁점 키워드를 전달하여 연관 조문(최대 10개)을 수집한다.

    Args:
        state: 현재 LangGraph 워크플로우 상태.

    Returns:
        Dict: 검색된 법령 결과(`statute_search_results`), 병합된 출처(`retrieved_sources`), 경고 목록(`warnings`).
    """
    set_node_name("execute_statute_search")
    from ai_legal_helper.tools.official_statute_search import search_official_statutes
    from ai_legal_helper.workflows.document_search import execute_document_search, law_names

    ver_res = state.get("verification_result", {}) or {}
    candidate_laws = list(ver_res.get("candidate_laws", []) or [])
    if state.get("answer_mode") == DOCUMENT_MODE:
        search_state = dict(state)
        if search_state.get("approval_status") == "APPROVED" and not search_state.get("approved_statute_laws"):
            raw_refs = list(candidate_laws) + [
                r.get("law_name", "")
                for r in (ver_res.get("legal_search_requests") or [])
                if isinstance(r, dict) and r.get("law_name")
            ]
            search_state["approved_statute_laws"] = law_names(raw_refs)
        doc_search_out = execute_document_search(search_state)
        warnings = list(state.get("warnings", []) or [])
        if not doc_search_out.get("statute_search_results"):
            warnings.append("공식 법령 원문 검색 시스템에서 요청하신 법령의 해당 조문을 찾지 못했습니다.")
        return {**doc_search_out, "warnings": warnings}
    missing_issues = list(ver_res.get("missing_legal_issues", []) or ver_res.get("missing_issues", []) or [])
    issue_results_raw = ver_res.get("issue_results") or state.get("issue_results") or []
    for ir in issue_results_raw:
        for ms in (ir.get("missing_statutes") or ir.get("missing_legal_sources") or []):
            if ms not in missing_issues:
                missing_issues.append(ms)
    q = state.get("question", "")

    # 손해배상, 특별손해, 지연손해금 등 일반 민사상 손해 쟁점이 포함된 경우 민법을 후보 법령에 보강 (P0-1 & P0-2)
    damages_keywords = ("손해", "손해배상", "특별손해", "추가 손해", "지연손해금", "지연이자")
    if any(k in q for k in damages_keywords) or any(any(k in iss for k in damages_keywords) for iss in missing_issues):
        if "민법" not in candidate_laws:
            candidate_laws.append("민법")

    # 특별법 우선 정렬: 일반법(민법, 형법 등)보다 특별법(주택임대차보호법 등)을 1순위로 탐색
    candidate_laws.sort(key=lambda law: 1 if law in ("민법", "형법", "상법", "민사소송법") else 0)

    statute_sources = search_official_statutes(
        query=q,
        candidate_laws=candidate_laws,
        effective_date=None,
        missing_issues=missing_issues,
        max_articles_per_law=10,
    )

    merged_sources = list(state.get("retrieved_sources", []) or [])
    existing_ids = {s.get("source_id") for s in merged_sources if s.get("source_id")}

    for s in statute_sources:
        sid = s.get("source_id")
        if sid and sid not in existing_ids:
            existing_ids.add(sid)
            merged_sources.append(s)

    warnings = list(state.get("warnings", []) or [])
    if not statute_sources:
        warnings.append("공식 법령 원문 검색 시스템에서 요청하신 법령의 해당 조문을 찾지 못했습니다.")

    return {
        "statute_search_results": statute_sources,
        "retrieved_sources": merged_sources,
        "warnings": warnings,
    }


def statute_search_result_condition(state: LegalState) -> str:
    """공식 법령 원문 검색 결과 유무에 따라 분기한다.

    Args:
        state: 현재 LangGraph 워크플로우 상태.

    Returns:
        str: 're_analyze' (법령 조회 성공 시) 또는 'insufficient' (조회 실패 시).
    """
    results = state.get("statute_search_results", [])
    if results:
        return "re_analyze"
    return "insufficient"


@trace
def re_analyze_node(state: LegalState) -> Dict:
    """공식 법령 원문 검색으로 확보된 법령 조문을 바탕으로 법률 분석을 재수행하고 답변을 재작성한다 (P0-04).

    전세보증금 사건 하드코딩을 제거하고, 사건 유형(categories) 및 기존 전문 에이전트 분석을 동적으로 반영하는
    도메인 중립적 4단계 표준 구조([1. 핵심 결론], [2. 지금 해야 할 일], [3. 쟁점별 상세 법률 분석], [4. 추가 확인사항 및 유의사항])를 적용한다.
    """
    set_node_name("re_analyze")
    if state.get("answer_mode") == DOCUMENT_MODE:
        return generate_answer(state, repair=True, increment_revision=False)
    from ai_legal_helper.llm.gateway import get_llm
    from ai_legal_helper.utils.text_formatter import clean_markdown_formatting
    from langchain_core.prompts import PromptTemplate

    q = state.get("question", "")
    case_ctx = state.get("case_context", "") or "(사건 맥락 없음)"
    statute_results = state.get("statute_search_results", []) or []
    categories = state.get("categories", []) or []
    categories_str = ", ".join(categories) if categories else "일반 법률"

    # 기존 전문 에이전트들의 분야별 분석 결과 보존 및 맥락 활용
    agent_analyses = []
    agent_results = state.get("agent_results", {}) or {}
    for agent_name, a_res in agent_results.items():
        if isinstance(a_res, dict) and a_res.get("analysis"):
            agent_analyses.append(f"[{agent_name} 전문 분석]:\n{a_res.get('analysis')}")
        elif isinstance(a_res, str) and a_res.strip():
            agent_analyses.append(f"[{agent_name} 전문 분석]:\n{a_res.strip()}")
    agent_context_text = "\n\n".join(agent_analyses) if agent_analyses else "(전문 분야 분석 초안 없음)"

    statute_names = list(dict.fromkeys([
        s.get("statute_name") or s.get("title") or "법령"
        for s in statute_results if s.get("statute_name") or s.get("title")
    ]))
    statute_names_str = ", ".join(statute_names) if statute_names else "관련 법령"

    statute_lines = []
    for s in statute_results:
        law = s.get("statute_name") or s.get("title") or "법령"
        art = s.get("article") or ""
        content = s.get("content") or ""
        url = s.get("source_url") or "https://www.law.go.kr"
        statute_lines.append(f"- 인용 표기: ({law} {art})\n  법령명 및 조문: {law} {art}\n  내용: {content}\n  공식URL: {url}")
    official_statutes_text = "\n\n".join(statute_lines) if statute_lines else "(조회된 공식 법령 없음)"

    # 도메인 중립적 5단계 표준 프롬프트
    prompt = PromptTemplate.from_template(
        "당신은 공인 법률 분석 전문가입니다.\n"
        "의뢰인의 질문과 사건 사실관계, 그리고 외부 공식 법령 검색(법제처 국가법령정보공동활용 open.law.go.kr)에서 새로 확보된 아래 공식 법령 조문 및 전문 에이전트 분석을 바탕으로, 객관적이고 정확한 법률 의견서를 작성하세요.\n\n"
        "[사용자 질문]\n{question}\n\n"
        "[사건 분야 및 맥락]\n분야: {categories_str}\n사건 사실관계: {case_context}\n\n"
        "[기존 전문 에이전트 분석 참고사항]\n{agent_context_text}\n\n"
        "[새로 확보된 공식 법령 조문 원문]\n{official_statutes_text}\n\n"
        "[작성 규칙 및 5단계 표준 구조]\n"
        "특정 사건에 국한된 편향 없이, 사용자의 실제 질문과 사건 유형({categories_str})에 정확히 부합하도록 다음 5개 표준 섹션으로 작성하세요.\n"
        "서두에 불필요한 시스템 실행 경과나 안내 문구를 작성하지 마시고, 곧바로 [1. 핵심 결론]부터 시작하세요.\n\n"
        "[1. 핵심 결론]\n"
        "- 사용자의 핵심 질문에 대해 3줄 이내로 명쾌하게 조건부 또는 확정 가능한 결론을 제시하세요.\n\n"
        "[2. 사건 사실관계 및 증거]\n"
        "- 확인된 핵심 사실관계와 관련된 사건 증거 자료를 객관적으로 정리하세요.\n\n"
        "[3. 쟁점별 법률 분석]\n"
        "- 확보된 공식 법령 조문과 사건 사실을 바탕으로 주요 쟁점별로 다음 5가지 요소를 빠짐없이 심층 분석하세요:\n"
        "  1) 적용 법률요건: 관련 법령 조문 및 판례가 요구하는 법률적 성립 요건\n"
        "  2) 사건 사실과의 연결: 의뢰인의 진술 및 사건 사실이 위 요건에 부합하는지 여부\n"
        "  3) 관련 법령 및 증거: 직접적인 근거가 되는 법조문 `(법령명 제O조)` 및 증거 자료 `(파일명.pdf, p.페이지)`\n"
        "  4) 법률적 판단: 권리 발생, 소멸, 대항력 등 구체적인 법률 효과\n"
        "  5) 남아 있는 불확실성: 상대방의 예상 항변, 추가 입증 필요 사실 등 법적 위험\n\n"
        "[4. 우선순위별 다음 행동]\n"
        "- 사건 유형({categories_str})과 현재 진행 상태에 맞는 우선순위별 구체적인 실행 조치(Action Plan)를 단계별(1단계, 2단계, 3단계 등)로 제시하세요.\n\n"
        "[5. 추가 확인사항]\n"
        "- 소송 및 분쟁 해결 시 주의해야 할 입증 책임, 불확실한 법적 한계 및 실무상 유의사항을 명확히 안내하세요.\n\n"
        "[인용 및 서식 규칙]\n"
        "- 법령 조문 인용 시 가상의 PDF 파일명을 쓰지 마시고, 반드시 `(법령명 제O조)` 형태(예: `(주택임대차보호법 제6조의2)`, `(민법 제598조)`)로 정확하게 인용하세요.\n"
        "- 사건 증거 인용 시 실제 사건 증거 파일명(예: `(차용증.pdf, p.1)`) 형태로 인용하세요.\n"
        "- 섹션 제목은 대괄호 `[제목]` 형태로 작성하고, 중요한 핵심 단어에는 **볼드** 강조를 적절히 사용하세요."
    )
    formatted_prompt = prompt.format(
        question=q,
        categories_str=categories_str,
        case_context=case_ctx,
        agent_context_text=agent_context_text,
        official_statutes_text=official_statutes_text,
    )
    llm = get_llm(temperature=0.0)
    res = llm.invoke(formatted_prompt)
    raw_content = str(res.content) if hasattr(res, "content") else str(res)

    return {
        "draft_answer": raw_content.strip(),
        "revision_count": state.get("revision_count", 0) + 1,
    }



@trace
def intent_analysis_node(state: LegalState) -> Dict:
    """사용자 질문의 의도(ConsultationIntent)와 문맥 복원 질의(resolved_query)를 도출한다.

    후속 질문에서 대명사·생략 표현이 복원되어 resolved_query가 원문 question과 달라진 경우,
    사건 ID가 존재하면 resolved_query로 PostgreSQL + Neo4j 사건 증거를 보강 검색하여
    graph_evidence 및 case_context에 반영한다.
    """
    set_node_name("intent_analysis")
    # 문서 사건은 질문을 변형하거나 과거 AI 결론에 따라 답변 종류를 고정하지 않는다.
    # 지시어 해석에 필요한 이전 사용자 발언은 원문 작성자가 진술로 구분하여 읽는다.
    if state.get("answer_mode") == DOCUMENT_MODE:
        # 순수 인사·감사까지 법률 주장 검증에 넣으면 주장 부재로 불필요하게 답변이 보류된다.
        # 전체 문장 일치만 허용하여 '감사합니다. 그런데 계약은?' 같은 실제 질문은 원문 경로로 남긴다.
        pure_greeting = re.fullmatch(
            r"(?:안녕하세요|안녕|감사합니다|고맙습니다|고마워요|고마워|수고하세요|수고하셨습니다|네|알겠습니다|알겠어요)[.!?~\s]*",
            state.get("question", "").strip(),
        )
        intent = ConsultationIntent.GENERAL_CONVERSATION if pure_greeting else ConsultationIntent.NEW_LEGAL_ANALYSIS
        return {"intent": intent.value,
                "resolved_query": state.get("question", ""), "intent_decision": {}}
    q = state.get("question", "")
    conv_ctx = state.get("conversation_context")
    case_ctx = state.get("case_context") or ""

    from ai_legal_helper.workflows.conversation_context import ConversationContext
    c_obj = None
    if conv_ctx:
        try:
            c_obj = ConversationContext(**conv_ctx) if isinstance(conv_ctx, dict) else conv_ctx
        except Exception:
            c_obj = None

    decision = analyze_consultation_intent(question=q, conversation_context=c_obj, case_context=case_ctx)
    # 의도와 길이만 기록하여 재작성된 상담 원문을 로그에 노출하지 않는다.
    logger.info(f"[의도 분석 완료] 판정 의도={decision.intent.value}, 복원 질의 길이={len(decision.resolved_query)}자")

    updates: Dict[str, Any] = {
        "intent": decision.intent.value,
        "resolved_query": decision.resolved_query,
        "intent_decision": decision.model_dump(),
    }

    # resolved_query가 원문 질문과 다르고 법률/사실 검토가 필요한 경우 사건 증거 보강 검색 수행
    from ai_legal_helper.observability.context import get_case_id
    case_id = get_case_id()
    if (
        case_id
        and decision.resolved_query
        and decision.resolved_query.strip() != q.strip()
        and decision.intent not in (ConsultationIntent.GENERAL_CONVERSATION, ConsultationIntent.NEEDS_CLARIFICATION)
    ):
        from ai_legal_helper.database.session import SessionLocal
        db = SessionLocal()
        try:
            refreshed_ev = _collect_graph_evidence(db, case_id, decision.resolved_query)
            refreshed_text = refreshed_ev.pop("context_text", "")
            prev_ev = dict(state.get("graph_evidence") or {})
            if refreshed_ev.get("valid_paths") or refreshed_ev.get("structured_matches"):
                updates["graph_evidence"] = refreshed_ev
                if refreshed_text and refreshed_text not in case_ctx:
                    updates["case_context"] = f"{case_ctx}\n\n{refreshed_text}" if case_ctx else refreshed_text
            elif not prev_ev:
                updates["graph_evidence"] = refreshed_ev
        except Exception as e:
            logger.warning(f"[NODE:intent_analysis] resolved_query 기반 증거 재검색 실패: {e}")
        finally:
            db.close()

    return updates


def intent_condition(state: LegalState) -> str:
    """의도 분석 결과에 따라 워크플로우 분기 경로를 결정한다."""
    intent_val = state.get("intent")
    if intent_val == ConsultationIntent.GENERAL_CONVERSATION.value:
        return "general_conversation"
    if intent_val == ConsultationIntent.NEEDS_CLARIFICATION.value:
        return "routing_exit"
    if intent_val == ConsultationIntent.FOLLOWUP_ACTION.value:
        return "followup_action"
    return "route"


@trace
def general_conversation_node(state: LegalState) -> Dict:
    """일상적 인사나 감사 표현에 대해 친절하고 전문적인 법률 도우미 안내를 생성한다."""
    set_node_name("general_conversation")
    q = state.get("question", "")
    
    # 간결하고 정중한 인사말 생성
    if any(k in q for k in ["감사", "고마", "수고"]):
        answer = "도움이 되어 기쁩니다. 사건 관련하여 추가로 궁금하신 쟁점이나 절차상 확인이 필요한 사항이 있으시면 언제든지 질문해 주시기 바랍니다."
    else:
        answer = "안녕하세요! 의뢰인님의 법률 문제를 신속하고 정확하게 도와드리는 AI Legal Helper입니다. 현재 사안에 대해 궁금하신 점이나 조언이 필요한 부분을 편하게 말씀해 주세요."

    return {
        "final_answer": answer,
        "draft_answer": answer,
        "final_disposition": "DELIVERED",
        "verification_status": "PASS",
        "categories": [],
        "selected_agents": [],
        "sources": [],
        "cited_sources": [],
        "retrieved_sources": [],
        "warnings": [],
        "messages": [AIMessage(content=answer)],
    }


FOLLOWUP_ACTION_PROMPT = """당신은 전문 변호사이자 실무 법률 가이드입니다.
의뢰인이 앞선 법률 분석을 확인한 후 "이제 뭘 해야 하죠?", "그다음 절차는요?"와 같이 실무적 행동 요령을 묻고 있습니다.

[의뢰인의 현재 질문]
{question}

[이전 상담 대화 맥락]
{conversation_context}

[사건 사실관계 및 확인된 정보]
{case_context}

[작성 지침]
- 복잡한 5단계 법률 의견서 형식을 쓰지 마세요. 불필요한 서론과 법리 반복을 생략하세요.
- 의뢰인이 지금 당장 실천할 수 있는 우선순위별 실행 가이드를 간결하고 명확하게 제시하세요.
- 반드시 다음 3가지 핵심 구조로 작성하세요:
  [1. 핵심 결론 및 우선순위 요약]
  [2. 단계별 구체적 실행 조치] (1단계: 즉시 조치, 2단계: 필수 서류 구비, 3단계: 법적 절차 신청)
  [3. 실무상 유의사항 및 사전 선행조건]
- 이전 상담에서 확인된 사실과 법률 조문이 있다면 일관성 있게 인용하되, 가상의 증거번호나 확인되지 않은 사실을 지어내지 마세요.
"""


@trace
def followup_action_node(state: LegalState) -> Dict:
    """이전 분석 결과를 바탕으로 불필요한 Specialist/RAG 중복 호출 없이 신속한 행동 플랜을 작성한다."""
    set_node_name("followup_action")
    q = state.get("question", "")
    conv_ctx_dict = state.get("conversation_context")
    case_ctx = state.get("case_context") or ""

    from ai_legal_helper.workflows.conversation_context import ConversationContext
    c_obj = None
    conv_summary = "(이전 대화 없음)"
    reusable_sources = []
    if conv_ctx_dict:
        try:
            c_obj = ConversationContext(**conv_ctx_dict) if isinstance(conv_ctx_dict, dict) else conv_ctx_dict
            conv_summary = c_obj.format_context_for_prompt(max_turns=3)
            reusable_sources = c_obj.previously_cited_sources
        except Exception:
            pass

    prompt_str = FOLLOWUP_ACTION_PROMPT.format(
        question=q,
        conversation_context=conv_summary,
        case_context=case_ctx[:1000] if case_ctx else "(사건 정보 없음)",
    )

    llm = get_llm(temperature=0.0)
    res = llm.invoke(prompt_str)
    raw_content = getattr(res, "content", str(res)).strip()

    logger.info(f"[실무 행동 가이드 작성 완료] 생성 분량={len(raw_content)}자")

    return {
        "draft_answer": raw_content,
        "retrieved_sources": reusable_sources,  # 직전 검증된 출처 재사용하여 Verifier Grounding 보장
        "categories": ["민법"],
        "selected_agents": ["민법"],
    }

@trace
def build_legal_graph(checkpointer: Optional[Any] = None):
    """법률 상담 LangGraph 상태 머신을 구성 및 컴파일한다.

    HILT 법령 원문 검색 및 Checkpointer가 포함된다.

    Args:
        checkpointer: 명시적으로 주입할 LangGraph 체크포인터 (미지정 시 get_checkpointer() 사용)

    Returns:
        CompiledStateGraph: 실행 가능한 LangGraph 애플리케이션.
    """
    graph = StateGraph(LegalState)
    graph.add_node("supervisor_initialize", supervisor_initialize_node)
    graph.add_node("intent_analysis", intent_analysis_node)
    graph.add_node("general_conversation", general_conversation_node)
    graph.add_node("followup_action", followup_action_node)
    graph.add_node("route", route_node)
    graph.add_node("plan", plan_node)
    graph.add_node("run_agents", run_agents_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("verification", verification_node)
    graph.add_node("revise", revise_node)
    graph.add_node("insufficient", insufficient_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("statute_search_approval", statute_search_approval_node)
    graph.add_node("execute_statute_search", execute_statute_search_node)
    graph.add_node("re_analyze", re_analyze_node)
    graph.add_node("routing_exit", routing_exit_node)

    graph.add_edge(START, "supervisor_initialize")
    graph.add_edge("supervisor_initialize", "intent_analysis")
    graph.add_conditional_edges("intent_analysis", intent_condition, {
        "general_conversation": "general_conversation",
        "routing_exit": "routing_exit",
        "followup_action": "followup_action",
        "route": "route",
    })
    graph.add_edge("general_conversation", END)
    graph.add_edge("followup_action", "verification")
    graph.add_conditional_edges("route", route_condition, {
        "plan": "plan",
        "routing_exit": "routing_exit",
    })
    graph.add_edge("routing_exit", END)
    graph.add_edge("plan", "run_agents")
    graph.add_edge("run_agents", "synthesize")
    graph.add_edge("synthesize", "verification")

    graph.add_conditional_edges("verification", verification_condition, {
        "finalize": "finalize",
        "statute_search_approval": "statute_search_approval",
        "execute_statute_search": "execute_statute_search",
        "revise": "revise",
        "insufficient": "insufficient"
    })

    graph.add_conditional_edges("statute_search_approval", statute_search_approval_condition, {
        "execute_statute_search": "execute_statute_search",
        "insufficient": "insufficient"
    })

    graph.add_conditional_edges("execute_statute_search", statute_search_result_condition, {
        "re_analyze": "re_analyze",
        "insufficient": "insufficient"
    })

    graph.add_edge("re_analyze", "verification")
    graph.add_edge("revise", "verification")
    graph.add_edge("insufficient", END)
    graph.add_edge("finalize", END)

    if checkpointer is None:
        checkpointer = get_checkpointer()
    app = graph.compile(checkpointer=checkpointer)
    logger.info("[워크플로우 그래프] 통합 법률 상담 엔진(공식 법령 검색 포함) 그래프 빌드 완료")
    return app


async def _execute_consultation(
    question: str,
    thread_id: str,
    resume_data: Optional[Dict[str, Any]],
    checkpointer: Any,
    conversation_context: Optional[Any] = None,
    on_step_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """지정된 체크포인터 환경에서 실제 LangGraph 워크플로우를 실행하고 결과를 수합한다."""
    from ai_legal_helper.observability.langfuse_client import flush_langfuse, get_langfuse_callback_handler

    app = build_legal_graph(checkpointer=checkpointer)
    callbacks = []
    # LangGraph 워크플로우 계측은 @trace 데코레이터와 TokenTrackingCallbackHandler가
    # ContextVar 활성 Span 및 계층적 Generation 추적을 전담하므로,
    # 중복 Generation 집계 방지를 위해 config callbacks에 기본 핸들러를 중복 추가하지 않는다.

    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": callbacks,
    }

    interrupt_payload = None
    try:
        if resume_data is not None:
            # 존재하지 않는 thread_id에 대한 resume 방어 검증
            if hasattr(checkpointer, "aget_tuple"):
                state_tuple = await checkpointer.aget_tuple(config)
            else:
                state_tuple = checkpointer.get_tuple(config)
            if state_tuple is None or not getattr(state_tuple, "checkpoint", None):
                raise ValueError(f"해당 thread_id('{thread_id}')에 대기 중이거나 저장된 워크플로우 상태가 존재하지 않습니다.")

            if on_step_callback:
                async for event in app.astream(Command(resume=resume_data), config, stream_mode="updates"):
                    for node_name in event.keys():
                        if node_name == "__interrupt__":
                            interrupt_payload = event[node_name][0]
                        else:
                            try:
                                if asyncio.iscoroutinefunction(on_step_callback):
                                    await on_step_callback(node_name)
                                else:
                                    on_step_callback(node_name)
                            except Exception as ex:
                                logger.warning(f"[진행 단계 콜백 경고] {node_name} 단계 진행 상태 알림 실패: {ex}")
                state_snapshot = await app.aget_state(config)
                final_state = dict(state_snapshot.values)
                if interrupt_payload is not None:
                    final_state["__interrupt__"] = [interrupt_payload]
            else:
                final_state = await app.ainvoke(Command(resume=resume_data), config)
        else:
            # 대화 맥락 비대화 및 무관한 이전 질의 오염을 방지하기 위해 최근 최대 3개 턴만 메시지 히스토리로 주입
            history_messages = conversation_context.to_chat_history_messages(max_turns=3) if conversation_context and hasattr(conversation_context, "to_chat_history_messages") else []
            conv_id = getattr(conversation_context, "conversation_id", None) or ""
            conv_dump = conversation_context.model_dump() if (conversation_context and hasattr(conversation_context, "model_dump")) else (conversation_context if isinstance(conversation_context, dict) else None)
            t_idx = getattr(conversation_context, "turn_index", 1) or 1
            c_id = getattr(conversation_context, "case_id", None) or (conversation_context.get("case_id") if isinstance(conversation_context, dict) else None)
            if c_id:
                from ai_legal_helper.observability.context import set_case_id
                set_case_id(c_id)

            inputs = {
                "messages": history_messages + [HumanMessage(content=question)],
                "conversation_id": conv_id,
                "conversation_context": conv_dump,
                "turn_index": t_idx,
                "case_id": c_id,
            }
            if on_step_callback:
                async for event in app.astream(inputs, config, stream_mode="updates"):
                    for node_name in event.keys():
                        if node_name == "__interrupt__":
                            interrupt_payload = event[node_name][0]
                        else:
                            try:
                                if asyncio.iscoroutinefunction(on_step_callback):
                                    await on_step_callback(node_name)
                                else:
                                    on_step_callback(node_name)
                            except Exception as ex:
                                logger.warning(f"[진행 단계 콜백 경고] {node_name} 단계 진행 상태 알림 실패: {ex}")
                state_snapshot = await app.aget_state(config)
                final_state = dict(state_snapshot.values)
                if interrupt_payload is not None:
                    final_state["__interrupt__"] = [interrupt_payload]
            else:
                final_state = await app.ainvoke(inputs, config)
    finally:
        flush_langfuse()

    if final_state is None:
        raise ValueError(f"워크플로우 실행 결과가 비어 있습니다. thread_id: {thread_id}")

    # HILT 인터럽트 발생 여부 감지
    if "__interrupt__" in final_state and final_state["__interrupt__"]:
        interrupt_obj = final_state["__interrupt__"][0]
        approval_payload = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj
        logger.info(f"[사용자 승인 대기] 공식 법령 검색 승인을 위해 상담 워크플로우 일시 중단 (스레드: {thread_id})")
        return {
            "status": "APPROVAL_REQUIRED",
            "approval_request": approval_payload,
            "answer": "해당 쟁점에 필요한 공식 법령(특별법 등) 원문 검색을 진행하기 위해 사용자 승인이 필요합니다.",
            "sources": final_state.get("cited_sources") or final_state.get("sources") or [],
            "cited_sources": final_state.get("cited_sources") or [],
            "retrieved_sources": final_state.get("retrieved_sources", []),
            "verification_result": final_state.get("verification_result", {}),
            "warnings": final_state.get("warnings", []),
            "revision_count": final_state.get("revision_count", 0),
            "trace_id": final_state.get("trace_id", ""),
            "request_id": final_state.get("request_id", thread_id),
            "selected_agents": final_state.get("selected_agents", []),
            "routing_status": "CLASSIFIED",
            "conversation_id": final_state.get("conversation_id") or getattr(conversation_context, "conversation_id", None),
            "turn_index": final_state.get("turn_index") or getattr(conversation_context, "turn_index", 1),
            "intent": final_state.get("intent"),
            "resolved_query": final_state.get("resolved_query"),
            "intent_decision": final_state.get("intent_decision"),
            "case_delta": final_state.get("case_delta"),
            "draft_answer": final_state.get("draft_answer"),
        }

    final_answer = final_state.get("final_answer", "답변을 생성하지 못했습니다.")
    final_disp = final_state.get("final_disposition")
    if not final_disp:
        ver_status = (final_state.get("verification_result") or {}).get("status")
        final_disp = "DELIVERED" if ver_status == "PASS" else "WITHHELD"

    from ai_legal_helper.agents.router import RouterStatus
    # 문서 사건에서 분류는 보조 검색용이므로 답변 검증 완료 후 분류 오류를 실행 오류로 덮지 않는다.
    router_st = "CLASSIFIED" if final_state.get("answer_mode") == DOCUMENT_MODE else final_state.get("router_status")
    if router_st == RouterStatus.ROUTER_ERROR.value:
        status_val = "ERROR"
        exec_status = "ERROR"
        routing_status = "ROUTER_ERROR"
    elif router_st == RouterStatus.NEEDS_CLARIFICATION.value:
        status_val = "SUCCESS"
        exec_status = "COMPLETED"
        routing_status = "NEEDS_CLARIFICATION"
    else:
        status_val = "SUCCESS"
        exec_status = "COMPLETED"
        routing_status = "CLASSIFIED"

    return {
        "status": status_val,
        "execution_status": exec_status,
        "routing_status": routing_status,
        "answer": final_answer,
        "final_disposition": final_disp,
        "sources": final_state.get("cited_sources") or final_state.get("sources") or [],
        "cited_sources": final_state.get("cited_sources") or [],
        "retrieved_sources": final_state.get("retrieved_sources", []),
        "verification_result": final_state.get("verification_result", {}),
        "verification_status": (final_state.get("verification_result") or {}).get("status") or final_state.get("verification_status", "UNVERIFIED"),
        "warnings": final_state.get("warnings", []),
        "revision_count": final_state.get("revision_count", 0),
        "trace_id": final_state.get("trace_id", ""),
        "request_id": final_state.get("request_id", thread_id),
        "selected_agents": final_state.get("selected_agents", []),
        "approval_request": final_state.get("approval_request"),
        "approval_status": final_state.get("approval_status"),
        "conversation_id": final_state.get("conversation_id") or getattr(conversation_context, "conversation_id", None),
        "turn_index": final_state.get("turn_index") or getattr(conversation_context, "turn_index", 1),
        "intent": final_state.get("intent"),
        "resolved_query": final_state.get("resolved_query"),
        "intent_decision": final_state.get("intent_decision"),
    }


@trace
async def run_legal_consultation(
    question: str, 
    thread_id: str, 
    resume_data: Optional[Dict[str, Any]] = None,
    checkpointer: Optional[Any] = None,
    conversation_context: Optional[Any] = None,
    on_step_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """법률 상담 슈퍼바이저 워크플로우를 실행하고 최종 답변, 출처 또는 승인 대기 상태를 반환한다.

    Args:
        question: 사용자의 법률 질의 내용
        thread_id: 대화 스레드 또는 요청 식별자
        resume_data: HILT 승인/거절 시 재개를 위한 사용자 결정 데이터 (예: {"approved": True})
        checkpointer: 명시적으로 주입할 체크포인터 (미지정 시 환경설정에 따라 자동 선택)
        conversation_context: 연속 대화 맥락 객체 (ConversationContext)
        on_step_callback: LangGraph 개별 노드 완료 시 호출되는 진행 상태 콜백 (Callable[[str], Any])

    Returns:
        Dict[str, Any]: 상담 처리 결과 딕셔너리.
            - HILT 인터럽트 발생 시: `status: "APPROVAL_REQUIRED"`, `approval_request: {...}`
            - 정상 완료 시: `status: "SUCCESS"`, `answer: "..."`, `sources: [...]`
    """
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    if checkpointer is not None:
        return await _execute_consultation(question, thread_id, resume_data, checkpointer, conversation_context=conversation_context, on_step_callback=on_step_callback)

    checkpointer_type = os.getenv("CHECKPOINTER_TYPE", "postgres").lower()
    if checkpointer_type == "memory" or AsyncPostgresSaver is None:
        if AsyncPostgresSaver is None and checkpointer_type != "memory":
            logger.warning(
                "[CHECKPOINTER_FALLBACK] langgraph-checkpoint-postgres 모듈이 설치되지 않아 "
                "로컬 MemorySaver로 폴백합니다. 영구 체크포인팅을 위해 pip install langgraph-checkpoint-postgres가 권장됩니다."
            )
        mem_saver = get_memory_checkpointer()
        return await _execute_consultation(question, thread_id, resume_data, mem_saver, conversation_context=conversation_context, on_step_callback=on_step_callback)
    else:
        conn_string = get_postgres_conn_string()
        async with AsyncPostgresSaver.from_conn_string(conn_string) as pg_saver:
            return await _execute_consultation(question, thread_id, resume_data, pg_saver, conversation_context=conversation_context, on_step_callback=on_step_callback)


