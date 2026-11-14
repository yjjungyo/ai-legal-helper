# -*- coding: utf-8 -*-
"""
테스트 모듈명: test_multi_turn_followup_resolution.py

[테스트 목적]
E2E 3턴 연속 상담 평가에서 발견된 멀티턴 문맥 절삭 및 단문 후속 질의("그래 해줘", "그래 정리해줘")
의도 판정 실패, 질의 복원 부재, 무한 제안 루프를 방지하는 최소 수정 로직을 엄격히 검증한다.

[주요 검증 항목]
1. `_is_short_followup_request`: 첫 턴 단문과 연속 대화 단문 수락을 정확히 구분하는지 검증
2. `_resolve_multi_turn_task`: 직전 AI 답변의 제안 문구와 원래 1턴 루트 질문의 기준일을 올바르게 복원하는지 검증
3. 다중 턴 추적: 3턴 연속 단문 질의 시 1턴 루트 질문 및 직전 작업 명칭을 역추적하여 재정리 질의를 구성하는지 검증
4. `supervisor_initialize_node`: 단문 후속 질의에서 intent=FOLLOWUP_ACTION 및 resolved_query, event_date 보존 검증
5. `synthesizer._format_last_answer_context`: 직전 답변 말미의 제안 문장이 프롬프트에서 절삭되지 않고 보존되는지 검증
6. `synthesizer`: 후속 질의 작성 시 말미의 반복적 제안 문구("원하시면 ~정리해드리겠습니다") 후처리 제거 검증
"""

import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage

from ai_legal_helper.workflows.legal_workflow import (
    _is_short_followup_request,
    _extract_proposal_from_answer,
    _resolve_multi_turn_task,
    supervisor_initialize_node,
)
from ai_legal_helper.agents.synthesizer import (
    _format_last_answer_context,
    synthesize,
)
from ai_legal_helper.agents.intent_analyzer import ConsultationIntent


@pytest.fixture
def turn1_context():
    """Turn 1 완료 후 구축된 대화 맥락 픽스처."""
    q1 = (
        "저는 등록 민간임대주택의 임대사업자입니다. 2026년 11월 1일에 새로운 임대차계약을 체결했습니다. "
        "임대차계약 신고 시 관리비와 전기·수도료 등 임차인 부담 비용의 금액이나 산정방식까지 신고해야 하나요?"
    )
    a1 = (
        "아니요. 2026.11.1 체결한 계약에 대해서는, 현재 확인된 자료 기준으로 관리비·전기·수도료 등 "
        "임차인 부담 비용의 금액 또는 산정방식까지 임대차계약 신고대상이라고 보기는 어렵습니다.\n\n"
        "• 법률상 신고의무의 기본 근거는 「민간임대주택에 관한 특별법」 제46조이고, 구체적 신고사항은 시행령 제36조가 정합니다.\n"
        "• 시행령 부칙은 제36조제1항 제2호의2 및 제2호의3 개정규정이 공포 후 6개월이 경과한 날(2027.4.28경)부터 시행하고, "
        "이 영 시행 이후 임대차계약을 체결하거나 갱신하는 경우부터 적용한다고 정합니다.\n\n"
        "원하시면 제가 이어서 “2026.11.1 계약 기준 실제 신고항목 체크리스트”로 1분 요약해드리겠습니다."
    )
    return {
        "conversation_id": "conv-test-1234",
        "turn_index": 1,
        "previous_turns": [
            {
                "turn_index": 1,
                "request_id": "req-1",
                "question": q1,
                "answer": a1,
                "answer_status": "DELIVERED",
                "cited_sources": [{"source_id": "law-1", "source_type": "STATUTE", "content": "시행령 제36조"}],
            }
        ],
        "last_answer": a1,
        "last_answer_status": "DELIVERED",
        "previously_cited_sources": [{"source_id": "law-1", "source_type": "STATUTE", "content": "시행령 제36조"}],
    }


@pytest.fixture
def turn2_context(turn1_context):
    """Turn 2 완료 후 구축된 대화 맥락 픽스처 (Turn 1 + Turn 2 누적)."""
    q2 = "그래 해줘"
    a2 = (
        "네, 2026. 11. 1. 체결한 등록 민간임대주택 임대차계약의 신고 준비를 위해 체크리스트 형태로 정리해 드립니다.\n\n"
        "1. 필수 신고 사항: 임대차기간, 임대료\n"
        "2. 보충 사항: 관리비·사용료 산정방식은 2027.4.28 이후 계약부터 적용 예정이므로 현재 신고 비대상입니다.\n\n"
        "원하시면 제가 바로 이어서 “임대사업자용 임대차계약 신고 체크리스트” 형태로, 무엇을 신고하고 무엇은 보충기재 사항인지 한눈에 정리해드리겠습니다."
    )
    ctx = dict(turn1_context)
    ctx["turn_index"] = 2
    ctx["previous_turns"] = list(turn1_context["previous_turns"]) + [
        {
            "turn_index": 2,
            "request_id": "req-2",
            "question": q2,
            "answer": a2,
            "answer_status": "DELIVERED",
            "cited_sources": [{"source_id": "law-1", "source_type": "STATUTE", "content": "시행령 제36조"}],
        }
    ]
    ctx["last_answer"] = a2
    return ctx


# ---------------------------------------------------------------------------
# 1. 단문 후속 질의 감지 및 제안 문구 추출 단위 테스트
# ---------------------------------------------------------------------------

def test_is_short_followup_request_positive(turn1_context):
    """이전 대화가 존재하고 사용자가 단문 동의/수락/정리 발언을 할 때 정확히 감지한다."""
    assert _is_short_followup_request("그래 해줘", turn1_context) is True
    assert _is_short_followup_request("응 해줘", turn1_context) is True
    assert _is_short_followup_request("네 해주세요", turn1_context) is True
    assert _is_short_followup_request("그래 정리해줘", turn1_context) is True
    assert _is_short_followup_request("체크리스트 정리해줘", turn1_context) is True
    assert _is_short_followup_request("체크리스트 줘", turn1_context) is True
    assert _is_short_followup_request("그렇게 진행해줘", turn1_context) is True


def test_is_short_followup_request_negative_cases(turn1_context):
    """첫 질문이거나 새로운 독립 질문, 인사말, 사실 정정 발언은 후속 단문으로 오판하지 않는다."""
    # 1. 이전 대화 맥락이 없는 경우 (첫 턴 단문 질문 보호)
    assert _is_short_followup_request("그래 해줘", None) is False
    assert _is_short_followup_request("보증금 반환 언제까지?", None) is False
    assert _is_short_followup_request("안녕하세요", None) is False

    # 2. 이전 대화가 있더라도 단순 인사말인 경우
    assert _is_short_followup_request("감사합니다 수고하세요", turn1_context) is False
    assert _is_short_followup_request("고마워", turn1_context) is False

    # 3. 새로운 독립적 법률 질문이 입력된 경우
    assert _is_short_followup_request("그런데 임대인이 파산하면 어떻게 되나요?", turn1_context) is False
    assert _is_short_followup_request("소송 비용은 얼마 정도 드나요?", turn1_context) is False


def test_extract_proposal_from_answer():
    """답변 원문의 말미에서 따옴표 제안 문구 및 체크리스트 키워드를 정확히 추출한다."""
    ans1 = "요약 결론입니다.\n\n원하시면 제가 이어서 “2026.11.1 계약 기준 실제 신고항목 체크리스트”로 1분 요약해드리겠습니다."
    assert _extract_proposal_from_answer(ans1) == "2026.11.1 계약 기준 실제 신고항목 체크리스트"

    ans2 = "원하시면 '임대사업자용 임대차계약 신고 체크리스트' 형태로 한눈에 정리해드리겠습니다."
    assert _extract_proposal_from_answer(ans2) == "임대사업자용 임대차계약 신고 체크리스트"

    ans3 = "추가 안내입니다.\n\n필요하시면 임대차계약 신고 준비를 위한 체크리스트 형태로 정리해 드릴 수 있습니다."
    extracted3 = _extract_proposal_from_answer(ans3)
    assert extracted3 is not None
    assert "체크리스트" in extracted3


# ---------------------------------------------------------------------------
# 2. 다중 턴 작업 복원 및 기준일 계승 테스트
# ---------------------------------------------------------------------------

def test_resolve_multi_turn_task_turn2(turn1_context):
    """Turn 2: '그래 해줘' 입력 시 Turn 1 제안과 기준일을 결합하여 구체적 작업으로 복원한다."""
    resolved_q, event_date = _resolve_multi_turn_task("그래 해줘", turn1_context)
    assert "체크리스트" in resolved_q
    assert "작성" in resolved_q
    assert event_date == "2026-11-01"


def test_resolve_multi_turn_task_turn3(turn2_context):
    """Turn 3: '그래 정리해줘' 입력 시 다중 턴을 역추적하여 직전 작성물을 간결하게 재정리하는 질의로 복원한다."""
    resolved_q, event_date = _resolve_multi_turn_task("그래 정리해줘", turn2_context)
    assert "재정리" in resolved_q or "정리" in resolved_q
    assert "체크리스트" in resolved_q
    assert event_date == "2026-11-01"


# ---------------------------------------------------------------------------
# 3. supervisor_initialize_node 통합 동작 테스트
# ---------------------------------------------------------------------------

def test_supervisor_initialize_node_restores_followup_query(turn1_context):
    """supervisor_initialize_node가 단문 '그래 해줘'를 FOLLOWUP_ACTION 및 복원 질의로 설정한다."""
    state = {
        "question": "그래 해줘",
        "conversation_context": turn1_context,
        "conversation_id": "conv-test-1234",
        "turn_index": 2,
    }

    out = supervisor_initialize_node(state)

    assert out["intent"] == ConsultationIntent.FOLLOWUP_ACTION.value
    assert "체크리스트" in out["resolved_query"]
    assert out["event_date"] == "2026-11-01"
    assert out["intent_decision"]["resolved_query"] == out["resolved_query"]
    assert out["intent_decision"]["event_date"] == "2026-11-01"


def test_supervisor_initialize_node_first_turn_short_not_followup():
    """첫 턴에 단문이 들어왔을 때 후속 질의로 오분류되지 않고 정상 신규 질문으로 처리된다."""
    state = {
        "question": "보증금 반환 방법",
        "conversation_context": None,
        "conversation_id": "conv-new-1",
        "turn_index": 1,
    }

    out = supervisor_initialize_node(state)

    assert out["intent"] == ConsultationIntent.NEW_LEGAL_ANALYSIS.value
    assert out["resolved_query"] == "보증금 반환 방법"


# ---------------------------------------------------------------------------
# 4. Synthesizer 맥락 보존 및 무한 제안 루프 차단 테스트
# ---------------------------------------------------------------------------

def test_format_last_answer_context_preserves_head_and_tail():
    """직전 답변이 1,500자를 초과하더라도 앞부분 결론과 뒷부분 제안 문장을 모두 보존한다."""
    long_answer = (
        "결론: 관리비·사용료는 신고 대상이 아닙니다.\n\n"
        + ("세부 법률 분석 내용입니다. " * 80)
        + "\n\n원하시면 제가 이어서 “2026.11.1 계약 기준 실제 신고항목 체크리스트”로 1분 요약해드리겠습니다."
    )
    assert len(long_answer) > 1000

    ctx_text = _format_last_answer_context(long_answer, max_chars=700)

    assert "결론: 관리비·사용료는 신고 대상이 아닙니다." in ctx_text
    assert "원하시면 제가 이어서 “2026.11.1 계약 기준 실제 신고항목 체크리스트”" in ctx_text
    assert "[...(중간 법률 세부 분석 생략)...]" in ctx_text


@patch("ai_legal_helper.agents.synthesizer.get_llm")
def test_synthesizer_strips_infinite_offer_loop(mock_get_llm):
    """후속 조치(FOLLOWUP_ACTION) 모드에서 생성된 답변 말미의 반복 제안 문구를 제거한다."""
    llm_mock = MagicMock()
    # LLM이 본문 작성 후 또다시 관성적으로 동일 제안을 덧붙인 상황 시뮬레이션
    llm_mock.invoke.return_value = AIMessage(
        content=(
            "### 2026.11.1 계약 기준 임대차계약 신고 체크리스트\n\n"
            "| 항목 | 신고 여부 | 근거 조문 |\n"
            "| --- | --- | --- |\n"
            "| 임대료 | 필수 | 시행령 제36조제1항제2호 |\n"
            "| 관리비·사용료 | 제외 | 시행령 부칙 유예 규정 |\n\n"
            "원하시면 '구청 제출용으로 완전한 신고 체크리스트' 형태로 바로 정리해 드리겠습니다."
        )
    )
    mock_get_llm.return_value = llm_mock

    messages = [HumanMessage(content="그래 해줘")]
    results = {"부동산": "체크리스트 초안"}

    out_messages = synthesize(
        messages,
        results,
        intent="FOLLOWUP_ACTION",
        resolved_query="2026.11.1 계약 기준 실제 신고항목 체크리스트 작성",
        user_question="그래 해줘",
        last_answer="원하시면 체크리스트로 요약해드리겠습니다.",
    )

    final_content = out_messages[-1].content
    # 본문 체크리스트 표는 보존되고, 말미의 반복 제안 꼬리표는 제거되어야 함
    assert "2026.11.1" in final_content and "체크리스트" in final_content
    assert "| 임대료 | 필수 |" in final_content
    assert "원하시면 '구청 제출용으로 완전한 신고 체크리스트' 형태로 바로 정리해 드리겠습니다." not in final_content


# ---------------------------------------------------------------------------
# 5. re_analyze_node & revise_node 후속 질의 맥락 계승 및 포맷 보존 테스트
# ---------------------------------------------------------------------------

@patch("ai_legal_helper.llm.gateway.get_llm")
def test_re_analyze_node_followup_preserves_resolved_query_and_strips_offer(mock_get_llm):
    """re_analyze_node가 단문 '그래 해줘' 대신 resolved_query를 작업 질의로 채택하고 꼬리표 제안을 제거한다."""
    from ai_legal_helper.workflows.legal_workflow import re_analyze_node

    llm_mock = MagicMock()
    llm_mock.invoke.return_value = AIMessage(
        content=(
            "| 항목 | 신고 여부 | 비고 |\n"
            "| --- | --- | --- |\n"
            "| 임대료 | 신고 대상 | 시행령 제36조 |\n\n"
            "원하시면 이 내용을 바로 행정청 제출용 1페이지 의견서 형식으로 바꿔드리겠습니다."
        )
    )
    mock_get_llm.return_value = llm_mock

    state = {
        "question": "그래 해줘",
        "resolved_query": "2026.11.1 계약 기준 실제 신고 체크리스트 작성",
        "intent": "FOLLOWUP_ACTION",
        "turn_index": 2,
        "categories": ["부동산"],
        "case_context": "(사건 맥락 없음)",
        "statute_search_results": [{"statute_name": "민간임대주택법", "article": "제46조", "content": "신고의무"}],
        "conversation_context": {
            "last_answer": "원하시면 2026.11.1 계약 기준 실제 신고 체크리스트를 바로 정리해드리겠습니다."
        },
    }

    result = re_analyze_node(state)
    draft = result["draft_answer"]

    # 1. LLM 호출 시 프롬프트에 복원 질의가 전달되었는지 검증
    invoked_prompt = mock_get_llm.return_value.invoke.call_args[0][0]
    assert "2026.11.1 계약 기준 실제 신고 체크리스트 작성" in invoked_prompt
    assert "그래 해줘" in invoked_prompt

    # 2. 결과물에서 '바꿔드리겠습니다' 제안 루프가 깔끔히 제거되었는지 검증
    assert "| 임대료 | 신고 대상 |" in draft
    assert "바꿔드리겠습니다" not in draft


@patch("ai_legal_helper.llm.gateway.get_llm")
def test_revise_node_followup_preserves_resolved_query_and_format(mock_get_llm):
    """revise_node가 검증 피드백 보강 시 resolved_query를 사용하고 초안 형식 보존 및 제안 루프를 차단한다."""
    from ai_legal_helper.workflows.legal_workflow import revise_node

    ai_msg = AIMessage(
        content=(
            "| 구분 | 세부 항목 | 2026.11.1 신고 대상 여부 |\n"
            "| --- | --- | --- |\n"
            "| 필수 | 임대료, 계약기간 | 대상 (법 제46조) |\n"
            "| 제외 | 관리비, 전기·수도료 | 비대상 (부칙 유예) |\n\n"
            "필요하시면 관련 제출 서식도 바로 제공해 드리겠습니다."
        )
    )
    llm_mock = MagicMock()
    llm_mock.invoke.return_value = ai_msg
    llm_mock.return_value = ai_msg
    mock_get_llm.return_value = llm_mock

    state = {
        "question": "그래 해줘",
        "resolved_query": "2026.11.1 계약 기준 실제 신고 체크리스트 작성",
        "intent": "FOLLOWUP_ACTION",
        "draft_answer": "| 구분 | 세부 항목 |",
        "categories": ["부동산"],
        "retrieved_sources": [],
        "verification_result": {
            "revision_instructions": ["법령 출처 제46조 표기 보완"],
        },
    }

    result = revise_node(state)
    draft = result["draft_answer"]

    # 1. revise_node 호출 시 LLM 프롬프트에 초안 형식 보존 지침이 포함되어 있는지 검증
    invoked_prompt = mock_get_llm.return_value.invoke.call_args[0][0]
    # invoke was called via prompt | llm, so call_args is StringPromptValue or str
    prompt_str = str(invoked_prompt)
    assert "초안의 형식을 유지한 채" in prompt_str

    # 2. 결과물에서 '제공해 드리겠습니다' 제안 루프가 제거되었는지 검증
    assert "| 필수 | 임대료, 계약기간 |" in draft
    assert "제공해 드리겠습니다" not in draft
