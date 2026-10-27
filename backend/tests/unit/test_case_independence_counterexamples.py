# -*- coding: utf-8 -*-
"""
모듈명: test_case_independence_counterexamples.py

[테스트 개요]
P0-4.2 최종 개발지시서 v3.0 및 최종 법률 판단 무결성 보완 지시서 v3.1에 따른 37대 반례 테스트 및 사건 독립성 교차 검증.
특정 사건(SC-001)에 고정된 금액, 일자, 채권자, 목적물 및 증거번호 가정을 전면 배제하고,
임의의 사건 데이터에서도 요건사실 검증, 시간·효력 발생일 및 권리순위 판단이 무결하게 동작함을 입증한다.

37대 필수 반례 테스트 목록:
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
14. test_counterexample_14_conflicting_deposit_candidates_not_defaulted_to_max: 보증금 후보 상충 시 최대 금액 자동 선택 제거.
15. test_counterexample_15_repaid_amount_never_redemanded: 이미 반환받은 원금을 재청구하지 않고 미반환 잔액만 청구.
16. test_counterexample_16_notice_receipt_disputed_blocks_verified: 도달 다툼 존재 시 해지 확정 판단 차단.
17. test_counterexample_17_repayment_deduction_in_installment_and_disposition: 분할반환 및 종합 답변에서 기변제액 공제 확인.
18. test_counterexample_18_arbitrary_landlord_name_no_choi_seong_ho: 특정 임대인 성명 하드코딩 배제.
19. test_counterexample_19_fake_citation_does_not_assert_universal_non_repayment: 가공 증거 부재가 전면적 미변제를 단정하지 않음.
20. test_counterexample_20_transfer_only_unconfirmed_opposing: [P0-01] 전입만 확인 시 대항요건 미확정.
21. test_counterexample_21_move_in_only_unconfirmed_opposing: [P0-01] 인도만 확인 시 대항요건 미확정.
22. test_counterexample_22_both_transfer_and_move_in_computes_next_day: [P0-01] 전입+인도 확인 시 익일 0시 효력일 산정.
23. test_counterexample_23_timeline_scheduled_ignored: [P0-02] Timeline SCHEDULED 미반영.
24. test_counterexample_24_timeline_requested_ignored: [P0-02] Timeline REQUESTED 미반영.
25. test_counterexample_25_timeline_actual_with_unverified_fact_ignored: [P0-02] Timeline ACTUAL이나 연결 Fact 미검증 시 미반영.
26. test_counterexample_26_notice_future_effect_date_conditional: [P0-03] 효력 발생일 미래 시 CONDITIONAL.
27. test_counterexample_27_notice_past_effect_date_verified: [P0-03] 효력 발생일 과거 경과 시 VERIFIED.
28. test_counterexample_28_single_fact_multiple_dates_separated: [P0-04] 단일 Fact 내 발송일·도달일 의미론적 분리.
29. test_counterexample_29_reach_date_not_overwritten_by_ack_date: [P0-04] 최초 도달일을 회신일로 덮어쓰지 않음.
30. test_counterexample_30_multiple_notices_dates_isolated: [P0-04] 복수 통지 간 날짜 혼합 방지 및 부정 문맥 처리.
31. test_counterexample_31_genuinely_disputed_fact_blocked: [P0-05] GENUINELY_DISPUTED 사실 배제.
32. test_counterexample_32_disputed_statement_overrides_positive_trust: [P0-05] 상충 사실 존재 시 긍정 Trust 배제.
33. test_counterexample_33_unregistered_registry_avoids_no_attachment: [P0-05] 등기부 미등록 시 부존재 단정 금지(UNCERTAIN).
34. test_counterexample_34_outdated_registry_marked_uncertain: [P0-05] 오래된 등기부(1개월 이상) UNCERTAIN 유지.
35. test_counterexample_35_verified_recent_registry_no_attachment: [P0-05] 최근 등기부 기준일 명시 및 NO_ATTACHMENT.
36. test_counterexample_36_uncertain_opposing_auction_avoids_senior_claim: 대항요건 미확정 경매 질의 시 선순위 단정 차단.
37. test_counterexample_37_conditional_verifier_leads_to_conditional_disposition: Verifier CONDITIONAL 시 최종 답변 조건부 결론 유지.
"""

import pytest
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing,
    PartyItemBrief,
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
    is_fact_strictly_verified,
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



def test_counterexample_14_unverified_notice_reach_blocked():
    """14. 통지 도달이 미검증(PARTY_ALLEGED, DISPUTED)인 경우 해지 효력 확정을 엄격 차단하고 CONDITIONAL 유지."""
    # 14-1. 일방 진술(PARTY_ALLEGED)로 도달 주장
    briefing_alleged = CaseEvidenceBriefing(
        case_id="case_alleged_reach",
        title="통지 도달 미검증 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임차인은 임대인에게 계약해지를 통지하였다고 진술하였다.",
                adjudication_status="PARTY_ALLEGED",
                trust_level="PARTY_ALLEGED",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="임대인은 2026.03.01 해지 통고를 수신하였다고 임차인이 주장한다.",
                adjudication_status="PARTY_ALLEGED",
                trust_level="PARTY_ALLEGED",
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}},
    )
    notice_alleged = evaluate_notice_status(briefing_alleged)
    assert notice_alleged["has_reached"] is False
    assert notice_alleged["reach_date"] is None
    assert notice_alleged["statutory_effect_date"] is None

    # 14-2. 도달 사실에 다툼(DISPUTED) 발생
    briefing_disputed = CaseEvidenceBriefing(
        case_id="case_disputed_reach",
        title="통지 도달 다툼 사건",
        facts=[
            FactItemBrief(
                fact_id="f3",
                statement="임차인은 2026.03.01 해지 통지를 보냈다고 주장한다.",
                adjudication_status="EVIDENCE_SUPPORTED",
            ),
            FactItemBrief(
                fact_id="f4",
                statement="임대인은 해지 통지를 받은 적 없다고 도달 부인하였다.",
                adjudication_status="DISPUTED",
                trust_level="DISPUTED",
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}},
    )
    notice_disputed = evaluate_notice_status(briefing_disputed)
    assert notice_disputed["has_reached"] is False
    assert notice_disputed["statutory_effect_date"] is None

    task = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="계약 해지 검증",
        required_statutes=["주택임대차보호법 제6조"],
        relevant_fact_ids=["f3"],
    )
    res = verify_issue(task, "계약 해지 여부", briefing_disputed, _build_dummy_sources())
    assert res.status == "CONDITIONAL"
    assert "TERMINATION_NOTICE_REACH_UNCONFIRMED" in res.reason_codes


def test_counterexample_15_opposing_power_effective_next_day_zero_hour_ranking():
    """15. 대항력 취득 시점(익일 0시)과 가압류 당일 설정 시 가압류가 선순위(ATTACHMENT_SENIOR) 판정 검증."""
    # 임차인이 2024.05.01 주택을 인도받고 주민등록 전입신고를 마침 (대항요건 구비)
    # 가압류 등기가 2024.05.01 당일 법원에 의해 접수·등기됨
    # -> 주택임대차보호법 제3조 제1항에 따라 대항력은 익일인 2024.05.02 00:00에 발생하므로 당일 설정된 가압류가 선순위임.
    briefing_same_day = CaseEvidenceBriefing(
        case_id="case_same_day_attachment",
        title="전입 당일 가압류 설정 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임차인은 2024년 5월 1일 주택을 인도받고 주민등록 전입신고를 마쳤으며 확정일자를 받았다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2024년 5월 1일 우리은행에 의해 채권최고액 5천만 원의 가압류 등기가 경료되었다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E09",
            ),
        ],
        source_registry={
            "E01": {"document_name": "계약서및전입초본.pdf"},
            "E09": {"document_name": "부동산등기사항전부증명서.pdf"},
        },
    )
    ranking = evaluate_attachment_ranking(briefing_same_day)
    assert ranking["tenant_opposing_date"] == "2024.05.01"
    assert ranking["tenant_opposing_effective_date"] == "2024.05.02"
    assert ranking["priority_status"] == "ATTACHMENT_SENIOR"

    task = LegalIssueTask(
        issue_id="ISSUE_ATTACHMENT_RANKING",
        issue_title="가압류 순위",
        required_statutes=["주택임대차보호법 제3조"],
        relevant_fact_ids=["f1", "f2"],
    )
    res = verify_issue(task, "가압류와 제 순위가 어떻게 되나요?", briefing_same_day, _build_dummy_sources())
    assert res.status == "CONDITIONAL"
    assert "ATTACHMENT_SENIOR_PRIORITY" in res.reason_codes
    assert "가압류가 선순위" in " ".join(res.safe_recommendations)


def test_counterexample_16_conflicting_deposit_candidates_refuse_max():
    """16. 보증금 후보 상충 발생 시 max() 자동 선택을 배제하고 단정 거부(0원 반환) 검증."""
    # 두 개의 검증된 사실에서 서로 다른 보증금 액수(2억 원 vs 3억 원)가 상충할 때
    briefing_conflict = CaseEvidenceBriefing(
        case_id="case_deposit_conflict",
        title="보증금 액수 상충 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차계약서상 보증금은 2억 원으로 기재되어 있다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="수정 합의서상 보증금은 3억 원으로 기재되어 있다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            ),
        ],
        source_registry={
            "E01": {"document_name": "계약서.pdf"},
            "E02": {"document_name": "수정합의서.pdf"},
        },
    )
    # 상충 시 임의로 3억 원을 고르지 않고 불확실성을 표시하기 위해 0원을 반환
    deposit = extract_case_contract_deposit(briefing_conflict)
    assert deposit == 0


def test_counterexample_17_advice_demands_only_unrepaid_balance_no_double_claim():
    """17. 5천만 원 기변제 후 잔액 1.7억 원인 사건에서, 권고안이 기변제금을 다시 청구하지 않고 잔액만 청구함을 검증."""
    briefing_repaid = CaseEvidenceBriefing(
        case_id="case_partial_settlement",
        title="일부 변제 후 잔액 청구 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차계약서상 전세보증금은 2억 2천만 원이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="임대인은 2026.09.10 5천만 원을 임차인 계좌로 반환 송금하였다 (거래번호: TX-9001).",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E07",
            ),
            FactItemBrief(
                fact_id="f3",
                statement="임차인은 2026.03.01 해지 통지를 보냈고 당일 임대인에게 도달하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
            ),
        ],
        source_registry={
            "E01": {"document_name": "임대차계약서.pdf"},
            "E05": {"document_name": "내용증명도달확인서.pdf"},
            "E07": {"document_name": "은행입금영수증.pdf"},
        },
    )
    dep_krw = extract_case_contract_deposit(briefing_repaid)
    repaid_krw, _ = extract_case_prior_verified_repayments(briefing_repaid)
    balance_krw = dep_krw - repaid_krw

    assert dep_krw == 220_000_000
    assert repaid_krw == 50_000_000
    assert balance_krw == 170_000_000

    # 쟁점별 권고 검증: 분할반환 제안 거절 및 일시반환 촉구
    task_prop = LegalIssueTask(
        issue_id="ISSUE_INSTALLMENT_PROPOSAL",
        issue_title="분할반환 제안 거절",
        required_statutes=["민법 제536조"],
        relevant_fact_ids=["f1", "f2"],
    )
    res_prop = verify_issue(task_prop, "임대인이 나눠서 준다는데 어쩌죠?", briefing_repaid, _build_dummy_sources())
    rec_text = " ".join(res_prop.safe_recommendations)

    # 1. 미반환 잔액 1억 7천만 원 청구 포함 확인
    assert "1억 7천만" in rec_text
    # 2. 이미 받은 5천만 원을 포함한 "2억 2천만 원 전액 일시반환"을 요구해서는 안 됨
    assert "2억 2천만 원 전액" not in rec_text
    assert "2억 2천만 원 전액의 일시반환" not in rec_text

    # 종합 답변 조립에서도 미반환 잔액 청구가 정확히 관철되는지 검증
    ans = assemble_grounded_answer(
        issue_results=[res_prop],
        briefing=briefing_repaid,
        draft_answer="초안",
        disposition="DELIVERED",
        current_question="분할반환 거절",
    )
    assert "1억 7천만" in ans
    assert "2억 2천만 원 전액 일시반환" not in ans


def test_counterexample_18_arbitrary_landlord_name_no_choi_seong_ho():
    """18. 임의의 임대인 성명(박영수)이 동적으로 인식되며 '최성호'가 일체 검출되지 않음."""
    briefing_custom_landlord = CaseEvidenceBriefing(
        case_id="case_custom_landlord",
        title="임의 임대인 사건",
        parties=[
            PartyItemBrief(party_id="p1", name="박영수", role="LANDLORD"),
            PartyItemBrief(party_id="p2", name="김민지", role="TENANT"),
        ],
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대인 박영수는 2026.08.01 보증금 3천만 원을 반환하였다 (거래번호: TX-888).",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E07",
            ),
        ],
        source_registry={"E07": {"document_name": "통장사본.pdf"}},
    )
    repaid_krw, sources = extract_case_prior_verified_repayments(briefing_custom_landlord)
    assert repaid_krw == 30_000_000
    assert len(sources) == 1

    # 최성호 이름이 어디에도 혼입되지 않음
    assert "최성호" not in str(briefing_custom_landlord)
    assert "최성호" not in str(sources)


def test_counterexample_19_fake_citation_does_not_assert_universal_non_repayment():
    """19. 가공 증거(99호증) 부재 판단이 다른 모든 변제의 부존재를 단정하지 않고 공적 증거 기준 잔액 청구로 안내함을 검증."""
    briefing_fake = CaseEvidenceBriefing(
        case_id="case_fake_ref",
        title="가공 증거 질문 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차계약서상 전세보증금은 2억 2천만 원이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}},
    )
    task_fake = LegalIssueTask(
        issue_id="ISSUE_FAKE_CITATION",
        issue_title="가공 증거 식별",
        required_statutes=[],
        relevant_fact_ids=["f1"],
    )
    # 유저가 을 제99호증으로 전액 변제되었다고 거짓 질문
    res_fake = verify_issue(task_fake, "을 제99호증에 따르면 전액 변제되었다는데 맞나요?", briefing_fake, _build_dummy_sources())
    rec_text = " ".join(res_fake.safe_recommendations)

    # 1. 99호증이 가공 자료임을 식별
    assert "가공의 자료" in rec_text
    # 2. 가공 증거 부재 확인 자체가 다른 변제의 부존재를 단정하는 것이 아님을 명시
    assert "가공 증거의 부재 확인 자체가 다른 모든 변제 사실의 부존재를 단정하는 것은 아니나" in rec_text
    # 3. 공식 제출·검증된 증거에 기초하여 대처하도록 안내
    assert "실제 공식 제출·검증된" in rec_text


# ==============================================================================
# P0-4.2 최종 법률 판단 무결성 보완 v3.1 신규 반례 테스트 (TC-20 ~ TC-37)
# ==============================================================================

def test_counterexample_20_transfer_only_unconfirmed_opposing():
    """20. [P0-01] 전입신고만 확인되고 주택 인도가 미확인인 경우 대항요건 미확정 처리 및 선순위 배제."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc20",
        title="전입만 확인된 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024.03.01 주민등록 전입신고를 완료하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2024.03.10 등기부상 가압류 5천만 원이 기재되어 있다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E09",
            ),
        ],
        source_registry={"E02": {"document_name": "주민등록초본.pdf"}, "E09": {"document_name": "등기부.pdf"}},
    )
    ranking = evaluate_attachment_ranking(briefing)
    assert ranking["has_transfer"] is True
    assert ranking["has_move_in"] is False
    assert ranking["has_opposing_power"] is False
    assert ranking["tenant_opposing_date"] is None
    assert ranking["priority_status"] != "TENANT_SENIOR"

    task = LegalIssueTask(
        issue_id="ISSUE_ATTACHMENT_RANKING",
        issue_title="가압류 순위",
        required_statutes=["주택임대차보호법 제3조"],
        relevant_fact_ids=["f1", "f2"],
    )
    res = verify_issue(task, "가압류보다 우선인가요?", briefing, _build_dummy_sources())
    assert res.status == "CONDITIONAL"
    assert "MOVE_IN_EVIDENCE_NEEDED" in res.reason_codes
    assert "선순위 우선변제권이 인정됩니다" not in " ".join(res.safe_recommendations)


def test_counterexample_21_move_in_only_unconfirmed_opposing():
    """21. [P0-01] 주택 인도만 확인되고 전입신고가 미확인인 경우 대항요건 미확정 처리."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc21",
        title="인도만 확인된 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024.03.01 주택을 인도받아 점유 및 입주하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2024.03.10 등기부상 가압류 5천만 원이 기재되어 있다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E09",
            ),
        ],
        source_registry={"E03": {"document_name": "확약서.pdf"}, "E09": {"document_name": "등기부.pdf"}},
    )
    ranking = evaluate_attachment_ranking(briefing)
    assert ranking["has_transfer"] is False
    assert ranking["has_move_in"] is True
    assert ranking["has_opposing_power"] is False
    assert ranking["tenant_opposing_date"] is None
    assert ranking["priority_status"] != "TENANT_SENIOR"

    task = LegalIssueTask(
        issue_id="ISSUE_ATTACHMENT_RANKING",
        issue_title="가압류 순위",
        required_statutes=["주택임대차보호법 제3조"],
        relevant_fact_ids=["f1", "f2"],
    )
    res = verify_issue(task, "가압류보다 우선인가요?", briefing, _build_dummy_sources())
    assert res.status == "CONDITIONAL"
    assert "TRANSFER_REGISTRATION_EVIDENCE_NEEDED" in res.reason_codes


def test_counterexample_22_both_transfer_and_move_in_computes_next_day():
    """22. [P0-01] 전입신고(03.01)와 주택인도(03.05)가 모두 확인된 경우 늦은 날 익일 0시(03.06) 대항력 효력일 산정."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc22",
        title="전입과 인도 모두 구비된 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024.03.01 주민등록 전입신고를 마쳤다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2024.03.05 주택을 인도받아 입주하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
            ),
            FactItemBrief(
                fact_id="f3",
                statement="2024.03.01 계약서에 확정일자를 받았다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f4",
                statement="2024.03.15 등기부상 가압류 3천만 원이 기재되어 있다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E09",
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}, "E02": {"document_name": "초본.pdf"}, "E03": {"document_name": "확인서.pdf"}, "E09": {"document_name": "등기부.pdf"}},
    )
    ranking = evaluate_attachment_ranking(briefing)
    assert ranking["has_opposing_power"] is True
    assert ranking["tenant_opposing_date"] == "2024.03.05"
    assert ranking["tenant_opposing_effective_date"] == "2024.03.06"
    assert ranking["tenant_priority_date"] == "2024.03.06"
    assert ranking["priority_status"] == "TENANT_SENIOR"


def test_counterexample_23_timeline_scheduled_ignored():
    """23. [P0-02] Timeline 이벤트가 SCHEDULED(예정) 상태인 경우 확정 날짜로 반영하지 않음."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc23",
        title="타임라인 예정 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차계약을 체결하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
        ],
        timeline=[
            TimelineItemBrief(
                event_id="t1",
                title="전입신고 예정",
                event_date="2024-03-01",
                event_type="ADMIN",
                occurrence_status="SCHEDULED",
                related_fact_ids=["f1"],
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}},
    )
    ranking = evaluate_attachment_ranking(briefing)
    assert ranking["has_transfer"] is False
    assert ranking["tenant_opposing_date"] is None


def test_counterexample_24_timeline_requested_ignored():
    """24. [P0-02] Timeline 이벤트가 REQUESTED(요청) 상태인 경우 확정 날짜로 반영하지 않음."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc24",
        title="타임라인 요청 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차계약을 체결하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
        ],
        timeline=[
            TimelineItemBrief(
                event_id="t1",
                title="주택 인도 요청",
                event_date="2024-03-05",
                event_type="ACTION",
                occurrence_status="REQUESTED",
                related_fact_ids=["f1"],
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}},
    )
    ranking = evaluate_attachment_ranking(briefing)
    assert ranking["has_move_in"] is False
    assert ranking["tenant_opposing_date"] is None


def test_counterexample_25_timeline_actual_with_unverified_fact_ignored():
    """25. [P0-02] Timeline 이벤트가 ACTUAL이라도 연결된 Fact가 미검증(PARTY_ALLEGED)이면 날짜 미반영."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc25",
        title="미검증 Fact 연결 타임라인",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024.03.01 전입신고를 마쳤다고 주장함",
                adjudication_status="PARTY_ALLEGED",
                trust_level="PARTY_ALLEGED",
            ),
        ],
        timeline=[
            TimelineItemBrief(
                event_id="t1",
                title="주민등록 전입",
                event_date="2024-03-01",
                event_type="ADMIN",
                occurrence_status="ACTUAL",
                related_fact_ids=["f1"],
            ),
        ],
    )
    ranking = evaluate_attachment_ranking(briefing)
    assert ranking["has_transfer"] is False
    assert ranking["tenant_opposing_date"] is None


def test_counterexample_26_notice_future_effect_date_conditional():
    """26. [P0-03] 통지 도달은 확인되었으나 3개월 경과 효력 발생일이 상담 기준일보다 미래인 경우 CONDITIONAL."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc26",
        title="해지 효력일 미래 사건",
        as_of_date="2026.04.10",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="계약은 묵시적으로 갱신되었다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2026.04.01 임차인이 해지통고를 보냈고 2026.04.03 임대인에게 도달하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}, "E05": {"document_name": "통고.pdf"}},
    )
    notice = evaluate_notice_status(briefing)
    assert notice["reach_date"] == "2026.04.03"
    assert notice["statutory_effect_date"] == "2026.07.03"
    assert notice["is_effect_date_future"] is True
    assert notice["is_effect_date_reached"] is False

    task = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="임대차계약 종료",
        required_statutes=["주택임대차보호법 제6조의2"],
        relevant_fact_ids=["f1", "f2"],
    )
    res = verify_issue(task, "계약 종료되었나요?", briefing, _build_dummy_sources())
    assert res.status == "CONDITIONAL"
    assert "TERMINATION_EFFECT_DATE_FUTURE" in res.reason_codes
    rec_text = " ".join(res.safe_recommendations)
    assert "2026.07.03에 해지 효력이 발생할 예정" in rec_text
    assert "이미 도과" not in rec_text
    assert "확정적으로 이행기에 도달" not in rec_text


def test_counterexample_27_notice_past_effect_date_verified():
    """27. [P0-03] 통지 도달 후 3개월 경과 효력 발생일이 상담 기준일 이전인 경우 VERIFIED."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc27",
        title="해지 효력일 과거 사건",
        as_of_date="2026.08.01",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="계약은 묵시적으로 갱신되었다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2026.04.01 임차인이 해지통고를 보냈고 2026.04.03 임대인에게 도달하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}, "E05": {"document_name": "통고.pdf"}},
    )
    notice = evaluate_notice_status(briefing)
    assert notice["reach_date"] == "2026.04.03"
    assert notice["statutory_effect_date"] == "2026.07.03"
    assert notice["is_effect_date_future"] is False
    assert notice["is_effect_date_reached"] is True

    task = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="임대차계약 종료",
        required_statutes=["주택임대차보호법 제6조의2"],
        relevant_fact_ids=["f1", "f2"],
    )
    res = verify_issue(task, "계약 종료되었나요?", briefing, _build_dummy_sources())
    assert res.status == "VERIFIED"
    assert "TERMINATION_FACTS_AND_LAW_SUPPORTED" in res.reason_codes


def test_counterexample_28_single_fact_multiple_dates_separated():
    """28. [P0-04] 하나의 Fact에 발송일(04.01)과 도달일(04.03)이 모두 존재할 때 의미론적으로 정확히 분리."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc28",
        title="발송과 도달 동시 서술",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2026.04.01 임차인이 해지통고를 발송했고 2026.04.03 임대인에게 도달하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
            ),
        ],
        source_registry={"E05": {"document_name": "도달보고.pdf"}},
    )
    notice = evaluate_notice_status(briefing)
    assert notice["sent_date"] == "2026.04.01"
    assert notice["reach_date"] == "2026.04.03"


def test_counterexample_29_reach_date_not_overwritten_by_ack_date():
    """29. [P0-04] 최초 도달일(04.03)과 임대인 회신일(04.05)이 다를 때 회신일로 도달일을 덮어쓰지 않음."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc29",
        title="도달일과 회신일 상이 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2026.04.03 내용증명이 임대인에게 도달하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2026.04.05 임대인이 보증금 반환 제안을 하며 회신 답변을 보냈다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E06",
            ),
        ],
        source_registry={"E05": {"document_name": "배달증명.pdf"}, "E06": {"document_name": "답변서.pdf"}},
    )
    notice = evaluate_notice_status(briefing)
    assert notice["reach_date"] == "2026.04.03"
    assert notice["landlord_ack_date"] == "2026.04.05"
    assert notice["has_landlord_acknowledgement"] is True


def test_counterexample_30_multiple_notices_dates_isolated():
    """30. [P0-04] 복수 해지통고가 존재하는 경우 통지별 날짜가 혼합되지 않고 가장 빠른 적법 도달일 추적."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc30",
        title="복수 통지 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="1차로 2026.02.01 문자메시지로 해지통고를 발송하였으나 수신 확인이 되지 않았다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E04",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2차로 2026.03.01 내용증명을 발송하여 2026.03.04 임대인에게 적법하게 도달하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
            ),
        ],
        source_registry={"E04": {"document_name": "문자캡처.pdf"}, "E05": {"document_name": "내용증명.pdf"}},
    )
    notice = evaluate_notice_status(briefing)
    assert notice["sent_date"] == "2026.02.01"
    assert notice["reach_date"] == "2026.03.04"


def test_counterexample_31_genuinely_disputed_fact_blocked():
    """31. [P0-05] adjudication_status가 GENUINELY_DISPUTED인 사실은 엄격 검증에서 배제."""
    fact = FactItemBrief(
        fact_id="f_disp",
        statement="임대인은 2026.04.05 보증금 5천만 원을 반환하였다고 주장함",
        adjudication_status="GENUINELY_DISPUTED",
        trust_level="EVIDENCE_SUPPORTED",
    )
    assert is_fact_strictly_verified(fact) is False


def test_counterexample_32_disputed_statement_overrides_positive_trust():
    """32. [P0-05] briefing.genuinely_disputed에 등재된 사실은 trust_level이 EVIDENCE_SUPPORTED여도 False 반환."""
    from ai_legal_helper.case_intelligence.case_briefing import DisputedConflictBrief
    fact = FactItemBrief(
        fact_id="f_claim",
        statement="임대인이 2026.05.01 통고를 수령하였다.",
        adjudication_status="CORROBORATED",
        trust_level="EVIDENCE_SUPPORTED",
    )
    briefing = CaseEvidenceBriefing(
        case_id="case_tc32",
        title="상충 사실 사건",
        facts=[fact],
        genuinely_disputed=[
            DisputedConflictBrief(
                fact_id="f_claim",
                statement="임대인이 2026.05.01 통고를 수령하였다.",
                opposing_statement="임대인은 2026.05.01 해외 체류 중으로 수령한 바 없다고 진술함",
                reason="도달 여부 상충",
            )
        ],
    )
    assert is_fact_strictly_verified(fact, briefing) is False


def test_counterexample_33_unregistered_registry_avoids_no_attachment():
    """33. [P0-05] 등기사항증명서가 미등록된 경우 가압류 부존재(NO_ATTACHMENT) 단정 금지 및 UNCERTAIN 유지."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc33",
        title="등기부 미등록 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차계약 체결 및 보증금 지급 완료",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}},
    )
    ranking = evaluate_attachment_ranking(briefing)
    assert ranking["has_attachment"] is False
    assert ranking["priority_status"] == "UNCERTAIN"
    assert "등기사항증명서 미제출" in ranking["summary_text"]


def test_counterexample_34_outdated_registry_marked_uncertain():
    """34. [P0-05] 등기부 열람일자가 상담 기준일 대비 1개월 이상 오래된 경우 UNCERTAIN 및 최신 등기부 확인 권고."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc34",
        title="오래된 등기부 사건",
        as_of_date="2026.05.01",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2026.02.01 열람한 등기사항증명서상 제한물권 없음",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E09",
                document_name="E09_등기사항증명서_20260201.pdf",
            ),
        ],
        source_registry={"E09": {"document_name": "등기부.pdf"}},
    )
    ranking = evaluate_attachment_ranking(briefing)
    assert ranking["priority_status"] == "UNCERTAIN"
    assert "1개월 이상 경과" in ranking["summary_text"]


def test_counterexample_35_verified_recent_registry_no_attachment():
    """35. [P0-05] 최근 등기부(1개월 이내) 확인 시 가압류 부존재(NO_ATTACHMENT) 인정 및 열람일 기준 명시."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc35",
        title="최근 등기부 사건",
        as_of_date="2026.05.01",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2026.04.25 발급받은 부동산 등기사항증명서상 제한물권 없음",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E09",
            ),
        ],
        source_registry={"E09": {"document_name": "등기사항전부증명서.pdf"}},
    )
    ranking = evaluate_attachment_ranking(briefing)
    assert ranking["priority_status"] == "NO_ATTACHMENT"
    assert "2026.04.25 열람 기준" in ranking["summary_text"] or "제한물권 없음" in ranking["summary_text"]


def test_counterexample_36_uncertain_opposing_auction_avoids_senior_claim():
    """36. 대항요건 미확정 상태에서 경매 관련 질의 시 선순위 대항력 행사를 단정하지 않고 배당신고 중심 안내."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc36",
        title="대항요건 미확정 경매 질문",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024.03.01 전입신고 완료",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            ),
            # 주택 인도 미확인 상태
            FactItemBrief(
                fact_id="f2",
                statement="2024.03.10 가압류 5천만 원 등재",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E09",
            ),
        ],
        source_registry={"E02": {"document_name": "초본.pdf"}, "E09": {"document_name": "등기부.pdf"}},
    )
    task = LegalIssueTask(
        issue_id="ISSUE_AUCTION_STRATEGY",
        issue_title="경매 대항력 선택",
        required_statutes=["주택임대차보호법 제3조", "민사집행법 제88조"],
        relevant_fact_ids=["f1", "f2"],
    )
    res = verify_issue(task, "경매 시 낙찰자에게 집을 안 비워줘도 되나요?", briefing, _build_dummy_sources())
    rec_text = " ".join(res.safe_recommendations)
    assert "선순위 대항력이 인정되지 않는 경우 매수인(낙찰자)에게 대항할 수 없으므로" in rec_text
    assert "선순위 대항력을 근거로 낙찰자에게 전액 반환받을 때까지 주택 인도를 거절할 수 있습니다" not in rec_text


def test_counterexample_37_conditional_verifier_leads_to_conditional_disposition():
    """37. Verifier가 CONDITIONAL인 경우 Final Disposition 종합 답변에서도 확정 단정을 배제하고 조건부 결론 유지."""
    briefing = CaseEvidenceBriefing(
        case_id="case_tc37",
        title="조건부 결론 종합 답변",
        as_of_date="2026.04.10",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차계약 체결",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2026.04.01 통고 발송 후 2026.04.03 도달 (묵시적으로 갱신됨)",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
            ),
        ],
        source_registry={"E01": {"document_name": "계약서.pdf"}, "E05": {"document_name": "통고.pdf"}},
    )
    task = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="임대차계약 종료",
        required_statutes=["주택임대차보호법 제6조의2"],
        relevant_fact_ids=["f1", "f2"],
    )
    v_res = verify_issue(task, "언제 종료되나요?", briefing, _build_dummy_sources())
    assert v_res.status == "CONDITIONAL"

    ans = assemble_grounded_answer(
        issue_results=[v_res],
        briefing=briefing,
        draft_answer="초안",
        disposition="CONDITIONAL",
        current_question="언제 종료되나요?",
    )
    assert "[3. 조건부 판단 및 미확인 사항]" in ans
    assert "2026.07.03에 해지 효력이 발생할 예정" in ans
    assert "현재 시점에서는 아직 효력이 발생하지 않았음" in ans or "현재 상담 기준 시점" in ans

