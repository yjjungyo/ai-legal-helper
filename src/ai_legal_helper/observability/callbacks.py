import uuid
import time
from typing import Any, Dict, List, Optional
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from ai_legal_helper.llm.usage import LLMUsageRecord, global_token_tracker
from ai_legal_helper.observability.context import (
    get_trace_id, get_case_id, get_agent_name, get_node_name
)
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

class TokenTrackingCallbackHandler(BaseCallbackHandler):
    """Callback Handler to track LLM token usage."""
    
    def __init__(self):
        self.call_start_times: Dict[str, float] = {}

    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> Any:
        run_id = str(kwargs.get("run_id", uuid.uuid4()))
        self.call_start_times[run_id] = time.time()

    def on_chat_model_start(
        self, serialized: Dict[str, Any], messages: List[List[Any]], **kwargs: Any
    ) -> Any:
        run_id = str(kwargs.get("run_id", uuid.uuid4()))
        self.call_start_times[run_id] = time.time()

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        run_id = str(kwargs.get("run_id", ""))
        start_time = self.call_start_times.pop(run_id, time.time())
        latency_ms = (time.time() - start_time) * 1000

        # Attempt to extract usage
        input_tokens = None
        output_tokens = None
        total_tokens = None
        usage_source = "unavailable"

        if response.llm_output and "token_usage" in response.llm_output:
            token_usage = response.llm_output["token_usage"]
            input_tokens = token_usage.get("prompt_tokens")
            output_tokens = token_usage.get("completion_tokens")
            total_tokens = token_usage.get("total_tokens")
            usage_source = "actual"

        model_id = kwargs.get("invocation_params", {}).get("model_name", "unknown")

        record = LLMUsageRecord(
            call_id=run_id,
            trace_id=get_trace_id(),
            case_id=get_case_id(),
            agent_name=get_agent_name(),
            node_name=get_node_name(),
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            usage_source=usage_source,
            latency_ms=latency_ms,
            status="SUCCESS"
        )
        global_token_tracker.add_record(record)
        logger.info(f"LLM Call End", extra=record.model_dump())
        
        # P3.6 Langfuse logging
        try:
            from ai_legal_helper.observability.langfuse_client import log_generation
            usage_dict = {
                "input": input_tokens or 0,
                "output": output_tokens or 0,
                "total": total_tokens or 0
            }
            log_generation(
                trace_id=get_trace_id(),
                parent_span_id=get_node_name() or get_agent_name(), # using node_name as span_id
                name="AzureOpenAI_Call",
                model=model_id,
                start_time=start_time,
                end_time=time.time(),
                usage=usage_dict
            )
        except Exception as e:
            logger.warning(f"Failed to log generation to Langfuse: {e}")

    def on_llm_error(
        self, error: BaseException, **kwargs: Any
    ) -> Any:
        run_id = str(kwargs.get("run_id", ""))
        start_time = self.call_start_times.pop(run_id, time.time())
        latency_ms = (time.time() - start_time) * 1000

        record = LLMUsageRecord(
            call_id=run_id,
            trace_id=get_trace_id(),
            case_id=get_case_id(),
            agent_name=get_agent_name(),
            node_name=get_node_name(),
            model_id="unknown",
            status="ERROR",
            error_type=type(error).__name__,
            latency_ms=latency_ms
        )
        global_token_tracker.add_record(record)
        logger.error(f"LLM Call Error: {str(error)}", extra=record.model_dump())
        
        # P3.6 Langfuse logging
        try:
            from ai_legal_helper.observability.langfuse_client import log_generation
            log_generation(
                trace_id=get_trace_id(),
                parent_span_id=get_node_name() or get_agent_name(),
                name="AzureOpenAI_Call",
                model="unknown",
                start_time=start_time,
                end_time=time.time(),
                usage={"input": 0, "output": 0, "total": 0},
                status_message=str(error)
            )
        except Exception as e:
            logger.warning(f"Failed to log generation error to Langfuse: {e}")

