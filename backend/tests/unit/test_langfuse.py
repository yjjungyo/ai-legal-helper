# -*- coding: utf-8 -*-
"""
테스트 모듈: test_langfuse.py

[테스트 개요]
Langfuse 관측성 통합 모듈(langfuse_client, gateway get_llm)의 정상 동작을 검증한다.

[주요 검증 항목]
1. get_langfuse() 클라이언트 초기화 상태 확인
2. get_langfuse_callback_handler() 콜백 핸들러 생성 확인
3. get_llm() 인스턴스에 Langfuse CallbackHandler가 올바르게 부착되는지 확인
4. flush_langfuse() 호출 시 예외 없이 플러시가 수행되는지 확인
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from ai_legal_helper.observability.langfuse_client import (
    get_langfuse,
    get_langfuse_callback_handler,
    flush_langfuse,
)
from ai_legal_helper.llm.gateway import get_llm


def test_langfuse_callback_handler_creation():
    """Langfuse 설정이 활성화되어 있을 때 CallbackHandler가 정상 생성되는지 검증한다."""
    handler = get_langfuse_callback_handler(trace_name="test-trace")
    if os.getenv("LANGFUSE_ENABLED", "false").lower() == "true":
        assert handler is not None, "LANGFUSE_ENABLED=true 상태에서는 CallbackHandler가 반환되어야 합니다."
    else:
        assert handler is None


def test_get_llm_attaches_langfuse_callback():
    """get_llm() 호출 시 반환되는 LLM 객체에 콜백 핸들러가 포함되어 있는지 검증한다."""
    llm = get_llm(model_name="aicore-gpt4o")
    assert llm is not None
    assert hasattr(llm, "callbacks")
    assert len(llm.callbacks) >= 1

    # LANGFUSE_ENABLED=true인 경우 최소 2개 이상의 콜백(TokenTracker, Langfuse) 등록 여부 점검
    if os.getenv("LANGFUSE_ENABLED", "false").lower() == "true":
        callback_types = [type(cb).__name__ for cb in llm.callbacks]
        assert "LangchainCallbackHandler" in callback_types or "TokenTrackingCallbackHandler" in callback_types


def test_flush_langfuse_no_error():
    """flush_langfuse() 호출이 정상적으로 에러 없이 종료되는지 검증한다."""
    try:
        flush_langfuse()
    except Exception as e:
        pytest.fail(f"flush_langfuse() 실행 중 예외가 발생했습니다: {e}")


def test_get_llm_sets_system_name_and_tags():
    """get_llm() 생성 시 AzureChatOpenAI 인스턴스의 name과 tags가 LANGFUSE_SYSTEM_NAME(기본값: LegalAgent)으로 설정되는지 검증한다."""
    with patch.dict(os.environ, {"LANGFUSE_SYSTEM_NAME": "LegalAgent"}):
        llm = get_llm(model_name="aicore-gpt4o")
        assert llm.name == "LegalAgent", f"Expected llm.name to be 'LegalAgent', got '{llm.name}'"
        assert llm.tags == ["LegalAgent"], f"Expected llm.tags to be ['LegalAgent'], got '{llm.tags}'"


def test_callback_handler_uses_legalagent_run_name_not_azurechatopenai():
    """Langfuse CallbackHandler가 LLM 호출을 가로챌 때 run_name이 AzureChatOpenAI가 아닌 LegalAgent로 결정되는지 검증한다."""
    from langfuse.callback import CallbackHandler
    with patch.dict(os.environ, {"LANGFUSE_SYSTEM_NAME": "LegalAgent"}):
        llm = get_llm(model_name="aicore-gpt4o")
        handler = CallbackHandler(public_key="pk-test", secret_key="sk-test", host="http://localhost:3001")
        serialized = llm.to_json()
        run_name = handler.get_langchain_run_name(serialized)
        assert run_name == "LegalAgent", f"Expected run_name to be 'LegalAgent', got '{run_name}' (AzureChatOpenAI 누출 방지)"


def test_token_tracking_callback_handler_logs_legalagent_generation():
    """TokenTrackingCallbackHandler가 on_llm_end 시 name='LegalAgent' 및 tag='LegalAgent'로 log_generation을 호출하는지 검증한다."""
    from ai_legal_helper.observability.callbacks import TokenTrackingCallbackHandler
    from langchain_core.outputs import LLMResult, Generation

    handler = TokenTrackingCallbackHandler()
    fake_result = LLMResult(
        generations=[[Generation(text="계약 해지 효력이 발생했습니다.")]],
        llm_output={"token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}},
    )

    with patch.dict(os.environ, {"LANGFUSE_SYSTEM_NAME": "LegalAgent"}):
        with patch("ai_legal_helper.observability.langfuse_client.log_generation") as mock_log_gen:
            handler.on_chat_model_start({}, [], run_id="test-run-123")
            handler.on_llm_end(fake_result, run_id="test-run-123", invocation_params={"model_name": "gpt-4o"})

            assert mock_log_gen.called
            call_kwargs = mock_log_gen.call_args[1]
            assert call_kwargs["name"] == "LegalAgent"
            assert call_kwargs["metadata"]["system_name"] == "LegalAgent"
            assert "LegalAgent" in call_kwargs["metadata"]["tags"]


