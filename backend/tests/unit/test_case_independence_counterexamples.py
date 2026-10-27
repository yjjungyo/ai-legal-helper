# -*- coding: utf-8 -*-
"""
모듈명: test_case_independence_counterexamples.py

[테스트 개요]
P0-4.2 최종 개발지시서 v3.0 (Section 12.3)에 따른 필수 12대 반례 테스트 및 사건 독립성 교차 검증.
특정 사건(SC-001)에 고정된 금액, 일자, 채권자, 목적물 및 증거번호 가정을 전면 배제하고,
임의의 사건 데이터(E2E-LEASE-02 등)에서도 법률 판단과 행동 권고가 온전히 일반화되어 동작함을 입증한다.

12대 필수 반례 테스트:
1. test_counterexample_01_non_sc001_deposit_isolation: 3억 원 외 다른 금액(2억 2천만 원) 사건에서 3억 원이 절대 출력되지 않음.
2. test_counterexample_02_lease_period_isolation: SC-001 기간(2022.03.01~2024.02.29)이 타 사건에 혼입되지 않음.
3. test_counterexample_03_sent_only_notice_unconfirmed: 통지 발송만 있고 도달 입증이 없는 경우 해지 효력 확정을 유보하고 CONDITIONAL 부여.
4. test_counterexample_04_distinguish_expiry_from_implicit_renewal: 기간 만료(제6조)와 묵시적 갱신 중 해지(제6조의2)를 구별하여 포섭.
5. test_counterexample_05_uncertain_priority_avoids_senior_claim: 날짜 결여 시 '선순위 우선변제권 인정'을 단정하지 않고 CONDITIONAL 처리.
6. test_counterexample_06_e03_bank_statement_by_doc_type: E03 라벨이 통장거래내역서인 경우 전입신고로 오인하지 않고 정상 식별.
7. test_counterexample_07_fake_citation_denied_without_hallucination: 99호증 등 가공 증거 지적 시 허위 사실을 생성하지 않고 부인.
8. test_counterexample_08_evidence_order_independence: 증거 등록 순서가 달라도 동일한 법률 판단 및 계산 결과 산출.
9. test_counterexample_09_two_distinct_returns_same_date_amount: 동일 일자·동액 분할 반환이라도 식별자가 다르면 각각 정산.
10. test_counterexample_10_duplicate_repayment_not_double_counted: 동일 거래 중복 사본은 이중 합산하지 않음.
11. test_counterexample_11_case_delta_and_disposition_balance_match: Case Delta 잔액과 Final Disposition 잔액이 단일 원천으로 100% 일치.
12. test_counterexample_12_unverified_facts_conditional: 증거는 등록되었으나 Fact가 미검증(EVIDENCE_INCOMPLETE)이면 VERIFIED를 주지 않음.
13. test_counterexample_13_cross_case_sc001_vs_e2e_lease_02: SC-001(3억 원, 오피스텔)과 E2E-LEASE-02(2억 2천만 원, 아파트) 간 교차 독립성 검증.
"""

import pytest
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing,
    FactItemBrief,
    EvidenceItemBrief,
    TimelineItemBrief,
)
from ai_legal_helper.case_intelligence.settlement_calculator import (
    extract_case_contract_deposit,
    extract_case_prior_verified_repayments,
    format_krw_to_korean,
    calculate_three_months_expiry,
    evaluate_notice_status,
    evaluate_attachment_ranking,
    find_case_property_info,
    find_evidence_labels_by_type,
)
from ai_legal_helper.workflows.issue_planner import LegalIssueTask, plan_legal_issues
from ai_legal_helper.agents.issue_verifier import verify_issue, IssueVerificationResult
from ai_legal_helper.workflows.final_disposition import (
    detect_case_delta,
    assemble_grounded_answer,
    determine_final_disposition,
)


def _build_dummy_sources():
    """테스트용 기본 법령 출처 목록을 생성한다."""
    return [
        {
            "source_type": "STATUTE",
            "source_law": "주택임대차보호법",
            "title": "주택임대차보호법 제3조",
            "citation": "주택임대차보호법 제3조",
            "content": "제3조(대항력 등) ① 임대차는 그 등기가 없는 경우에도 임차인이 주택의 인도와 주민등록을 마친 때에는 그 다음 날부터 제삼자에 대하여 효력이 생긴다.",
        },
        {
            "source_type": "STATUTE",
            "source_law": "주택임대차보호법",
            "title": "주택임대차보호법 제3조의2",
            "citation": "주택임대차보호법 제3조의2",
            "content": "제3조의2(보증금의 회수) ② 제3조제1항의 대항요건과 임대차계약증서상의 확정일자를 갖춘 임차인은 민사집행법에 따른 경매 시 환가대금에서 후순위권리자나 그 밖의 채권자보다 우선하여 보증금을 변제받을 권리가 있다.",
        },
        {
            "source_type": "STATUTE",
            "source_law": "주택임대차보호법",
            "title": "주택임대차보호법 제6조의2",
            "citation": "주택임대차보호법 제6조의2",
            "content": "제6조의2(묵시적 갱신의 경우 계약의 해지) ① 제6조제1항에 따라 계약이 갱신된 경우 임차인은 언제든지 임대인에게 계약해지를 통지할 수 있다. ② 제1항에 따른 해지는 임대인이 그 통지를 받은 날부터 3개월이 지나면 그 효력이 발생한다.",
        },
        {
            "source_type": "STATUTE",
            "source_law": "민법",
            "title": "민법 제536조",
            "citation": "민법 제536조",
            "content": "제536조(동시이행의 항변권) ① 쌍무계약의 당사자 일방은 상대방이 그 채무이행을 제공할 때까지 자기의 채무이행을 거절할 수 있다.",
        },
        {
            "source_type": "STATUTE",
            "source_law": "민법",
            "title": "민법 제111조",
            "citation": "민법 제111조",
            "content": "제111조(의사표시의 효력발생시기) ① 상대방이 있는 의사표시는 상대방에게 도달한 때에 그 효력이 생긴다.",
        },
    ]


def test_counterexample_01_non_sc001_deposit_isolation():
    """1. SC-001 외 다른 보증금(2억 2천만 원) 사건에서 3억 원이 절대 출력되지 않음."""
    briefing = CaseEvidenceBriefing(
        case_id="case_non_sc001",
        title="신도림 현대아파트 임대차 상담",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임차인 이서윤은 임대인 최성호와 신도림 현대아파트 102동 405호에 대해 보증금 2억 2천만 원(220,000,000원)에 임대차계약을 체결하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
        ],
        source_registry={"E01": {"document_name": "E01_아파트_임대차계약서.pdf"}},
    )

    deposit = extract_case_contract_deposit(briefing)
    assert deposit == 220_000_000
    assert "3억" not in format_krw_to_korean(deposit)
    assert "2억 2천만" in format_krw_to_korean(deposit)

    # Verifier 실행 시 3억 원이 추천에 혼입되지 않는지 검증
    task = LegalIssueTask(
        issue_id="ISSUE_NO_WAIT_DUTY",
        issue_title="새 임차인 유치 대기의무 부존재",
        required_statutes=["민법 제536조"],
        relevant_fact_ids=["f1"],
    )
    res = verify_issue(task, "임대인이 새 세입자 올 때까지 기다리라고 합니다.", briefing, _build_dummy_sources())
    combined_rec = " ".join(res.safe_recommendations)
    assert "3억" not in combined_rec
    assert "2억 2천만" in combined_rec


def test_counterexample_02_lease_period_isolation():
    """2. 다른 사건의 임대차 기간(2023.05.01~2025.04.30) 상담에서 SC-001 기간(2022.03.01~2024.02.29)이 혼입되지 않음."""
    briefing = CaseEvidenceBriefing(
        case_id="case_custom_period",
        title="마포 다세대주택 임대차",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차 기간은 2023.05.01부터 2025.04.30까지로 약정하고 보증금 1억 5천만 원을 지급하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="임차인은 2025.01.10 만기 해지 통고를 발송하였고 2025.01.12 임대인에게 도달하여 확인되었다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
            ),
        ],
        source_registry={
            "E01": {"document_name": "E01_임대차계약서.pdf"},
            "E05": {"document_name": "E05_해지통고_내용증명.pdf"},
        },
    )

    task = LegalIssueTask(
        issue_id="ISSUE_PROOF_OF_CONTENTS",
        issue_title="내용증명 우편 작성",
        required_statutes=["주택임대차보호법 제6조의2", "민법 제111조"],
        relevant_fact_ids=["f1", "f2"],
    )
    res = verify_issue(task, "내용증명에 어떤 내용을 써야 하나요?", briefing, _build_dummy_sources())
    combined_rec = " ".join(res.safe_recommendations)
    assert "2022.03.01" not in combined_rec
    assert "2024.02.29" not in combined_rec
    assert "3억" not in combined_rec


def test_counterexample_03_sent_only_notice_unconfirmed():
    """3. 해지 통고 발송 사실만 있고 도달 입증이 없는 경우 해지 효력 확정을 유보하고 CONDITIONAL 부여."""
    briefing = CaseEvidenceBriefing(
        case_id="case_sent_only",
        title="통지 발송만 된 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차 기간 만기 후 별도 거절 통지가 없어 묵시적으로 갱신되었다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="임차인은 2026.04.01 임대인에게 계약해지를 통지하는 문자메시지를 발신하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
            ),
        ],
        source_registry={
            "E01": {"document_name": "E01_계약서.pdf"},
            "E05": {"document_name": "E05_문자발신캡처.png"},
        },
    )

    notice_info = evaluate_notice_status(briefing)
    assert notice_info["has_sent"] is True
    assert notice_info["has_reached"] is False
    assert notice_info["statutory_effect_date"] is None

    task = LegalIssueTask(
        issue_id="ISSUE_NOTICE_REACH",
        issue_title="문자메시지에 의한 해지의사표시 도달 및 효력",
        required_statutes=["주택임대차보호법 제6조의2", "민법 제111조"],
        relevant_fact_ids=["f1", "f2"],
    )
    res = verify_issue(task, "문자 보냈는데 언제 해지되나요?", briefing, _build_dummy_sources())
    assert res.status == "CONDITIONAL"
    assert "NOTICE_REACH_UNCONFIRMED" in res.reason_codes
    assert "도달 입증" in " ".join(res.safe_recommendations)


def test_counterexample_04_distinguish_expiry_from_implicit_renewal():
    """4. 당초 계약 만기 만료(제6조)와 묵시적 갱신 중 해지(제6조의2 3개월)를 정확히 구별."""
    # 4-1. 당초 계약 기간 만료 사건
    briefing_expiry = CaseEvidenceBriefing(
        case_id="case_expiry",
        title="만기 만료 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024년 2월 28일 임대차계약 기간 만료 및 해지 통고 완료",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
        ],
        source_registry={"E01": {"document_name": "E01_계약서.pdf"}, "E05": {"document_name": "E05_통고.pdf"}},
    )
    notice_expiry = evaluate_notice_status(briefing_expiry)
    assert notice_expiry["is_implicit_renewal"] is False

    task_expiry = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="임대차계약 종료",
        required_statutes=["주택임대차보호법 제6조"],
        relevant_fact_ids=["f1"],
    )
    res_expiry = verify_issue(task_expiry, "계약 만료되었습니다.", briefing_expiry, [
        {"source_type": "STATUTE", "source_law": "주택임대차보호법", "title": "주택임대차보호법 제6조", "content": "제6조 계약의 갱신"}
    ])
    assert res_expiry.status == "VERIFIED"
    assert "TERMINATION_FACTS_AND_LAW_SUPPORTED" in res_expiry.reason_codes

    # 4-2. 묵시적 갱신 중 해지 사건 (도달일로부터 3개월 역산)
    briefing_renewal = CaseEvidenceBriefing(
        case_id="case_renewal",
        title="묵시적 갱신 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="계약은 만기 후 묵시적으로 갱신되었다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="임차인이 2026.01.31 해지 통고 문자를 발송하였고 당일 도달하여 임대인이 수신 확인하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
            ),
        ],
        source_registry={"E01": {"document_name": "E01_계약서.pdf"}, "E05": {"document_name": "E05_도달확인.pdf"}},
    )
    notice_renewal = evaluate_notice_status(briefing_renewal)
    assert notice_renewal["is_implicit_renewal"] is True
    assert notice_renewal["has_reached"] is True
    # 1월 31일 도달 시 3개월 후는 4월 30일 (월말 달력 연산)
    assert notice_renewal["statutory_effect_date"] == "2026.04.30"


def test_counterexample_05_uncertain_priority_avoids_senior_claim():
    """5. 등기일자 결여로 권리순위가 불명확한 경우 '선순위 우선변제권 인정'을 확정하지 않고 CONDITIONAL 처리."""
    briefing = CaseEvidenceBriefing(
        case_id="case_uncertain_ranking",
        title="가압류 일자 미확인 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임차인은 전입신고 및 주택 인도를 마쳤다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="등기부상 가압류 5천만 원이 기재되어 있으나 설정 일자는 확인되지 않는다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E09",
            ),
        ],
        source_registry={"E03": {"document_name": "E03_주민등록초본.pdf"}, "E09": {"document_name": "E09_등기부.pdf"}},
    )

    ranking = evaluate_attachment_ranking(briefing)
    assert ranking["priority_status"] == "UNCERTAIN"

    task = LegalIssueTask(
        issue_id="ISSUE_ATTACHMENT_RANKING",
        issue_title="가압류 순위",
        required_statutes=["주택임대차보호법 제3조", "주택임대차보호법 제3조의2"],
        relevant_fact_ids=["f1", "f2"],
    )
    res = verify_issue(task, "가압류보다 제가 우선인가요?", briefing, _build_dummy_sources())
    assert res.status == "CONDITIONAL"
    assert "PRIORITY_UNCERTAIN_NEEDS_REGISTRY" in res.reason_codes
    combined_rec = " ".join(res.safe_recommendations)
    assert "선순위 우선변제권이 인정됩니다" not in combined_rec
    assert "단정할 수 없으며" in combined_rec


def test_counterexample_06_e03_bank_statement_by_doc_type():
    """6. E03 증거가 주민등록초본이 아니라 은행거래내역서인 경우, 번호에 의존하지 않고 doc_type에 맞춰 처리."""
    briefing = CaseEvidenceBriefing(
        case_id="case_e03_bank",
        title="E03이 은행거래내역서인 사건",
        evidences=[
            EvidenceItemBrief(
                evidence_id="ev_01",
                evidence_label="E01",
                document_name="임대차계약서.pdf",
                document_type="LEASE_CONTRACT",
            ),
            EvidenceItemBrief(
                evidence_id="ev_02",
                evidence_label="E02",
                document_name="주민등록초본.pdf",
                document_type="RESIDENCE_PROOF",
            ),
            EvidenceItemBrief(
                evidence_id="ev_03",
                evidence_label="E03",
                document_name="신한은행_거래내역서.pdf",
                document_type="PAYMENT_STATEMENT",
            ),
        ],
        source_registry={
            "E01": {"document_name": "임대차계약서.pdf"},
            "E02": {"document_name": "주민등록초본.pdf"},
            "E03": {"document_name": "신한은행_거래내역서.pdf"},
        },
    )

    residence_labels = find_evidence_labels_by_type(briefing, ["RESIDENCE", "주민등록", "초본"])
    payment_labels = find_evidence_labels_by_type(briefing, ["PAYMENT", "BANK", "거래내역"])

    assert "E02" in residence_labels
    assert "E03" not in residence_labels
    assert "E03" in payment_labels


def test_counterexample_07_fake_citation_denied_without_hallucination():
    """7. 질문에서 99호증 등 가공 증거를 지적할 때 허구 사실을 생성하지 않고 부인."""
    briefing = CaseEvidenceBriefing(
        case_id="case_fake_test",
        title="가공 증거 질의 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="보증금 1억 원 임대차계약을 체결하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            )
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}},
    )

    task = LegalIssueTask(
        issue_id="ISSUE_FAKE_CITATION",
        issue_title="가공의 증거 라벨 식별",
        required_statutes=[],
        relevant_fact_ids=["f1"],
    )
    res = verify_issue(task, "임대인이 증거 99호증으로 보증금 다 갚았다고 하는데요?", briefing, _build_dummy_sources())
    assert res.status == "VERIFIED"
    assert "FAKE_CITATION_DENIED_AND_RESOLVED" in res.reason_codes
    combined_rec = " ".join(res.safe_recommendations)
    assert "가공의 자료" in combined_rec
    assert "3억" not in combined_rec


def test_counterexample_08_evidence_order_independence():
    """8. 증거 등록 순서가 역순이라도 동일한 보증금 추출 및 권리 분석 결과 산출."""
    briefing_asc = CaseEvidenceBriefing(
        case_id="case_asc",
        title="오름차순 등록 사건",
        facts=[
            FactItemBrief(fact_id="f1", statement="보증금 2억 원에 계약 체결", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E01"),
            FactItemBrief(fact_id="f2", statement="보증금 중 5천만 원 반환 입금 확인 [TX-101]", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E02"),
        ],
        source_registry={"E01": {}, "E02": {}},
    )
    briefing_desc = CaseEvidenceBriefing(
        case_id="case_desc",
        title="내림차순 등록 사건",
        facts=[
            FactItemBrief(fact_id="f2", statement="보증금 중 5천만 원 반환 입금 확인 [TX-101]", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E02"),
            FactItemBrief(fact_id="f1", statement="보증금 2억 원에 계약 체결", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E01"),
        ],
        source_registry={"E02": {}, "E01": {}},
    )

    dep_asc = extract_case_contract_deposit(briefing_asc)
    dep_desc = extract_case_contract_deposit(briefing_desc)
    assert dep_asc == dep_desc == 200_000_000

    rep_asc, _ = extract_case_prior_verified_repayments(briefing_asc)
    rep_desc, _ = extract_case_prior_verified_repayments(briefing_desc)
    assert rep_asc == rep_desc == 50_000_000


def test_counterexample_09_two_distinct_returns_same_date_amount():
    """9. 동일 일자·동액 분할 반환이라도 식별자(TX-ID)가 다르면 둘 다 정산 (P0-3.1 및 v3.0)."""
    briefing = CaseEvidenceBriefing(
        case_id="case_two_tx",
        title="동일 일자 복수 거래 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2026.05.10 임대인이 보증금 중 3천만 원을 1차 변제하여 입금 확인 (거래번호: TX-9001)",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2026.05.10 임대인이 보증금 중 3천만 원을 2차 변제하여 입금 확인 (거래번호: TX-9002)",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
            ),
        ],
        source_registry={"E02": {}, "E03": {}},
    )

    total_rep, sources = extract_case_prior_verified_repayments(briefing)
    assert total_rep == 60_000_000
    assert len(sources) == 2


def test_counterexample_10_duplicate_repayment_not_double_counted():
    """10. 동일 거래의 중복 업로드(동일 TX-ID 또는 동일 영수증 사본)는 이중 집계하지 않음."""
    briefing = CaseEvidenceBriefing(
        case_id="case_dup_tx",
        title="중복 영수증 업로드 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2026.05.10 임대인이 보증금 중 3천만 원을 변제 입금 (거래번호: TX-9001)",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2026.05.10 임대인이 보증금 중 3천만 원을 변제 입금 (거래번호: TX-9001) 재발급 사본",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
            ),
        ],
        source_registry={"E02": {}, "E03": {}},
    )

    total_rep, sources = extract_case_prior_verified_repayments(briefing)
    assert total_rep == 30_000_000
    assert len(sources) == 1


def test_counterexample_11_case_delta_and_disposition_balance_match():
    """11. Case Delta의 미반환 잔액과 Final Disposition의 잔액이 단일 원천으로 100% 동일."""
    briefing = CaseEvidenceBriefing(
        case_id="case_balance_sync",
        title="잔액 동기화 검증 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차계약 체결 보증금 2억 5천만 원",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="임대인이 보증금 중 5천만 원을 일부 변제하여 입금 확인 (거래번호: TX-777)",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}, "E02": {"document_name": "이체확인증.pdf"}},
    )

    delta = detect_case_delta(briefing, current_question="얼마 돌려받아야 하나요?")
    assert delta is not None

    deposit = extract_case_contract_deposit(briefing)
    repaid, _ = extract_case_prior_verified_repayments(briefing)
    expected_balance = deposit - repaid
    assert expected_balance == 200_000_000

    # Case Delta 문안에 정확히 200,000,000원 반영
    assert any("200,000,000원" in s for s in delta["impacted_determinations"])

    # Final Answer 생성 시 동일 잔액(2억 원) 반영
    issue_task = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="보증금 반환의무",
        required_statutes=["주택임대차보호법 제6조"],
        relevant_fact_ids=["f1"],
    )
    v_res = verify_issue(issue_task, "보증금 잔액 청구", briefing, [
        {"source_type": "STATUTE", "source_law": "주택임대차보호법", "title": "주택임대차보호법 제6조", "content": "제6조 계약의 갱신"}
    ])
    final_ans = assemble_grounded_answer(
        issue_results=[v_res],
        briefing=briefing,
        draft_answer="보증금 반환 청구",
        disposition="CAUTIONARY",
        current_question="얼마 돌려받아야 하나요?",
        case_delta=delta,
    )
    assert "2억 원" in final_ans
    assert "3억" not in final_ans


def test_counterexample_12_unverified_facts_conditional():
    """12. 증거는 등록되었으나 Fact 상태가 EVIDENCE_INCOMPLETE인 경우 VERIFIED를 주지 않음."""
    briefing = CaseEvidenceBriefing(
        case_id="case_unverified_fact",
        title="미검증 Fact 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="보증금 1억 8천만 원 계약 체결 사실",
                adjudication_status="EVIDENCE_INCOMPLETE",
                evidence_label="E01",
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}},
    )

    task = LegalIssueTask(
        issue_id="ISSUE_INSTALLMENT_PROPOSAL",
        issue_title="분할반환 제안 대응",
        required_statutes=["민법 제536조"],
        relevant_fact_ids=["f1"],
    )
    res = verify_issue(task, "분할반환 제안 거절할 수 있나요?", briefing, _build_dummy_sources())
    assert res.status != "VERIFIED"
    assert res.status in ("CONDITIONAL", "NEEDS_EVIDENCE")


def test_counterexample_13_cross_case_sc001_vs_e2e_lease_02():
    """13. SC-001(3억 원, 오피스텔)과 E2E-LEASE-02(2억 2천만 원, 아파트) 간 교차 독립성 검증."""
    # 사건 A: SC-001
    briefing_a = CaseEvidenceBriefing(
        case_id="SC-001",
        title="가람오피스텔 503호 상담",
        facts=[
            FactItemBrief(
                fact_id="fa_1",
                statement="가람오피스텔 503호에 대해 전세보증금 3억 원에 임대차계약을 체결하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
        ],
        source_registry={"E01": {"document_name": "E01_가람오피스텔_계약서.pdf"}},
    )

    # 사건 B: E2E-LEASE-02
    briefing_b = CaseEvidenceBriefing(
        case_id="E2E-LEASE-02",
        title="신도림 현대아파트 102동 405호 상담",
        facts=[
            FactItemBrief(
                fact_id="fb_1",
                statement="신도림 현대아파트 102동 405호에 대해 전세보증금 2억 2천만 원에 임대차계약을 체결하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
        ],
        source_registry={"E01": {"document_name": "E01_현대아파트_계약서.pdf"}},
    )

    # 각각의 목적물 및 금액 추출 검증
    prop_a, type_a = find_case_property_info(briefing_a)
    dep_a = extract_case_contract_deposit(briefing_a)
    assert prop_a == "가람오피스텔 503호"
    assert type_a == "오피스텔"
    assert dep_a == 300_000_000

    prop_b, type_b = find_case_property_info(briefing_b)
    dep_b = extract_case_contract_deposit(briefing_b)
    assert "신도림 현대아파트" in prop_b
    assert type_b == "아파트"
    assert dep_b == 220_000_000

    # 각각의 다음 행동 가이드 조립 검증
    task_a = LegalIssueTask(issue_id="ISSUE_EVIDENCE_GAPS", issue_title="서류 발급", required_statutes=[], relevant_fact_ids=["fa_1"])
    task_b = LegalIssueTask(issue_id="ISSUE_EVIDENCE_GAPS", issue_title="서류 발급", required_statutes=[], relevant_fact_ids=["fb_1"])

    res_a = verify_issue(task_a, "서류 확인", briefing_a, _build_dummy_sources())
    res_b = verify_issue(task_b, "서류 확인", briefing_b, _build_dummy_sources())

    ans_a = assemble_grounded_answer(
        issue_results=[res_a],
        briefing=briefing_a,
        draft_answer="서류 확인 초안",
        disposition="CAUTIONARY",
        current_question="서류 확인",
    )
    ans_b = assemble_grounded_answer(
        issue_results=[res_b],
        briefing=briefing_b,
        draft_answer="서류 확인 초안",
        disposition="CAUTIONARY",
        current_question="서류 확인",
    )

    # 사건 A에는 가람오피스텔이 들어가고, 사건 B에는 현대아파트가 들어가며 상호 혼입이 없음
    assert "가람오피스텔 503호" in ans_a
    assert "현대아파트" not in ans_a

    assert "신도림 현대아파트" in ans_b
    assert "가람오피스텔" not in ans_b
    assert "3억" not in ans_b

