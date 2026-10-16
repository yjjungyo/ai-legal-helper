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
) -> Optional[Any]:
    """LangChain 및 LangGraph 실행 추적을 위한 Langfuse CallbackHandler를 생성한다.

    컨텍스트에 활성 Trace가 존재하는 경우 해당 Trace 하위에 스팬 및 생성을 연결하고,
    그렇지 않은 경우 독립적인 신규 추적 세션을 생성한다.

    Args:
        trace_id: 연결할 상위 추적 ID (미지정 시 ContextVar 확인)
        session_id: 상담 세션 또는 사건 ID (선택사항)
        user_id: 사용자 ID (선택사항)
        metadata: 추가 메타데이터 딕셔너리
        trace_name: 추적 이름 (선택사항)

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

    try:
        active_trace = _active_traces.get(trace_id) if trace_id else None
        if active_trace:
            return CallbackHandler(
                public_key=pub_key,
                secret_key=sec_key,
                host=host,
                stateful_client=active_trace,
                metadata=metadata,
            )

        return CallbackHandler(
            public_key=pub_key,
            secret_key=sec_key,
            host=host,
            session_id=session_id,
            user_id=user_id,
            trace_name=trace_name,
            metadata=metadata,
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


def start_trace(trace_id: str, name: str, session_id: Optional[str] = None, metadata: Optional[Dict] = None):
    """새로운 최상위 Trace를 시작하고 내부 활성 목록에 등록한다.

    Args:
        trace_id: 고유 추적 ID
        name: 워크플로우 또는 태스크 이름
        session_id: 상담 세션 또는 사건 식별자
        metadata: 부가 메타데이터
    """
    lf = get_langfuse()
    if not lf:
        return
    if trace_id not in _active_traces:
        try:
            trace = lf.trace(
                id=trace_id,
                name=name,
                session_id=session_id,
                metadata=metadata or {},
            )
            _active_traces[trace_id] = trace
        except Exception:
            pass


def end_trace(trace_id: str):
    """지정된 Trace를 종료 처리한다."""
    lf = get_langfuse()
    if not lf:
        return
    if trace_id in _active_traces:
        pass


def start_span(trace_id: str, span_id: str, name: str, parent_span_id: Optional[str] = None, input: Any = None):
    """Trace 하위에 새로운 작업 구간(Span)을 생성한다.

    Args:
        trace_id: 소속 Trace ID
        span_id: 고유 구간 ID
        name: 작업 또는 함수명
        parent_span_id: 상위 구간 ID (선택사항)
        input: 작업 입력 데이터 (LANGFUSE_CAPTURE_CONTENT 설정에 따라 마스킹)
    """
    lf = get_langfuse()
    if not lf:
        return
    trace = _active_traces.get(trace_id)
    if not trace:
        return

    capture_content = os.getenv("LANGFUSE_CAPTURE_CONTENT", "false").lower() == "true"
    safe_input = input if capture_content else "[MASKED FOR PRIVACY]"

    parent = _active_spans.get(parent_span_id) if parent_span_id else trace
    try:
        span = parent.span(
            id=span_id,
            name=name,
            input=safe_input,
        )
        _active_spans[span_id] = span
    except Exception:
        pass


def end_span(span_id: str, output: Any = None, level: str = "DEFAULT", status_message: str = ""):
    """작업 구간(Span)을 완료하고 결과를 기록한다.

    Args:
        span_id: 완료할 구간 ID
        output: 작업 출력 결과
        level: 로그 레벨 (DEFAULT, WARNING, ERROR)
        status_message: 상태 메시지
    """
    lf = get_langfuse()
    if not lf:
        return
    span = _active_spans.get(span_id)
    if span:
        capture_content = os.getenv("LANGFUSE_CAPTURE_CONTENT", "false").lower() == "true"
        safe_output = output if capture_content else "[MASKED FOR PRIVACY]"
        try:
            span.end(output=safe_output, level=level, status_message=status_message)
        except Exception:
            pass


def update_span(span_id: str, metadata: Dict[str, Any]):
    """작업 구간(Span)의 메타데이터를 갱신한다."""
    lf = get_langfuse()
    if not lf:
        return
    span = _active_spans.get(span_id)
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
):
    """LLM 단독 호출 결과를 수동으로 기록한다."""
    lf = get_langfuse()
    if not lf:
        return
    trace = _active_traces.get(trace_id)
    if not trace:
        return

    parent = _active_spans.get(parent_span_id) if parent_span_id else trace
    level = "ERROR" if status_message else "DEFAULT"

    try:
        parent.generation(
            name=name,
            model=model,
            start_time=start_time,
            end_time=end_time,
            usage=usage,
            input="[MASKED FOR PRIVACY]",
            output="[MASKED FOR PRIVACY]",
            level=level,
            status_message=status_message,
        )
    except Exception:
        pass
