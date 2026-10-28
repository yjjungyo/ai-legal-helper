# -*- coding: utf-8 -*-
"""
모듈명: callbacks.py

[모듈 개요]
LangChain LLM 호출의 시작·종료·오류 시점을 가로채어 토큰 사용량(LLMUsageRecord)을 집계하고,
활성 Span(`get_current_span_id()`) 하위에 Langfuse Generation 레코드를 기록하는 콜백 핸들러 모듈이다.
"""
import os
import uuid
import time
from typing import Any, Dict, List
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from ai_legal_helper.llm.usage import LLMUsageRecord, global_token_tracker
from ai_legal_helper.observability.context import (
    get_trace_id, get_case_id, get_agent_name, get_node_name, get_current_span_id
)
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)


class TokenTrackingCallbackHandler(BaseCallbackHandler):
    """LLM 호출별 토큰 사용량과 지연 시간을 추적하고 Langfuse Generation을 기록하는 콜백 핸들러."""

    def __init__(self):
        """콜백 핸들러의 호출 시작 시각 및 입력 데이터 저장소를 초기화한다."""
        self.call_start_times: Dict[str, float] = {}
        self.call_inputs: Dict[str, Any] = {}

    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> Any:
        """일반 LLM 호출 시작 시각 및 프롬프트를 기록한다."""
        run_id = str(kwargs.get("run_id", uuid.uuid4()))
        self.call_start_times[run_id] = time.time()
        self.call_inputs[run_id] = prompts

    def on_chat_model_start(
        self, serialized: Dict[str, Any], messages: List[List[Any]], **kwargs: Any
    ) -> Any:
        """채팅 모델(ChatModel) 호출 시작 시각 및 입력 메시지들을 기록한다."""
        run_id = str(kwargs.get("run_id", uuid.uuid4()))
        self.call_start_times[run_id] = time.time()
        formatted_msgs = []
        for batch in (messages or []):
            for msg in batch:
                content = getattr(msg, "content", str(msg))
                role = getattr(msg, "type", getattr(msg, "role", "message"))
                formatted_msgs.append({"role": role, "content": content})
        self.call_inputs[run_id] = formatted_msgs

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """LLM 호출 완료 시 토큰 사용량을 집계하고 현재 활성 Span 하위에 실제 입출력을 포함한 Generation을 기록한다."""
        run_id = str(kwargs.get("run_id", ""))
        start_time = self.call_start_times.pop(run_id, time.time())
        input_data = self.call_inputs.pop(run_id, None)
        latency_ms = (time.time() - start_time) * 1000

        output_text = None
        if response.generations:
            for gen_list in response.generations:
                for g in gen_list:
                    txt = getattr(g, "text", "") or getattr(getattr(g, "message", None), "content", "")
                    if txt:
                        output_text = (output_text + "\n" + txt) if output_text else txt

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
            status="SUCCESS",
        )
        global_token_tracker.add_record(record)
        logger.info("LLM Call End", extra=record.model_dump())

        # Langfuse logging: 실제 입출력 텍스트를 전달하여 개발/테스트 시 원문 검증 가능
        try:
            from ai_legal_helper.observability.langfuse_client import log_generation
            usage_dict = {
                "input": input_tokens or 0,
                "output": output_tokens or 0,
                "total": total_tokens or 0,
            }
            LANGFUSE_SYSTEM_NAME = os.getenv("LANGFUSE_SYSTEM_NAME", "LegalAgent")
            log_generation(
                trace_id=get_trace_id(),
                parent_span_id=get_current_span_id() or get_node_name() or get_agent_name(),
                name=LANGFUSE_SYSTEM_NAME,
                model=model_id,
                start_time=start_time,
                end_time=time.time(),
                usage=usage_dict,
                input=input_data,
                output=output_text,
                metadata={"system_name": LANGFUSE_SYSTEM_NAME, "tags": [LANGFUSE_SYSTEM_NAME]},
            )
        except Exception as e:
            logger.warning(f"Failed to log generation to Langfuse: {e}")

    def on_llm_error(
        self, error: BaseException, **kwargs: Any
    ) -> Any:
        """LLM 호출 실패 시 에러 내역을 토큰 추적기 및 Langfuse Generation에 기록한다."""
        run_id = str(kwargs.get("run_id", ""))
        start_time = self.call_start_times.pop(run_id, time.time())
        input_data = self.call_inputs.pop(run_id, None)
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
            latency_ms=latency_ms,
        )
        global_token_tracker.add_record(record)
        logger.error(f"LLM Call Error: {str(error)}", extra=record.model_dump())

        LANGFUSE_SYSTEM_NAME = os.getenv("LANGFUSE_SYSTEM_NAME", "LegalAgent")
        try:
            from ai_legal_helper.observability.langfuse_client import log_generation
            log_generation(
                trace_id=get_trace_id(),
                parent_span_id=get_current_span_id() or get_node_name() or get_agent_name(),
                name=LANGFUSE_SYSTEM_NAME,
                model="unknown",
                start_time=start_time,
                end_time=time.time(),
                usage={"input": 0, "output": 0, "total": 0},
                status_message=str(error),
                input=input_data,
                output=f"ERROR: {str(error)}",
                metadata={"system_name": LANGFUSE_SYSTEM_NAME, "tags": [LANGFUSE_SYSTEM_NAME]},
            )
        except Exception as e:
            logger.warning(f"Failed to log generation error to Langfuse: {e}")


