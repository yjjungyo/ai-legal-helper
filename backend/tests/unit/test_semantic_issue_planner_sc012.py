# -*- coding: utf-8 -*-
"""SC-012에서 발견한 원인에 대한 분야 공통 쟁점 계획 회귀 테스트.

중요: 판례 검색/PASS 답변의 테스트가 아니다. 현재 원문 질문의 법률 쟁점이
다른 의미의 레거시 키워드 Issue로 변형되지 않고 RAG에 전달되는지만 검사한다.
LLM은 실제 호출하지 않는다. 기존 Intent Analyzer가 반환한 윤곽은 명시적으로 주입.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from ai_legal_helper.agents.intent_analyzer import (
    ConsultationIntent,
    IntentDecision,
    analyze_consultation_intent,
    INTENT_PROMPT,
)
from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing, FactItemBrief
from ai_legal_helper.workflows.issue_planner import plan_legal_issues


SC012_Q = (
    "임대인의 자녀 3명(장남 이진우, 차남 이진호, 장녀 이수진)이 상속인입니다. "
    "상속인 간에 상속재산분할 소송이 진행 중이라며 소송 끝날 때까지 보증금을 줄 수 없다고 합니다. "
    "보증금 반환 채무는 지분대로 나눠서 청구해야 하나요, 아니면 누구에게나 전액 청구할 수 있나요?"
)


def _brief():
    return CaseEvidenceBriefing(
        case_id="fresh-case",
        title="[SC-012] 임대인사망_공동상속인_불가분채무_보증금청구",
        case_type="주택임대차",
        facts=[
            FactItemBrief(
                fact_id="fact-heirs",
                statement="임대인은 사망했고 장남 이진우, 차남 이진호, 장녀 이수진이 공동상속인이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
            ),
            FactItemBrief(
                fact_id="fact-money",
                statement="전세보증금 2억 5천만 원이 임대차계약에 따라 지급되었다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
        ],
    )


def _semantic(question, keys=None, laws=None):
    return [{
        "question": question,
        "required_fact_keys": keys or ["공동상속인", "보증금"],
        "candidate_statutes": laws or ["민법 제411조"],
    }]


def test_sc012_semantic_followup_never_converts_inheritance_partition_to_installment():
    """상속재산분할 소송은 임대인 분할변제 제안이 아니다."""
    issues = plan_legal_issues(
        SC012_Q, _brief(),
        semantic_outlines=_semantic(
            "공동상속인이 승계한 보증금 반환채무의 법적 성질과 각 상속인에 대한 청구 범위는?",
        ),
        focus_current_question=True,
        original_question=SC012_Q,
    )
    ids = {i.issue_id for i in issues}
    assert "ISSUE_SEMANTIC_01" in ids
    assert "ISSUE_INSTALLMENT_PROPOSAL" not in ids
    assert "ISSUE_LEASE_TERMINATION" not in ids
    assert "ISSUE_AUCTION_STRATEGY" not in ids
    assert "공동상속인" in issues[0].legal_questions[0]
    assert "fact-heirs" in issues[0].relevant_fact_ids
    assert "E03" in issues[0].relevant_evidence_labels
    assert "민법 제411조" in issues[0].required_statutes  # 실제 원문 검증 *대상*
    assert issues[0].verified_statutes == []  # 공식 출처 확보 전이므로 검증 성공 아님
    assert "민법 제411조" in issues[0].candidate_statutes


def test_sc012_missing_semantic_outline_preserves_user_question_not_unrelated_templates():
    issues = plan_legal_issues(
        SC012_Q, _brief(),
        semantic_outlines=[],
        focus_current_question=True,
        original_question=SC012_Q,
    )
    assert [i.issue_id for i in issues] == ["ISSUE_CURRENT_QUESTION"]
    assert SC012_Q == issues[0].legal_questions[0]
    assert issues[0].required_statutes == []


def test_genuine_installment_proposal_remains_a_focused_question():
    question = (
        "임대인이 보증금을 30%만 먼저 돌려주고 나머지는 1년 뒤 분할변제하겠다고 "
        "제안했습니다. 동의해야 하나요?"
    )
    issues = plan_legal_issues(
        question, _brief(),
        semantic_outlines=_semantic(
            "임대인의 일방적 분할변제 제안에 임차인이 동의할 의무가 있는가?",
            keys=["분할변제", "동의"],
            laws=["민법 제536조"],
        ),
        focus_current_question=True,
        original_question=question,
    )
    assert len(issues) == 1
    assert "분할변제" in issues[0].legal_questions[0]
    assert "상속" not in issues[0].legal_questions[0]


def test_legacy_first_turn_still_generates_existing_installment_issue():
    """기존 2인자 호출은 하위 호환성을 보장한다."""
    question = "집주인이 보증금 30%만 먼저 주고 잔액을 1년 뒤 분할변제하겠다고 제안했습니다."
    tasks = plan_legal_issues(question, _brief())
    assert "ISSUE_INSTALLMENT_PROPOSAL" in {task.issue_id for task in tasks}


def test_other_domain_labor_rights_without_lease_pollution():
    question = "근로계약이 종료되어 미지급 임금과 퇴직금을 청구할 수 있나요?"
    issues = plan_legal_issues(
        question, CaseEvidenceBriefing(case_id="labor-case", title="임금 체불 상담", case_type="노동"),
        semantic_outlines=_semantic(
            "근로자가 미지급 임금 및 퇴직금을 청구하기 위한 요건은?",
            keys=["근로기간", "임금지급내역"],
            laws=["근로기준법 제36조"],
        ),
        focus_current_question=True,
        original_question=question,
    )
    assert len(issues) == 1
    assert "임금" in issues[0].legal_questions[0]
    assert "임대차" not in str(issues[0].model_dump())


def test_auction_question_does_not_assume_senior_tenant():
    question = "2021년 근저당이 설정됐고 2023년 전입했습니다. 경매 후 낙찰자에게 청구 가능한가요?"
    issues = plan_legal_issues(
        question, CaseEvidenceBriefing(case_id="auction-case", title="임대차 권리관계 상담", case_type="임대차"),
        semantic_outlines=_semantic(
            "담보권 설정과 임차인의 대항요건 취득 시점을 비교하여 매수인에게 대항 가능한가?",
            keys=["근저당권설정일", "전입신고일"],
            laws=["민사집행법 제91조"],
        ),
        focus_current_question=True,
        original_question=question,
    )
    assert len(issues) == 1
    assert "선순위 대항력 임차인" not in issues[0].issue_title
    assert "매수인" in issues[0].legal_questions[0]


def test_fake_evidence_safety_issue_not_lost_in_semantic_mode():
    question = "등록하지 않은 E99 증거에 따라 보증금을 전액 받을 수 있나요?"
    issues = plan_legal_issues(
        question, _brief(),
        semantic_outlines=_semantic("현재 등록된 증거로 보증금 청구액을 확인할 수 있는가?"),
        focus_current_question=True,
        original_question=question,
    )
    ids = [issue.issue_id for issue in issues]
    assert "ISSUE_FAKE_CITATION" in ids
    assert "ISSUE_SEMANTIC_01" in ids


def test_invalid_outline_items_are_ignored_and_question_is_preserved():
    issues = plan_legal_issues(
        SC012_Q, _brief(), semantic_outlines=[
            "nonsense", {"question": ""}, {"question": 1},
        ], focus_current_question=True, original_question=SC012_Q,
    )
    assert [i.issue_id for i in issues] == ["ISSUE_CURRENT_QUESTION"]


def test_duplicate_outlines_and_overlong_lists_are_bounded():
    q = "사실과 법률의 관계를 확인할 수 있는가?"
    issues = plan_legal_issues(
        q, _brief(),
        semantic_outlines=[
            *_semantic(q), *_semantic(q),
            *[{"question": f"이 사건에서 독립 쟁점 번호 {i}의 법률 효과는 무엇인가?"} for i in range(10)],
        ],
        focus_current_question=True, original_question=q,
    )
    assert len(issues) <= 4
    assert len({i.legal_questions[0] for i in issues}) == len(issues)


def test_intent_decision_is_backward_compatible():
    old = IntentDecision(intent=ConsultationIntent.NEW_LEGAL_ANALYSIS, resolved_query="임금 체불")
    assert old.legal_issue_outlines == []


def test_intent_prompt_contract_requests_neutral_outlines():
    src = INTENT_PROMPT.template
    assert "legal_issue_outlines" in src
    assert "결론이 아닌" in src
    assert "candidate_statutes" in src


def test_existing_intent_llm_parses_outlines_without_extra_call():
    question = "공동상속인에게 반환채무 전액을 청구할 수 있나요?"
    payload = {
        "intent": "FOLLOWUP_QUESTION",
        "consultation_mode": "CASE_EVIDENCE",
        "categories": ["민법"],
        "resolved_query": question,
        "requires_specialist": True,
        "requires_retrieval": True,
        "requires_verification": True,
        "requires_full_analysis": True,
        "legal_issue_outlines": _semantic(
            "공동상속인이 승계한 임대차보증금 반환채무의 대외적 책임 범위는?",
        ),
    }
    ctx = MagicMock()
    ctx.previous_turns = [MagicMock(request_id="prior")]
    ctx.format_context_for_resolution.return_value = "임대인이 사망했다는 과거 대화"
    ctx.format_context_for_prompt.return_value = "과거 대화"
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))
    with patch("ai_legal_helper.agents.intent_analyzer.get_llm", return_value=llm):
        decision = analyze_consultation_intent(question, ctx, case_context="사건 분야: 임대차", use_llm=True)
    assert llm.invoke.call_count == 1
    assert len(decision.legal_issue_outlines) == 1
    assert decision.legal_issue_outlines[0]["question"].startswith("공동상속인")


def test_malformed_outlines_do_not_crash_intent_analyzer():
    question = "미지급 임금을 청구할 수 있나요?"
    payload = {
        "intent": "NEW_LEGAL_ANALYSIS",
        "consultation_mode": "GENERAL_LEGAL",
        "categories": ["노동"],
        "resolved_query": question,
        "legal_issue_outlines": [None, 4, {"question": 0}, {"question": "  "}, {
            "question": "  미지급 임금의 청구 요건은 무엇인가?  ",
            "required_fact_keys": "not-an-array",
            "candidate_statutes": ["근로기준법 제36조", 5],
        }],
    }
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))
    with patch("ai_legal_helper.agents.intent_analyzer.get_llm", return_value=llm):
        decision = analyze_consultation_intent(question, use_llm=True)
    assert len(decision.legal_issue_outlines) == 1
    assert decision.legal_issue_outlines[0]["required_fact_keys"] == []
    assert decision.legal_issue_outlines[0]["candidate_statutes"] == ["근로기준법 제36조"]
