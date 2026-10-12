"""
실행 컨텍스트 추적 모듈 (Context Tracking)

이 모듈은 `contextvars`를 사용하여 현재 실행 중인 비동기 태스크나 스레드 내에서
전역적으로 유지되어야 하는 관측성(Observability) 및 상태 데이터를 관리한다.
P0 단계에서 도입된 `trace_id`, `agent_name` 등의 로깅 컨텍스트뿐만 아니라,
P2.1 단계에서 AgentExecutor 내부 도구 실행 시 추출된 RAG 검색 출처(retrieved_sources)를
Thread 경계를 넘어 우회하여 수집하기 위한 용도로도 사용된다.

주의: `contextvars`는 Python 3.9+에서 `asyncio.to_thread`를 통해 자동으로 복사되므로
별도의 `ctx.run` 호출 없이도 병렬 스레드로 안전하게 전달된다. 단, 가변 객체(리스트)를
직접 수정할 경우 예상치 못한 부작용이 발생할 수 있으므로, 값 갱신 시에는 새로운 리스트를 
할당하는 방식을 권장한다.
"""
import contextvars
from typing import Optional
import uuid

_trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('trace_id', default=None)
_request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('request_id', default=None)
_case_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('case_id', default=None)
_run_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('run_id', default=None)
_agent_name_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('agent_name', default=None)
_node_name_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('node_name', default=None)
_current_span_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar('current_span_id', default=None)

def set_current_span_id(span_id: str) -> contextvars.Token:
    return _current_span_id_var.set(span_id)

def get_current_span_id() -> Optional[str]:
    return _current_span_id_var.get()

def reset_current_span_id(token: contextvars.Token):
    _current_span_id_var.reset(token)

def set_trace_id(trace_id: str) -> contextvars.Token:
    """추적 ID를 컨텍스트에 설정한다."""
    return _trace_id_var.set(trace_id)

def get_trace_id() -> Optional[str]:
    """컨텍스트에서 추적 ID를 가져온다."""
    return _trace_id_var.get()

def reset_trace_id(token: contextvars.Token):
    """추적 ID를 토큰 발급 시점의 상태로 롤백한다."""
    _trace_id_var.reset(token)

def set_request_id(request_id: str) -> contextvars.Token:
    """요청 ID를 컨텍스트에 설정한다."""
    return _request_id_var.set(request_id)

def get_request_id() -> Optional[str]:
    """컨텍스트에서 요청 ID를 가져온다."""
    return _request_id_var.get()

def reset_request_id(token: contextvars.Token):
    """요청 ID를 롤백한다."""
    _request_id_var.reset(token)

def set_case_id(case_id: str) -> contextvars.Token:
    """사건 ID를 컨텍스트에 설정한다."""
    return _case_id_var.set(case_id)

def get_case_id() -> Optional[str]:
    """컨텍스트에서 사건 ID를 가져온다."""
    return _case_id_var.get()

def reset_case_id(token: contextvars.Token):
    """사건 ID를 롤백한다."""
    _case_id_var.reset(token)

def set_run_id(run_id: str) -> contextvars.Token:
    """실행 ID를 컨텍스트에 설정한다."""
    return _run_id_var.set(run_id)

def get_run_id() -> Optional[str]:
    """컨텍스트에서 실행 ID를 가져온다."""
    return _run_id_var.get()

def reset_run_id(token: contextvars.Token):
    """실행 ID를 롤백한다."""
    _run_id_var.reset(token)

def set_agent_name(agent_name: str) -> contextvars.Token:
    """현재 실행 중인 에이전트의 이름을 컨텍스트에 설정한다."""
    return _agent_name_var.set(agent_name)

def get_agent_name() -> Optional[str]:
    """컨텍스트에서 에이전트의 이름을 가져온다."""
    return _agent_name_var.get()

def reset_agent_name(token: contextvars.Token):
    """에이전트의 이름을 롤백한다."""
    _agent_name_var.reset(token)

def set_node_name(node_name: str) -> contextvars.Token:
    """현재 실행 중인 LangGraph 노드의 이름을 컨텍스트에 설정한다."""
    return _node_name_var.set(node_name)

def get_node_name() -> Optional[str]:
    """컨텍스트에서 노드의 이름을 가져온다."""
    return _node_name_var.get()

def reset_node_name(token: contextvars.Token):
    """노드의 이름을 롤백한다."""
    _node_name_var.reset(token)

_retrieved_sources_var: contextvars.ContextVar[list] = contextvars.ContextVar('retrieved_sources', default=[])

def add_retrieved_source(source: dict):
    """
    RAG 검색 과정에서 참조된 문서 출처를 컨텍스트 변수에 추가한다.

    AgentExecutor가 툴의 결과를 반환하지 않는 문제를 해결하기 위해 도입되었다.
    가변 객체의 공유로 인한 부작용을 방지하기 위해, 기존 리스트에 원소를 추가하여
    새로운 리스트를 생성한 뒤 설정하는 방식을 사용한다.

    Args:
        source (dict): 추가할 검색 출처 정보
    """
    sources = _retrieved_sources_var.get()
    # It's better to create a new list or just append. Since contextvars are somewhat tricky with mutable objects,
    # let's set a new list.
    new_sources = list(sources) + [source]
    _retrieved_sources_var.set(new_sources)

def get_retrieved_sources() -> list:
    """
    컨텍스트에서 RAG 검색 출처 목록을 가져온다.
    
    Returns:
        list: 현재 컨텍스트에 누적된 출처 딕셔너리의 리스트
    """
    return _retrieved_sources_var.get()

def reset_retrieved_sources():
    """
    RAG 검색 출처 목록을 빈 리스트로 초기화한다.
    주로 새로운 에이전트 실행 시작 지점에서 호출하여 이전 데이터를 정리한다.
    """
    _retrieved_sources_var.set([])

def get_context_dict() -> dict:
    """
    현재 컨텍스트에 저장된 주요 로깅 식별자들을 딕셔너리로 반환한다.
    
    이 딕셔너리는 외부 로깅 시스템(OpenTelemetry, TokenTracker 등)에 
    전달할 메타데이터로 활용된다.

    Returns:
        dict: 추적, 요청, 에이전트 정보 등을 포함한 딕셔너리
    """
    return {
        "trace_id": get_trace_id(),
        "request_id": get_request_id(),
        "case_id": get_case_id(),
        "run_id": get_run_id(),
        "agent_name": get_agent_name(),
        "node_name": get_node_name(),
    }

