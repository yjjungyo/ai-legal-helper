# -*- coding: utf-8 -*-
"""
모듈명: decorators.py

[모듈 개요]
함수 및 코루틴 실행 전후의 구조화 로깅, OpenTelemetry Span 기록, Langfuse Trace/Span 계층 추적을
자동화하는 `@trace` 데코레이터 모듈이다.

[주요 기능]
1. 실행 시작/성공/오류 시점의 소요 시간(elapsed_ms) 및 소스 위치 한국어 로깅
2. 상위 Span ID(`prev_span_id`)를 보존하여 중첩 `@trace` 호출 시 부모-자식 Span 트리 구성
3. 예외 발생 시 API 키, 토큰, 이메일, 전화번호, 주민등록번호 등 민감정보(PII) 자동 마스킹
"""
import functools
import inspect
import time
import uuid
from typing import Callable, Any, Optional
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.observability.context import (
    get_trace_id, set_trace_id, reset_trace_id,
    get_request_id, set_request_id, reset_request_id,
    get_agent_name, get_node_name,
    set_current_span_id, get_current_span_id, reset_current_span_id
)
from ai_legal_helper.observability.telemetry import get_tracer
from ai_legal_helper.observability.pii_masker import mask_pii
from ai_legal_helper.observability.langfuse_client import start_trace, start_span, end_span, end_trace, flush_langfuse
from opentelemetry.trace import Status, StatusCode

logger = get_logger(__name__)

# 함수명 및 LangGraph 노드명 매핑을 위한 한국어 단계명 사전
FUNCTION_KR_NAMES: dict[str, str] = {
    # 1. 6단계 상담 워크플로우 노드 (LangGraph)
    "supervisor_initialize_node": "1단계: 사건·맥락 확인",
    "supervisor_initialize": "1단계: 사건·맥락 확인",
    "intent_analysis_node": "1단계: 의도 분석",
    "intent_analysis": "1단계: 의도 분석",
    "route_node": "2단계: 분야 판별",
    "route": "2단계: 분야 판별",
    "route_categories": "2단계: 법률 분야 분류",
    "route_categories_detailed": "2단계: 법률 분야 상세 분류",
    "plan_node": "2단계: 쟁점 계획",
    "plan": "2단계: 쟁점 계획",
    "plan_tools": "2단계: 도구 및 에이전트 계획",
    "run_agents_node": "3단계: 법령·판례 검색",
    "run_agents": "3단계: 법령·판례 검색",
    "execute_statute_search_node": "3단계: 공식 법령 조회",
    "execute_statute_search": "3단계: 공식 법령 조회",
    "statute_search_approval_node": "3단계: 공식 검색 승인 대기",
    "statute_search_approval": "3단계: 공식 검색 승인 대기",
    "synthesize_node": "4단계: 쟁점별 분석",
    "synthesize": "4단계: 쟁점별 분석",
    "re_analyze_node": "4단계: 쟁점별 재분석",
    "re_analyze": "4단계: 쟁점별 재분석",
    "followup_action_node": "4단계: 후속 조치 가이드",
    "followup_action": "4단계: 후속 조치 가이드",
    "verification_node": "5단계: 근거 검증",
    "verification": "5단계: 근거 검증",
    "run_verification": "5단계: 조문·증거 일치성 검증",
    "revise_node": "5단계: 답변 보강",
    "revise": "5단계: 답변 보강",
    "finalize_node": "6단계: 최종 답변 작성",
    "finalize": "6단계: 최종 답변 작성",
    "insufficient_node": "6단계: 판단 유보 안내 작성",
    "insufficient": "6단계: 판단 유보 안내 작성",
    "routing_exit_node": "6단계: 분류 오류 안내",
    "routing_exit": "6단계: 분류 오류 안내",
    "general_conversation_node": "6단계: 일반 대화 안내",
    "general_conversation": "6단계: 일반 대화 안내",

    # 2. 통합 상담 실행 함수
    "run_legal_consultation": "통합 법률 상담 워크플로우",
    "_execute_consultation": "법률 상담 그래프 실행",
    "build_legal_graph": "법률 상담 워크플로우 그래프 빌드",

    # 3. 문서 기반 직접 상담 (Document Grounded Mode)
    "generate_answer": "문서 사건: 원문 기반 답변 작성",
    "verify_answer": "문서 사건: 원문 및 근거 검증",

    # 4. 전문 에이전트 및 RAG / 검색 / 사건 인텔리전스
    "run_specialist_agent": "전문 에이전트 분석",
    "build_react_agent": "전문 에이전트 초기화",
    "plan_legal_actions": "법률 대응 행동 계획 수립",
    "retrieve_with_status": "법률 지식베이스 검색",
    "retrieve": "법률 문서 검색",
    "_get_client": "벡터DB 클라이언트 연결",
    "_get_vs": "벡터스토어 컬렉션 로드",
    "_list_collections": "벡터DB 컬렉션 목록 조회",
    "make_fixed_retrieval_tool": "법률 검색 도구 생성",
    "_run": "법률 검색 도구 실행",
    "rewrite_query": "검색 질의어 법령 용어 확장",
    "search_official_statutes": "국가법령정보센터 공식 조문 검색",
    "search_case_evidence": "사건 증거 문서 검색",
    "search_evidence_in_postgres": "DB 사건 증거 검색",
    "search_traversal": "지식그래프 연관 경로 탐색",
    "search_hybrid": "하이브리드 지식 그래프 검색",
    "retrieve_structured_evidence": "구조화 사건 증거 조회",
    "analyze_consultation_intent": "상담 질문 의도 분석",
    "synthesize_legal_answers": "법률 답변 종합 합성",
    "classify_case_type": "사건 유형 자동 분류",
    "extract_case_facts": "사건 사실관계 추출",
    "extract_case_info": "의뢰인 진술 사건 정보 추출",
    "extract_claims_from_evidence": "증거 문서 주장·사실 추출",
    "extract_text_from_evidence": "증거 문서 원문 텍스트 추출",
    "ingest_evidence": "증거 문서 수집 및 색인",
    "process_new_statement": "신규 진술 분석 및 반영",
    "build_case_timeline": "사건 타임라인 구축",
    "build_timeline_from_facts": "사건 타임라인 구성",

    # 5. 법률 문서 생성 워크플로우
    "context_node": "문서작성: 사건 맥락 수집",
    "requirements_node": "문서작성: 필수 기재사항 점검",
    "generate_node": "문서작성: 법률 문서 초안 생성",
    "review_gate_node": "문서작성: 품질 검토 게이트",
}


def get_kr_step_name(func_name: str) -> str:
    """함수명 또는 노드명에 대응하는 가독성 높은 한국어 단계명을 반환한다.

    Args:
        func_name: 대상 함수명 또는 노드 식별자.

    Returns:
        str: 매핑된 한국어 단계명 (사전에 없는 경우 원본 함수명 반환).
    """
    if func_name in FUNCTION_KR_NAMES:
        return FUNCTION_KR_NAMES[func_name]
    if func_name.endswith("_node"):
        base_name = func_name[:-5]
        if base_name in FUNCTION_KR_NAMES:
            return FUNCTION_KR_NAMES[base_name]
    return func_name


def _get_func_meta(func: Callable) -> tuple[str, int]:
    """함수의 소스 파일 경로와 시작 라인 번호를 안전하게 조회한다 (OSError 방지)."""
    try:
        code_obj = getattr(func, "__code__", None)
        if code_obj is not None:
            return code_obj.co_filename, code_obj.co_firstlineno
        return inspect.getfile(func), inspect.getsourcelines(func)[1]
    except Exception:
        return getattr(func, "__module__", "unknown"), 0




def _sanitize_span_output(func_name: str, output_data: Any) -> Any:
    """Langfuse Span Output에 기록될 출력 데이터를 경량화·요약하여 관측 성능 및 가독성을 최적화한다.

    LangGraph 파이프라인 내부에서는 전체 원본 상태(State)가 노드 간에 온전히 전달되어야 하지만,
    Langfuse Span Output에 수백 KB의 사건 증거 원문(case_evidence_briefing), 검색 출처 덤프(retrieved_sources),
    중복 단위 쟁점 검증 결과(issue_results)가 그대로 직렬화되면 트리 뷰 오염과 대용량 페이로드 오버헤드가 발생한다.
    본 함수는 워크플로우의 실제 동작에는 일절 영향을 주지 않으면서 관측 계층(Langfuse)에만
    핵심 상태, 식별자, 항목 개수, 프리뷰 요약본을 전달하도록 정제한다.

    Args:
        func_name: 대상 함수명 또는 노드 식별자.
        output_data: 노드 또는 함수가 반환한 원본 출력 데이터.

    Returns:
        Any: 민감정보가 마스킹되고 대용량 원문이 경량 요약된 관측용 출력 객체.
    """
    if output_data is None:
        return None

    try:
        if isinstance(output_data, dict):
            sanitized: dict[str, Any] = {}
            for k, v in output_data.items():
                if v is None:
                    sanitized[k] = None
                    continue

                # 1. 사건 증거 종합 브리핑 객체 경량화 (수백 KB의 원문 문서 전문 덤프 방지)
                if k == "case_evidence_briefing" and isinstance(v, dict):
                    sanitized[k] = {
                        "case_id": v.get("case_id"),
                        "title": v.get("title"),
                        "case_type": v.get("case_type"),
                        "facts_count": len(v.get("facts", [])),
                        "timeline_count": len(v.get("timeline", [])),
                        "documents_count": len(v.get("source_documents", [])),
                        "source_registry_count": len(v.get("source_registry", {})),
                        "summary_preview": (v.get("formatted_summary") or "")[:250] + "..." if len(v.get("formatted_summary") or "") > 250 else v.get("formatted_summary", ""),
                    }
                # 2. 사건 증거 출처 목록 경량화 (원문 텍스트 전문 제외 및 식별자 메타데이터 보존)
                elif k == "case_evidence_sources" and isinstance(v, list):
                    sanitized[k] = {
                        "total_count": len(v),
                        "items": [
                            {
                                "label": s.get("evidence_label") or s.get("label"),
                                "document_name": s.get("document_name") or s.get("filename") or s.get("source_id"),
                                "source_type": s.get("source_type"),
                                "review_status": s.get("review_status"),
                            }
                            for s in v[:10]
                            if isinstance(s, dict)
                        ],
                    }
                # 3. 검색된 법령/판례 출처 목록 경량화 (원문 content 제외, 식별자 및 120자 프리뷰 보존)
                elif k == "retrieved_sources" and isinstance(v, list):
                    sanitized[k] = {
                        "total_count": len(v),
                        "items": [
                            {
                                "source_id": s.get("source_id"),
                                "source_type": s.get("source_type"),
                                "name": s.get("law_name") or s.get("document_name") or s.get("title"),
                                "content_preview": (s.get("content", "")[:120] + "...") if s.get("content") else "",
                            }
                            for s in v[:10]
                            if isinstance(s, dict)
                        ],
                    }
                # 4. 검증 완료 출처 목록 경량화
                elif k == "verified_sources" and isinstance(v, list):
                    sanitized[k] = {
                        "total_count": len(v),
                        "items": [
                            {
                                "source_id": s.get("source_id"),
                                "source_type": s.get("source_type"),
                                "citation_tag": s.get("citation_tag") or s.get("evidence_label"),
                            }
                            for s in v[:10]
                            if isinstance(s, dict)
                        ],
                    }
                # 5. 단위 쟁점 검증 결과 목록 경량화 (최상위와 verification_result 간 중복 덤프 해소)
                elif k == "issue_results" and isinstance(v, list):
                    sanitized[k] = [
                        {
                            "task_id": r.get("task_id"),
                            "status": r.get("status"),
                            "core_issue": r.get("core_issue"),
                            "supported_statutes": r.get("supported_statute_ids", []),
                            "unsupported_claims_count": len(r.get("unsupported_claims", [])),
                        }
                        for r in v
                        if isinstance(r, dict)
                    ]
                # 6. 종합 검증 결과(verification_result) 객체 경량화
                elif k == "verification_result" and isinstance(v, dict):
                    v_sanitized = {
                        "status": v.get("status"),
                        "reason_code": v.get("reason_code"),
                        "candidate_laws": v.get("candidate_laws", []),
                        "claims_count": len(v.get("claims", [])),
                        "warnings": v.get("warnings", []),
                        "revision_instructions": v.get("revision_instructions", []),
                        "issue_results_count": len(v.get("issue_results", [])),
                    }
                    if "citation_audit" in v and isinstance(v["citation_audit"], dict):
                        v_sanitized["citation_audit"] = {
                            "audit_status": v["citation_audit"].get("audit_status"),
                            "verified_count": len(v["citation_audit"].get("verified_sources", [])),
                            "unverified_citations": v["citation_audit"].get("unverified_citations", []),
                        }
                    sanitized[k] = v_sanitized
                # 7. 장문의 사건 컨텍스트 축약
                elif k == "case_context" and isinstance(v, str):
                    if len(v) > 300:
                        sanitized[k] = mask_pii(v[:300]) + f"... [총 {len(v)}자 원문 축약]"
                    else:
                        sanitized[k] = mask_pii(v)
                # 8. 지식 그래프 근거 축약
                elif k == "graph_evidence" and isinstance(v, dict):
                    sanitized[k] = {
                        "available": v.get("available"),
                        "search_mode": v.get("search_mode"),
                        "valid_paths_count": len(v.get("valid_paths", [])),
                        "evidence_gaps_count": len(v.get("evidence_gaps", [])),
                        "contradictions_count": len(v.get("contradictions", [])),
                    }
                # 9. 초안 답변 (답변 확인을 위해 최대 3000자까지 보존)
                elif k == "draft_answer" and isinstance(v, str):
                    if len(v) > 3000:
                        sanitized[k] = mask_pii(v[:3000]) + f"... [총 {len(v)}자 축약]"
                    else:
                        sanitized[k] = mask_pii(v)
                # 10. 일반 긴 문자열 축약
                elif isinstance(v, str):
                    if len(v) > 1500:
                        sanitized[k] = mask_pii(v[:1500]) + f"... [총 {len(v)}자 축약]"
                    else:
                        sanitized[k] = mask_pii(v)
                else:
                    # 기본 숫자, 불리언, 소형 리스트/딕셔너리는 그대로 보존
                    sanitized[k] = v
            return sanitized

        elif isinstance(output_data, str):
            if len(output_data) > 3000:
                return mask_pii(output_data[:3000]) + f"... [총 {len(output_data)}자 축약]"
            return mask_pii(output_data)

        return output_data
    except Exception as exc:
        logger.debug(f"Span output 경량화 중 오류: {exc}")
        return repr(output_data)[:1000]


def trace(func: Callable) -> Callable:
    """함수 또는 비동기 코루틴의 실행 흐름과 성능을 OpenTelemetry 및 Langfuse에 기록하는 데코레이터.

    Args:
        func: 추적 대상 함수 또는 코루틴.

    Returns:
        Callable: 추적 로직이 래핑된 함수.
    """
    is_coroutine = inspect.iscoroutinefunction(func)
    src_file, src_line = _get_func_meta(func)

    def log_entry(
        start_time: float,
        current_trace_id: str,
        current_span_id: str,
        is_new_trace: bool,
        parent_agent: str,
        parent_node: str,
        parent_span_id: Optional[str] = None,
        input_data: Any = None,
    ):
        log_data = {
            "status": "START",
            "source_file": src_file,
            "source_function": func.__name__,
            "source_line": src_line,
            "agent_name": parent_agent,
            "node_name": parent_node,
        }
        step_desc = get_kr_step_name(func.__name__)
        log_data["step_name_kr"] = step_desc
        logger.info(f"[{step_desc}] 단계 시작 ({func.__name__})", extra=log_data)

        # P3.6 Langfuse: 실제 상위 Span UUID(parent_span_id)를 우선 연결하여 중첩 트리 구조를 형성
        try:
            if is_new_trace:
                start_trace(
                    trace_id=current_trace_id,
                    name=f"Workflow:{func.__name__}",
                    metadata={"agent_name": parent_agent},
                )
            start_span(
                trace_id=current_trace_id,
                span_id=current_span_id,
                name=func.__name__,
                parent_span_id=parent_span_id or parent_node or parent_agent,
                input=input_data,
            )
        except Exception as ex:
            logger.debug(f"Langfuse 시작 스팬 기록 오류: {ex}")

    def log_success(start_time: float, current_span_id: str, parent_agent: str, parent_node: str, output_data: Any = None):
        elapsed_ms = (time.time() - start_time) * 1000
        log_data = {
            "status": "SUCCESS",
            "source_file": src_file,
            "source_function": func.__name__,
            "source_line": src_line,
            "elapsed_ms": elapsed_ms,
            "agent_name": parent_agent,
            "node_name": parent_node,
        }
        step_desc = get_kr_step_name(func.__name__)
        log_data["step_name_kr"] = step_desc
        logger.info(f"[{step_desc}] 단계 완료 ({elapsed_ms:.1f}ms)", extra=log_data)

        try:
            sanitized_output = _sanitize_span_output(func.__name__, output_data)
            end_span(span_id=current_span_id, output=sanitized_output)
        except Exception as ex:
            logger.debug(f"Langfuse 완료 스팬 기록 오류: {ex}")

    def log_interrupt(start_time: float, current_span_id: str, e: Exception, parent_agent: str, parent_node: str):
        elapsed_ms = (time.time() - start_time) * 1000
        log_data = {
            "status": "INTERRUPT",
            "source_file": src_file,
            "source_function": func.__name__,
            "source_line": src_line,
            "elapsed_ms": elapsed_ms,
            "agent_name": parent_agent,
            "node_name": parent_node,
        }
        step_desc = get_kr_step_name(func.__name__)
        log_data["step_name_kr"] = step_desc
        logger.info(f"[HITL_INTERRUPT] [{step_desc}] 사용자 승인(HITL) 대기 일시 중단: {e}", extra=log_data)
        try:
            end_span(span_id=current_span_id, level="DEFAULT", status_message="Interrupted for HITL decision")
        except Exception as ex:
            logger.debug(f"Langfuse 중단 스팬 기록 오류: {ex}")

    def log_error(start_time: float, current_span_id: str, e: Exception, parent_agent: str, parent_node: str):
        elapsed_ms = (time.time() - start_time) * 1000

        tb = e.__traceback__
        while tb and tb.tb_next:
            tb = tb.tb_next

        error_file = tb.tb_frame.f_code.co_filename if tb else src_file
        error_function = tb.tb_frame.f_code.co_name if tb else func.__name__
        error_line = tb.tb_lineno if tb else src_line

        import traceback
        import re

        def scrub_sensitive_info(text: str) -> str:
            if not isinstance(text, str):
                return text
            text = re.sub(r'(api[_-]?key)=[\w-]+', r'\1=***', text, flags=re.IGNORECASE)
            text = re.sub(r'(sk-)[a-zA-Z0-9]{20,}', r'\1***', text)
            text = re.sub(r'(Bearer\s+)[a-zA-Z0-9\-\._~+/]+=*', r'\1***', text, flags=re.IGNORECASE)
            text = re.sub(r'(azure[_-]?openai[_-]?endpoint)=https?://[^\s\'"]+', r'\1=***', text, flags=re.IGNORECASE)
            text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', r'***@***.***', text)
            text = re.sub(r'\b010-\d{3,4}-\d{4}\b', '010-****-****', text)
            text = re.sub(r'\b\d{6}-[1-4]\d{6}\b', '******-*******', text)
            return mask_pii(text)

        raw_stack_trace = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        stack_trace = scrub_sensitive_info(raw_stack_trace)
        safe_error_msg = scrub_sensitive_info(str(e))

        log_data = {
            "status": "ERROR",
            "source_file": src_file,
            "source_function": func.__name__,
            "source_line": src_line,
            "error_file": error_file,
            "error_function": error_function,
            "error_line": error_line,
            "exception_type": type(e).__name__,
            "elapsed_ms": elapsed_ms,
            "stack_trace": stack_trace,
            "agent_name": parent_agent,
            "node_name": parent_node,
        }
        step_desc = get_kr_step_name(func.__name__)
        log_data["step_name_kr"] = step_desc
        logger.error(f"[{step_desc}] 단계 처리 오류 발생: {safe_error_msg}", extra=log_data)

        try:
            end_span(
                span_id=current_span_id,
                level="ERROR",
                status_message=safe_error_msg,
            )
        except Exception as ex:
            logger.debug(f"Langfuse 오류 스팬 기록 실패: {ex}")

    if is_coroutine:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            tracer = get_tracer()
            current_trace_id = get_trace_id()
            is_new_trace = False
            token = None
            if not current_trace_id:
                current_trace_id = str(uuid.uuid4())
                is_new_trace = True
                token = set_trace_id(current_trace_id)

            parent_agent = get_agent_name()
            parent_node = get_node_name()
            prev_span_id = get_current_span_id()

            start_time = time.time()
            current_span_id = str(uuid.uuid4())
            span_token = set_current_span_id(current_span_id)
            input_payload = None
            if args or kwargs:
                input_payload = {
                    "args": [mask_pii(repr(a)[:500]) for a in args],
                    "kwargs": {k: mask_pii(repr(v)[:500]) for k, v in kwargs.items()},
                }
            log_entry(start_time, current_trace_id, current_span_id, is_new_trace, parent_agent, parent_node, prev_span_id, input_data=input_payload)

            with tracer.start_as_current_span(func.__name__) as span:
                span.set_attribute("trace_id", current_trace_id)
                if parent_agent:
                    span.set_attribute("agent_name", parent_agent)
                if parent_node:
                    span.set_attribute("node_name", parent_node)

                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    log_success(start_time, current_span_id, parent_agent, parent_node, output_data=result)
                    return result
                except Exception as e:
                    exc_name = type(e).__name__
                    if exc_name in ("GraphInterrupt", "Interrupt"):
                        span.set_status(Status(StatusCode.OK))
                        span.set_attribute("hitl.interrupted", True)
                        span.set_attribute("hitl.reason", "Interrupted for HITL")
                        log_interrupt(start_time, current_span_id, e, parent_agent, parent_node)
                        raise e
                    import re
                    safe_span_msg = str(e)
                    safe_span_msg = re.sub(r'(api[_-]?key)=[\w-]+', r'\1=***', safe_span_msg, flags=re.IGNORECASE)
                    safe_span_msg = re.sub(r'(sk-)[a-zA-Z0-9]{20,}', r'\1***', safe_span_msg)
                    safe_span_msg = re.sub(r'(Bearer\s+)[a-zA-Z0-9\-\._~+/]+=*', r'\1***', safe_span_msg, flags=re.IGNORECASE)
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, safe_span_msg))
                    log_error(start_time, current_span_id, e, parent_agent, parent_node)
                    raise e
                finally:
                    reset_current_span_id(span_token)
                    if is_new_trace and token:
                        end_trace(current_trace_id)
                        flush_langfuse()
                        reset_trace_id(token)
        return async_wrapper
    else:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            tracer = get_tracer()
            current_trace_id = get_trace_id()
            is_new_trace = False
            token = None
            if not current_trace_id:
                current_trace_id = str(uuid.uuid4())
                is_new_trace = True
                token = set_trace_id(current_trace_id)

            parent_agent = get_agent_name()
            parent_node = get_node_name()
            prev_span_id = get_current_span_id()

            start_time = time.time()
            current_span_id = str(uuid.uuid4())
            span_token = set_current_span_id(current_span_id)
            input_payload = None
            if args or kwargs:
                input_payload = {
                    "args": [mask_pii(repr(a)[:500]) for a in args],
                    "kwargs": {k: mask_pii(repr(v)[:500]) for k, v in kwargs.items()},
                }
            log_entry(start_time, current_trace_id, current_span_id, is_new_trace, parent_agent, parent_node, prev_span_id, input_data=input_payload)

            with tracer.start_as_current_span(func.__name__) as span:
                span.set_attribute("trace_id", current_trace_id)
                if parent_agent:
                    span.set_attribute("agent_name", parent_agent)
                if parent_node:
                    span.set_attribute("node_name", parent_node)

                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    log_success(start_time, current_span_id, parent_agent, parent_node, output_data=result)
                    return result
                except Exception as e:
                    exc_name = type(e).__name__
                    if exc_name in ("GraphInterrupt", "Interrupt"):
                        span.set_status(Status(StatusCode.OK))
                        span.set_attribute("hitl.interrupted", True)
                        span.set_attribute("hitl.reason", "Interrupted for HITL")
                        log_interrupt(start_time, current_span_id, e, parent_agent, parent_node)
                        raise e
                    import re
                    safe_span_msg = str(e)
                    safe_span_msg = re.sub(r'(api[_-]?key)=[\w-]+', r'\1=***', safe_span_msg, flags=re.IGNORECASE)
                    safe_span_msg = re.sub(r'(sk-)[a-zA-Z0-9]{20,}', r'\1***', safe_span_msg)
                    safe_span_msg = re.sub(r'(Bearer\s+)[a-zA-Z0-9\-\._~+/]+=*', r'\1***', safe_span_msg, flags=re.IGNORECASE)
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, safe_span_msg))
                    log_error(start_time, current_span_id, e, parent_agent, parent_node)
                    raise e
                finally:
                    reset_current_span_id(span_token)
                    if is_new_trace and token:
                        end_trace(current_trace_id)
                        flush_langfuse()
                        reset_trace_id(token)
        return sync_wrapper
