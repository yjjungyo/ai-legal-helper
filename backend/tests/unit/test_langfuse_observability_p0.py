"""Langfuse Observability 고도화 v2.0 (1차 정확성 확보: P0-1, P0-2, P0-3) 단위 테스트 모듈.

본 모듈은 다음 5대 핵심 요구사항을 검증한다:
- TC-01: 단일 워크플로우 실행 시 Trace 이름('LegalConsultation') 표준화 및 LLM 1회 호출당 Generation 1회 정확 기록 (P0-1, P0-3)
- TC-02: 서로 다른 상담(Trace A, Trace B) 동시 실행 시 동일 노드명 Span의 상호 오염 차단 및 격리 검증 (P0-2)
- TC-03: 동일 워크플로우 내 중첩·반복 에이전트 호출 시 Span 이름 스택(Stack) 정상 동작 및 부모 복원 (P0-2)
- TC-04: Git Commit SHA 및 시스템 식별자('LegalAgent')의 Trace/Generation 메타데이터 자동 주입 검증 (P0-3)
- TC-05: 워크플로우 종료 시 end_trace()에 의한 내부 활성 Span 및 Trace 인덱스 메모리 누수 방지 정리 (P0-2)
"""

import time
from unittest.mock import MagicMock, patch
import pytest

from ai_legal_helper.observability import langfuse_client
from ai_legal_helper.observability.context import (
    set_trace_id, reset_trace_id, set_case_id, reset_case_id,
    set_current_span_id, reset_current_span_id
)
from ai_legal_helper.observability.callbacks import TokenTrackingCallbackHandler


@pytest.fixture(autouse=True)
def clean_langfuse_state():
    """각 테스트 전후로 Langfuse 클라이언트 내부 메모리 상태를 초기화한다."""
    langfuse_client._active_traces.clear()
    langfuse_client._active_spans.clear()
    langfuse_client._span_names.clear()
    langfuse_client._trace_spans.clear()
    langfuse_client._trace_spans_by_name.clear()
    langfuse_client._span_to_trace.clear()
    yield
    langfuse_client._active_traces.clear()
    langfuse_client._active_spans.clear()
    langfuse_client._span_names.clear()
    langfuse_client._trace_spans.clear()
    langfuse_client._trace_spans_by_name.clear()
    langfuse_client._span_to_trace.clear()


def test_tc01_single_trace_and_generation_instrumentation():
    """TC-01: 단일 Trace 표준 이름('LegalConsultation') 및 LLM 1회 호출당 1회 Generation 기록 검증."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_lf.trace.return_value = mock_trace
    mock_gen = MagicMock()
    mock_trace.generation.return_value = mock_gen

    with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
        trace_id = "trace-tc01-uuid"
        case_id = "case-tc01-uuid"

        # 1. 최상위 Trace 시작
        langfuse_client.start_trace(
            trace_id=trace_id,
            name="LegalConsultation",
            session_id=case_id,
            metadata={"request_id": "req-tc01", "case_id": case_id},
        )

        # Trace 생성 확인
        mock_lf.trace.assert_called_once()
        trace_args, trace_kwargs = mock_lf.trace.call_args
        assert trace_kwargs.get("id") == trace_id
        assert trace_kwargs.get("name") == "LegalConsultation"
        assert trace_kwargs.get("session_id") == case_id
        assert "LegalAgent" in trace_kwargs.get("tags", [])
        assert trace_kwargs.get("metadata", {}).get("git_commit") is not None

        # 2. TokenTrackingCallbackHandler를 통한 LLM 호출 완료 시뮬레이션
        t_token = set_trace_id(trace_id)
        c_token = set_case_id(case_id)
        try:
            handler = TokenTrackingCallbackHandler()
            run_id = "run-tc01-llm"
            handler.call_start_times[run_id] = time.time()
            handler.call_inputs[run_id] = "임차보증금 반환 요건 질문"

            # 가상 LLM 응답 생성
            mock_llm_res = MagicMock()
            mock_gen_obj = MagicMock()
            mock_gen_obj.text = "주택임대차보호법 제3조 제1항에 따르면..."
            mock_gen_obj.message = None
            mock_llm_res.generations = [[mock_gen_obj]]
            mock_llm_res.llm_output = {
                "token_usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 80,
                    "total_tokens": 200,
                }
            }

            handler.on_llm_end(mock_llm_res, run_id=run_id, invocation_params={"model_name": "gpt-4o"})

            # Generation이 Trace에 정확히 1회 기록되었는지 검증
            mock_trace.generation.assert_called_once()
            _, gen_kwargs = mock_trace.generation.call_args
            assert gen_kwargs.get("name") == "LegalAgent"
            assert "LegalAgent" in gen_kwargs.get("metadata", {}).get("tags", [])
            assert gen_kwargs.get("usage", {}).get("total") == 200
            assert gen_kwargs.get("metadata", {}).get("git_commit") is not None
        finally:
            reset_trace_id(t_token)
            reset_case_id(c_token)


def test_tc02_concurrent_traces_span_isolation():
    """TC-02: 서로 다른 상담(Trace A, Trace B) 동시 실행 시 동일 노드명 Span 격리 검증.
    
    Trace A와 Trace B가 동시에 동일한 'supervisor_initialize' 노드를 실행할 때,
    Trace A 하위의 후속 작업이 Trace B의 Span에 잘못 연결되지 않는지 검증한다.
    """
    mock_lf = MagicMock()
    trace_a_mock = MagicMock()
    trace_b_mock = MagicMock()

    span_a_mock = MagicMock()
    span_b_mock = MagicMock()
    child_a_mock = MagicMock()

    trace_a_mock.span.return_value = span_a_mock
    trace_b_mock.span.return_value = span_b_mock
    span_a_mock.span.return_value = child_a_mock

    def mock_trace_lookup(id, **kwargs):
        if id == "trace-A":
            return trace_a_mock
        return trace_b_mock

    mock_lf.trace.side_effect = mock_trace_lookup

    with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
        # 1. 두 개의 서로 다른 워크플로우 Trace 시작
        langfuse_client.start_trace(trace_id="trace-A", name="LegalConsultation")
        langfuse_client.start_trace(trace_id="trace-B", name="LegalConsultation")

        # 2. 동시 실행: Trace A에서 'supervisor_initialize' 시작
        langfuse_client.start_span(
            trace_id="trace-A",
            span_id="span-A-sup",
            name="supervisor_initialize",
        )
        assert "span-A-sup" in langfuse_client._trace_spans["trace-A"]
        assert langfuse_client._trace_spans_by_name["trace-A"]["supervisor_initialize"] == ["span-A-sup"]

        # 3. 동시 실행: Trace B에서도 동일한 노드명 'supervisor_initialize' 시작
        langfuse_client.start_span(
            trace_id="trace-B",
            span_id="span-B-sup",
            name="supervisor_initialize",
        )
        assert "span-B-sup" in langfuse_client._trace_spans["trace-B"]
        assert langfuse_client._trace_spans_by_name["trace-B"]["supervisor_initialize"] == ["span-B-sup"]

        # 4. Trace A의 내부 작업: parent_span_id로 노드명 'supervisor_initialize'를 지정하여 하위 Span 생성
        langfuse_client.start_span(
            trace_id="trace-A",
            span_id="span-A-child",
            name="extract_facts",
            parent_span_id="supervisor_initialize",
        )

        # [검증] Trace A의 하위 Span은 반드시 Trace A의 'span-A-sup'에 연결되어야 하며,
        # Trace B의 'span-B-sup'에 오염 연결되어서는 안 된다.
        span_a_mock.span.assert_called_once()
        _, child_kwargs = span_a_mock.span.call_args
        assert child_kwargs.get("id") == "span-A-child"
        assert child_kwargs.get("name") == "extract_facts"

        # Trace B의 span_b_mock.span()은 전혀 호출되지 않았어야 함
        span_b_mock.span.assert_not_called()


def test_tc03_nested_span_stack_and_cleanup():
    """TC-03: 단일 워크플로우 내 중첩·반복 에이전트 실행 시 Span 이름 스택(Stack) 동작 및 부모 복원 검증."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    parent_span_mock = MagicMock()
    nested_span_mock = MagicMock()

    mock_trace.span.return_value = parent_span_mock
    parent_span_mock.span.return_value = nested_span_mock

    with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
        trace_id = "trace-nested-uuid"
        langfuse_client.start_trace(trace_id=trace_id, name="LegalConsultation")

        # 1. 1차 'agent_loop' Span 시작
        langfuse_client.start_span(trace_id=trace_id, span_id="agent-loop-1", name="agent_loop")
        assert langfuse_client._trace_spans_by_name[trace_id]["agent_loop"] == ["agent-loop-1"]

        # 2. 중첩된 2차 'agent_loop' Span 시작
        langfuse_client.start_span(
            trace_id=trace_id,
            span_id="agent-loop-2",
            name="agent_loop",
            parent_span_id="agent_loop",
        )
        assert langfuse_client._trace_spans_by_name[trace_id]["agent_loop"] == ["agent-loop-1", "agent-loop-2"]

        # 3. 2차 Span 종료 -> 스택에서 pop되어 직전 1차 Span으로 복원되어야 함
        langfuse_client.end_span("agent-loop-2")
        assert langfuse_client._trace_spans_by_name[trace_id]["agent_loop"] == ["agent-loop-1"]
        assert "agent-loop-2" not in langfuse_client._active_spans

        # 4. 1차 Span 종료 -> 스택이 완전히 비워짐
        langfuse_client.end_span("agent-loop-1")
        assert "agent_loop" not in langfuse_client._trace_spans_by_name[trace_id]
        assert "agent-loop-1" not in langfuse_client._active_spans


def test_tc04_git_commit_and_system_metadata_injection():
    """TC-04: Git Commit SHA 및 시스템 메타데이터('LegalAgent')의 자동 주입 검증."""
    git_sha = langfuse_client.get_git_commit()
    # 실제 git 저장소 환경에서는 유효한 7자리 이상의 sha 문자열이 반환되어야 함
    assert git_sha is not None
    assert len(git_sha) >= 7

    sys_name = langfuse_client.get_system_name()
    assert sys_name == "LegalAgent"

    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_lf.trace.return_value = mock_trace

    with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
        langfuse_client.start_trace(
            trace_id="trace-tc04",
            name="LegalConsultation",
            metadata={"custom_key": "custom_val"}
        )

        _, trace_kwargs = mock_lf.trace.call_args
        meta = trace_kwargs.get("metadata", {})
        assert meta.get("git_commit") == git_sha
        assert meta.get("system_name") == "LegalAgent"
        assert meta.get("custom_key") == "custom_val"
        assert "LegalAgent" in trace_kwargs.get("tags", [])


def test_tc05_end_trace_memory_cleanup():
    """TC-05: end_trace() 호출 시 trace_id 격리 인덱스 및 활성 Span 완전 해제 검증."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_lf.trace.return_value = mock_trace

    with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
        trace_id = "trace-tc05"
        langfuse_client.start_trace(trace_id=trace_id, name="LegalConsultation")

        # 여러 개의 Span 추가
        langfuse_client.start_span(trace_id=trace_id, span_id="s1", name="node1")
        langfuse_client.start_span(trace_id=trace_id, span_id="s2", name="node2")

        # 활성 상태 확인
        assert trace_id in langfuse_client._active_traces
        assert trace_id in langfuse_client._trace_spans
        assert "s1" in langfuse_client._active_spans
        assert "s2" in langfuse_client._active_spans
        assert langfuse_client._span_to_trace.get("s1") == trace_id

        # end_trace 실행
        langfuse_client.end_trace(trace_id)

        # [검증] 해당 trace_id 및 하위 span에 대한 모든 메모리 인덱스가 정리되어야 함
        assert trace_id not in langfuse_client._active_traces
        assert trace_id not in langfuse_client._trace_spans
        assert trace_id not in langfuse_client._trace_spans_by_name
        assert "s1" not in langfuse_client._active_spans
        assert "s2" not in langfuse_client._active_spans
        assert "s1" not in langfuse_client._span_to_trace
        assert "s2" not in langfuse_client._span_to_trace

