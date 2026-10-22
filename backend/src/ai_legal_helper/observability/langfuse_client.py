# -*- coding: utf-8 -*-
"""
모듈명: langfuse_client.py

[모듈 개요]
Langfuse 기반 LLM 관측성(Observability) 및 실행 추적(Tracing) 클라이언트 모듈이다.
Langfuse v2 서버와의 통신 및 LangChain/LangGraph 통합을 위한 CallbackHandler를 제공한다.

[주요 기능]
1. Langfuse 싱글톤 클라이언트 초기화 및 연결 상태 관리
2. 분산 추적을 위한 Trace 및 Span 시작/종료 관리 (_active_traces, _active_spans)
3. LangChain/LangGraph 호출 시 LLM 프롬프트, 생성 토큰, 지연 시간을 실시간 추적하는 CallbackHandler 제공
4. 비동기/백그라운드 태스크 종료 시 버퍼링된 추적 데이터를 즉시 전송하는 flush_langfuse 제공

[주의사항]
- LangChain 1.x 환경에서 langfuse v2 SDK의 이전 모듈 경로(langchain.callbacks) 호환성을 위해 Shim 레이어를 구성한다.
- 민감정보(API 키, 사용자 비밀 등) 보호를 위해 LANGFUSE_CAPTURE_CONTENT 설정에 따라 입출력을 마스킹한다.
"""
import os
import sys
import types
import uuid
import re
from typing import Optional, Dict, Any, List

# LangChain 1.x 버전에서 langfuse 2.x SDK의 이전 import 경로 호환성 보장
if "langchain.callbacks" not in sys.modules:
    try:
        import langchain_core.callbacks
        import langchain_core.agents
        import langchain_core.documents

        m_callbacks = types.ModuleType("langchain.callbacks")
        m_callbacks_base = types.ModuleType("langchain.callbacks.base")
        m_callbacks_base.BaseCallbackHandler = langchain_core.callbacks.BaseCallbackHandler
        m_schema_agent = types.ModuleType("langchain.schema.agent")
        m_schema_agent.AgentAction = langchain_core.agents.AgentAction
        m_schema_agent.AgentFinish = langchain_core.agents.AgentFinish
        m_schema_doc = types.ModuleType("langchain.schema.document")
        m_schema_doc.Document = langchain_core.documents.Document

        sys.modules["langchain.callbacks"] = m_callbacks
        sys.modules["langchain.callbacks.base"] = m_callbacks_base
        sys.modules["langchain.schema"] = types.ModuleType("langchain.schema")
        sys.modules["langchain.schema.agent"] = m_schema_agent
        sys.modules["langchain.schema.document"] = m_schema_doc
    except Exception:
        pass

try:
    from langfuse import Langfuse
    from langfuse.callback import CallbackHandler
except ImportError:
    Langfuse = None
    CallbackHandler = None

_langfuse: Optional[Any] = None

# 실행 중인 활성 Trace와 Span 인스턴스를 관리하는 딕셔너리
_active_traces: Dict[str, Any] = {}
_active_spans: Dict[str, Any] = {}
# 노드명/함수명 기반 부모 탐색 지원을 위한 이름 매핑 인덱스
_active_spans_by_name: Dict[str, str] = {}
_span_names: Dict[str, str] = {}


def get_system_name() -> str:
    """환경변수 `LANGFUSE_SYSTEM_NAME`으로부터 현재 시스템 식별자를 반환한다.

    기본값은 'LegalAgent'이며, 다중 애플리케이션(LegalChat, LegalRAG 등) 간의
    비교 및 대시보드 필터링을 지원한다.

    Returns:
        str: 시스템 식별자 문자열 (예: 'LegalAgent', 'LegalChat', 'LegalRAG')
    """
    return os.getenv("LANGFUSE_SYSTEM_NAME", "LegalAgent")


def get_langfuse() -> Optional[Any]:
    """Langfuse 싱글톤 인스턴스를 생성하거나 반환한다.

    Returns:
        Optional[Langfuse]: Langfuse가 활성화되고 키가 올바른 경우 클라이언트 객체, 그렇지 않으면 None.
    """
    global _langfuse
    if Langfuse is None:
        return None
    if _langfuse is None and os.getenv("LANGFUSE_ENABLED", "false").lower() == "true":
        try:
            pub_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
            sec_key = os.getenv("LANGFUSE_SECRET_KEY", "")
            host = os.getenv("LANGFUSE_HOST", "http://localhost:3001")
            if pub_key and sec_key:
                _langfuse = Langfuse(
                    public_key=pub_key,
                    secret_key=sec_key,
                    host=host,
                )
        except Exception:
            _langfuse = None
    return _langfuse


def get_langfuse_callback_handler(
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    trace_name: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Optional[Any]:
    """LangChain 및 LangGraph 실행 추적을 위한 Langfuse CallbackHandler를 생성한다.

    컨텍스트에 활성 Trace가 존재하는 경우 해당 Trace 하위에 스팬 및 생성을 연결하고,
    그렇지 않은 경우 독립적인 신규 추적 세션을 생성한다.
    시스템 식별자(LANGFUSE_SYSTEM_NAME, 기본값 'LegalAgent')를 태그 및 메타데이터에 자동 주입한다.

    Args:
        trace_id: 연결할 상위 추적 ID (미지정 시 ContextVar 확인)
        session_id: 상담 세션 또는 사건 ID (선택사항)
        user_id: 사용자 ID (선택사항)
        metadata: 추가 메타데이터 딕셔너리
        trace_name: 추적 이름 (선택사항)
        tags: 태그 목록 (선택사항)

    Returns:
        Optional[CallbackHandler]: Langfuse가 활성화된 경우 CallbackHandler 객체, 비활성화 시 None.
    """
    if CallbackHandler is None:
        return None
    if os.getenv("LANGFUSE_ENABLED", "false").lower() != "true":
        return None

    pub_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sec_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    host = os.getenv("LANGFUSE_HOST", "http://localhost:3001")
    if not pub_key or not sec_key:
        return None

    # ContextVar에서 trace_id 조회
    if not trace_id:
        try:
            from ai_legal_helper.observability.context import get_trace_id
            trace_id = get_trace_id()
        except ImportError:
            pass

    # ContextVar에서 case_id를 session_id로 활용
    if not session_id:
        try:
            from ai_legal_helper.observability.context import get_case_id
            session_id = get_case_id()
        except ImportError:
            pass

    sys_name = get_system_name()
    combined_tags = list(tags) if tags else []
    if sys_name and sys_name not in combined_tags:
        combined_tags.append(sys_name)

    combined_metadata = dict(metadata or {})
    if sys_name and "system_name" not in combined_metadata:
        combined_metadata["system_name"] = sys_name

    try:
        active_trace = _active_traces.get(trace_id) if trace_id else None
        if active_trace:
            return CallbackHandler(
                public_key=pub_key,
                secret_key=sec_key,
                host=host,
                stateful_client=active_trace,
                metadata=combined_metadata,
                tags=combined_tags,
            )

        return CallbackHandler(
            public_key=pub_key,
            secret_key=sec_key,
            host=host,
            session_id=session_id,
            user_id=user_id,
            trace_name=trace_name,
            metadata=combined_metadata,
            tags=combined_tags,
        )
    except Exception:
        return None


def flush_langfuse():
    """Langfuse에 버퍼링된 모든 추적 및 세대 데이터를 즉시 서버로 전송한다.

    백그라운드 태스크나 일회성 LLM 스크립트 종료 시 데이터 유실을 방지하기 위해 호출한다.
    """
    lf = get_langfuse()
    if lf:
        try:
            lf.flush()
        except Exception:
            pass


def start_trace(
    trace_id: str,
    name: str,
    session_id: Optional[str] = None,
    metadata: Optional[Dict] = None,
    tags: Optional[List[str]] = None,
):
    """새로운 최상위 Trace를 시작하고 내부 활성 목록에 등록한다.

    시스템 식별자(LANGFUSE_SYSTEM_NAME, 기본값 'LegalAgent')를 기본 태그 및 메타데이터로 자동 주입하여,
    다른 애플리케이션(LegalChat, LegalRAG 등)과 Langfuse 대시보드 상에서 비교 및 필터링할 수 있도록 지원한다.

    Args:
        trace_id: 고유 추적 ID
        name: 워크플로우 또는 태스크 이름
        session_id: 상담 세션 또는 사건 식별자
        metadata: 부가 메타데이터
        tags: 태그 목록 (선택사항)
    """
    lf = get_langfuse()
    if not lf:
        return
    if trace_id not in _active_traces:
        try:
            sys_name = get_system_name()
            trace_tags = list(tags) if tags else []
            if sys_name and sys_name not in trace_tags:
                trace_tags.append(sys_name)

            trace_metadata = dict(metadata or {})
            if sys_name and "system_name" not in trace_metadata:
                trace_metadata["system_name"] = sys_name

            trace = lf.trace(
                id=trace_id,
                name=name,
                session_id=session_id,
                metadata=trace_metadata,
                tags=trace_tags,
            )
            _active_traces[trace_id] = trace
        except Exception:
            pass


def end_trace(trace_id: str):
    """지정된 Trace를 종료 처리하고 활성 추적 캐시에서 제거한다."""
    lf = get_langfuse()
    if not lf:
        return
    _active_traces.pop(trace_id, None)


def start_span(
    trace_id: str,
    span_id: str,
    name: str,
    parent_span_id: Optional[str] = None,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Trace 하위에 새로운 작업 구간(Span)을 생성하고 계층 트리(Tree)에 연결한다.

    상위 Trace가 아직 시작되지 않은 경우 자동으로 생성(Lazy Creation)하며,
    `parent_span_id`로 UUID뿐만 아니라 노드명/함수명 문자열이 전달되더라도 활성 스팬 인덱스를 통해
    올바른 부모 Span 객체를 찾아 연결한다. 시스템 식별자(LANGFUSE_SYSTEM_NAME)를 메타데이터 및 태그에 반영한다.

    Args:
        trace_id: 소속 Trace ID
        span_id: 고유 구간 ID
        name: 작업 또는 함수명
        parent_span_id: 상위 구간 ID 또는 노드명 (선택사항)
        input: 작업 입력 데이터 (LANGFUSE_CAPTURE_CONTENT 설정에 따라 마스킹)
        metadata: 추가 메타데이터 (선택사항)
    """
    lf = get_langfuse()
    if not lf:
        return

    sys_name = get_system_name()

    # Trace가 아직 생성되지 않은 경우 자동 지연 생성 (Lazy Trace Creation)
    trace = _active_traces.get(trace_id)
    if not trace:
        try:
            from ai_legal_helper.observability.context import get_case_id
            session_id = get_case_id()
            trace = lf.trace(
                id=trace_id,
                name=f"Workflow:{name}",
                session_id=session_id,
                metadata={"system_name": sys_name},
                tags=[sys_name],
            )
            _active_traces[trace_id] = trace
        except Exception:
            return

    capture_content = os.getenv("LANGFUSE_CAPTURE_CONTENT", "true").lower() == "true"
    safe_input = input if capture_content else ("[MASKED FOR PRIVACY]" if input is not None else None)

    span_metadata = dict(metadata or {})
    if sys_name and "system_name" not in span_metadata:
        span_metadata["system_name"] = sys_name

    # 부모 Span 탐색: 1) UUID 직접 매칭 -> 2) 노드명 매칭 -> 3) Root Trace
    parent = None
    if parent_span_id:
        parent = _active_spans.get(parent_span_id)
        if not parent and parent_span_id in _active_spans_by_name:
            parent = _active_spans.get(_active_spans_by_name[parent_span_id])
    if not parent:
        parent = trace

    try:
        span = parent.span(
            id=span_id,
            name=name,
            input=safe_input,
            metadata=span_metadata,
        )
        _active_spans[span_id] = span
        _active_spans_by_name[name] = span_id
        _span_names[span_id] = name
    except Exception:
        pass


def end_span(span_id: str, output: Any = None, level: str = "DEFAULT", status_message: str = ""):
    """작업 구간(Span)을 완료하고 결과를 기록한 뒤 활성 구간 캐시에서 제거한다.

    Args:
        span_id: 완료할 구간 ID
        output: 작업 출력 결과
        level: 로그 레벨 (DEFAULT, WARNING, ERROR)
        status_message: 상태 메시지
    """
    lf = get_langfuse()
    if not lf:
        return
    span = _active_spans.pop(span_id, None)
    name = _span_names.pop(span_id, None)
    if name and _active_spans_by_name.get(name) == span_id:
        _active_spans_by_name.pop(name, None)

    if span:
        capture_content = os.getenv("LANGFUSE_CAPTURE_CONTENT", "true").lower() == "true"
        safe_output = output if capture_content else ("[MASKED FOR PRIVACY]" if output is not None else None)
        try:
            span.end(output=safe_output, level=level, status_message=status_message)
        except Exception:
            pass


def update_span(span_id: str, metadata: Dict[str, Any]):
    """작업 구간(Span)의 메타데이터를 갱신한다. UUID 또는 등록된 스팬 이름을 모두 지원한다."""
    lf = get_langfuse()
    if not lf:
        return

    target_span_id = span_id
    if target_span_id not in _active_spans and target_span_id in _active_spans_by_name:
        target_span_id = _active_spans_by_name[target_span_id]

    span = _active_spans.get(target_span_id)
    if span:
        try:
            span.update(metadata=metadata)
        except Exception:
            pass


def log_generation(
    trace_id: str,
    parent_span_id: Optional[str],
    name: str,
    model: str,
    start_time: float,
    end_time: float,
    usage: Dict[str, int],
    status_message: str = "",
    input: Any = None,
    output: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """LLM 단독 호출 결과를 수동으로 기록한다."""
    lf = get_langfuse()
    if not lf:
        return

    sys_name = get_system_name()

    trace = _active_traces.get(trace_id)
    if not trace:
        try:
            from ai_legal_helper.observability.context import get_case_id
            session_id = get_case_id()
            trace = lf.trace(
                id=trace_id,
                name="LLM_Trace",
                session_id=session_id,
                metadata={"system_name": sys_name},
                tags=[sys_name],
            )
            _active_traces[trace_id] = trace
        except Exception:
            return

    # 부모 Span 탐색: UUID -> 노드명 -> Root Trace
    parent = None
    if parent_span_id:
        parent = _active_spans.get(parent_span_id)
        if not parent and parent_span_id in _active_spans_by_name:
            parent = _active_spans.get(_active_spans_by_name[parent_span_id])
    if not parent:
        parent = trace

    level = "ERROR" if status_message else "DEFAULT"
    capture_content = os.getenv("LANGFUSE_CAPTURE_CONTENT", "true").lower() == "true"
    safe_input = input if capture_content else ("[MASKED FOR PRIVACY]" if input is not None else None)
    safe_output = output if capture_content else ("[MASKED FOR PRIVACY]" if output is not None else None)

    gen_metadata = dict(metadata or {})
    if sys_name and "system_name" not in gen_metadata:
        gen_metadata["system_name"] = sys_name

    try:
        parent.generation(
            name=name,
            model=model,
            start_time=start_time,
            end_time=end_time,
            usage=usage,
            input=safe_input,
            output=safe_output,
            level=level,
            status_message=status_message,
            metadata=gen_metadata,
        )
    except Exception:
        pass


def log_score(
    trace_id: Optional[str],
    name: str,
    value: float,
    comment: Optional[str] = None,
    observation_id: Optional[str] = None,
):
    """Langfuse에 정량적/정성적 평가 점수(Score)를 기록한다.

    대시보드의 Scores/Evaluation 화면에서 인용 존재율(citation_existence_rate),
    근거 지지율(citation_support_rate), 검증 상태(verification_status) 등을 필터링·모니터링할 수 있다.

    Args:
        trace_id: 점수를 연결할 Trace 식별자 (미지정 시 현재 ContextVar 참조)
        name: 점수 항목명 (예: 'citation_existence_rate', 'citation_support_rate', 'verification_status')
        value: 수치 평가 점수 (0.0 ~ 1.0)
        comment: 평가 사유 또는 상세 코멘트 (선택사항)
        observation_id: 특정 Span 또는 Generation ID (선택사항)
    """
    lf = get_langfuse()
    if not lf:
        return

    if not trace_id:
        try:
            from ai_legal_helper.observability.context import get_trace_id
            trace_id = get_trace_id()
        except ImportError:
            pass

    if not trace_id:
        return

    try:
        trace = _active_traces.get(trace_id)
        if trace and hasattr(trace, "score"):
            trace.score(
                name=name,
                value=float(value),
                comment=comment,
                observation_id=observation_id,
            )
        elif hasattr(lf, "score"):
            lf.score(
                trace_id=trace_id,
                name=name,
                value=float(value),
                comment=comment,
                observation_id=observation_id,
            )
    except Exception:
        pass


# PII 및 민감정보 마스킹 패턴 (P2-02)
_RRN_PATTERN = re.compile(r"\b(\d{6})[- ]?([1-4]\d{6})\b")
_PHONE_PATTERN = re.compile(r"\b(01[016789]|02|0[3-6]\d)[- ]?(\d{3,4})[- ]?(\d{4})\b")
_API_KEY_PATTERN = re.compile(r"\b(sk-[A-Za-z0-9_\-]{20,}|OC=[A-Za-z0-9_\-]+|bearer\s+[A-Za-z0-9_\-\.]{20,})\b", re.IGNORECASE)


def mask_pii(text: Optional[str]) -> str:
    """텍스트 내 주민등록번호, 전화번호, API 키 등 민감정보(PII)를 자동으로 마스킹한다 (P2-02).

    Args:
        text: 원본 문자열.

    Returns:
        str: 민감정보가 안전하게 대체된 문자열.
    """
    if not text:
        return ""

    # 1. 주민등록번호 (생년월일 6자리 유지, 뒷자리 마스킹)
    cleaned = _RRN_PATTERN.sub(r"\1-*******", text)

    # 2. 전화번호/휴대전화 (국번 가운데 마스킹)
    cleaned = _PHONE_PATTERN.sub(r"\1-****-\3", cleaned)

    # 3. API 키 마스킹
    cleaned = _API_KEY_PATTERN.sub("[MASKED_API_KEY]", cleaned)

    return cleaned


def build_consultation_trace_summary(
    request_id: str,
    case_id: Optional[str] = None,
    execution_status: str = "COMPLETED",
    verification_status: str = "UNVERIFIED",
    answer_status: str = "DELIVERED",
    selected_agents: Optional[List[str]] = None,
    revision_count: int = 0,
    retrieval_info: Optional[Dict[str, Any]] = None,
    verification_info: Optional[Dict[str, Any]] = None,
    usage_info: Optional[Dict[str, Any]] = None,
    hilt_info: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
    turn_index: int = 1,
    intent: Optional[str] = None,
    resolved_query: Optional[str] = None,
) -> Dict[str, Any]:
    """한 번의 상담 세션에 대한 의사결정 및 실행 전체 흐름을 일목요연하게 요약한 구조화 메타데이터를 생성한다 (P2-02).

    Langfuse 대시보드에서 Trace 클릭 시, 최종 답변이 어떤 근거와 판단 과정을 거쳐 생성되었는지
    한눈에 파악할 수 있도록 돕는다.

    Args:
        request_id: 상담 요청 식별자.
        case_id: 연결된 사건 식별자.
        execution_status: 워크플로우 실행 상태 (IN_PROGRESS, APPROVAL_REQUIRED, COMPLETED, ERROR).
        verification_status: 법률 검증 상태 (PASS, REVISE, INSUFFICIENT, UNVERIFIED).
        answer_status: 최종 조언 제공 상태 (DELIVERED, WITHHELD, CAUTIONARY, REVISED).
        selected_agents: Supervisor가 선정한 전문 에이전트 목록.
        revision_count: 재분석/재검증 루프 수행 횟수.
        retrieval_info: 검색 인덱스 및 수집 출처 요약 정보.
        verification_info: Citation Validator 및 근거 지지율 요약.
        usage_info: LLM 호출 횟수, 토큰량, 지연시간 요약.
        hilt_info: HILT 공식 법령 검색 승인/거절 내역.

    Returns:
        Dict[str, Any]: Langfuse Trace metadata에 부착될 완성된 요약 딕셔너리.
    """
    return {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "turn_index": turn_index,
        "conversation_intent": intent,
        "resolved_query": resolved_query,
        "case_id": case_id,
        "execution_status": execution_status,
        "verification_status": verification_status,
        "answer_status": answer_status,
        "selected_agents": selected_agents or [],
        "revision_count": revision_count,
        "retrieval": retrieval_info or {},
        "verification": verification_info or {},
        "usage": usage_info or {},
        "hilt": hilt_info or {},
    }
