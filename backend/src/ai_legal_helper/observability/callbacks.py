# -*- coding: utf-8 -*-
"""
모듈명: callbacks.py

[모듈 개요]
LangChain LLM 호출의 시작·종료·오류 시점을 가로채어 토큰 사용량(LLMUsageRecord)을 집계하고,
활성 Span(`get_current_span_id()`) 하위에 Langfuse Generation 레코드를 기록하는 콜백 핸들러 모듈이다.
Azure OpenAI 실제 응답의 정밀 모델명(예: 'gpt-5.4-2026-03-05')을 추출하여
Langfuse에서 모델 식별 및 비용(Cost)이 정확하게 집계되도록 지원한다.
"""
import os
import uuid
import time
from typing import Any, Dict, List, Optional
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
        """콜백 핸들러의 호출 시작 시각, 입력 데이터, 모델 식별자 저장소를 초기화한다."""
        self.call_start_times: Dict[str, float] = {}
        self.call_inputs: Dict[str, Any] = {}
        self.call_models: Dict[str, str] = {}
        self.call_params: Dict[str, Dict[str, Any]] = {}

    def _extract_model_from_context(
        self, serialized: Optional[Dict[str, Any]], kwargs: Dict[str, Any]
    ) -> str:
        """호출 시작 시점에 전달된 직렬화 정보 및 파라미터로부터 모델/배포명을 추출한다."""
        inv_params = kwargs.get("invocation_params") or {}
        if inv_params.get("azure_deployment"):
            return str(inv_params["azure_deployment"])
        if inv_params.get("model_name"):
            return str(inv_params["model_name"])
        if inv_params.get("model"):
            return str(inv_params["model"])

        if serialized and isinstance(serialized, dict):
            s_kwargs = serialized.get("kwargs") or {}
            if s_kwargs.get("azure_deployment"):
                return str(s_kwargs["azure_deployment"])
            if s_kwargs.get("model_name"):
                return str(s_kwargs["model_name"])
            if s_kwargs.get("model"):
                return str(s_kwargs["model"])
            if s_kwargs.get("deployment_name"):
                return str(s_kwargs["deployment_name"])

        meta = kwargs.get("metadata") or {}
        if meta.get("model_name"):
            return str(meta["model_name"])

        return os.getenv("AZURE_OPENAI_DEPLOYMENT_CHAT", "gpt-4o")

    def _extract_model_parameters(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """호출 파라미터에서 온도, 최대 토큰 등 모델 매개변수를 안전하게 추출한다."""
        inv_params = kwargs.get("invocation_params") or {}
        params: Dict[str, Any] = {}
        for k in ("temperature", "max_tokens", "max_completion_tokens", "top_p", "stream"):
            if k in inv_params and inv_params[k] is not None:
                params[k] = inv_params[k]
        return params

    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> Any:
        """일반 LLM 호출 시작 시각, 프롬프트, 모델 정보를 기록한다."""
        run_id = str(kwargs.get("run_id", uuid.uuid4()))
        self.call_start_times[run_id] = time.time()
        self.call_inputs[run_id] = prompts
        self.call_models[run_id] = self._extract_model_from_context(serialized, kwargs)
        self.call_params[run_id] = self._extract_model_parameters(kwargs)

    def on_chat_model_start(
        self, serialized: Dict[str, Any], messages: List[List[Any]], **kwargs: Any
    ) -> Any:
        """채팅 모델(ChatModel) 호출 시작 시각, 입력 메시지, 모델 정보를 기록한다."""
        run_id = str(kwargs.get("run_id", uuid.uuid4()))
        self.call_start_times[run_id] = time.time()
        formatted_msgs = []
        for batch in (messages or []):
            for msg in batch:
                content = getattr(msg, "content", str(msg))
                role = getattr(msg, "type", getattr(msg, "role", "message"))
                formatted_msgs.append({"role": role, "content": content})
        self.call_inputs[run_id] = formatted_msgs
        self.call_models[run_id] = self._extract_model_from_context(serialized, kwargs)
        self.call_params[run_id] = self._extract_model_parameters(kwargs)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """LLM 호출 완료 시 실제 응답 모델명과 토큰을 집계하고 활성 Span 하위에 Generation을 기록한다."""
        run_id = str(kwargs.get("run_id", ""))
        start_time = self.call_start_times.pop(run_id, time.time())
        input_data = self.call_inputs.pop(run_id, None)
        start_model = self.call_models.pop(run_id, None)
        model_parameters = self.call_params.pop(run_id, None)
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

        # 모델명 결정: Azure OpenAI 응답 결과(response.llm_output['model_name'])가 최우선
        # (예: 'gpt-5.4-2026-03-05'와 같은 정밀 배포 모델명이 있어야 Langfuse에서 모델 매칭 및 비용(Cost) 계산 가능)
        model_id = None
        if response.llm_output and isinstance(response.llm_output, dict):
            model_id = response.llm_output.get("model_name") or response.llm_output.get("model")

        if not model_id or model_id == "unknown":
            model_id = start_model

        if not model_id or model_id == "unknown":
            inv_params = kwargs.get("invocation_params") or {}
            model_id = (
                inv_params.get("azure_deployment")
                or inv_params.get("model_name")
                or inv_params.get("model")
            )

        if not model_id or model_id == "unknown":
            model_id = os.getenv("AZURE_OPENAI_DEPLOYMENT_CHAT", "gpt-4o")

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

        # Langfuse logging: 실제 입출력 텍스트 및 정확한 모델명/토큰을 전달
        try:
            from ai_legal_helper.observability.langfuse_client import log_generation
            usage_dict = {
                "input": input_tokens or 0,
                "output": output_tokens or 0,
                "total": total_tokens or 0,
            }
            usage_details = {
                "input": input_tokens or 0,
                "output": output_tokens or 0,
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
                usage_details=usage_details,
                model_parameters=model_parameters,
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
        model_id = (
            self.call_models.pop(run_id, None)
            or kwargs.get("invocation_params", {}).get("azure_deployment")
            or kwargs.get("invocation_params", {}).get("model_name")
            or os.getenv("AZURE_OPENAI_DEPLOYMENT_CHAT", "gpt-4o")
        )
        model_parameters = self.call_params.pop(run_id, None)
        latency_ms = (time.time() - start_time) * 1000

        record = LLMUsageRecord(
            call_id=run_id,
            trace_id=get_trace_id(),
            case_id=get_case_id(),
            agent_name=get_agent_name(),
            node_name=get_node_name(),
            model_id=model_id,
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
                model=model_id,
                start_time=start_time,
                end_time=time.time(),
                usage={"input": 0, "output": 0, "total": 0},
                status_message=str(error),
                model_parameters=model_parameters,
                input=input_data,
                output=f"ERROR: {str(error)}",
                metadata={"system_name": LANGFUSE_SYSTEM_NAME, "tags": [LANGFUSE_SYSTEM_NAME]},
            )
        except Exception as e:
            logger.warning(f"Failed to log generation error to Langfuse: {e}")
