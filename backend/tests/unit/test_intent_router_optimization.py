# -*- coding: utf-8 -*-
"""
모듈명: test_intent_router_optimization.py

[모듈 개요]
사용자 질문 분석 단계(intent_analysis_node)와 라우팅 단계(route_node) 간의
중복 LLM 호출을 제거하고 Fast-Path로 전환하는 통합 최적화 기능을 검증하는 단위 테스트 모듈이다.

[주요 검증 항목]
1. `test_intent_analyzer_extracts_categories`:
   - LLM 응답에 포함된 categories가 유효성 검증을 거쳐 IntentDecision에 정상 반영되는지 검증
2. `test_heuristic_rule_fallback_categories`:
   - 규칙 기반 폴백 시 질문 키워드(노동, 형법, 민법, 인사말)에 따라 적절한 기본 categories가 채워지는지 검증
3. `test_route_node_fast_path_skips_llm`:
   - intent_decision에 사전 도출된 categories가 존재할 때 route_node가 LLM(route_categories_detailed)을
     전혀 호출하지 않고 즉시 Fast-Path로 0.00초 반환하는지 검증
4. `test_route_node_document_mode_skips_llm`:
   - DOCUMENT_MODE(문서 상담) 실행 시 Specialist 분기가 불필요하므로 route_node의 LLM 호출이 스킵되는지 검증
5. `test_route_node_fallback_when_pre_categories_empty`:
   - 사전 categories가 없는 경우(단위 테스트 등 직접 호출) 기존 route_categories_detailed LLM으로 정상 폴백되는지 검증
"""

from unittest.mock import MagicMock, patch
import pytest

from ai_legal_helper.agents.intent_analyzer import (
    ConsultationIntent,
    ConsultationMode,
    IntentDecision,
    analyze_consultation_intent,
    _heuristic_rule_fallback,
)
from ai_legal_helper.workflows.legal_workflow import route_node
from ai_legal_helper.workflows.document_consultation import DOCUMENT_MODE
from ai_legal_helper.agents.router import RouterDecision, RouterStatus


def test_intent_analyzer_extracts_categories():
    """LLM 응답에서 법률 분야(categories)를 추출하고 유효한 분야만 정제하는지 검증한다.

    [검증 내용]
    - 허용된 8대 분야(민법, 형법 등)는 유지되고, 허용되지 않은 분야('우주법')는 필터링되는지 확인.
    - 최대 3개까지만 채택되는지 확인.
    """
    mock_llm = MagicMock()
    mock_llm.invoke.return_value.content = (
        '{"intent": "NEW_LEGAL_ANALYSIS", "consultation_mode": "CASE_EVIDENCE", '
        '"categories": ["민법", "형법", "우주법", "노동", "상법"], '
        '"resolved_query": "보증금 미반환 및 사기 혐의 검토", '
        '"requires_specialist": true, "requires_retrieval": true, '
        '"reason": "민사 보증금 및 형사 사기 쟁점"}'
    )

    with patch("ai_legal_helper.agents.intent_analyzer.get_llm", return_value=mock_llm):
        decision = analyze_consultation_intent(
            question="보증금을 돌려받지 못했는데 형사 고소도 가능한가요?",
            conversation_context=None,
            case_context="",
        )

    # 1. 의도 및 쿼리 복원 확인
    assert decision.intent == ConsultationIntent.NEW_LEGAL_ANALYSIS
    # 2. 유효 분야 필터링 및 최대 3개 제한 확인 (우주법 제외 -> 민법, 형법, 노동)
    assert decision.categories == ["민법", "형법", "노동"]


def test_heuristic_rule_fallback_categories():
    """LLM 호출 실패 또는 규칙 폴백 시 질문 유형에 맞는 기본 법률 분야가 지정되는지 검증한다."""
    # 인사말: 분야 없음
    d_greet = _heuristic_rule_fallback("감사합니다!", has_history=False)
    assert d_greet.categories == []

    # 노동 질문: 노동 분야
    d_labor = _heuristic_rule_fallback("퇴직금을 지급받지 못했습니다.", has_history=False)
    assert d_labor.categories == ["노동"]

    # 형사 질문: 형법 분야
    d_crim = _heuristic_rule_fallback("상대방에게 사기를 당해 고소하고 싶습니다.", has_history=False)
    assert d_crim.categories == ["형법"]

    # 일반 사건: 기본 민법 분야
    d_civil = _heuristic_rule_fallback("임대차 계약 만기 후 보증금 반환 분쟁입니다.", has_history=False)
    assert d_civil.categories == ["민법"]


def test_route_node_fast_path_skips_llm():
    """intent_decision에 사전 도출된 categories가 있으면 route_node가 LLM을 전혀 호출하지 않고 즉시 반환하는지 검증한다."""
    state = {
        "question": "보증금을 반환받지 못했습니다.",
        "resolved_query": "임대차 보증금 반환 청구 및 대항력 요건 검토",
        "intent": "NEW_LEGAL_ANALYSIS",
        "intent_decision": {
            "intent": "NEW_LEGAL_ANALYSIS",
            "categories": ["민법"],
            "reason": "임대차 보증금 반환 채무불이행 쟁점",
        },
        "case_context": "",
    }

    with patch("ai_legal_helper.agents.router.route_categories_detailed") as mock_route:
        result = route_node(state)

        # route_categories_detailed가 전혀 호출되지 않아야 함 (Fast-Path)
        mock_route.assert_not_called()

    assert result["categories"] == ["민법"]
    assert result["selected_agents"] == ["민법"]
    assert result["router_status"] == RouterStatus.CLASSIFIED.value
    assert "Intent 분석에서 사전 도출된 법률 분야 채택" in result["router_reason"]


def test_route_node_document_mode_skips_llm():
    """DOCUMENT_MODE(문서 상담) 실행 시 route_node가 LLM을 호출하지 않고 Fast-Path로 즉시 반환하는지 검증한다."""
    state = {
        "question": "제출된 17개 자료를 대조하여 사실관계를 분석해주세요.",
        "resolved_query": "제출된 17개 자료를 대조하여 사실관계를 분석해주세요.",
        "answer_mode": DOCUMENT_MODE,
        "case_evidence_briefing": {
            "case_type": "민법",
        },
    }

    with patch("ai_legal_helper.agents.router.route_categories_detailed") as mock_route:
        result = route_node(state)

        # DOCUMENT_MODE에서는 LLM 라우팅이 불필요하므로 호출되지 않아야 함
        mock_route.assert_not_called()

    assert result["categories"] == ["민법"]
    assert result["router_status"] == RouterStatus.CLASSIFIED.value
    assert "DOCUMENT_MODE" in result["router_reason"]


def test_route_node_fallback_when_pre_categories_empty():
    """state에 사전 도출된 categories가 없을 때(레거시 호출 또는 서브 플로우) 기존 LLM 라우터로 정상 폴백하는지 검증한다."""
    state = {
        "question": "회사에서 부당해고를 당했습니다.",
        "resolved_query": "회사에서 부당해고를 당했습니다.",
        "intent_decision": {},  # 사전 카테고리 없음
        "case_context": "",
    }

    mock_decision = RouterDecision(
        status=RouterStatus.CLASSIFIED,
        categories=["노동"],
        reason="부당해고 및 구제신청 쟁점",
    )

    with patch("ai_legal_helper.agents.router.route_categories_detailed", return_value=mock_decision) as mock_route:
        result = route_node(state)

        # 사전 카테고리가 없으므로 route_categories_detailed가 1회 호출되어야 함
        mock_route.assert_called_once()

    assert result["categories"] == ["노동"]
    assert result["router_status"] == RouterStatus.CLASSIFIED.value
    assert result["router_reason"] == "부당해고 및 구제신청 쟁점"
