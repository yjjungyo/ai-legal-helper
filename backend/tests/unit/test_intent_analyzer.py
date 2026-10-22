# -*- coding: utf-8 -*-
"""
모듈명: test_intent_analyzer.py

[모듈 개요]
Phase 2: 질문 의도 분석(ConsultationIntent), 문맥 복원 질의(resolved_query) 생성,
그리고 코드 레벨의 엄격한 가드레일 정책을 검증하는 단위 테스트 모듈이다.

[테스트 항목]
1. `test_first_turn_guardrail_prevents_followup`: 첫 번째 질문 시 FOLLOWUP 계열 차단 및 NEW_LEGAL_ANALYSIS 보정 검증
2. `test_followup_action_classification`: "이제 뭘 해야 하죠?"가 FOLLOWUP_ACTION으로 분류되고 RAG/Specialist가 비활성화되는지 검증
3. `test_followup_question_classification`: "임차권등기명령은 언제 신청하나요?"가 FOLLOWUP_QUESTION으로 분류되는지 검증
4. `test_fact_clarification_classification`: "확정일자는 2022년 3월 10일입니다."가 FACT_CLARIFICATION으로 분류되는지 검증
5. `test_general_conversation_classification`: "감사합니다", "안녕하세요"가 GENERAL_CONVERSATION으로 분류되는지 검증
6. `test_resolved_query_enrichment`: 단문 후속 질의 시 생략된 문맥이 resolved_query에 복원되는지 검증
7. `test_rewrite_query_with_resolved_query`: query_rewrite 모듈이 resolved_query를 반영하는지 검증
"""

import pytest
from unittest.mock import MagicMock, patch

from ai_legal_helper.agents.intent_analyzer import (
    ConsultationIntent,
    IntentDecision,
    analyze_consultation_intent,
    _heuristic_rule_fallback,
)
from ai_legal_helper.workflows.conversation_context import (
    ConversationTurn,
    ConversationContext,
)
from ai_legal_helper.rag.query_rewrite import rewrite_query


def test_first_turn_guardrail_prevents_followup():
    """첫 번째 질문(이전 턴 없음)인 경우, FOLLOWUP 계열로 분류되지 않고 NEW_LEGAL_ANALYSIS로 보정되는지 검증한다."""
    # LLM이 실수로 FOLLOWUP_ACTION으로 반환하는 시나리오 모의
    mock_llm = MagicMock()
    mock_llm.invoke.return_value.content = '{"intent": "FOLLOWUP_ACTION", "resolved_query": "이제 뭘 해야 하죠?", "requires_specialist": false, "requires_retrieval": false, "reason": "테스트"}'

    with patch("ai_legal_helper.agents.intent_analyzer.get_llm", return_value=mock_llm):
        decision = analyze_consultation_intent(
            question="이제 뭘 해야 하죠?",
            conversation_context=None,  # 첫 번째 턴 (대화 이력 없음)
            case_context="",
        )

    # 가드레일에 의해 NEW_LEGAL_ANALYSIS로 강제 보정되어야 함
    assert decision.intent == ConsultationIntent.NEW_LEGAL_ANALYSIS
    assert decision.requires_specialist is True
    assert decision.requires_retrieval is True


def test_followup_action_classification():
    """이전 상담이 존재할 때 '이제 뭘 해야 하죠?'가 FOLLOWUP_ACTION으로 분류되고 적응형 플래그가 설정되는지 검증한다."""
    t1 = ConversationTurn(
        turn_index=1,
        request_id="req-1",
        question="전세보증금을 반환받지 못했습니다.",
        answer="임대차계약 해지 통보와 임차권등기명령이 필요합니다.",
        answer_status="DELIVERED",
    )
    ctx = ConversationContext(
        conversation_id="conv-1",
        current_question="이제 뭘 해야 하죠?",
        previous_turns=[t1],
        last_answer=t1.answer,
    )

    decision = _heuristic_rule_fallback(
        question="이제 뭘 해야 하죠?",
        has_history=True,
        case_context="전세보증금 미반환 분쟁",
    )

    assert decision.intent == ConsultationIntent.FOLLOWUP_ACTION
    assert decision.requires_specialist is False  # Specialist 생략
    assert decision.requires_retrieval is False   # RAG 생략
    assert decision.requires_verification is True # 검증은 유지
    assert "우선순위 조치" in decision.resolved_query


def test_followup_question_classification():
    """앞선 답변의 세부 항목 질문이 FOLLOWUP_QUESTION으로 분류되는지 검증한다."""
    t1 = ConversationTurn(
        turn_index=1,
        request_id="req-1",
        question="보증금 반환 절차",
        answer="임차권등기명령을 신청해야 합니다.",
        answer_status="DELIVERED",
    )
    ctx = ConversationContext(
        conversation_id="conv-2",
        current_question="임차권등기명령은 언제 신청하나요?",
        previous_turns=[t1],
    )

    mock_llm = MagicMock()
    mock_llm.invoke.return_value.content = '{"intent": "FOLLOWUP_QUESTION", "resolved_query": "앞선 전세보증금 반환 절차에서 임차권등기명령 신청 요건 및 가능 시점", "requires_specialist": true, "requires_retrieval": true, "requires_verification": true, "requires_full_analysis": false, "reason": "세부 요건 질의"}'

    with patch("ai_legal_helper.agents.intent_analyzer.get_llm", return_value=mock_llm):
        decision = analyze_consultation_intent(
            question="임차권등기명령은 언제 신청하나요?",
            conversation_context=ctx,
            case_context="",
        )

    assert decision.intent == ConsultationIntent.FOLLOWUP_QUESTION
    assert decision.requires_specialist is True
    assert decision.requires_retrieval is True
    assert "임차권등기명령" in decision.resolved_query


def test_fact_clarification_classification():
    """사용자의 새로운 사실 진술이 FACT_CLARIFICATION으로 분류되는지 검증한다."""
    t1 = ConversationTurn(
        turn_index=1,
        request_id="req-1",
        question="보증금 우선변제권 요건",
        answer="대항력과 확정일자가 필요합니다.",
        answer_status="DELIVERED",
    )
    ctx = ConversationContext(
        conversation_id="conv-3",
        current_question="확정일자는 2022년 3월 10일입니다.",
        previous_turns=[t1],
    )

    decision = _heuristic_rule_fallback(
        question="확정일자는 2022년 3월 10일입니다.",
        has_history=True,
        case_context="",
    )

    assert decision.intent == ConsultationIntent.FACT_CLARIFICATION
    assert decision.requires_specialist is True
    assert decision.requires_retrieval is False


def test_general_conversation_classification():
    """단순 인사 및 감사 표현이 GENERAL_CONVERSATION으로 분류되고 무거운 실행이 전부 생략되는지 검증한다."""
    decision = _heuristic_rule_fallback(
        question="도움 주셔서 감사합니다!",
        has_history=True,
    )
    assert decision.intent == ConsultationIntent.GENERAL_CONVERSATION
    assert decision.requires_specialist is False
    assert decision.requires_retrieval is False
    assert decision.requires_verification is False
    assert decision.requires_full_analysis is False


def test_rewrite_query_with_resolved_query():
    """rewrite_query가 resolved_query를 반영하여 키워드를 보강하는지 검증한다."""
    mock_llm = MagicMock()
    mock_llm.invoke.return_value.content = '{"terms": ["임차권등기명령", "주택임대차보호법 제3조의3"]}'

    with patch("ai_legal_helper.rag.query_rewrite.get_llm", return_value=mock_llm):
        rewritten = rewrite_query(
            question="이제 뭘 해야 하죠?",
            category_ko="민법",
            resolved_query="보증금 반환 지연에 따른 임차권등기명령 신청 조치",
            max_terms=2,
        )

    assert "이제 뭘 해야 하죠?" in rewritten
    assert "키워드: 임차권등기명령, 주택임대차보호법 제3조의3" in rewritten

