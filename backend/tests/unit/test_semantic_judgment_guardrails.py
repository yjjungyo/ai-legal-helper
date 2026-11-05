"""Grounded semantic boundary regressions; no network or real LLM required."""
import json
from unittest.mock import patch

from ai_legal_helper.case_intelligence.semantic_judgment import (
    SemanticDecision, classify_statement,
)
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing, FactItemBrief,
)
from ai_legal_helper.case_intelligence.settlement_calculator import (
    extract_case_contract_deposit, extract_case_prior_verified_repayments,
)
from ai_legal_helper.tools.statute_temporal import article_effective_date, extract_addenda
from ai_legal_helper.legal_knowledge.article_effective_interpreter import interpret_article_dates
import xml.etree.ElementTree as ET


def test_exact_quote_and_allowed_label():
    sentence = "임대인이 2천만 원을 입금한 사실은 은행거래내역으로 확인되었다."
    result = classify_statement(
        sentence,
        task="REPAYMENT",
        labels=("ACTUAL_REPAYMENT", "PROPOSAL_OR_PLAN"),
        invoke_fn=lambda _: json.dumps({
            "label": "ACTUAL_REPAYMENT",
            "evidence_quote": "2천만 원을 입금한 사실",
            "source_quote": "",
            "explanation": "거래 내역",
        }),
    )
    assert result.label == "ACTUAL_REPAYMENT"


def test_fabricated_quote_cannot_promote_claim():
    result = classify_statement(
        "반환을 검토 중이라고 말했다.",
        task="REPAYMENT",
        labels=("ACTUAL_REPAYMENT",),
        invoke_fn=lambda _: {
            "label": "ACTUAL_REPAYMENT",
            "evidence_quote": "실제로 반환하였다",
        },
    )
    assert result.label == "UNKNOWN"
    assert result.status == "REVIEW_UNAVAILABLE"


def test_source_quote_must_come_from_registered_source():
    result = classify_statement(
        "보증금을 지급하였다.",
        task="REPAYMENT", labels=("ACTUAL_REPAYMENT",),
        source_text="은행에서 지급 취소 처리하였습니다.",
        invoke_fn=lambda _: {
            "label": "ACTUAL_REPAYMENT",
            "evidence_quote": "보증금을 지급하였다",
            "source_quote": "은행 이체 완료",
        },
    )
    assert result.label == "UNKNOWN"


def _evidence_fact(statement: str, fid: str) -> FactItemBrief:
    return FactItemBrief(
        fact_id=fid, statement=statement,
        adjudication_status="EVIDENCE_SUPPORTED",
        evidence_label=f"E{fid}", document_name=f"거래_{fid}.pdf",
    )


def test_proposal_and_actual_refund_are_never_same_transaction():
    briefing = CaseEvidenceBriefing(
        case_id="synthetic", title="계약 반환",
        facts=[
            _evidence_fact("임대인은 보증금 3억 원을 계약 원금으로 약정했다.", "01"),
            _evidence_fact("임대인은 보증금 2천만 원을 나누어 돌려주자고 제안했다.", "02"),
            _evidence_fact("임대인은 보증금 500만 원을 실제 이체해 반환했다.", "03"),
        ],
    )
    def stub(text, *, task, **kwargs):
        if task == "CONTRACT_DEPOSIT_PRINCIPAL_CLASSIFICATION":
            return (
                SemanticDecision("CONTRACT_PRINCIPAL", "보증금 3억 원")
                if "계약 원금" in text else SemanticDecision("UNRELATED", text)
            )
        if task == "ACTUAL_DEPOSIT_REFUND_TRANSACTION":
            return (
                SemanticDecision("ACTUAL_REPAYMENT", "500만 원을 실제 이체해 반환했다")
                if "실제 이체" in text else SemanticDecision("PROPOSAL_OR_PLAN", text)
            )
        return SemanticDecision("UNKNOWN", "", status="UNCONFIRMED")
    with patch("ai_legal_helper.case_intelligence.semantic_judgment.classify_statement", side_effect=stub):
        assert extract_case_contract_deposit(briefing) == 300_000_000
        total, sources = extract_case_prior_verified_repayments(briefing)
    assert total == 5_000_000
    assert any("거래_03.pdf" in src for src in sources)


def test_no_llm_does_not_infer_money_from_keywords():
    briefing = CaseEvidenceBriefing(
        case_id="unknown", title="증거 미해석",
        facts=[_evidence_fact("보증금 3억 원은 나중에 반환하겠다고 했다.", "01")],
    )
    with patch(
        "ai_legal_helper.case_intelligence.semantic_judgment.classify_statement",
        return_value=SemanticDecision("UNKNOWN", "", status="UNCONFIRMED"),
    ):
        assert extract_case_contract_deposit(briefing) == 0
        assert extract_case_prior_verified_repayments(briefing)[0] == 0


def test_article_date_extraction_handles_actual_korean_date_regex():
    official = "제1조(시행일) 이 영은 2027년 4월 28일부터 시행한다."
    result = interpret_article_dates(
        article_ids=["제36조"], official_addenda=[official],
        promulgation_date="2026-10-27",
        llm_invoke=lambda _: json.dumps([{
            "article_id": "제36조",
            "effective_from": "2027-04-28",
            "basis": "GENERAL_EFFECTIVE_DATE",
            "evidence_quote": "2027년 4월 28일부터 시행한다",
        }]),
    )
    assert result[0].effective_from == "2027-04-28"
    assert result[0].status == "SOURCE_GROUNDED_CANDIDATE"


def test_bulk_index_does_not_interpret_unreviewed_addenda():
    root = ET.fromstring(
        "<법령><조문단위><조문번호>36</조문번호></조문단위>"
        "<부칙단위><부칙공포번호>36796</부칙공포번호>"
        "<부칙공포일자>20261027</부칙공포일자>"
        "<부칙내용>제1조(시행일) 공포 후 6개월이 경과한 날부터 시행한다</부칙내용>"
        "</부칙단위></법령>"
    )
    addenda = extract_addenda(root, "36796")
    result, status = article_effective_date(
        root.find(".//조문단위"), "제36조", addenda,
    )
    assert result is None
    assert status == "UNCONFIRMED"
