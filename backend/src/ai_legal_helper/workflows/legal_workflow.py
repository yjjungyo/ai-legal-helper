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
from typing import Dict, List, Any, Optional
import os
import uuid
import asyncio
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from langgraph.constants import Send
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

logger = get_logger(__name__)

_checkpointer_instance = None

def get_checkpointer():
    """LangGraph 체크포인터를 획득한다.

    비동기 워크플로우(ainvoke)와의 완벽한 호환성 및 Windows 비동기 루프 안정성을 위해
    MemorySaver 인스턴스를 제공한다.
    모든 상담 요청과 HILT 승인 대기 정보는 PostgreSQL DB(ConsultationRecord)에
    실시간으로 영구 저장되어 서버 재시작 후에도 완벽히 보존된다.

    Returns:
        BaseCheckpointSaver: MemorySaver 인스턴스.
    """
    global _checkpointer_instance
    if _checkpointer_instance is None:
        _checkpointer_instance = MemorySaver()
    return _checkpointer_instance


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
        "approval_request": None,
        "approval_status": "NONE",
        "statute_search_results": [],
        "hilt_executed": False,
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
        # Neo4j 드라이버가 None이더라도 GraphRAGRetriever.search_hybrid 내부의 ChromaDB 벡터 폴백을 실행한다.
        result = GraphRAGRetriever(driver).search_hybrid(case_id, question)
        checked = (
            validate_graph_paths(db, case_id, result.get("traversal_paths", []))
            if result.get("traversal_paths")
            else {"valid": [], "invalid": [], "checked": 0}
        )
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
        # Fallback: add vector matches as StandardSource(CASE_EVIDENCE, HYBRID_VECTOR_FALLBACK)
        from ai_legal_helper.rag.source_schema import build_source_from_vector_match
        for v in vector_matches[:10]:
            extra_sources.append(build_source_from_vector_match(v))

    combined_sources = sources + extra_sources
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
        warnings.append(f"상충하는 증거가 존재하는 항목이 {len(graph_ev['contradictions'])}건 있습니다.")

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
        logger.debug(f"Langfuse log_score in verification_node failed: {ex}")

    return {
        "verification_result": result,
        "retrieved_sources": verified_sources,
    }

def verification_condition(state: LegalState) -> str:
    """법률 답변의 검증 결과에 따라 다음 실행 단계(Node)를 결정한다.

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
    ver_res = state.get("verification_result", {}) or {}
    status = ver_res.get("status", "PASS")
    reason_code = ver_res.get("reason_code", "NONE")
    candidate_laws = ver_res.get("candidate_laws", [])
    hilt_executed = state.get("hilt_executed", False)
    revision_count = state.get("revision_count", 0)

    # 1. 모든 필수 검증을 통과했다면 최종 확정
    if status == "PASS":
        return "finalize"

    # 2. 법률 근거 부족이 원인이고 후보 법령이 식별된 경우 HILT 법령 검색 승인 요청 (1회 한정)
    if not hilt_executed and candidate_laws and (
        reason_code in ("LEGAL_SOURCE_MISSING", "LEGAL_SOURCE_INSUFFICIENT")
        or (status in ("INSUFFICIENT", "REVISE") and reason_code != "NONE")
    ):
        return "statute_search_approval"

    # 3. 최초 검증 실패 시(REVISE 또는 일반 INSUFFICIENT) 1회에 한해 적응형 보강 검색(revise) 시도
    if revision_count < 1:
        return "revise"

    # 4. HILT 공식 법령 원문 검색이 완료된 상태:
    #    사용자 승인을 거쳐 공식 법령 원문이 확보되었고 재분석된 상태이므로, 혹시 남아있을 수 있는 미검증 인용은
    #    finalize_node의 sanitize_unverified_citations를 거쳐 깨끗이 정화한 후 최종 확정(finalize)으로 종결한다.
    if hilt_executed:
        return "finalize"

    # 5. 이미 재검토를 거쳤음에도 미통과 시 안전 종료
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
        "3. 만약 질문이 주택임대차보호법 등 특별법에 관한 것이나 검색된 출처에 해당 조문이 없다면, 일반 민법 규정을 단정적으로 적용하지 마시고 특별법 관련 근거 자료가 부족함을 명확히 명시하세요.\n"
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
    """근거 부족(INSUFFICIENT) 판정 시 검증 지적사항과 모순을 마크다운 기호 없는 표준 플레인 텍스트로 안내한다."""
    set_node_name("insufficient")
    from ai_legal_helper.agents.verification import sanitize_unverified_citations
    from ai_legal_helper.utils.text_formatter import clean_markdown_formatting

    sanitized_draft = sanitize_unverified_citations(
        state.get("draft_answer", ""),
        state.get("retrieved_sources", []),
        case_context=state.get("case_context", ""),
    )

    ver_res = state.get("verification_result", {}) or {}
    missing_issues = ver_res.get("missing_issues", []) or []
    contradictions = ver_res.get("contradictions", []) or []
    warnings_list = ver_res.get("warnings", []) or []

    # 구조화된 법률의견서 플레인 텍스트 구성
    parts = []
    parts.append("[안내: 법률적 근거 부족으로 인한 검증 안내 - INSUFFICIENT]\n")
    parts.append("질문하신 사안에 대해 데이터베이스 내 관련 법령(특별법 등) 조문 또는 판례 근거가 충분히 확보되지 않았거나, "
                 "인용된 법조문과의 법률적 모순이 확인되어 확정적인 법률 조언을 제공할 수 없습니다.\n")

    if missing_issues:
        parts.append("[1. 확인이 필요한 핵심 쟁점 및 법령 누락]")
        for issue in missing_issues:
            parts.append(f"- {issue}")
        parts.append("")

    if contradictions:
        parts.append("[2. 감지된 법률적 모순 및 불일치]")
        for contra in contradictions:
            parts.append(f"- {contra}")
        parts.append("")

    if warnings_list:
        parts.append("[3. 법률검증 Agent(Verification) 주의사항]")
        for w in warnings_list:
            parts.append(f"- {w}")
        parts.append("")

    parts.append("========================================\n")
    parts.append("[참고: 미검증 참고 초안 (법적 효력 없음)]")
    parts.append("경고: 아래 내용은 검색된 제한적 자료를 바탕으로 작성된 미검증 초안으로, "
                 "실제 법률 사실과 다르거나 잘못된 법조문이 적용되었을 위험이 있습니다. "
                 "절대 법적 판단이나 행동의 근거로 사용하지 마시고, 반드시 변호사 또는 대한법률구조공단 등 전문기관의 개별 상담을 받으시기 바랍니다.\n")
    parts.append(clean_markdown_formatting(sanitized_draft))

    final = clean_markdown_formatting("\n".join(parts))
    warnings = state.get("warnings", []) + ["답변의 근거가 부족하여 INSUFFICIENT 처리되었습니다."]
    return {
        "final_answer": final,
        "warnings": warnings,
        "messages": [HumanMessage(content="dummy", name="system"), final]
    }

@trace
def finalize_node(state: LegalState) -> Dict:
    """검증 통과 시 혹시 남아 있을 수 있는 미검증 인용을 정화하고 마크다운 기호를 정제하여 답변을 확정한다."""
    set_node_name("finalize")
    from ai_legal_helper.agents.verification import sanitize_unverified_citations
    from ai_legal_helper.utils.text_formatter import clean_markdown_formatting

    sanitized = sanitize_unverified_citations(
        state.get("draft_answer", ""),
        state.get("retrieved_sources", []),
        case_context=state.get("case_context", ""),
    )
    final = clean_markdown_formatting(sanitized)
    
    # 법률검증 Agent의 실무 권고 및 유의사항(warnings)을 정제하여 전달
    ver_res = state.get("verification_result", {}) or {}
    warnings = list(state.get("warnings", []) or [])
    ver_warnings = ver_res.get("warnings", []) or []
    for w in ver_warnings:
        if w not in warnings:
            warnings.append(w)

    return {
        "final_answer": final,
        "warnings": warnings,
        "messages": [final] # append to MessagesState
    }


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
    explanation = ver_res.get("explanation", "현재 검색된 법률 자료만으로는 해당 쟁점을 충분히 검증할 수 없습니다.")

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

    logger.info(f"[HILT:statute_search_approval] decision={approved}, reason={user_reason}")
    return {
        "approval_request": approval_payload,
        "approval_status": "APPROVED" if approved else "REJECTED",
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

    ver_res = state.get("verification_result", {}) or {}
    candidate_laws = list(ver_res.get("candidate_laws", []) or [])
    missing_issues = ver_res.get("missing_legal_issues", []) or ver_res.get("missing_issues", [])
    q = state.get("question", "")

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
    """공식 법령 원문 검색으로 확보된 법령 조문을 바탕으로 법률 분석을 재수행하고 답변을 재작성한다.

    법률검증 Agent의 1차 검토 경과와 법제처 국가법령정보공동활용(open.law.go.kr) API를 통한 공식 법령 출처
    및 조문 원문이 답변에 어떻게 반영되었는지 서두에 명확히 밝히도록 작성한다.

    Args:
        state: 현재 LangGraph 워크플로우 상태.

    Returns:
        Dict: 재작성된 초안(`draft_answer`), 증가된 재검토 횟수(`revision_count`).
    """
    set_node_name("re_analyze")
    from ai_legal_helper.llm.gateway import get_llm
    from ai_legal_helper.utils.text_formatter import clean_markdown_formatting
    from langchain_core.prompts import PromptTemplate

    q = state.get("question", "")
    case_ctx = state.get("case_context", "") or "(사건 맥락 없음)"
    statute_results = state.get("statute_search_results", []) or []

    statute_names = list(dict.fromkeys([
        s.get("statute_name") or s.get("title") or "법령"
        for s in statute_results if s.get("statute_name") or s.get("title")
    ]))
    statute_names_str = ", ".join(statute_names) if statute_names else "관련 특별법"

    statute_lines = []
    for s in statute_results:
        law = s.get("statute_name") or s.get("title") or "법령"
        art = s.get("article") or ""
        content = s.get("content") or ""
        fname = s.get("filename") or f"{law}_{art}.txt"
        url = s.get("source_url") or "https://www.law.go.kr"
        statute_lines.append(f"- 인용 표기: ({fname}, p.1)\n  법령명 및 조문: {law} {art}\n  내용: {content}\n  공식URL: {url}")
    official_statutes_text = "\n\n".join(statute_lines) if statute_lines else "(조회된 공식 법령 없음)"

    # 동적 조문 요약 목록 (하드코딩 배제: 조회된 실제 법령 및 조문 번호만 추출)
    retrieved_articles = [
        f"{s.get('statute_name', '')} {s.get('article', '')}".strip()
        for s in statute_results if s.get("article")
    ]
    retrieved_articles_summary = ", ".join(dict.fromkeys([a for a in retrieved_articles if a])) or statute_names_str

    prompt = PromptTemplate.from_template(
        "당신은 공인 법률 분석 전문가입니다.\n"
        "내부 데이터베이스 검색 결과 법률 근거 부족으로 인해 법률검증 Agent의 검토를 거쳐, 의뢰인의 승인(HITL) 후 외부 공식 법령 원문 검색 시스템(법제처 국가법령정보공동활용 open.law.go.kr)에서 아래의 신뢰할 수 있는 공식 법령 조문을 확보했습니다.\n\n"
        "[사용자 질문]\n{question}\n\n"
        "[사건 맥락]\n{case_context}\n\n"
        "[새로 확보된 공식 법령 원문]\n{official_statutes_text}\n\n"
        "[작성 규칙]\n"
        "1. [필수 서두 안내 작성]\n"
        "   답변의 맨 처음에 반드시 다음 형식의 [공식 법령 원문 연동 및 근거 보강 안내] 섹션을 작성하세요:\n"
        "   [공식 법령 원문 연동 및 근거 보강 안내]\n"
        "   - 보강 경과: 1차 검토 결과 질문의 핵심 쟁점을 직접 규율하는 법령 조문이 내부 DB에 부재하여 법률검증 Agent에 의해 근거 보강이 요청되었습니다.\n"
        "   - 공식 출처: 의뢰인의 승인(HITL)을 거쳐 법제처 국가법령정보공동활용 시스템(open.law.go.kr)에서 {statute_names_str} 조문을 실시간으로 공식 조회하였습니다.\n"
        "   - 반영 근거: 확보된 공식 법령 조문 원문({retrieved_articles_summary})을 바탕으로 질문의 핵심 법률 쟁점 및 당사자의 법적 권리·의무 관계를 재분석하여 작성하였습니다.\n\n"
        "2. 반드시 위 [새로 확보된 공식 법령 원문]의 구체적인 조문 내용과 사건 맥락을 종합하여 정확하고 명확한 법률 의견을 제시하세요. 검색된 법령 원문에 없는 법률 효과를 단정하지 마시고, 입증이 필요한 사항은 실무상 주의사항으로 명확히 안내하세요.\n"
        "3. 법령 조문 인용 시 위 [새로 확보된 공식 법령 원문]에 기재된 `(파일명, p.1)` 형태를 정확하게 1회만 사용하여 인용하세요. 중복 괄호 `(( ... ))`를 작성하지 마세요.\n"
        "4. 마크다운 특수문자(#, ##, ###, **, *, ---, > 등)를 일체 사용하지 마세요. 화면에 마크다운 기호가 그대로 노출되므로 [제목], 1., 2., - 불릿 등의 일반 플레인 텍스트로만 정돈하여 작성하세요."
    )
    llm = get_llm(temperature=0.0)
    res = (prompt | llm).invoke({
        "question": q,
        "case_context": case_ctx,
        "official_statutes_text": official_statutes_text,
        "statute_names_str": statute_names_str,
        "retrieved_articles_summary": retrieved_articles_summary,
    })
    raw_content = str(res.content) if hasattr(res, "content") else str(res)
    cleaned_draft = clean_markdown_formatting(raw_content)

    return {
        "draft_answer": cleaned_draft,
        "revision_count": state.get("revision_count", 0) + 1,
    }


@trace
def build_legal_graph():
    """법률 상담 LangGraph 상태 머신을 구성 및 컴파일한다.

    HILT 법령 원문 검색 및 Checkpointer가 포함된다.

    Returns:
        CompiledStateGraph: 실행 가능한 LangGraph 애플리케이션.
    """
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
    graph.add_node("statute_search_approval", statute_search_approval_node)
    graph.add_node("execute_statute_search", execute_statute_search_node)
    graph.add_node("re_analyze", re_analyze_node)

    graph.add_edge(START, "supervisor_initialize")
    graph.add_edge("supervisor_initialize", "route")
    graph.add_edge("route", "plan")
    graph.add_edge("plan", "run_agents")
    graph.add_edge("run_agents", "synthesize")
    graph.add_edge("synthesize", "verification")

    graph.add_conditional_edges("verification", verification_condition, {
        "finalize": "finalize",
        "statute_search_approval": "statute_search_approval",
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

    checkpointer = get_checkpointer()
    app = graph.compile(checkpointer=checkpointer)
    logger.info("[GRAPH] Unified Legal Engine (with HILT Statute Search) build complete")
    return app


@trace
async def run_legal_consultation(
    question: str, 
    thread_id: str, 
    resume_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """법률 상담 슈퍼바이저 워크플로우를 실행하고 최종 답변, 출처 또는 승인 대기 상태를 반환한다.

    Args:
        question: 사용자의 법률 질의 내용
        thread_id: 대화 스레드 또는 요청 식별자
        resume_data: HILT 승인/거절 시 재개를 위한 사용자 결정 데이터 (예: {"approved": True})

    Returns:
        Dict[str, Any]: 상담 처리 결과 딕셔너리.
            - HILT 인터럽트 발생 시: `status: "APPROVAL_REQUIRED"`, `approval_request: {...}`
            - 정상 완료 시: `status: "SUCCESS"`, `answer: "..."`, `sources: [...]`
    """
    from ai_legal_helper.observability.langfuse_client import flush_langfuse, get_langfuse_callback_handler

    app = build_legal_graph()
    callbacks = []
    lf_cb = get_langfuse_callback_handler()
    if lf_cb:
        callbacks.append(lf_cb)

    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": callbacks,
    }

    try:
        if resume_data is not None:
            final_state = await app.ainvoke(Command(resume=resume_data), config)
        else:
            inputs = {"messages": [HumanMessage(content=question)]}
            final_state = await app.ainvoke(inputs, config)
    finally:
        flush_langfuse()

    # HILT 인터럽트 발생 여부 감지
    if "__interrupt__" in final_state and final_state["__interrupt__"]:
        interrupt_obj = final_state["__interrupt__"][0]
        approval_payload = interrupt_obj.value if hasattr(interrupt_obj, "value") else interrupt_obj
        logger.info(f"[RUN_LEGAL_CONSULTATION] Interrupted for approval on thread {thread_id}")
        return {
            "status": "APPROVAL_REQUIRED",
            "approval_request": approval_payload,
            "answer": "해당 쟁점에 필요한 공식 법령(특별법 등) 원문 검색을 진행하기 위해 사용자 승인이 필요합니다.",
            "sources": final_state.get("retrieved_sources", []),
            "verification_result": final_state.get("verification_result", {}),
            "warnings": final_state.get("warnings", []),
            "revision_count": final_state.get("revision_count", 0),
            "trace_id": final_state.get("trace_id", ""),
            "request_id": final_state.get("request_id", thread_id),
            "selected_agents": final_state.get("selected_agents", []),
        }

    final_answer = final_state.get("final_answer", "답변을 생성하지 못했습니다.")

    return {
        "status": "SUCCESS",
        "answer": final_answer,
        "sources": final_state.get("retrieved_sources", []),
        "verification_result": final_state.get("verification_result", {}),
        "warnings": final_state.get("warnings", []),
        "revision_count": final_state.get("revision_count", 0),
        "trace_id": final_state.get("trace_id", ""),
        "request_id": final_state.get("request_id", thread_id),
        "selected_agents": final_state.get("selected_agents", []),
        "approval_request": final_state.get("approval_request"),
        "approval_status": final_state.get("approval_status"),
    }

