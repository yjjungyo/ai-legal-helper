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
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

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

# 실행 중인 활성 Trace와 Span 인스턴스를 관리하는 딕셔너리 (하위 호환성 유지)
_active_traces: Dict[str, Any] = {}
_active_spans: Dict[str, Any] = {}
# 노드명/함수명 기반 부모 탐색 지원을 위한 이름 매핑 인덱스
_active_spans_by_name: Dict[str, str] = {}
_span_names: Dict[str, str] = {}

# [P0-2 고도화] Trace별 활성 Span 격리 저장소 및 종료된 Trace 추적기
_trace_spans: Dict[str, Dict[str, Any]] = {}
_trace_spans_by_name: Dict[str, Dict[str, List[str]]] = {}
_span_to_trace: Dict[str, str] = {}
_ended_traces: set[str] = set()

_git_commit_cache: Optional[str] = None


def get_git_commit() -> str:
    """현재 소스코드의 Git Commit SHA를 반환한다 (P0-3 표준 메타데이터).

    환경변수 `GIT_COMMIT_SHA` 또는 `git rev-parse HEAD` 명령어를 통해 확인하며,
    최초 조회 후 메모리에 캐싱하여 성능 저하 및 중복 서브프로세스 호출을 방지한다.

    Returns:
        str: Git Commit SHA 문자열 (확인 불가 시 'unknown').
    """
    global _git_commit_cache
    if _git_commit_cache is not None:
        return _git_commit_cache

    env_sha = os.getenv("GIT_COMMIT_SHA") or os.getenv("GIT_COMMIT")
    if env_sha:
        _git_commit_cache = env_sha.strip()
        return _git_commit_cache

    try:
        import subprocess
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            _git_commit_cache = res.stdout.strip()
            return _git_commit_cache
    except Exception:
        pass

    _git_commit_cache = "unknown"
    return _git_commit_cache


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
    """새로운 최상위 Trace를 시작하거나 기존 Trace의 메타데이터 및 이름을 갱신한다.

    시스템 식별자(LANGFUSE_SYSTEM_NAME, 기본값 'LegalAgent') 및 Git Commit SHA를
    기본 태그와 메타데이터로 자동 주입한다. 이미 생성된 Trace가 있는 경우(예: HTTP 미들웨어에서
    생성 후 비동기 태스크에서 'LegalConsultation'으로 구체화) 상태를 안전하게 업데이트한다 (P0-3).

    Args:
        trace_id: 고유 추적 ID
        name: 워크플로우 또는 태스크 이름 (예: 'LegalConsultation')
        session_id: 상담 세션 또는 사건 식별자 (case_id 등)
        metadata: 부가 메타데이터
        tags: 태그 목록 (선택사항)
    """
    lf = get_langfuse()
    if not lf:
        return

    sys_name = get_system_name()
    trace_tags = list(tags) if tags else []
    if sys_name and sys_name not in trace_tags:
        trace_tags.append(sys_name)

    # 새 Trace 시작 또는 재개 시 종료된 Trace 집합에서 제거 (P0 잔여 결함 보완)
    _ended_traces.discard(trace_id)

    trace_metadata = dict(metadata or {})
    if sys_name and "system_name" not in trace_metadata:
        trace_metadata["system_name"] = sys_name
    git_sha = get_git_commit()
    if git_sha and "git_commit" not in trace_metadata:
        trace_metadata["git_commit"] = git_sha

    if trace_id not in _active_traces:
        try:
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
    else:
        # P0-3: 이미 존재하는 Trace인 경우 (HTTP 레벨 생성 후 백그라운드 태스크에서 재명명/메타데이터 보강)
        try:
            trace = _active_traces[trace_id]
            if trace and hasattr(trace, "update"):
                trace.update(
                    name=name,
                    session_id=session_id,
                    metadata=trace_metadata,
                    tags=trace_tags,
                )
        except Exception:
            pass


def end_trace(trace_id: str):
    """지정된 Trace를 종료 처리하고 해당 Trace에 속한 모든 활성 Span 및 인덱스를 안전하게 정리한다 (P0-2)."""
    lf = get_langfuse()
    if not lf:
        return

    # 종료된 Trace 식별자를 기록하여 지연 콜백에 의한 임의 생성/오염 차단 (TC-P0-10)
    _ended_traces.add(trace_id)
    _active_traces.pop(trace_id, None)

    # P0-2: trace_id에 속한 모든 Span 인스턴스 및 이름 스택 일괄 메모리 해제
    trace_spans = _trace_spans.pop(trace_id, None) or {}
    for sid in trace_spans:
        _active_spans.pop(sid, None)
        _span_names.pop(sid, None)
        _span_to_trace.pop(sid, None)

    _trace_spans_by_name.pop(trace_id, None)


def _resolve_parent_span(
    trace_id: str,
    parent_span_id: Optional[str],
    current_span_name: str,
    current_span_id: str,
) -> Optional[Any]:
    """현재 trace_id에 엄격히 격리된 범위 내에서만 부모 Span을 탐색한다 (P0 잔여 결함 보완).

    전역 이름 기반 조회를 원천 차단하며, 타 Trace 소속 Span에 대한 오염 연결을 거부한다.

    Args:
        trace_id: 현재 작업이 속한 Trace ID
        parent_span_id: 상위 구간 ID(UUID) 또는 노드/함수명
        current_span_name: 현재 생성할 구간명 (진단 로그용)
        current_span_id: 현재 생성할 구간 ID (진단 로그용)

    Returns:
        Optional[Any]: 검증된 부모 Span 인스턴스 (미해결 시 None).
    """
    if not parent_span_id:
        return None

    # 1단계: 현재 trace_id 격리 저장소에서 UUID 직접 매칭
    parent = _trace_spans.get(trace_id, {}).get(parent_span_id)
    if parent:
        return parent

    # 2단계: 현재 trace_id 격리 이름 스택에서 최신 활성 스팬 매칭 (중첩 에이전트 지원)
    if trace_id in _trace_spans_by_name and parent_span_id in _trace_spans_by_name[trace_id]:
        stack = _trace_spans_by_name[trace_id][parent_span_id]
        if stack:
            cand_id = stack[-1]
            parent = _trace_spans.get(trace_id, {}).get(cand_id)
            if parent:
                return parent

    # 3단계: 전역 UUID 인덱스 검증 - 반드시 _span_to_trace[parent_span_id] == trace_id 인 경우에만 허용
    if parent_span_id in _active_spans:
        owner_trace = _span_to_trace.get(parent_span_id)
        if owner_trace == trace_id:
            return _active_spans[parent_span_id]
        else:
            logger.warning(
                f"[SPAN_CROSS_TRACE_REJECTED] Rejected cross-trace parent '{parent_span_id}' "
                f"(belongs to '{owner_trace}') from being linked into trace '{trace_id}' "
                f"for span '{current_span_name}'({current_span_id})."
            )
            return None

    # 전역 이름 매칭(_active_spans_by_name)은 원천 차단됨!

    # 4단계: 부모 미해결 진단 로그 기록
    logger.warning(
        f"[SPAN_PARENT_UNRESOLVED] trace_id={trace_id}, span={current_span_name}({current_span_id}): "
        f"parent '{parent_span_id}' not found in active spans of this trace. Linking to root trace."
    )
    return None

def start_span(
    trace_id: str,
    span_id: str,
    name: str,
    parent_span_id: Optional[str] = None,
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Trace 하위에 새로운 작업 구간(Span)을 생성하고 계층 트리(Tree)에 연결한다.

    [P0-2 개선사항]
    1. trace_id별 격리 인덱스(_trace_spans, _trace_spans_by_name)를 우선 탐색하여,
       동일한 노드/에이전트가 다른 사건에서 동시 실행되더라도 부모가 섞이지 않도록 격리한다.
    2. ContextVar 기반의 UUID parent_span_id를 최우선 연결하고, 이름 기반 탐색 시에도
       해당 trace_id 내부의 최근 활성 스팬 스택([-1])을 참조하여 정확한 중첩 관계를 형성한다.
    3. 부모를 찾지 못할 경우 조용히 연결을 누락시키지 않고 경고 진단 로그를 기록한 후 Root Trace에 연결한다.
    4. 시스템 식별자(LANGFUSE_SYSTEM_NAME) 및 Git Commit을 메타데이터에 기록한다.

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

    # 비동기 종료 후 지연 콜백인 경우 새 Trace 생성 차단 (TC-P0-10)
    if trace_id in _ended_traces:
        logger.warning(
            f"[DELAYED_CALLBACK_IGNORED] start_span rejected for ended trace_id={trace_id}, span={name}({span_id})"
        )
        return

    # Trace가 아직 생성되지 않은 경우 자동 지연 생성 (Lazy Trace Creation)
    trace = _active_traces.get(trace_id)
    if not trace:
        try:
            from ai_legal_helper.observability.context import get_case_id
            session_id = get_case_id()
            git_sha = get_git_commit()
            trace = lf.trace(
                id=trace_id,
                name=f"Workflow:{name}",
                session_id=session_id,
                metadata={"system_name": sys_name, "git_commit": git_sha, "tags": [sys_name]},
                tags=[sys_name],
            )
            _active_traces[trace_id] = trace
        except Exception:
            return

    capture_content = os.getenv("LANGFUSE_CAPTURE_CONTENT", "false").lower() == "true"
    safe_input = input if capture_content else ("[MASKED FOR PRIVACY]" if input is not None else None)

    span_metadata = dict(metadata or {})
    if sys_name and "system_name" not in span_metadata:
        span_metadata["system_name"] = sys_name

    # 엄격한 trace_id 격리 부모 탐색 (전역 이름 탐색 제거)
    parent = _resolve_parent_span(trace_id, parent_span_id, name, span_id)
    if not parent:
        parent = trace

    try:
        span = parent.span(
            id=span_id,
            name=name,
            input=safe_input,
            metadata=span_metadata,
        )
        # Trace별 격리 인덱스 등록
        if trace_id not in _trace_spans:
            _trace_spans[trace_id] = {}
        _trace_spans[trace_id][span_id] = span

        if trace_id not in _trace_spans_by_name:
            _trace_spans_by_name[trace_id] = {}
        if name not in _trace_spans_by_name[trace_id]:
            _trace_spans_by_name[trace_id][name] = []
        _trace_spans_by_name[trace_id][name].append(span_id)

        _span_to_trace[span_id] = trace_id

        # 전역 인덱스 등록 (하위 호환성 유지)
        _active_spans[span_id] = span
        _active_spans_by_name[name] = span_id
        _span_names[span_id] = name
    except Exception:
        pass


def end_span(span_id: str, output: Any = None, level: str = "DEFAULT", status_message: str = ""):
    """작업 구간(Span)을 완료하고 결과를 기록한 뒤 활성 구간 캐시에서 안전하게 제거한다 (P0-2).

    Args:
        span_id: 완료할 구간 ID
        output: 작업 출력 결과
        level: 로그 레벨 (DEFAULT, WARNING, ERROR)
        status_message: 상태 메시지
    """
    lf = get_langfuse()
    if not lf:
        return

    # P0-2: Trace별 격리 인덱스 정리
    trace_id = _span_to_trace.pop(span_id, None)
    if trace_id and trace_id in _trace_spans:
        _trace_spans[trace_id].pop(span_id, None)

    name = _span_names.pop(span_id, None)
    if trace_id and name and trace_id in _trace_spans_by_name and name in _trace_spans_by_name[trace_id]:
        stack = _trace_spans_by_name[trace_id][name]
        if span_id in stack:
            stack.remove(span_id)
        if not stack:
            _trace_spans_by_name[trace_id].pop(name, None)

    # 전역 인덱스 정리
    span = _active_spans.pop(span_id, None)
    if name and _active_spans_by_name.get(name) == span_id:
        _active_spans_by_name.pop(name, None)

    if span:
        capture_content = os.getenv("LANGFUSE_CAPTURE_CONTENT", "false").lower() == "true"
        safe_output = output if capture_content else ("[MASKED FOR PRIVACY]" if output is not None else None)
        try:
            span.end(output=safe_output, level=level, status_message=status_message)
        except Exception:
            pass


def update_span(span_id: str, metadata: Dict[str, Any]):
    """작업 구간(Span)의 메타데이터를 갱신한다. UUID 또는 등록된 스팬 이름을 모두 지원한다 (P0-2)."""
    lf = get_langfuse()
    if not lf:
        return

    target_span = _active_spans.get(span_id)
    if not target_span and span_id in _active_spans_by_name:
        target_span = _active_spans.get(_active_spans_by_name[span_id])

    if target_span:
        try:
            target_span.update(metadata=metadata)
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
    model_parameters: Optional[Dict[str, Any]] = None,
    usage_details: Optional[Dict[str, int]] = None,
):
    """LLM 단독 호출 결과를 수동으로 기록한다 (P0-1 단일 계측 기준).

    모델명(model)이 정확히 전달되어야 Langfuse에서 모델 단가 매칭을 통한 비용(Cost) 계산이 수행된다.
    누락되거나 'unknown'인 경우 환경변수 배포 모델명으로 자동 보정한다.
    """
    lf = get_langfuse()
    if not lf:
        return

    sys_name = get_system_name()

        # 비동기 종료 후 지연 콜백인 경우 새 Trace 생성 차단 (TC-P0-10)
    if trace_id in _ended_traces:
        logger.warning(
            f"[DELAYED_CALLBACK_IGNORED] log_generation rejected for ended trace_id={trace_id}, gen={name}"
        )
        return

    trace = _active_traces.get(trace_id)
    if not trace:
        try:
            from ai_legal_helper.observability.context import get_case_id
            session_id = get_case_id()
            git_sha = get_git_commit()
            trace = lf.trace(
                id=trace_id,
                name="LLM_Trace",
                session_id=session_id,
                metadata={"system_name": sys_name, "git_commit": git_sha, "tags": [sys_name]},
                tags=[sys_name],
            )
            _active_traces[trace_id] = trace
        except Exception:
            return

    # 엄격한 trace_id 격리 부모 탐색 (전역 이름 탐색 제거)
    parent = _resolve_parent_span(trace_id, parent_span_id, name, "generation")
    if not parent:
        parent = trace

    level = "ERROR" if status_message else "DEFAULT"
    capture_content = os.getenv("LANGFUSE_CAPTURE_CONTENT", "false").lower() == "true"
    safe_input = input if capture_content else ("[MASKED FOR PRIVACY]" if input is not None else None)
    safe_output = output if capture_content else ("[MASKED FOR PRIVACY]" if output is not None else None)

    gen_metadata = dict(metadata or {})
    if sys_name and "system_name" not in gen_metadata:
        gen_metadata["system_name"] = sys_name
    if sys_name and "tags" not in gen_metadata:
        gen_metadata["tags"] = [sys_name]
    git_sha = get_git_commit()
    if git_sha and "git_commit" not in gen_metadata:
        gen_metadata["git_commit"] = git_sha

    # 모델명이 누락되거나 'unknown'인 경우 환경변수 배포 모델명으로 안전하게 보정 (Langfuse Cost 집계 보장)
    resolved_model = model
    if not resolved_model or resolved_model == "unknown":
        resolved_model = os.getenv("AZURE_OPENAI_DEPLOYMENT_CHAT", "gpt-4o")

    try:
        gen_kwargs = {
            "name": name,
            "model": resolved_model,
            "start_time": start_time,
            "end_time": end_time,
            "usage": usage,
            "input": safe_input,
            "output": safe_output,
            "level": level,
            "status_message": status_message,
            "metadata": gen_metadata,
        }
        if model_parameters:
            gen_kwargs["model_parameters"] = model_parameters
        if usage_details:
            gen_kwargs["usage_details"] = usage_details
        parent.generation(**gen_kwargs)
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
