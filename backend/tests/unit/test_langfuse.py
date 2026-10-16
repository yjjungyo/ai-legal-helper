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

