# -*- coding: utf-8 -*-
"""4단계 법률요건 포섭 회귀 테스트: 법률별 결론 하드코딩 없는 출처 연결 검사."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import pytest

from ai_legal_helper.agents.subsumption_audit import audit_legal_applications
from ai_legal_helper.rag.grounding_context import (
    format_grounding_sources, prune_sources_for_consultation,
)


SC012_EFFECT = "공동상속인 각각에 대해 보증금 반환 청구의 가능 범위를 검토할 수 있습니다."
SC013_EFFECT = "낙찰자에게 대항 가능한지 여부는 근저당과 전입신고 효력 발생 시점에 따라 다릅니다."
LABOR_EFFECT = "임금 지급일과 퇴직 사실을 확인해 체불 여부를 판단할 수 있습니다."


@pytest.fixture
def sources():
    return [
        {"source_id": "STATUTE:CIVIL", "source_type": "STATUTE", "statute_name": "민법",
         "article": "제411조", "content": "제411조(불가분채무) 여러 사람이 불가분채무를 부담하는 경우에 관한 규정"},
        {"source_id": "E03_상속관계.txt", "source_type": "CASE_EVIDENCE",
         "content": "임대인이 사망했고 자녀 세 명이 공동상속인입니다."},
        {"source_id": "PRECEDENT:001", "source_type": "PRECEDENT",
         "case_number": "2023다318857", "court": "대법원", "decision_date": "2024-08-01",
         "content": "[판시사항] 공동임대인의 임대차 보증금 반환채무의 성질\n[판결요지] 다른 사실관계에 따라 적용 구별이 필요하다.",
         "retrieval_method": "OFFICIAL_PRECEDENT_SEARCH"},
    ]


def make_claim(effect=SC012_EFFECT, law="STATUTE:CIVIL"):
    return SimpleNamespace(claim=effect, claim_type="LEGAL_APPLICATION",
                           grounding_status="SUPPORTED",
                           source_ids=[law, "E03_상속관계.txt"])


def make_check(effect=SC012_EFFECT, law="STATUTE:CIVIL"):
    return {
        "claim": effect, "legal_effect": "보증금 반환 청구의 대외적 범위",
        "rule_source_ids": [law],
        "requirements": [{
            "requirement": "임대인의 사망과 공동상속인 승계 여부",
            "status": "MET",
            "fact_source_ids": ["E03_상속관계.txt"],
            "fact_quote": "임대인이 사망했고 자녀 세 명이 공동상속인입니다.",
            "reason": "사건 원문에 상속인과 임대인의 사망이 기재됨",
        }],
        "exception_analysis": "다른 채무 성질의 예외가 적용되는지 확인해야 한다.",
        "precedent_analyses": [],
        "conclusion_status": "SUPPORTED",
        "condition_in_answer": "",
    }


def audit(claims, checks, sources, *, question="증거를 기준으로 반환채무 책임을 검토해 주세요.", answer=SC012_EFFECT):
    return audit_legal_applications(
        claims=claims, application_checks=checks,
        retrieved_sources=sources, question=question, answer=answer,
    )


def test_grounded_statute_and_case_facts_pass_structure_only(sources):
    a = audit([make_claim()], [make_check()], sources)
    assert a["status"] == "PASS" and a["passed_claims"] == 1
    assert a["failed_claims"] == 0
    # 주의: 구조 감사 PASS가 법률적으로 각자 전액 책임이라는 결론을 증명하지는 않는다.


def test_missing_check_fails_closed_even_when_claim_has_official_source(sources):
    a = audit([make_claim()], [], sources)
    assert "MISSING_OR_AMBIGUOUS_APPLICATION_CHECK" in a["findings"][0]["reason_codes"]


def test_duplicate_checks_not_accepted_as_evidence(sources):
    c = make_check()
    a = audit([make_claim()], [c, deepcopy(c)], sources)
    assert a["failed_claims"] == 1


def test_plain_statute_explanation_uses_existing_policy(sources):
    claim = SimpleNamespace(claim="민법의 불가분채무 규정에 관한 설명", claim_type="LEGAL_RULE",
                            grounding_status="SUPPORTED", source_ids=["STATUTE:CIVIL"])
    a = audit([claim], [], sources, answer=claim.claim)
    assert a["status"] == "PASS" and a["audited_claims"] == 0


def test_case_fact_not_promoted_to_legal_effect(sources):
    claim = SimpleNamespace(claim="임대인이 사망했습니다.", claim_type="CASE_FACT",
                            grounding_status="SUPPORTED", source_ids=["E03_상속관계.txt"])
    assert audit([claim], [], sources, answer=claim.claim)["audited_claims"] == 0


def test_evidence_document_cannot_replace_rule_source(sources):
    c = make_check(law="E03_상속관계.txt")
    claim = make_claim(law="E03_상속관계.txt")
    a = audit([claim], [c], sources)
    assert "RULE_SOURCE_NOT_RETRIEVED" in a["findings"][0]["reason_codes"]


def test_unknown_statute_id_cannot_be_accepted(sources):
    c = make_check(law="STATUTE:FAKE")
    a = audit([make_claim(law="STATUTE:FAKE")], [c], sources)
    assert "RULE_SOURCE_NOT_RETRIEVED" in a["findings"][0]["reason_codes"]


def test_rule_link_must_also_be_attached_to_claim(sources):
    c = make_check()
    claim = make_claim()
    claim.source_ids = ["E03_상속관계.txt"]
    a = audit([claim], [c], sources)
    assert "CLAIM_RULE_SOURCE_DISCONNECTED" in a["findings"][0]["reason_codes"]


def test_unverified_fact_premise_fails(sources):
    c = make_check()
    c["requirements"][0]["fact_source_ids"] = ["NOT_EXISTS"]
    c["requirements"][0]["fact_quote"] = "누군가 확인하지 않은 전입 날짜"
    a = audit([make_claim()], [c], sources)
    assert "FACT_PREMISE_UNGROUNDED" in a["findings"][0]["reason_codes"]


def test_current_user_statement_is_valid_factual_basis(sources):
    c = make_check()
    c["requirements"][0]["fact_source_ids"] = []
    c["requirements"][0]["fact_quote"] = "임대인이 사망했고 자녀 세 명이 공동상속인입니다."
    a = audit([make_claim()], [c], sources,
              question="임대인이 사망했고 자녀 세 명이 공동상속인입니다. 반환채무는 누구에게 청구할 수 있나요?")
    assert a["status"] == "PASS"


def test_unknown_requirement_cannot_support_categorical_legal_effect(sources):
    c = make_check()
    c["requirements"][0].update(status="UNKNOWN", fact_source_ids=[], fact_quote="",
                                reason="기초 사실이 추가 확인되지 않았다.")
    a = audit([make_claim()], [c], sources)
    assert "UNKNOWN_REQUIREMENT_WITH_CATEGORICAL_CONCLUSION" in a["findings"][0]["reason_codes"]


def test_known_unknown_can_form_conditional_conclusion_if_condition_written(sources):
    effect = "임대인 지위가 승계되었다면 법률상 반환의무가 인정될 수 있습니다."
    c = make_check(effect)
    c["requirements"][0].update(status="UNKNOWN", fact_source_ids=[], fact_quote="", reason="승계 사실 미확인")
    c.update(conclusion_status="CONDITIONAL", condition_in_answer="임대인 지위가 승계되었다면")
    a = audit([make_claim(effect)], [c], sources, answer=effect)
    assert a["status"] == "PASS" and a["passed_claims"] == 1


def test_conditional_conclusion_hidden_from_user_not_accepted(sources):
    c = make_check()
    c["requirements"][0].update(status="UNKNOWN", fact_source_ids=[], fact_quote="", reason="미확인")
    c["conclusion_status"] = "CONDITIONAL"
    c["condition_in_answer"] = "질문과 답변에 없는 임대인 지위 승계 요건"
    a = audit([make_claim()], [c], sources)
    assert "UNSTATED_CONDITION_IN_ANSWER" in a["findings"][0]["reason_codes"]


def test_not_met_requirement_supports_negative_effect_when_grounded(sources):
    """부정적 법률 결론에서는 불충족 자체가 근거일 수 있으므로 regex로 정답 결정 금지."""
    effect = "임대인의 서명이 없었다는 사실은 아직 확인되지 않았습니다."
    c = make_check(effect)
    c["requirements"][0]["status"] = "NOT_MET"
    a = audit([make_claim(effect)], [c], sources, answer=effect)
    assert a["status"] == "PASS"


def test_missing_exception_review_fails_structure(sources):
    c = make_check()
    c["exception_analysis"] = ""
    a = audit([make_claim()], [c], sources)
    assert "EXCEPTION_REVIEW_MISSING" in a["findings"][0]["reason_codes"]


def test_precedent_requires_real_holding_quote_and_comparison(sources):
    c = make_check(law="PRECEDENT:001")
    a = audit([make_claim(law="PRECEDENT:001")], [c], sources)
    assert "PRECEDENT_COMPARISON_MISSING" in a["findings"][0]["reason_codes"]


def precedent_comparison(status="SIMILAR"):
    return {
        "source_id": "PRECEDENT:001",
        "holding_quote": "공동임대인의 임대차 보증금 반환채무의 성질",
        "material_similarities": "임대차보증금 반환채무가 문제된다는 점",
        "material_differences": "현재는 임대인의 사망 후 상속인 승계 여부가 추가로 문제됨",
        "applicability": status,
        "reason": "당사자 법적 지위 차이가 결론에 영향을 미칠 수 있음",
    }


def test_matching_precedent_with_material_difference_review_is_structurally_valid(sources):
    c = make_check(law="PRECEDENT:001")
    c["precedent_analyses"] = [precedent_comparison()]
    a = audit([make_claim(law="PRECEDENT:001")], [c], sources)
    assert a["status"] == "PASS"


def test_fabricated_precedent_holding_is_rejected(sources):
    c = make_check(law="PRECEDENT:001")
    p = precedent_comparison()
    p["holding_quote"] = "실제 판결문에 나오지 않은 판시사항"
    c["precedent_analyses"] = [p]
    a = audit([make_claim(law="PRECEDENT:001")], [c], sources)
    assert "PRECEDENT_HOLDING_NOT_IN_SOURCE" in a["findings"][0]["reason_codes"]


def test_distinguished_precedent_alone_cannot_prove_categorical_claim(sources):
    c = make_check(law="PRECEDENT:001")
    c["precedent_analyses"] = [precedent_comparison("DISTINGUISHABLE")]
    a = audit([make_claim(law="PRECEDENT:001")], [c], sources)
    assert "DISTINGUISHED_PRECEDENT_ONLY_SUPPORT" in a["findings"][0]["reason_codes"]


def test_court_and_decision_date_reach_grounding_prompt(sources):
    prompt, _ = format_grounding_sources(sources)
    assert '"case_number": "2023다318857"' in prompt
    assert '"court": "대법원"' in prompt
    assert '"decision_date": "2024-08-01"' in prompt


def test_precedent_remains_full_in_rewrite_context(sources):
    long_source = {**sources[-1], "content": "중요한 판시사항과 반대사실 " * 50}
    pruned = prune_sources_for_consultation([long_source], draft_answer="임대인의 의무",
                                            verification={"claims": []})
    assert len(pruned) == 1
    assert pruned[0]["content"] == long_source["content"]


def test_other_legal_domain_wages_uses_same_proof_contract(sources):
    law = {"source_id": "STATUTE:LABOR", "source_type": "STATUTE",
           "content": "퇴직시 지급금품의 지급기한 등에 관한 근로기준법 조문"}
    fact = {"source_id": "E11_근로계약서.txt", "source_type": "CASE_EVIDENCE",
            "content": "근로기간은 2025년 3월부터 2026년 2월까지이다."}
    c = make_check(LABOR_EFFECT, "STATUTE:LABOR")
    c["requirements"][0] = {
        "requirement": "근로관계 종료와 금품 지급 여부",
        "status": "MET", "fact_source_ids": ["E11_근로계약서.txt"],
        "fact_quote": "근로기간은 2025년 3월부터 2026년 2월까지이다.",
        "reason": "근로기간은 문서에서 확인됨",
    }
    assert audit([make_claim(LABOR_EFFECT, "STATUTE:LABOR")], [c],
                 [law, fact], answer=LABOR_EFFECT)["status"] == "PASS"


def test_semantic_auction_timeline_unknown_does_not_become_senior_tenant(sources):
    """SC-013 근저당/전입 선후를 날짜 키워드로 하드코딩하지 않고 불명 시 조건으로 남긴다."""
    c = make_check(SC013_EFFECT)
    c["requirements"][0].update(
        requirement="최선순위 담보권 등기일과 임차인 대항요건 효력일의 선후",
        status="UNKNOWN", fact_source_ids=[], fact_quote="", reason="대항요건 일자 공식 증거 미확인",
    )
    c["conclusion_status"] = "CONDITIONAL"
    c["condition_in_answer"] = "근저당과 전입신고 효력 발생 시점에 따라"
    assert audit([make_claim(SC013_EFFECT)], [c], sources, answer=SC013_EFFECT)["status"] == "PASS"


def test_verifier_integration_blocks_pass_when_application_check_missing(sources):
    """출처 ID가 맞고 모델이 PASS라 해도 핵심 포섭 누락이면 REVISE."""
    import json
    from unittest.mock import MagicMock, patch
    from ai_legal_helper.agents.verification import run_verification

    reply = {
        "status": "PASS", "reason_code": "NONE", "recommended_action": "FINALIZE",
        "claims": [{
            "claim": SC012_EFFECT, "claim_type": "LEGAL_APPLICATION",
            "fact_status": "VERIFIED_FACT",
            "source_ids": ["STATUTE:CIVIL", "E03_상속관계.txt"],
            "grounding_status": "SUPPORTED", "reason": "법령 및 사건 자료 확인",
        }],
        "application_checks": [],
        "question_coverage": [{"question": "법률 책임 범위", "answered": True, "reason": "답변함"}],
        "consistency_checks": {
            name: {"passed": True, "reason": "근거 대조", "source_ids": ["E03_상속관계.txt"]}
            for name in ("opening_conclusion", "timeline", "expressed_intent", "provenance")
        },
    }
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(reply, ensure_ascii=False)
    qa = MagicMock(status="PASS", requires_llm_eval=True, legal_risk_passed=True,
                   citation_audit={}, preserved_points=[], repair_targets=[])
    qa.model_dump.return_value = {"status": "PASS"}
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm), \
         patch("ai_legal_helper.agents.qa_checker.check_deterministic_qa", return_value=qa):
        result = run_verification("상속인에게 반환채무 청구가 가능한가요?", SC012_EFFECT,
                                  sources, case_context="사건이 등록됨", require_question_coverage=True)
    assert llm.invoke.call_count == 1
    assert result["application_audit"]["failed_claims"] == 1
    assert result["status"] != "PASS"
    assert result["claims"][0]["grounding_status"] == "UNSUPPORTED"


def test_verifier_integration_accepts_supported_check_without_extra_llm(sources):
    """요건포섭을 추가한 기존 1회 검증 응답을 정상 처리(추가 노드/호출 없음)."""
    import json
    from unittest.mock import MagicMock, patch
    from ai_legal_helper.agents.verification import run_verification

    reply = {
        "status": "PASS", "reason_code": "NONE", "recommended_action": "FINALIZE",
        "claims": [{
            "claim": SC012_EFFECT, "claim_type": "LEGAL_APPLICATION",
            "fact_status": "VERIFIED_FACT", "source_ids": ["STATUTE:CIVIL", "E03_상속관계.txt"],
            "grounding_status": "SUPPORTED", "reason": "법령 및 사건 자료 확인",
        }],
        "application_checks": [make_check()],
        "question_coverage": [{"question": "법률 책임 범위", "answered": True, "reason": "답변함"}],
        "consistency_checks": {
            name: {"passed": True, "reason": "근거 대조", "source_ids": ["E03_상속관계.txt"]}
            for name in ("opening_conclusion", "timeline", "expressed_intent", "provenance")
        },
    }
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(reply, ensure_ascii=False)
    qa = MagicMock(status="PASS", requires_llm_eval=True, legal_risk_passed=True,
                   citation_audit={}, preserved_points=[], repair_targets=[])
    qa.model_dump.return_value = {"status": "PASS"}
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm), \
         patch("ai_legal_helper.agents.qa_checker.check_deterministic_qa", return_value=qa):
        result = run_verification("상속인에게 반환채무 청구가 가능한가요?", SC012_EFFECT,
                                  sources, case_context="사건이 등록됨", require_question_coverage=True)
    assert llm.invoke.call_count == 1
    assert result["application_audit"]["passed_claims"] == 1
    assert result["application_audit"]["failed_claims"] == 0
    # PASS 여부는 포섭 체인 존재 외에 다른 인용·시행일·질문 충족 검사가 함께 결정.
    assert result["status"] != "INSUFFICIENT"


def test_document_verification_prompt_renders_all_subsumption_json_examples():
    """PromptTemplate JSON 예시의 중괄호가 새로운 필수 변수로 해석되면 검증기가 중단된다."""
    from langchain_core.prompts import PromptTemplate
    from ai_legal_helper.agents.document_verification_prompt import DOCUMENT_VERIFICATION_PROMPT
    prompt = PromptTemplate.from_template(DOCUMENT_VERIFICATION_PROMPT)
    assert set(prompt.input_variables) == {"question", "draft_answer", "retrieved_sources", "case_context"}
    rendered = prompt.format(
        question="법률 질문", draft_answer="법률 효과 결론",
        retrieved_sources="법령 원문", case_context="사건 증거",
    )
    assert "application_checks" in rendered
    assert '{"requirement"' in rendered


def test_semantic_issue_with_fact_and_statute_is_not_auto_verified():
    """새 범용 Issue가 출처 1+1만으로 법률요건 포섭 VERIFIED가 되지 않는다."""
    from ai_legal_helper.agents.issue_verifier import verify_issue
    from ai_legal_helper.workflows.issue_planner import LegalIssueTask
    from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing, FactItemBrief
    task = LegalIssueTask(
        issue_id="ISSUE_SEMANTIC_01",
        issue_title="공동상속인의 반환의무 법적 성질",
        legal_questions=["공동상속인의 반환채무 대외적 책임 범위는?"],
        relevant_fact_ids=["f1"],
        required_statutes=["민법 제411조"],
    )
    case = CaseEvidenceBriefing(
        case_id="generic-fact-and-law", title="사건",
        facts=[FactItemBrief(
            fact_id="f1", statement="임대인이 사망했다",
            adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E03",
        )],
        source_registry={"E03": {"file": "E03_상속관계.txt"}},
    )
    sources = [{
        "source_id": "OFFICIAL:CIVIL:411", "source_type": "STATUTE",
        "title": "민법 제411조", "statute_name": "민법", "article": "제411조",
        "content": "민법 제411조 불가분채무의 법률 요건이 규정되어 있다.",
    }]
    result = verify_issue(task, SC012_EFFECT, case, sources)
    assert result.status == "CONDITIONAL"
    assert "GENERAL_SOURCES_PRESENT_SUBSUMPTION_UNCHECKED" in result.reason_codes
    assert "민법 제411조" in result.supported_statute_ids
