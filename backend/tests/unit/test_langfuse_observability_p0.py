"""Langfuse Observability 고도화 v2.0 (1차 정확성 확보: P0-1, P0-2, P0-3) 단위 테스트 모듈.

본 모듈은 다음 6대 핵심 요구사항을 검증한다:
- TC-01: 단일 워크플로우 실행 시 Trace 이름('LegalConsultation') 표준화 및 LLM 1회 호출당 Generation 1회 정확 기록 (P0-1, P0-3)
- TC-02: 서로 다른 상담(Trace A, Trace B) 동시 실행 시 동일 노드명 Span의 상호 오염 차단 및 격리 검증 (P0-2)
- TC-03: 동일 워크플로우 내 중첩·반복 에이전트 호출 시 Span 이름 스택(Stack) 정상 동작 및 부모 복원 (P0-2)
- TC-04: Git Commit SHA 및 시스템 식별자('LegalAgent')의 Trace/Generation 메타데이터 자동 주입 검증 (P0-3)
- TC-05: 워크플로우 종료 시 end_trace()에 의한 내부 활성 Span 및 Trace 인덱스 메모리 누수 방지 정리 (P0-2)
- TC-06: Azure OpenAI 응답 모델명(예: 'gpt-5.4-2026-03-05') 정밀 추출을 통한 Langfuse 모델 식별 및 비용(Cost) 산출 보장 (P0-1)
"""

import os
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
    langfuse_client._ended_traces.clear()
    yield
    langfuse_client._active_traces.clear()
    langfuse_client._active_spans.clear()
    langfuse_client._span_names.clear()
    langfuse_client._trace_spans.clear()
    langfuse_client._trace_spans_by_name.clear()
    langfuse_client._span_to_trace.clear()
    langfuse_client._ended_traces.clear()


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
                },
                "model_name": "gpt-4o",
            }

            handler.on_llm_end(mock_llm_res, run_id=run_id, invocation_params={"model_name": "gpt-4o"})

            # Generation이 Trace에 정확히 1회 기록되었는지 검증
            mock_trace.generation.assert_called_once()
            _, gen_kwargs = mock_trace.generation.call_args
            assert gen_kwargs.get("name") == "LegalAgent"
            assert gen_kwargs.get("model") == "gpt-4o"
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


def test_tc06_model_name_extraction_for_cost_calculation():
    """TC-06: Azure OpenAI 응답 모델명(예: 'gpt-5.4-2026-03-05') 추출 및 Langfuse Cost 계산 연계 검증.
    
    AzureChatOpenAI 호출 시 invocation_params에는 model_name이 없고 azure_deployment만 존재하며,
    실제 세부 모델 버전(예: 'gpt-5.4-2026-03-05')은 response.llm_output['model_name']에 담겨 전달된다.
    이를 정확히 추출하여 Langfuse Generation의 model 필드에 기록함으로써 비용(Cost)이 산출되도록 보장한다.
    """
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_lf.trace.return_value = mock_trace

    with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
        trace_id = "trace-tc06"
        langfuse_client.start_trace(trace_id=trace_id, name="LegalConsultation")

        t_token = set_trace_id(trace_id)
        try:
            handler = TokenTrackingCallbackHandler()
            run_id = "run-tc06-azure"

            # 1. on_chat_model_start: Azure deployment 정보 수신
            handler.on_chat_model_start(
                serialized={"kwargs": {"azure_deployment": "gpt-5.4"}},
                messages=[[MagicMock(type="human", content="사건 질의")]],
                run_id=run_id,
                invocation_params={"azure_deployment": "gpt-5.4", "temperature": 0.2},
            )

            # 2. on_llm_end: Azure OpenAI 실제 응답에 정밀 모델명('gpt-5.4-2026-03-05') 수신
            mock_llm_res = MagicMock()
            mock_gen_obj = MagicMock()
            mock_gen_obj.text = "답변 텍스트"
            mock_gen_obj.message = None
            mock_llm_res.generations = [[mock_gen_obj]]
            mock_llm_res.llm_output = {
                "token_usage": {
                    "prompt_tokens": 15950,
                    "completion_tokens": 4966,
                    "total_tokens": 20916,
                },
                "model_name": "gpt-5.4-2026-03-05",
            }

            handler.on_llm_end(
                mock_llm_res,
                run_id=run_id,
                invocation_params={"azure_deployment": "gpt-5.4", "temperature": 0.2},
            )

            # 3. [검증] Langfuse Generation에 정밀 모델명 및 토큰 상세가 정확히 전달되었는지 확인
            mock_trace.generation.assert_called_once()
            _, gen_kwargs = mock_trace.generation.call_args
            assert gen_kwargs.get("name") == "LegalAgent"
            assert gen_kwargs.get("model") == "gpt-5.4-2026-03-05"  # 반드시 unknown이 아닌 실제 모델명이어야 함!
            assert gen_kwargs.get("usage", {}).get("input") == 15950
            assert gen_kwargs.get("usage", {}).get("output") == 4966
            assert gen_kwargs.get("usage", {}).get("total") == 20916
            assert gen_kwargs.get("usage_details", {}).get("input") == 15950
            assert gen_kwargs.get("model_parameters", {}).get("temperature") == 0.2
        finally:
            reset_trace_id(t_token)


def test_tc07_cross_trace_name_lookup_rejected():
    """TC-P0-07: Trace A에만 존재하는 부모 이름을 Trace B에서 요청했을 때 교차 연결되지 않는지 검증.
    
    Trace A에 'agent_alpha'가 존재하더라도, Trace B에서 parent_span_id='agent_alpha'로 스팬을 시작하면
    Trace A의 스팬에 절대로 연결되지 않고 Trace B의 Root Trace에 연결되어야 한다.
    """
    mock_lf = MagicMock()
    trace_a_mock = MagicMock()
    trace_b_mock = MagicMock()
    span_a_alpha = MagicMock()
    child_b_mock = MagicMock()

    trace_a_mock.span.return_value = span_a_alpha
    trace_b_mock.span.return_value = child_b_mock

    def mock_trace_lookup(id, **kwargs):
        return trace_a_mock if id == "trace-A" else trace_b_mock

    mock_lf.trace.side_effect = mock_trace_lookup

    with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
        langfuse_client.start_trace(trace_id="trace-A", name="LegalConsultation")
        langfuse_client.start_trace(trace_id="trace-B", name="LegalConsultation")

        # Trace A에서만 'agent_alpha' 생성
        langfuse_client.start_span(trace_id="trace-A", span_id="span-A-alpha", name="agent_alpha")
        assert "span-A-alpha" in langfuse_client._trace_spans["trace-A"]

        # Trace B에서 존재하지 않는 부모명 'agent_alpha'로 스팬 생성 시도
        langfuse_client.start_span(
            trace_id="trace-B",
            span_id="span-B-child",
            name="tool_call",
            parent_span_id="agent_alpha",
        )

        # [검증] Trace A의 span_a_alpha.span()은 호출되지 않아야 함 (교차 연결 차단)
        span_a_alpha.span.assert_not_called()

        # [검증] Trace B의 루트 트레이스에 직접 연결되어야 함
        trace_b_mock.span.assert_called_once()
        _, b_kwargs = trace_b_mock.span.call_args
        assert b_kwargs.get("id") == "span-B-child"


def test_tc08_concurrent_same_name_nested_agents():
    """TC-P0-08: 서로 다른 Trace에서 동일 이름의 Agent가 동시에 중첩 실행되는 경우 확인.
    
    Trace A와 Trace B가 동시에 동일한 'lease_agent'를 실행하고,
    Trace A에서만 중첩 호출이 발생하더라도 두 Trace의 이름 스택이 완전히 독립적으로 동작해야 한다.
    """
    mock_lf = MagicMock()
    trace_a_mock = MagicMock()
    trace_b_mock = MagicMock()
    span_a_1 = MagicMock()
    span_a_2 = MagicMock()
    span_b_1 = MagicMock()

    trace_a_mock.span.side_effect = [span_a_1, MagicMock()]
    span_a_1.span.return_value = span_a_2
    trace_b_mock.span.return_value = span_b_1

    def mock_trace_lookup(id, **kwargs):
        return trace_a_mock if id == "trace-A" else trace_b_mock

    mock_lf.trace.side_effect = mock_trace_lookup

    with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
        langfuse_client.start_trace(trace_id="trace-A", name="LegalConsultation")
        langfuse_client.start_trace(trace_id="trace-B", name="LegalConsultation")

        # 1. Trace A와 Trace B에서 각각 'lease_agent' 시작
        langfuse_client.start_span(trace_id="trace-A", span_id="a-lease-1", name="lease_agent")
        langfuse_client.start_span(trace_id="trace-B", span_id="b-lease-1", name="lease_agent")

        # 2. Trace A에서만 중첩 'lease_agent' 시작
        langfuse_client.start_span(
            trace_id="trace-A",
            span_id="a-lease-2",
            name="lease_agent",
            parent_span_id="lease_agent",
        )
        assert langfuse_client._trace_spans_by_name["trace-A"]["lease_agent"] == ["a-lease-1", "a-lease-2"]
        assert langfuse_client._trace_spans_by_name["trace-B"]["lease_agent"] == ["b-lease-1"]

        # 3. Trace A의 중첩 스팬 종료 -> Trace A 스택은 a-lease-1로 복원, Trace B는 불변
        langfuse_client.end_span("a-lease-2")
        assert langfuse_client._trace_spans_by_name["trace-A"]["lease_agent"] == ["a-lease-1"]
        assert langfuse_client._trace_spans_by_name["trace-B"]["lease_agent"] == ["b-lease-1"]


def test_tc09_cross_trace_uuid_parent_rejected():
    """TC-P0-09: 다른 Trace의 UUID를 부모로 전달했을 때 연결이 거부되는지 확인.
    
    Trace A 소속인 Span UUID를 Trace B의 start_span(parent_span_id=...)으로 전달하면
    교차 연결이 거부([SPAN_CROSS_TRACE_REJECTED])되고 Trace B의 Root Trace에 연결되어야 한다.
    """
    mock_lf = MagicMock()
    trace_a_mock = MagicMock()
    trace_b_mock = MagicMock()
    span_a_uuid = MagicMock()
    child_b = MagicMock()

    trace_a_mock.span.return_value = span_a_uuid
    trace_b_mock.span.return_value = child_b

    def mock_trace_lookup(id, **kwargs):
        return trace_a_mock if id == "trace-A" else trace_b_mock

    mock_lf.trace.side_effect = mock_trace_lookup

    with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
        langfuse_client.start_trace(trace_id="trace-A", name="LegalConsultation")
        langfuse_client.start_trace(trace_id="trace-B", name="LegalConsultation")

        # Trace A에서 스팬 생성 (UUID: 'span-A-secret-uuid')
        langfuse_client.start_span(trace_id="trace-A", span_id="span-A-secret-uuid", name="node_a")

        # Trace B에서 부모로 Trace A의 UUID를 직접 지정
        langfuse_client.start_span(
            trace_id="trace-B",
            span_id="span-B-rogue-child",
            name="node_b",
            parent_span_id="span-A-secret-uuid",
        )

        # [검증] Trace A의 span_a_uuid.span()은 절대로 호출되어서는 안 됨
        span_a_uuid.span.assert_not_called()

        # [검증] Trace B의 루트 트레이스에 직접 격리 연결되어야 함
        trace_b_mock.span.assert_called_once()
        _, b_kwargs = trace_b_mock.span.call_args
        assert b_kwargs.get("id") == "span-B-rogue-child"


def test_tc10_delayed_callback_after_end_trace():
    """TC-P0-10: 비동기 상담 종료 이후 지연된 Callback이 도착했을 때 새 Trace가 임의 생성되거나 잘못 연결되지 않는지 검증.
    
    end_trace(trace_id) 호출 이후 해당 trace_id로 start_span()이나 log_generation()이 도착하더라도,
    Langfuse에 새로운 임의 Trace(예: 'Workflow:...' 또는 'LLM_Trace')가 생성되지 않고 안전하게 무시되어야 한다.
    """
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_lf.trace.return_value = mock_trace

    with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
        trace_id = "trace-tc10-ended"
        langfuse_client.start_trace(trace_id=trace_id, name="LegalConsultation")
        assert mock_lf.trace.call_count == 1

        # 상담 정상 종료
        langfuse_client.end_trace(trace_id)
        assert trace_id in langfuse_client._ended_traces
        assert trace_id not in langfuse_client._active_traces

        # 지연된 span 시작 시도
        langfuse_client.start_span(
            trace_id=trace_id,
            span_id="delayed-span-id",
            name="delayed_tool_execution",
        )

        # 지연된 generation 기록 시도
        langfuse_client.log_generation(
            trace_id=trace_id,
            parent_span_id=None,
            name="LegalAgent",
            model="gpt-5.4",
            start_time=time.time(),
            end_time=time.time(),
            usage={"input": 10, "output": 10, "total": 20},
        )

        # [검증] 추가적인 lf.trace() 호출이 전혀 발생하지 않았어야 함 (호출 횟수 그대로 1회 유지)
        assert mock_lf.trace.call_count == 1
        assert "delayed-span-id" not in langfuse_client._active_spans


def test_tc11_privacy_masking_default_when_env_unset():
    """TC-11: LANGFUSE_CAPTURE_CONTENT 환경변수 미설정 시 기본 마스킹 동작 검증 (개인정보 보호 원칙).
    
    환경변수가 전혀 설정되지 않은 기본 상태에서는 법률 상담 질문 및 답변 원문이
    Langfuse에 평문으로 전송되지 않고 '[MASKED FOR PRIVACY]'로 마스킹되어야 한다.
    """
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_lf.trace.return_value = mock_trace

    # LANGFUSE_CAPTURE_CONTENT 환경변수를 완전히 제거한 환경 시뮬레이션
    env_clean = dict(os.environ)
    env_clean.pop("LANGFUSE_CAPTURE_CONTENT", None)

    with patch.dict(os.environ, env_clean, clear=True):
        with patch.object(langfuse_client, "get_langfuse", return_value=mock_lf):
            trace_id = "trace-tc11-privacy"
            langfuse_client.start_trace(trace_id=trace_id, name="LegalConsultation")

            langfuse_client.start_span(
                trace_id=trace_id,
                span_id="span-tc11",
                name="user_query_node",
                input={"client_ssn": "900101-1234567", "deposit": 50000000},
            )

            # [검증] 환경변수 미설정 시 기본값은 마스킹이어야 함
            _, span_kwargs = mock_trace.span.call_args
            assert span_kwargs.get("input") == "[MASKED FOR PRIVACY]"
