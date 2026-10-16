import functools
import inspect
import time
import uuid
from typing import Callable, Any
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

def trace(func: Callable) -> Callable:
    is_coroutine = inspect.iscoroutinefunction(func)

    def log_entry(start_time: float, current_trace_id: str, current_span_id: str, is_new_trace: bool, parent_agent: str, parent_node: str):
        log_data = {
            "status": "START",
            "source_file": inspect.getfile(func),
            "source_function": func.__name__,
            "source_line": inspect.getsourcelines(func)[1],
            "agent_name": parent_agent,
            "node_name": parent_node,
        }
        logger.info(f"Starting execution of {func.__name__}", extra=log_data)
        
        # P3.6 Langfuse
        try:
            if is_new_trace:
                start_trace(
                    trace_id=current_trace_id, 
                    name=f"Workflow:{func.__name__}", 
                    metadata={"agent_name": parent_agent}
                )
            start_span(
                trace_id=current_trace_id,
                span_id=current_span_id,
                name=func.__name__,
                parent_span_id=parent_node or parent_agent
            )
        except Exception as ex:
            logger.debug(f"Langfuse log_entry error: {ex}")
        
    def log_success(start_time: float, current_span_id: str, parent_agent: str, parent_node: str):
        elapsed_ms = (time.time() - start_time) * 1000
        log_data = {
            "status": "SUCCESS",
            "source_file": inspect.getfile(func),
            "source_function": func.__name__,
            "source_line": inspect.getsourcelines(func)[1],
            "elapsed_ms": elapsed_ms,
            "agent_name": parent_agent,
            "node_name": parent_node,
        }
        logger.info(f"Successfully completed {func.__name__}", extra=log_data)

        # P3.6 Langfuse
        try:
            end_span(
                span_id=current_span_id
            )
        except Exception as ex:
            logger.debug(f"Langfuse log_success error: {ex}")

    def log_error(start_time: float, current_span_id: str, e: Exception, parent_agent: str, parent_node: str):
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Get actual error location
        tb = e.__traceback__
        while tb and tb.tb_next:
            tb = tb.tb_next
            
        error_file = tb.tb_frame.f_code.co_filename if tb else inspect.getfile(func)
        error_function = tb.tb_frame.f_code.co_name if tb else func.__name__
        error_line = tb.tb_lineno if tb else inspect.getsourcelines(func)[1]

        import traceback
        import re

        def scrub_sensitive_info(text: str) -> str:
            if not isinstance(text, str):
                return text
            # Scrub API Keys and common tokens
            text = re.sub(r'(api[_-]?key)=[\w-]+', r'\1=***', text, flags=re.IGNORECASE)
            text = re.sub(r'(sk-)[a-zA-Z0-9]{20,}', r'\1***', text)
            # Bearer tokens
            text = re.sub(r'(Bearer\s+)[a-zA-Z0-9\-\._~+/]+=*', r'\1***', text, flags=re.IGNORECASE)
            # Azure credentials (e.g., Endpoint or keys in dicts/strings)
            text = re.sub(r'(azure[_-]?openai[_-]?endpoint)=https?://[^\s\'"]+', r'\1=***', text, flags=re.IGNORECASE)
            # PII - Email
            text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', r'***@***.***', text)
            # PII - SSN / Phone (basic examples for KR: 010-XXXX-XXXX, YYMMDD-XXXXXXX)
            text = re.sub(r'\b010-\d{3,4}-\d{4}\b', '010-****-****', text)
            text = re.sub(r'\b\d{6}-[1-4]\d{6}\b', '******-*******', text)
            return text

        raw_stack_trace = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        stack_trace = scrub_sensitive_info(raw_stack_trace)
        safe_error_msg = scrub_sensitive_info(str(e))

        log_data = {
            "status": "ERROR",
            "source_file": inspect.getfile(func),
            "source_function": func.__name__,
            "source_line": inspect.getsourcelines(func)[1],
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

        # P3.6 Langfuse
        try:
            end_span(
                span_id=current_span_id,
                level="ERROR",
                status_message=safe_error_msg
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

            start_time = time.time()
            current_span_id = str(uuid.uuid4())
            span_token = set_current_span_id(current_span_id)
            log_entry(start_time, current_trace_id, current_span_id, is_new_trace, parent_agent, parent_node)

            with tracer.start_as_current_span(func.__name__) as span:
                span.set_attribute("trace_id", current_trace_id)
                if parent_agent: span.set_attribute("agent_name", parent_agent)
                if parent_node: span.set_attribute("node_name", parent_node)
                
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    log_success(start_time, current_span_id, parent_agent, parent_node)
                    return result
                except Exception as e:
                    import re
                    # Re-scrub for span just in case, or we could extract it from above if we factored it out, 
                    # but easiest is to scrub it again for OTel
                    safe_span_msg = str(e)
                    safe_span_msg = re.sub(r'(api[_-]?key)=[\w-]+', r'\1=***', safe_span_msg, flags=re.IGNORECASE)
                    safe_span_msg = re.sub(r'(sk-)[a-zA-Z0-9]{20,}', r'\1***', safe_span_msg)
                    safe_span_msg = re.sub(r'(Bearer\s+)[a-zA-Z0-9\-\._~+/]+=*', r'\1***', safe_span_msg, flags=re.IGNORECASE)
                    span.record_exception(e) # OTel record_exception might capture raw traceback, this is a risk. We should set_status with scrubbed message.
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

            start_time = time.time()
            current_span_id = str(uuid.uuid4())
            span_token = set_current_span_id(current_span_id)
            log_entry(start_time, current_trace_id, current_span_id, is_new_trace, parent_agent, parent_node)

            with tracer.start_as_current_span(func.__name__) as span:
                span.set_attribute("trace_id", current_trace_id)
                if parent_agent: span.set_attribute("agent_name", parent_agent)
                if parent_node: span.set_attribute("node_name", parent_node)

                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    log_success(start_time, current_span_id, parent_agent, parent_node)
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
