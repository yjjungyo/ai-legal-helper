# -*- coding: utf-8 -*-
"""
테스트 모듈명: test_multi_turn_followup_resolution.py

[테스트 목적]
E2E 3턴 연속 상담 평가에서 발견된 멀티턴 문맥 절삭 및 단문 후속 질의("그래 해줘", "그래 정리해줘")
의도 판정 실패, 질의 복원 부재, 무한 제안 루프를 방지하는 최소 수정 로직을 엄격히 검증한다.

[주요 검증 항목]
1. 기존 Intent Analyzer를 이용해 직전 답변 제안과 현재 단문을 의미적으로 연결하는지 검증
2. 기존 응답의 끝부분·검증 상태 보존 및 새로운 쟁점의 오염 방지 검증
3. 후속 질문에서도 현재 사건 증거와 쟁점을 다시 로딩하는지 검증
4. `supervisor_initialize_node`: 단문 후속 질의에서 intent=FOLLOWUP_ACTION 및 resolved_query, event_date 보존 검증
5. `synthesizer._format_last_answer_context`: 직전 답변 말미의 제안 문장이 프롬프트에서 절삭되지 않고 보존되는지 검증
6. `synthesizer`: 후속 질의 작성 시 말미의 반복적 제안 문구("원하시면 ~정리해드리겠습니다") 후처리 제거 검증
"""

import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage

from ai_legal_helper.workflows.legal_workflow import (
    supervisor_initialize_node, supervisor_condition,
)
from ai_legal_helper.workflows.conversation_context import ConversationContext
from ai_legal_helper.agents.intent_analyzer import (
    IntentDecision, ConsultationMode, analyze_consultation_intent,
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
        "current_question": "그래 해줘",
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
    ctx["current_question"] = "그래 정리해줘"
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
# 1. 의미 기반 문맥 복원: 기존 LLM 분석기를 재사용하며 정규식 제안 추출 금지
# ---------------------------------------------------------------------------

def test_resolution_context_keeps_actual_last_offer(turn1_context):
    """결론 앞부분만 잘라 제안이 누락되는 오류를 방지한다."""
    turn1_context["current_question"] = "그래 해줘"
    ctx = ConversationContext(**turn1_context)
    prompt_ctx = ctx.format_context_for_resolution()
    assert "2026.11.1 계약 기준 실제 신고항목 체크리스트" in prompt_ctx
    assert "과거 AI 답변은 잠정적 설명" in prompt_ctx
    assert "직전 AI 답변 말미" in prompt_ctx
    assert len(prompt_ctx) <= 3200


def test_three_turns_preserve_root_question_and_newest_offer(turn2_context):
    """3턴에서도 최초 사건과 직전 턴에 실제 제안된 작업을 혼동하지 않는다."""
    ctx = ConversationContext(**turn2_context)
    prompt_ctx = ctx.format_context_for_resolution()
    assert "2026년 11월 1일에 새로운 임대차계약" in prompt_ctx
    assert "임대사업자용 임대차계약 신고 체크리스트" in prompt_ctx
    assert "턴 2" in prompt_ctx
    assert len(prompt_ctx) <= 3200


def test_unresolved_short_followup_fails_closed(turn1_context):
    """LLM 장애/불명확 출력 시 존재하지 않는 체크리스트를 임의로 만들지 않는다."""
    turn1_context["current_question"] = "그래 해줘"
    ctx = ConversationContext(**turn1_context)
    with patch("ai_legal_helper.agents.intent_analyzer.get_llm") as llm:
        llm.return_value.invoke.side_effect = RuntimeError("model unavailable")
        decision = analyze_consultation_intent("그래 해줘", ctx, use_llm=True)
    assert decision.intent == ConsultationIntent.NEEDS_CLARIFICATION
    assert decision.resolved_query == "그래 해줘"
    assert decision.requires_retrieval is False


def test_unresolved_llm_output_does_not_fabricate_task(turn1_context):
    turn1_context["current_question"] = "그래 해줘"
    ctx = ConversationContext(**turn1_context)
    response = AIMessage(content='''{
      "intent": "FOLLOWUP_ACTION",
      "consultation_mode": "GENERAL_LEGAL",
      "categories": ["행정"],
      "resolved_query": "그래 해줘",
      "requires_specialist": false,
      "requires_retrieval": false,
      "requires_verification": true,
      "requires_full_analysis": false
    }''')
    with patch("ai_legal_helper.agents.intent_analyzer.get_llm") as llm:
        llm.return_value.invoke.return_value = response
        decision = analyze_consultation_intent("그래 해줘", ctx, use_llm=True)
    assert decision.intent == ConsultationIntent.NEEDS_CLARIFICATION
    assert decision.categories == []


def test_resolution_context_preserves_withheld_state(turn1_context):
    turn1_context["current_question"] = "그다음은?"
    turn1_context["previous_turns"][-1]["answer_status"] = "WITHHELD"
    turn1_context["last_answer_status"] = "WITHHELD"
    ctx = ConversationContext(**turn1_context)
    prompt_ctx = ctx.format_context_for_resolution()
    assert "WITHHELD" in prompt_ctx
    assert "사실 확정 불가" in prompt_ctx


def test_semantic_intent_prompt_receives_last_offer(turn1_context):
    """LLM에 실제 말미 제안과 현재 원문이 함께 전달되는지 검증."""
    turn1_context["current_question"] = "그래 해줘"
    ctx = ConversationContext(**turn1_context)
    response = AIMessage(content="""{
      "intent": "FOLLOWUP_ACTION",
      "consultation_mode": "GENERAL_LEGAL",
      "categories": ["행정"],
      "resolved_query": "2026년 11월 1일 계약을 기준으로 신고항목 체크리스트 작성",
      "requires_specialist": false,
      "requires_retrieval": false,
      "requires_verification": true,
      "requires_full_analysis": false,
      "event_date": "2026-11-01",
      "event_type": "CONTRACT_SIGNED",
      "statute_mention_date": null
    }""")
    with patch("ai_legal_helper.agents.intent_analyzer.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = response
        decision = analyze_consultation_intent("그래 해줘", ctx, use_llm=True)
    sent_prompt = mock_llm.return_value.invoke.call_args[0][0]
    assert "실제 신고항목 체크리스트" in sent_prompt
    assert "그래 해줘" in sent_prompt
    assert decision.intent == ConsultationIntent.FOLLOWUP_ACTION
    assert decision.event_date == "2026-11-01"
    assert decision.resolved_query.endswith("체크리스트 작성")


def _decision(intent, resolved, consultation_mode=ConsultationMode.GENERAL_LEGAL,
              event_date=None, categories=None):
    """실제 LLM 출력 파싱과 분리해 Supervisor 전파·사건 로딩을 테스트한다."""
    return IntentDecision(
        intent=intent,
        consultation_mode=consultation_mode,
        categories=categories or ["행정"],
        resolved_query=resolved,
        event_date=event_date,
        requires_verification=True,
    )


def test_short_case_offer_is_not_forced_to_full_new_analysis(turn1_context):
    """사건 상담이라도 지시 대상이 구체화된 짧은 수락은 FOLLOWUP_ACTION을 유지."""
    turn1_context["current_question"] = "그래 해줘"
    turn1_context["case_id"] = "case-42"
    ctx = ConversationContext(**turn1_context)
    response = AIMessage(content='''{
      "intent": "FOLLOWUP_ACTION",
      "consultation_mode": "CASE_EVIDENCE",
      "categories": ["행정"],
      "resolved_query": "2026년 11월 1일 계약에 관한 신고항목 체크리스트 작성",
      "requires_specialist": false,
      "requires_retrieval": false,
      "requires_verification": true,
      "requires_full_analysis": false
    }''')
    with patch("ai_legal_helper.agents.intent_analyzer.get_llm") as llm:
        llm.return_value.invoke.return_value = response
        decision = analyze_consultation_intent(
            "그래 해줘", ctx, case_context="사건명: 임대차 계약", use_llm=True,
        )
    assert decision.intent == ConsultationIntent.FOLLOWUP_ACTION
    assert decision.requires_retrieval is False
    assert "체크리스트 작성" in decision.resolved_query


def test_supervisor_semantic_followup_preserves_raw_question(turn1_context):
    turn1_context["current_question"] = "그래 해줘"
    task = "2026년 11월 1일 계약을 기준으로 신고항목 체크리스트 작성"
    with patch("ai_legal_helper.workflows.legal_workflow.analyze_consultation_intent",
               return_value=_decision(ConsultationIntent.FOLLOWUP_ACTION, task,
                                      event_date="2026-11-01")) as analyzer:
        out = supervisor_initialize_node({
            "question": "그래 해줘",
            "conversation_context": turn1_context,
            "conversation_id": "conv-test-1234",
            "turn_index": 2,
        })
    assert analyzer.call_args.kwargs["use_llm"] is True
    assert out["question"] == "그래 해줘"
    assert out["resolved_query"] == task
    assert out["intent"] == "FOLLOWUP_ACTION"
    assert out["intent_decision"]["event_date"] == "2026-11-01"
    assert out["retrieved_sources"] == []  # 이전 조문을 최신 법령 근거로 자동 확정 금지


def test_supervisor_new_question_does_not_inherit_old_offer(turn1_context):
    turn1_context["current_question"] = "회사의 근로계약 해지에 대해 알려줘"
    question = turn1_context["current_question"]
    with patch("ai_legal_helper.workflows.legal_workflow.analyze_consultation_intent",
               return_value=_decision(ConsultationIntent.NEW_LEGAL_ANALYSIS, question,
                                      categories=["노동"])):
        out = supervisor_initialize_node({
            "question": question, "conversation_context": turn1_context,
        })
    assert out["resolved_query"] == question
    assert out["categories"] == ["노동"]
    assert "체크리스트" not in out["resolved_query"]


def test_supervisor_no_offer_does_not_fabricate_task(turn1_context):
    turn1_context["current_question"] = "네"
    turn1_context["previous_turns"][-1]["answer"] = "분석은 여기까지입니다."
    turn1_context["last_answer"] = "분석은 여기까지입니다."
    with patch("ai_legal_helper.workflows.legal_workflow.analyze_consultation_intent",
               return_value=_decision(ConsultationIntent.NEEDS_CLARIFICATION, "네",
                                      categories=[])):
        out = supervisor_initialize_node({
            "question": "네", "conversation_context": turn1_context,
        })
    assert out["resolved_query"] == "네"
    assert out["intent"] == "NEEDS_CLARIFICATION"
    assert supervisor_condition(out) == "routing_exit"


def test_supervisor_first_turn_short_is_not_followup():
    with patch("ai_legal_helper.workflows.legal_workflow.analyze_consultation_intent") as analyzer:
        out = supervisor_initialize_node({
            "question": "보증금 반환 방법",
            "conversation_context": None,
            "conversation_id": "conv-new-1",
            "turn_index": 1,
        })
    analyzer.assert_not_called()
    assert out["intent"] == ConsultationIntent.NEW_LEGAL_ANALYSIS.value
    assert out["resolved_query"] == "보증금 반환 방법"


def test_followup_case_reloads_current_evidence_and_plans_issues(turn1_context):
    """이전에는 FOLLOWUP_ACTION 분기가 최신 승인 증거를 읽지 않는 결함이 있었다."""
    turn1_context["current_question"] = "그럼 지금 이사해도 될까?"
    turn1_context["case_id"] = "case-42"
    question = "임대차 보증금 미반환 사건에서 이사 시 권리 유지 요건 검토"
    d = _decision(ConsultationIntent.FOLLOWUP_QUESTION, question,
                  consultation_mode=ConsultationMode.CASE_EVIDENCE,
                  categories=["민법"])
    briefing = MagicMock()
    briefing.model_dump.return_value = {
        "source_documents": [
            {"review_status": "APPROVED", "document_name": "E01_계약서.txt",
             "content": "최신 승인 원문"}
        ],
        "source_registry": {
            "E01": {"source_id": "E01", "content": "최신 승인 원문"}
        },
    }
    briefing.source_registry = {"E01": {"source_id": "E01", "content": "최신 승인 원문"}}
    briefing.formatted_summary = "최신 승인 사실: 계약 종료 및 보증금 미반환"
    issue = MagicMock()
    issue.model_dump.return_value = {"issue_id": "issue-1", "issue_title": "이사 시 권리"}
    with patch("ai_legal_helper.workflows.legal_workflow.analyze_consultation_intent",
               return_value=d), \
         patch("ai_legal_helper.database.session.SessionLocal") as session, \
         patch("ai_legal_helper.case_intelligence.case_briefing.build_case_evidence_briefing",
               return_value=briefing) as build, \
         patch("ai_legal_helper.workflows.issue_planner.plan_legal_issues",
               return_value=[issue]) as planner:
        out = supervisor_initialize_node({
            "question": "그럼 지금 이사해도 될까?",
            "conversation_context": turn1_context,
            "case_id": "case-42",
        })
    build.assert_called_once()
    assert build.call_args.args[2] == question
    assert planner.call_args.args[0] == question
    assert out["answer_mode"] == "DOCUMENT_GROUNDED"
    assert out["case_context"] == briefing.formatted_summary
    assert len(out["issue_tasks"]) == 1
    assert out["case_evidence_sources"] == [{"source_id": "E01"}]
    session.return_value.close.assert_called_once()


# ---------------------------------------------------------------------------
# 2. 기존 Synthesizer 및 후속 재작성 로직의 회귀검증
# ---------------------------------------------------------------------------
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
