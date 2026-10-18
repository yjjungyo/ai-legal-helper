# -*- coding: utf-8 -*-
"""
모듈명: decorators.py

[모듈 개요]
함수 및 코루틴 실행 전후의 구조화 로깅, OpenTelemetry Span 기록, Langfuse Trace/Span 계층 추적을
자동화하는 `@trace` 데코레이터 모듈이다.

[주요 기능]
1. 실행 시작/성공/오류 시점의 소요 시간(elapsed_ms) 및 소스 위치 로깅
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
from ai_legal_helper.observability.langfuse_client import start_trace, start_span, end_span, end_trace, flush_langfuse
from opentelemetry.trace import Status, StatusCode

logger = get_logger(__name__)


def _get_func_meta(func: Callable) -> tuple[str, int]:
    """함수의 소스 파일 경로와 시작 라인 번호를 안전하게 조회한다 (OSError 방지)."""
    try:
        code_obj = getattr(func, "__code__", None)
        if code_obj is not None:
            return code_obj.co_filename, code_obj.co_firstlineno
        return inspect.getfile(func), inspect.getsourcelines(func)[1]
    except Exception:
        return getattr(func, "__module__", "unknown"), 0


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
        logger.info(f"Starting execution of {func.__name__}", extra=log_data)

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
            logger.debug(f"Langfuse log_entry error: {ex}")

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
        logger.info(f"Successfully completed {func.__name__}", extra=log_data)

        try:
            end_span(span_id=current_span_id, output=output_data)
        except Exception as ex:
            logger.debug(f"Langfuse log_success error: {ex}")

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
            return text

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
        logger.error(f"Error in {func.__name__}: {safe_error_msg}", extra=log_data)

        try:
            end_span(
                span_id=current_span_id,
                level="ERROR",
                status_message=safe_error_msg,
            )
        except Exception as ex:
            logger.debug(f"Langfuse log_error error: {ex}")

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
                    "args": [repr(a)[:500] for a in args],
                    "kwargs": {k: repr(v)[:500] for k, v in kwargs.items()},
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
                    "args": [repr(a)[:500] for a in args],
                    "kwargs": {k: repr(v)[:500] for k, v in kwargs.items()},
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

