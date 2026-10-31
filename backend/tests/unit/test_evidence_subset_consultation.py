"""증거 일부 등록 단계에서 거래 방향과 법률 판단 전제를 보존하는 회귀 테스트.

외부 LLM·DB 호출 없이 실제 의도 분류, 쟁점 검증 및 최종 조립을 연결한다.
문서의 일반 의무 조항이나 지급 자료가 종료·반환 사실로 승격되지 않아야 한다.
"""

from unittest.mock import MagicMock, patch

import pytest

from ai_legal_helper.agents.intent_analyzer import (
    _heuristic_rule_fallback,
    analyze_consultation_intent,
)
from ai_legal_helper.agents.issue_verifier import verify_issue, IssueVerificationResult
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing, EvidenceItemBrief, FactItemBrief, PartyItemBrief,
)
from ai_legal_helper.workflows.final_disposition import (
    assemble_grounded_answer, detect_case_delta,
)
from ai_legal_helper.workflows.issue_planner import LegalIssueTask


QUESTION = (
    "등록된 계약서와 입금·전입 자료를 기준으로 현재까지 확인되는 계약 사실, 당사자, "
    "보증금 지급 여부, 임차인의 권리 및 앞으로 확인할 사항을 분석해 주세요."
)


@pytest.fixture
def subset_briefing():
    """통지·반환 자료가 없는 계약·지급·거주 기록 브리핑을 만든다.

    Returns:
        CaseEvidenceBriefing: 현재 권리 유지는 당사자 진술로 구분한 격리 사건.
    """
    statements = [
        ("계약", "임대인은 가상임대인이고 임차인은 가상임차인이다.", "E01"),
        ("계약", "임대차 목적물은 가상주택 101호로 주거용이다.", "E01"),
        ("기간", "계약기간은 2022년 3월 1일부터 2024년 2월 28일까지이다.", "E01"),
        ("금액", "보증금은 300,000,000원이다.", "E01"),
        ("조항", "계약 종료 시 임차인은 목적물을 반환하고 임대인은 보증금을 반환한다.", "E01"),
        ("지급", "임차인이 임대인에게 계약금 30,000,000원과 잔금 270,000,000원을 지급하였다.", "E02"),
        ("입주", "실제 입주일은 2022년 3월 1일이다.", "E03"),
        ("전입", "전입신고일은 2022년 3월 2일이다.", "E03"),
        ("확정일자", "확정일자 부여일은 2022년 2월 22일이다.", "E03"),
    ]
    names = {"E01": "E01_계약서.txt", "E02": "E02_지급내역.txt", "E03": "E03_거주기록.txt"}
    facts = [FactItemBrief(
        fact_id=f"f{i}", statement=statement, fact_type=kind,
        adjudication_status="EVIDENCE_SUPPORTED", evidence_label=label,
        document_name=names[label],
    ) for i, (kind, statement, label) in enumerate(statements)]
    facts.append(FactItemBrief(
        fact_id="current", statement="현재 전입 유지 및 거주는 임차인 진술상 유지 중이다.",
        adjudication_status="PARTY_ALLEGED", evidence_label="E03", document_name=names["E03"],
    ))
    return CaseEvidenceBriefing(
        case_id="subset-only", title="기초 계약 분석", as_of_date="2026.10.30",
        parties=[PartyItemBrief(party_id="p1", name="가상임대인", role="임대인"),
                 PartyItemBrief(party_id="p2", name="가상임차인", role="임차인")],
        facts=facts,
        evidences=[EvidenceItemBrief(evidence_id=label, evidence_label=label,
                    document_name=name, document_type="TXT") for label, name in names.items()],
        source_registry={label: {"document_name": name} for label, name in names.items()},
    )


@pytest.mark.parametrize("history", [False, True])
def test_material_review_is_not_repayment_update(subset_briefing, history):
    """대화 유무와 무관하게 자료 분석 요청에서 새 반환 진술을 생성하지 않는다."""
    decision = _heuristic_rule_fallback(QUESTION, has_history=history)
    assert decision.intent.value == "NEW_LEGAL_ANALYSIS"
    assert decision.requires_retrieval
    delta = detect_case_delta(subset_briefing, None, QUESTION, "일부 입금/변제 주장 검토")
    assert not delta or not delta["has_delta"]


def test_llm_rewrite_cannot_invent_payment_statement():
    """LLM이 분석 요청을 변제 진술로 재작성해도 원질문 기준으로 교정한다."""
    llm = MagicMock()
    llm.invoke.return_value.content = (
        '{"intent":"FACT_CLARIFICATION","resolved_query":"일부 입금/변제 주장",'
        '"requires_retrieval":false}'
    )
    with patch("ai_legal_helper.agents.intent_analyzer.get_llm", return_value=llm):
        decision = analyze_consultation_intent(QUESTION)
    assert decision.intent.value == "NEW_LEGAL_ANALYSIS"
    assert decision.resolved_query == QUESTION
    assert decision.requires_verification and decision.requires_retrieval


@pytest.mark.parametrize("question", [
    "계약서와 이체 자료를 분석해 주세요.",
    "임차인이 임대인에게 보증금을 입금했어요. 지급 여부를 확인해주세요.",
    "임대인이 일부 입금했나요?", "보증금을 돌려받지 못했어요.",
    "임차인이 3억 원을 입금했어요.", "2천만 원을 입금했어요.",
    "집주인이 일부 반환받았을까요?", "임대인이 안 입금했어요.",
])
def test_no_new_return_claim_without_affirmative_statement(subset_briefing, question):
    """자료 언급·반대 방향 지급·의문·부정 표현은 일부 반환 주장으로 만들지 않는다."""
    delta = detect_case_delta(subset_briefing, None, question, "")
    assert not delta or not any("입금 진술 접수" in s for s in delta["changed_facts"])


@pytest.mark.parametrize("question", [
    "집주인이 2천만 원을 입금했어요. 남은 보증금은 얼마인가요?",
    "임대인이 5천만원을 입금했다고 합니다. 남은 보증금은 얼마인가요?",
    "보증금 중 2천만 원을 돌려받았습니다.",
    "집주인이 보증금 중 2천만 원을 돌려줬어요.",
    "임대인이 2026.10.20 2천만 원을 입금했어요.",
])
def test_actual_return_statement_still_supported(subset_briefing, question):
    """실제 반환 진술은 증빙 없는 주장으로 처리하되 기초 지급과 혼동하지 않는다."""
    delta = detect_case_delta(subset_briefing, None, question, "")
    assert delta["has_delta"]
    assert delta["calculation_basis"]["status"] == "PROVISIONAL"
    assert any("USER_ALLEGED" in s for s in delta["changed_facts"])


@pytest.mark.parametrize("statement", [
    "계약 종료 시 임차인은 목적물을 반환하고 임대인은 보증금을 반환한다.",
    "계약기간은 2022년 3월 1일부터 2024년 2월 28일까지이다.",
    "최초 임대차 기간이 2024년 2월 28일 만료되었다.",
    "계약은 아직 종료되지 않았다.",
    "2024년 2월 28일 임대차계약 기간 만료 및 해지 통고 완료",
])
def test_clause_or_original_expiry_does_not_verify_termination(subset_briefing, statement):
    """조항·최초 만기·종료 부정만으로 실제 종료를 검증하지 않는다."""
    subset_briefing.facts = [FactItemBrief(
        fact_id="only", statement=statement, evidence_label="E01",
        adjudication_status="EVIDENCE_SUPPORTED",
    )]
    issue = LegalIssueTask(issue_id="ISSUE_LEASE_TERMINATION", issue_title="종료 여부",
                           relevant_fact_ids=["only"], required_statutes=["주택임대차보호법 제6조"])
    sources = [{"source_law": "주택임대차보호법", "title": "주택임대차보호법 제6조",
                "content": "제6조(계약의 갱신) 갱신거절 통지가 없으면 동일 조건으로 갱신된다."}]
    result = verify_issue(issue, "", subset_briefing, sources)
    assert result.status != "VERIFIED"
    assert all("확정적으로 이행기" not in rec for rec in result.safe_recommendations)


def test_subset_answer_preserves_facts_and_unknowns(subset_briefing):
    """기초 분석은 당사자·기간·지급·권리 확인 범위를 보존하고 절차를 강요하지 않는다."""
    answer = assemble_grounded_answer([], subset_briefing, "이미 종료되어 즉시 소송", "CAUTIONARY",
                                     current_question=QUESTION)
    for expected in ["가상임대인", "가상임차인", "2024년 2월 28일", "270,000,000원",
                     "전입신고일", "확정일자", "임차인 진술", "갱신", "원본"]:
        assert expected in answer
    for forbidden in ["이미 종료 확정", "일부 입금/변제 진술", "즉시 임차권등기명령",
                      "연 12%", "기본 요건사실은 충실", "다음 세입자"]:
        assert forbidden not in answer
    for ev in subset_briefing.evidences:
        assert f"{ev.document_name} [" in answer


def test_final_conclusion_keeps_verified_termination_reason(subset_briefing):
    """검증된 해지 근거를 기간 만료라는 다른 종료 사유로 바꾸지 않는다."""
    result = IssueVerificationResult(
        issue_id="ISSUE_LEASE_TERMINATION", issue_title="종료 여부", status="VERIFIED",
        safe_recommendations=["묵시적 갱신 후 해지 통고가 도달하여 법정 효력이 발생하였습니다."],
    )
    answer = assemble_grounded_answer([result], subset_briefing, "", "CAUTIONARY")
    conclusion = answer.split("[2.")[0]
    assert "묵시적 갱신 후 해지" in conclusion
    assert "기간 만료로 이미 종료" not in answer
    assert "다음 세입자" not in answer


def test_no_verified_issues_does_not_create_litigation_advice(subset_briefing):
    """검증 결과가 비어 있어도 자동으로 분쟁 대응 명령을 생성하지 않는다."""
    answer = assemble_grounded_answer([], subset_briefing, "", "CAUTIONARY")
    assert "청구 내용증명을 발송" not in answer
    assert "임차권등기명령을 신청" not in answer
    assert "기본 요건사실은 충실" not in answer


def test_notice_receipt_without_renewal_context_is_not_termination(subset_briefing):
    """도달 자료가 있어도 갱신 경위를 모르면 즉시 종료와 이행기를 확정하지 않는다."""
    subset_briefing.facts.append(FactItemBrief(
        fact_id="notice", statement="2026년 10월 1일 해지 통지가 임대인에게 도달하였다.",
        adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E01",
    ))
    issue = LegalIssueTask(issue_id="ISSUE_NOTICE_REACH", issue_title="통지",
                          relevant_fact_ids=["notice"], required_statutes=["민법 제111조"])
    result = verify_issue(issue, "", subset_briefing, [{
        "source_law": "민법", "title": "민법 제111조", "content": "제111조(의사표시의 효력발생시기) 의사표시는 도달 시 효력이 생긴다.",
    }])
    assert result.status == "CONDITIONAL"
    assert "NOTICE_RENEWAL_STATUS_UNCONFIRMED" in result.reason_codes


@pytest.mark.parametrize("with_issues", [True, False])
def test_finalize_preserves_subset_answer_and_quality_state(subset_briefing, with_issues):
    """워크플로우 최종 노드도 초안 PASS로 미확인을 덮거나 빈 쟁점의 초안을 노출하지 않는다."""
    from ai_legal_helper.workflows.legal_workflow import finalize_node

    results = [IssueVerificationResult(
        issue_id="ISSUE_LEASE_TERMINATION", issue_title="종료", status="CONDITIONAL",
        safe_recommendations=["종료 통지와 갱신 경위 확인 필요"],
    ).model_dump()] if with_issues else []
    state = {
        "question": QUESTION, "resolved_query": "일부 입금/변제 주장",
        "draft_answer": "",
        "case_evidence_briefing": subset_briefing.model_dump(), "retrieved_sources": [],
        "verification_result": {"status": "PASS", "issue_results": results},
        "warnings": [],
    }
    with patch("ai_legal_helper.workflows.final_disposition.build_claim_citations", return_value=[]):
        result = finalize_node(state)
    assert result["final_disposition"] != "DELIVERED"
    assert "가상임대인" in result["final_answer"]
    assert "이미 종료 확정" not in result["final_answer"]
    assert not result["case_delta"]
