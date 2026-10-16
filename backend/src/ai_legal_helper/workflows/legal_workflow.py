# -*- coding: utf-8 -*-
"""
모듈명: legal_workflow.py

[모듈 개요]
법률 상담 과정에서 여러 전문 Agent의 실행을 관리하는 Supervisor 워크플로우를 정의한다.

[주요 기능]
1. 사용자 질문 라우팅 및 계획 수립
2. 전문 Agent 병렬 실행
3. 종합 답변(Synthesize) 생성
4. 수석 검증관(Verification)을 통한 Grounding 체크
5. 검증 결과에 따른 재검토 및 최종 상태(PASS/REVISE/INSUFFICIENT) 결정

[처리 흐름]
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
- 재검토 횟수는 최대 1회로 제한된다. 무한 루프를 방지한다.
- 비동기 `run_agents_node` 호출 시 ContextVar의 복제 동작을 위해 파이썬 내장 `asyncio.to_thread`를 사용한다.
"""
from typing import Dict, List, Any
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
import operator
from typing import Annotated

from ai_legal_helper.workflows.state import LegalState
from ai_legal_helper.agents.router import route_categories
from ai_legal_helper.agents.planner import plan_tools
from ai_legal_helper.agents.specialist import run_specialist_agent
from ai_legal_helper.agents.synthesizer import synthesize
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.observability.context import set_node_name
from langgraph.constants import Send
import asyncio

logger = get_logger(__name__)

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
    case_id = get_case_id()
    
    case_context = ""
    # 사건이 지정되지 않은 일반 상담에서는 GraphRAG 를 사용하지 않는다.
    graph_evidence: Dict[str, Any] = {"available": False, "valid_paths": [], "invalid_count": 0,
                                      "evidence_gaps": [], "contradictions": []}
    if case_id:
        db = SessionLocal()
        try:
            case = db.query(Case).filter(Case.id == case_id).first()
            if case:
                facts = db.query(Fact).filter(Fact.case_id == case_id).all()
                events = db.query(Event).filter(Event.case_id == case_id).order_by(Event.event_date).all()
                
                # Fetch approved evidence claims to serve as case evidence
                approved_claims = db.query(EvidenceClaim).filter(
                    EvidenceClaim.case_id == case_id,
                    EvidenceClaim.review_status == "APPROVED"
                ).all()

                context_parts = [f"[사건 기본 정보]\n제목: {case.title}"]
                if facts:
                    fact_lines = "\n".join([f"- {f.statement} (유형: {f.fact_type}, 신뢰도: {f.confidence})" for f in facts])
                    context_parts.append(f"\n[기존 사실관계]\n{fact_lines}")
                if events:
                    event_lines = "\n".join([f"- {e.event_date or '날짜미상'}: {e.title}" for e in events])
                    context_parts.append(f"\n[타임라인]\n{event_lines}")
                if approved_claims:
                    claim_lines = "\n".join([f"- {c.statement} (종류: {c.claim_type}, 파일ID: {c.evidence_id})" for c in approved_claims])
                    context_parts.append(f"\n[사건 증거(승인된 추출 정보)]\n{claim_lines}")

                case_context = "\n".join(context_parts)
                
                # [P2.4 GraphRAG 통합]
                # 그래프 검색 → PostgreSQL 대조 검증 → 검증 통과 경로만 컨텍스트에 추가한다.
                # Neo4j 장애/미구성 시 graph_evidence.available=False 로 기존 흐름을 그대로 진행한다.
                graph_evidence = _collect_graph_evidence(db, case_id, q or "")
                graph_text = graph_evidence.pop("context_text", "")
                if graph_text:
                    case_context += "\n\n" + graph_text
                    
        finally:
            db.close()
            
    return {
        "request_id": req_id,
        "trace_id": trace_id,
        "question": q or "(질문 미확인)",
        "revision_count": 0,
        "warnings": [],
        "retrieved_sources": [],
        "case_context": case_context,
        "graph_evidence": graph_evidence,
    }


def _collect_graph_evidence(db, case_id: str, question: str) -> Dict[str, Any]:
    """사건 그래프에서 질문 관련 증거 경로를 검색하고 코드 레벨로 검증한다.

    Args:
        db: SQLAlchemy 세션(검증용).
        case_id: 사건 ID.
        question: 사용자 질문(키워드 추출 대상).

    Returns:
        {available, valid_paths, invalid_count, evidence_gaps, contradictions, context_text}
        context_text 는 호출자가 꺼내 쓴 뒤 state 에서는 제거한다(중복 저장 방지).

    Notes:
        어떤 예외도 전파하지 않는다. GraphRAG 는 보조 근거이므로 실패해도 상담은 계속된다.
    """
    empty = {"available": False, "valid_paths": [], "invalid_count": 0,
             "evidence_gaps": [], "contradictions": [], "context_text": ""}
    try:
        from ai_legal_helper.database.neo4j import get_neo4j_driver
        from ai_legal_helper.rag.graph_rag import (
            GraphRAGRetriever, validate_graph_paths, format_graph_context,
        )
        driver = get_neo4j_driver()
        if driver is None:
            return empty
        result = GraphRAGRetriever(driver).search_hybrid(case_id, question)
        checked = validate_graph_paths(db, case_id, result.get("traversal_paths", []))
        if checked["invalid"]:
            # 원문 대신 ID/사유만 기록 (개인정보 보호)
            logger.warning(f"[GRAPH_RAG] 검증 실패 경로 {len(checked['invalid'])}건 제외")
        return {
            "available": result.get("available", False),
            "valid_paths": checked["valid"],
            "vector_matches": result.get("vector_matches", []),
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
    set_node_name("route")
    q = state.get("question", "(질문 미확인)")
    cats = route_categories(q)
    logger.debug(f"[NODE:route] q_len={len(q)} cats={cats}")
    return {"categories": cats, "selected_agents": cats}

@trace
def plan_node(state: LegalState) -> Dict:
    set_node_name("plan")
    cats = state.get("categories", [])
    plan = plan_tools(cats)
    logger.debug(f"[NODE:plan] plan={plan}")
    return {"plan": plan, "analysis_plan": plan}

@trace
async def run_agents_node(state: LegalState) -> Dict:
    set_node_name("run_agents")
    cats = state.get("categories", [])
    q = state.get("question", "")
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

    tasks = [_run_agent_with_ctx(c) for c in cats]
    responses = await asyncio.gather(*tasks)
    
    for cat, text, sources in responses:
        results[cat] = text
        all_sources.extend(sources)

    logger.debug(f"[NODE:run_agents] done: {list(results.keys())}")
    return {"results": results, "agent_results": results, "retrieved_sources": all_sources}

@trace
def synthesize_node(state: LegalState) -> Dict:
    set_node_name("synthesize")
    msgs = synthesize(state.get("messages", []), state.get("results", {}))
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
    from ai_legal_helper.agents.verification import run_verification
    from ai_legal_helper.rag.graph_rag import graph_paths_to_sources, validate_graph_paths
    from ai_legal_helper.observability.context import get_case_id

    q = state.get("question", "")
    draft = state.get("draft_answer", "")
    sources = list(state.get("retrieved_sources", []))
    graph_ev = state.get("graph_evidence") or {}
    graph_paths = graph_ev.get("valid_paths", [])
    vector_matches = graph_ev.get("vector_matches", [])

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

    extra_sources = graph_paths_to_sources(graph_paths)
    if not graph_ev.get("available") and vector_matches:
        # Fallback: add vector matches as sources so Verification Agent can ground against them
        for v in vector_matches[:10]:
            extra_sources.append({
                "source_id": f"VECTOR:{v.get('node_id')}",
                "category": "EVIDENCE_VECTOR",
                "content": f"{v.get('node_type')}: {v.get('content')}",
            })

    result = run_verification(q, draft, sources + extra_sources,
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
        warnings.append(f"상충하는 증거가 존재하는 항목이 {len(graph_ev['contradictions'])}건 있습니다.")

    result["warnings"] = warnings
    result["graph_checks"] = graph_checks
    return {"verification_result": result}

def verification_condition(state: LegalState) -> str:
    """법률 답변의 검증 결과에 따라 다음 실행 단계(Node)를 결정한다.

    Supervisor가 Verification Agent의 결과(`PASS`, `REVISE`, `INSUFFICIENT`)를 바탕으로
    답변을 확정할지, 재검토할지, 근거 부족으로 종료할지 라우팅한다.

    Args:
        state: 
            현재까지의 워크플로우 상태 (verification_result, revision_count 포함).

    Returns:
        다음 이동할 LangGraph Node의 이름.
        - 'finalize': 검증 통과 (PASS)
        - 'revise': 수정 필요 (REVISE)
        - 'insufficient': 근거 부족 (INSUFFICIENT)

    Notes:
        무한 재검토 루프를 막기 위해 `revision_count`가 1 이상일 경우
        `REVISE` 상태라도 `insufficient` 노드로 강제 이동한다.
    """
    status = state.get("verification_result", {}).get("status", "PASS")
    
    # 1. 모든 필수 검증을 통과했다면 최종 확정
    if status == "PASS":
        return "finalize"
        
    # 2. 완전한 근거 부족인 경우
    elif status == "INSUFFICIENT":
        return "insufficient"
        
    # 3. 수정이 필요하고 아직 재검토하지 않았다면 revise
    else: # REVISE
        if state.get("revision_count", 0) >= 1:
            return "insufficient"
        return "revise"

@trace
def revise_node(state: LegalState) -> Dict:
    set_node_name("revise")
    from ai_legal_helper.llm.gateway import get_llm
    from langchain_core.prompts import PromptTemplate
    
    instructions = state.get("verification_result", {}).get("revision_instructions", [])
    draft = state.get("draft_answer", "")
    
    inst_text = "\n- ".join(instructions) if instructions else "답변을 출처에 맞게 수정하세요."
    
    prompt = PromptTemplate.from_template(
        "당신은 법률 답변 수정 전문가입니다.\n기존 답변에 근거가 부족하거나 누락된 쟁점이 있습니다.\n"
        "[수정 지침]\n- {instructions}\n\n[기존 답변]\n{draft}\n\n"
        "지침을 반영하여 답변을 다시 작성하세요. 거짓된 법률 정보나 없는 출처를 지어내지 마세요."
    )
    llm = get_llm(temperature=0.0)
    res = (prompt | llm).invoke({"instructions": inst_text, "draft": draft})
    
    return {
        "draft_answer": res.content,
        "revision_count": 1 # we use 1 to signal we revised
    }

@trace
def insufficient_node(state: LegalState) -> Dict:
    set_node_name("insufficient")
    final = state.get("draft_answer", "") + "\n\n[안내] 답변의 일부 주장에 대한 법률적 근거가 부족하여, 참고용으로만 활용하시기 바랍니다."
    warnings = state.get("warnings", []) + ["답변의 근거가 부족하여 INSUFFICIENT 처리되었습니다."]
    return {
        "final_answer": final,
        "warnings": warnings,
        "messages": [HumanMessage(content="dummy", name="system"), final] # we just append final
    }

@trace
def finalize_node(state: LegalState) -> Dict:
    set_node_name("finalize")
    final = state.get("draft_answer", "")
    return {
        "final_answer": final,
        "messages": [final] # append to MessagesState
    }

@trace
def build_legal_graph():
    graph = StateGraph(LegalState)
    graph.add_node("supervisor_initialize", supervisor_initialize_node)
    graph.add_node("route", route_node)
    graph.add_node("plan", plan_node)
    graph.add_node("run_agents", run_agents_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("verification", verification_node)
    graph.add_node("revise", revise_node)
    graph.add_node("insufficient", insufficient_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "supervisor_initialize")
    graph.add_edge("supervisor_initialize", "route")
    graph.add_edge("route", "plan")
    graph.add_edge("plan", "run_agents")
    graph.add_edge("run_agents", "synthesize")
    graph.add_edge("synthesize", "verification")
    
    graph.add_conditional_edges("verification", verification_condition, {
        "finalize": "finalize",
        "insufficient": "insufficient",
        "revise": "revise"
    })
    
    graph.add_edge("revise", "verification")
    graph.add_edge("insufficient", END)
    graph.add_edge("finalize", END)

    app = graph.compile(checkpointer=MemorySaver())
    logger.info("[GRAPH] Unified Legal Engine (with Supervisor/Verification) build complete")
    return app

@trace
async def run_legal_consultation(question: str, thread_id: str) -> Dict[str, Any]:
    """법률 상담 슈퍼바이저 워크플로우를 실행하고 최종 답변 및 출처를 반환한다.

    Args:
        question: 사용자의 법률 질의 내용
        thread_id: 대화 스레드 또는 요청 식별자

    Returns:
        Dict[str, Any]: 답변(answer), 참조 출처(sources), 검증 결과(verification_result) 등을 포함한 결과 딕셔너리
    """
    from ai_legal_helper.observability.langfuse_client import flush_langfuse

    app = build_legal_graph()
    config = {
        "configurable": {"thread_id": thread_id},
    }
    inputs = {"messages": [HumanMessage(content=question)]}

    try:
        final_state = await app.ainvoke(inputs, config)
    finally:
        flush_langfuse()

    final_answer = final_state.get("final_answer", "답변을 생성하지 못했습니다.")

    return {
        "answer": final_answer,
        "sources": final_state.get("retrieved_sources", []),
        "verification_result": final_state.get("verification_result", {}),
        "warnings": final_state.get("warnings", []),
        "revision_count": final_state.get("revision_count", 0),
        "trace_id": final_state.get("trace_id", ""),
        "request_id": final_state.get("request_id", ""),
        "selected_agents": final_state.get("selected_agents", []),
    }
