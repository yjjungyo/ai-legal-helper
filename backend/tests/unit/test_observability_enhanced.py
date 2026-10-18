# -*- coding: utf-8 -*-
"""
모듈명: test_observability_enhanced.py

[모듈 개요]
AI Legal Helper의 고도화된 관측성(Observability) 파이프라인을 검증하는 종합 단위 테스트이다.

[검증 항목]
1. 계층적 Span 트리 구성 (UUID 부모 매핑 및 노드명/함수명 매핑)
2. 지연 Trace 자동 생성 (Lazy Trace Creation)
3. 정량 평가 점수 기록 (log_score)
4. Span 메타데이터 갱신 (UUID 및 Name 매핑 지원)
5. GraphRAG 및 증거 파이프라인의 Span 계측 정상 작동
6. 개인정보 및 민감 데이터 마스킹 정책 (LANGFUSE_CAPTURE_CONTENT)
"""
import os
import uuid
import pytest
from unittest.mock import MagicMock, patch

from ai_legal_helper.observability.context import (
    set_trace_id, get_trace_id, reset_trace_id,
    set_current_span_id, get_current_span_id, reset_current_span_id,
    set_node_name, reset_node_name
)
from ai_legal_helper.observability.langfuse_client import (
    start_trace, end_trace, start_span, end_span, update_span,
    log_generation, log_score, get_system_name, get_langfuse_callback_handler,
    _active_traces, _active_spans, _active_spans_by_name, _span_names
)
from ai_legal_helper.observability.decorators import trace


@pytest.fixture(autouse=True)
def clean_observability_state():
    """각 테스트 전후에 활성 추적 상태와 컨텍스트를 초기화한다."""
    _active_traces.clear()
    _active_spans.clear()
    _active_spans_by_name.clear()
    _span_names.clear()
    yield
    _active_traces.clear()
    _active_spans.clear()
    _active_spans_by_name.clear()
    _span_names.clear()


def test_hierarchical_span_tree_with_nested_trace_decorator():
    """중첩된 @trace 함수 호출 시 상위 Span UUID를 부모로 참조하여 올바른 트리 계층을 구성하는지 검증한다."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_parent_span = MagicMock()
    mock_child_span = MagicMock()

    mock_lf.trace.return_value = mock_trace
    mock_trace.span.return_value = mock_parent_span
    mock_parent_span.span.return_value = mock_child_span

    with patch("ai_legal_helper.observability.langfuse_client.get_langfuse", return_value=mock_lf):
        @trace
        def child_func():
            return "child_done"

        @trace
        def parent_func():
            return child_func()

        result = parent_func()
        assert result == "child_done"

        # 부모 Span은 Trace로부터 생성되고, 자식 Span은 부모 Span으로부터 생성되어야 함
        assert mock_trace.span.called
        assert mock_parent_span.span.called


def test_name_based_parent_span_resolution():
    """parent_span_id로 노드명 문자열이 전달되었을 때 활성 인덱스를 통해 부모 Span을 정확히 찾아내는지 검증한다."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_node_span = MagicMock()
    mock_agent_span = MagicMock()

    mock_lf.trace.return_value = mock_trace
    mock_trace.span.return_value = mock_node_span
    mock_node_span.span.return_value = mock_agent_span

    with patch("ai_legal_helper.observability.langfuse_client.get_langfuse", return_value=mock_lf):
        trace_id = str(uuid.uuid4())
        start_trace(trace_id=trace_id, name="Root_Workflow")

        node_span_id = str(uuid.uuid4())
        start_span(trace_id=trace_id, span_id=node_span_id, name="run_agents")

        # UUID가 아닌 'run_agents'라는 이름으로 부모를 지정
        agent_span_id = str(uuid.uuid4())
        start_span(trace_id=trace_id, span_id=agent_span_id, name="legal_specialist", parent_span_id="run_agents")

        # run_agents 스팬(mock_node_span) 아래에 자식 스팬이 생성되었는지 확인
        assert mock_node_span.span.called
        assert mock_node_span.span.call_args[1]["name"] == "legal_specialist"

        end_span(agent_span_id)
        end_span(node_span_id)
        end_trace(trace_id)


def test_lazy_trace_creation_in_start_span_and_log_generation():
    """상위 Trace가 명시적으로 생성되지 않은 상태에서 start_span이나 log_generation 호출 시 자동 생성되는지 검증한다."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_lf.trace.return_value = mock_trace

    with patch("ai_legal_helper.observability.langfuse_client.get_langfuse", return_value=mock_lf):
        orphan_trace_id = str(uuid.uuid4())
        span_id = str(uuid.uuid4())

        # Trace 시작 없이 바로 start_span 호출
        start_span(trace_id=orphan_trace_id, span_id=span_id, name="auto_trace_test")

        # Lazy Trace가 자동 기동되어 _active_traces에 등록되었는지 확인
        assert mock_lf.trace.called
        assert orphan_trace_id in _active_traces
        assert span_id in _active_spans

        # log_generation 역시 미등록 Trace에서 자동 복구되는지 확인
        gen_trace_id = str(uuid.uuid4())
        log_generation(
            trace_id=gen_trace_id,
            parent_span_id=None,
            name="Orphan_LLM_Call",
            model="gpt-4o",
            start_time=100.0,
            end_time=101.0,
            usage={"total": 50},
        )
        assert gen_trace_id in _active_traces


def test_log_score_evaluation_recording():
    """log_score 함수를 통해 Langfuse에 인용 비율 및 검증 평가 점수가 올바르게 기록되는지 검증한다."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_lf.trace.return_value = mock_trace

    with patch("ai_legal_helper.observability.langfuse_client.get_langfuse", return_value=mock_lf):
        trace_id = str(uuid.uuid4())
        start_trace(trace_id=trace_id, name="Test_Consultation")

        # 1. 인용 존재율 기록
        log_score(trace_id=trace_id, name="citation_existence_rate", value=1.0, comment="All cited docs found")
        assert mock_trace.score.called
        assert mock_trace.score.call_args[1]["name"] == "citation_existence_rate"
        assert mock_trace.score.call_args[1]["value"] == 1.0

        # 2. 인용 지지율 기록
        log_score(trace_id=trace_id, name="citation_support_rate", value=0.85)
        assert mock_trace.score.call_args[1]["name"] == "citation_support_rate"
        assert mock_trace.score.call_args[1]["value"] == 0.85

        # 3. 종합 검증 상태 점수 기록
        log_score(trace_id=trace_id, name="verification_status", value=1.0, comment="PASS")
        assert mock_trace.score.call_args[1]["name"] == "verification_status"
        assert mock_trace.score.call_args[1]["comment"] == "PASS"


def test_update_span_by_name_and_uuid():
    """update_span이 span_id(UUID)뿐만 아니라 등록된 함수/노드명으로도 메타데이터를 정상 갱신하는지 검증한다."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_span = MagicMock()
    mock_lf.trace.return_value = mock_trace
    mock_trace.span.return_value = mock_span

    with patch("ai_legal_helper.observability.langfuse_client.get_langfuse", return_value=mock_lf):
        trace_id = str(uuid.uuid4())
        span_id = str(uuid.uuid4())
        start_trace(trace_id=trace_id, name="Metadata_Trace")
        start_span(trace_id=trace_id, span_id=span_id, name="graph_rag_hybrid_search")

        # 1. UUID로 메타데이터 갱신
        update_span(span_id, {"fallback": False, "paths_count": 5})
        assert mock_span.update.called
        assert mock_span.update.call_args[1]["metadata"]["paths_count"] == 5

        # 2. 스팬 이름으로 메타데이터 갱신
        update_span("graph_rag_hybrid_search", {"extra_info": "verified"})
        assert mock_span.update.call_args[1]["metadata"]["extra_info"] == "verified"


def test_privacy_masking_policy():
    """LANGFUSE_CAPTURE_CONTENT=false 상태에서 입력/출력이 마스킹 처리되는지 검증한다."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_span = MagicMock()
    mock_lf.trace.return_value = mock_trace
    mock_trace.span.return_value = mock_span

    with patch.dict(os.environ, {"LANGFUSE_CAPTURE_CONTENT": "false"}):
        with patch("ai_legal_helper.observability.langfuse_client.get_langfuse", return_value=mock_lf):
            trace_id = str(uuid.uuid4())
            span_id = str(uuid.uuid4())
            start_trace(trace_id=trace_id, name="Privacy_Trace")

            start_span(trace_id=trace_id, span_id=span_id, name="sensitive_node", input={"client_ssn": "900101-1234567"})
            assert mock_trace.span.call_args[1]["input"] == "[MASKED FOR PRIVACY]"

            end_span(span_id=span_id, output={"private_result": "confidential_data"})
            assert mock_span.end.call_args[1]["output"] == "[MASKED FOR PRIVACY]"


def test_unmasked_content_in_development_mode():
    """개발/테스트 검증 모드(기본값 또는 LANGFUSE_CAPTURE_CONTENT=true)에서 실제 입력·출력 원문이 보존되는지 검증한다."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_span = MagicMock()
    mock_lf.trace.return_value = mock_trace
    mock_trace.span.return_value = mock_span

    with patch.dict(os.environ, {"LANGFUSE_CAPTURE_CONTENT": "true"}):
        with patch("ai_legal_helper.observability.langfuse_client.get_langfuse", return_value=mock_lf):
            trace_id = str(uuid.uuid4())
            span_id = str(uuid.uuid4())
            start_trace(trace_id=trace_id, name="Dev_Trace")

            test_input = {"question": "임차인이 보증금을 돌려받지 못했을 때의 구제 절차는?", "case_id": "case-123"}
            start_span(trace_id=trace_id, span_id=span_id, name="consultation_node", input=test_input)
            assert mock_trace.span.call_args[1]["input"] == test_input
            assert mock_trace.span.call_args[1]["input"] != "[MASKED FOR PRIVACY]"

            test_output = {"answer": "주택임대차보호법에 따른 임차권등기명령을 신청할 수 있습니다.", "status": "SUCCESS"}
            end_span(span_id=span_id, output=test_output)
            assert mock_span.end.call_args[1]["output"] == test_output
            assert mock_span.end.call_args[1]["output"] != "[MASKED FOR PRIVACY]"


def test_system_name_tagging_and_metadata_in_traces():
    """LANGFUSE_SYSTEM_NAME이 Trace, Lazy Trace, CallbackHandler에 태그 및 메타데이터로 올바르게 주입되는지 검증한다."""
    mock_lf = MagicMock()
    mock_trace = MagicMock()
    mock_lf.trace.return_value = mock_trace

    # 1. 기본 환경(LegalAgent)에서 start_trace 호출 시 태그 및 메타데이터 주입 확인
    with patch.dict(os.environ, {"LANGFUSE_SYSTEM_NAME": "LegalAgent"}):
        with patch("ai_legal_helper.observability.langfuse_client.get_langfuse", return_value=mock_lf):
            assert get_system_name() == "LegalAgent"

            trace_id = str(uuid.uuid4())
            start_trace(
                trace_id=trace_id,
                name="SystemNameTestTrace",
                tags=["custom-tag"],
                metadata={"test_key": "val1"},
            )

            assert mock_lf.trace.called
            call_kwargs = mock_lf.trace.call_args[1]
            assert "LegalAgent" in call_kwargs["tags"]
            assert "custom-tag" in call_kwargs["tags"]
            assert call_kwargs["metadata"]["system_name"] == "LegalAgent"
            assert call_kwargs["metadata"]["test_key"] == "val1"
            end_trace(trace_id)

    # 2. 비교 대상 시스템(LegalChat, LegalRAG)으로 설정 변경 시 태그/메타데이터 동적 반영 확인
    for other_system in ["LegalChat", "LegalRAG"]:
        mock_lf.reset_mock()
        with patch.dict(os.environ, {"LANGFUSE_SYSTEM_NAME": other_system}):
            with patch("ai_legal_helper.observability.langfuse_client.get_langfuse", return_value=mock_lf):
                assert get_system_name() == other_system

                t_id = str(uuid.uuid4())
                start_trace(trace_id=t_id, name=f"{other_system}_Trace")
                c_kwargs = mock_lf.trace.call_args[1]
                assert other_system in c_kwargs["tags"]
                assert c_kwargs["metadata"]["system_name"] == other_system
                end_trace(t_id)

    # 3. 지연 Trace(Lazy Trace) 생성 시에도 시스템명 태그 및 메타데이터 주입 확인
    mock_lf.reset_mock()
    with patch.dict(os.environ, {"LANGFUSE_SYSTEM_NAME": "LegalAgent"}):
        with patch("ai_legal_helper.observability.langfuse_client.get_langfuse", return_value=mock_lf):
            lazy_id = str(uuid.uuid4())
            start_span(trace_id=lazy_id, span_id=str(uuid.uuid4()), name="LazySpan")
            lazy_kwargs = mock_lf.trace.call_args[1]
            assert "LegalAgent" in lazy_kwargs["tags"]
            assert lazy_kwargs["metadata"]["system_name"] == "LegalAgent"


def test_system_name_in_callback_handler_and_telemetry():
    """CallbackHandler 및 OpenTelemetry 초기화 시 LANGFUSE_SYSTEM_NAME이 연동되는지 검증한다."""
    from ai_legal_helper.observability.telemetry import init_telemetry

    # 1. CallbackHandler에 system_name 태그 및 메타데이터 주입 확인
    with patch.dict(os.environ, {
        "LANGFUSE_ENABLED": "true",
        "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
        "LANGFUSE_SECRET_KEY": "sk-lf-test",
        "LANGFUSE_HOST": "http://localhost:3001",
        "LANGFUSE_SYSTEM_NAME": "LegalAgent",
    }):
        with patch("ai_legal_helper.observability.langfuse_client.CallbackHandler") as mock_cb_class:
            handler = get_langfuse_callback_handler(trace_name="CB_System_Test")
            assert mock_cb_class.called
            cb_kwargs = mock_cb_class.call_args[1]
            assert "LegalAgent" in cb_kwargs["tags"]
            assert cb_kwargs["metadata"]["system_name"] == "LegalAgent"

    # 2. OpenTelemetry init_telemetry 기본 서비스명이 LANGFUSE_SYSTEM_NAME으로 설정되는지 확인
    with patch.dict(os.environ, {"LANGFUSE_SYSTEM_NAME": "LegalAgent"}):
        with patch("ai_legal_helper.observability.telemetry.Resource.create") as mock_resource:
            init_telemetry()
            assert mock_resource.called
            res_attrs = mock_resource.call_args[1]["attributes"]
            assert res_attrs["service.name"] == "LegalAgent"



