# -*- coding: utf-8 -*-
"""
모듈명: test_cross_case_dynamic_grounding.py

[모듈 개요]
사건별 동적 사실관계 컨텍스트 인출(DynamicCaseContext) 및 교차 사건 일반화(Cross-Case Generalization)를
검증하는 단위 테스트 스위트 (P0-4.2 최종 보완).

[배경 및 목적]
기존 코드베이스는 SC-001 사건(가람오피스텔 503호, 보증금 3억 원, 묵시적 갱신, 동진은행·HUG 가압류)에 맞추어
Verifier 및 Planner 내 일부 법률 권고와 안내 문구가 하드코딩되어 있었다.
이로 인해 E2E-LEASE-02 사건(수원 다세대주택 502호, 보증금 2억 2천만 원 중 5천만 원 기변제, 잔액 1억 7천만 원, 가압류 없음)
등 다른 사건을 상담할 때 사실관계 불일치(2억 2천만 원 vs 3억 원)와 부적절한 가압류·경매 분석이 발생하는 결함이 있었다.
본 테스트는 임의의 사건 브리핑이 주어졌을 때 제품 코드가 고정값을 출력하지 않고,
각 사건의 Fact, Evidence, Parties, Timeline에서 동적으로 추출된 정확한 사실과 권리를
정확하게 포섭하여 일관성 있는 법률 판단과 행동 권고를 제공하는지 엄격히 검증한다.

[테스트 케이스 목록]
1. test_dynamic_context_sc001: SC-001 브리핑에서 3억 원, 가람오피스텔, 묵시적 갱신, 가압류(동진은행/HUG) 동적 추출 검증
2. test_dynamic_context_e2e_lease_02: E2E-LEASE-02 브리핑에서 2억 2천만 원, 수원 다세대주택 502호, 잔액 1억 7천만 원, 가압류 부존재 동적 추출 검증
3. test_verifier_no_hardcoding_sc001: SC-001 사건에 대해 Verifier가 3억 원/가람오피스텔/동진은행을 정상 포섭하고 E2E-02 수치가 침범하지 않음을 검증
4. test_verifier_no_hardcoding_e2e_02: E2E-LEASE-02 사건에 대해 Verifier가 2억 2천만 원(또는 잔액 1억 7천만 원)/다세대주택을 정상 포섭하고 3억 원/가람오피스텔/동진은행이 일체 노출되지 않음을 검증
5. test_fake_citation_dynamic_registry: 미등록 증거 번호(예: 99호증) 질의 시 실제 등록된 서류명을 동적으로 인용하고 허위 수치를 생성하지 않음을 검증
6. test_final_disposition_action_tailoring: final_disposition의 단계별 행동 권고가 각 사건의 목적물, 잔액, 담보/가압류 상태에 맞게 동적 분기함을 검증
"""

import pytest
from typing import List

from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing,
    EvidenceItemBrief,
    PartyItemBrief,
    FactItemBrief,
    TimelineItemBrief,
    EvidenceGapBrief,
)
from ai_legal_helper.case_intelligence.dynamic_context import (
    DynamicCaseContext,
    extract_dynamic_case_context,
    format_krw_to_korean,
)
from ai_legal_helper.workflows.issue_planner import (
    plan_legal_issues,
    LegalIssueTask,
)
from ai_legal_helper.agents.issue_verifier import (
    verify_issue,
    verify_all_issues,
)
from ai_legal_helper.workflows.final_disposition import (
    determine_final_disposition,
    assemble_grounded_answer,
)


# ---------------------------------------------------------------------------
# 테스트 픽스처: SC-001 브리핑 (보증금 3억 원, 가람오피스텔 503호, 가압류 2건)
# ---------------------------------------------------------------------------
@pytest.fixture
def briefing_sc001() -> CaseEvidenceBriefing:
    """SC-001 사건의 CaseEvidenceBriefing 픽스처.

    - 보증금: 300,000,000원
    - 목적물: 서울특별시 영등포구 가람오피스텔 503호
    - 임대차기간: 2022-03-01 ~ 2024-02-29 (묵시적 갱신 후 2026-06-30 해지 통고 -> 2026-09-30 효력 발생)
    - 대항요건: 2022-03-02 전입신고 및 점유
    - 확정일자: 2022-03-02 확정일자 부여
    - 가압류: 동진은행 7,200만 원 (2025-05-10), HUG 1억 2,000만 원 (2025-11-20)
    """
    evidences = [
        EvidenceItemBrief(
            evidence_id="ev_sc01_01",
            evidence_label="E01",
            document_name="01_주택임대차계약서.pdf",
            document_type="LEASE_CONTRACT",
        ),
        EvidenceItemBrief(
            evidence_id="ev_sc01_02",
            evidence_label="E02",
            document_name="02_주민등록표등본.pdf",
            document_type="RESIDENT_REGISTRATION",
        ),
        EvidenceItemBrief(
            evidence_id="ev_sc01_03",
            evidence_label="E03",
            document_name="03_부동산등기사항전부증명서.pdf",
            document_type="PROPERTY_REGISTRY",
        ),
    ]

    parties = [
        PartyItemBrief(party_id="pty_sc01_01", name="김임차", role="임차인"),
        PartyItemBrief(party_id="pty_sc01_02", name="박임대", role="임대인"),
        PartyItemBrief(party_id="pty_sc01_03", name="동진은행", role="채권자"),
    ]

    facts = [
        FactItemBrief(
            fact_id="f_sc01_01",
            statement="임대인 박임대와 임차인 김임차는 가람오피스텔 503호에 대해 전세보증금 300,000,000원에 임대차계약을 체결하였다.",
            adjudication_status="EVIDENCE_SUPPORTED",
            evidence_label="E01",
        ),
        FactItemBrief(
            fact_id="f_sc01_02",
            statement="임차인은 2022년 3월 1일 보증금 잔금을 전액 지급하였다.",
            adjudication_status="EVIDENCE_SUPPORTED",
            evidence_label="E01",
        ),
        FactItemBrief(
            fact_id="f_sc01_03",
            statement="묵시적 갱신 중 임차인은 2026년 6월 30일 임대차계약 해지 통고를 하였으며 문자메시지가 같은 날 임대인에게 도달하였다.",
            adjudication_status="EVIDENCE_SUPPORTED",
            evidence_label="E04",
        ),
        FactItemBrief(
            fact_id="f_sc01_04",
            statement="부동산 등기부에 채권자 동진은행의 가압류 72,000,000원 및 채권자 HUG의 가압류 120,000,000원이 등재되어 있다.",
            adjudication_status="EVIDENCE_SUPPORTED",
            evidence_label="E03",
        ),
    ]

    timeline = [
        TimelineItemBrief(event_id="t1", title="임대차계약 시작일", event_date="2022-03-01", event_type="CONTRACT_START"),
        TimelineItemBrief(event_id="t2", title="전입신고 및 확정일자 취득", event_date="2022-03-02", event_type="RESIDENT_REG"),
        TimelineItemBrief(event_id="t3", title="최초 계약 만료 (묵시적 갱신 진행)", event_date="2024-02-29", event_type="CONTRACT_EXPIRE"),
        TimelineItemBrief(event_id="t4", title="해지 통고 도달", event_date="2026-06-30", event_type="TERMINATION_NOTICE"),
        TimelineItemBrief(event_id="t5", title="해지 효력 발생일(통지 도달 3개월 후)", event_date="2026-09-30", event_type="TERMINATION_EFFECTIVE"),
    ]

    return CaseEvidenceBriefing(
        case_id="case_sc_001",
        title="보증금 3억 원 반환 청구 사건 (SC-001)",
        evidences=evidences,
        parties=parties,
        facts=facts,
        timeline=timeline,
        gaps=[],
        source_registry={
            "E01": {"document_name": "01_주택임대차계약서.pdf"},
            "E02": {"document_name": "02_주민등록표등본.pdf"},
            "E03": {"document_name": "03_부동산등기사항전부증명서.pdf"},
        },
    )


# ---------------------------------------------------------------------------
# 테스트 픽스처: E2E-LEASE-02 브리핑 (보증금 2억 2천만 원, 일부반환 5천만 원, 수원 다세대 502호)
# ---------------------------------------------------------------------------
@pytest.fixture
def briefing_e2e_02() -> CaseEvidenceBriefing:
    """E2E-LEASE-02 사건의 CaseEvidenceBriefing 픽스처.

    - 보증금: 220,000,000원
    - 목적물: 경기도 수원시 팔달구 매산로 123, 다세대주택 502호
    - 임대차기간: 2024-09-01 ~ 2026-08-31 (만기 2개월 전 2026-06-15 갱신거절 및 종료통지 -> 2026-08-31 만기 종료)
    - 대항요건: 2024-09-01 전입 및 확정일자
    - 기변제액: 50,000,000원 (2026-09-02 계좌 입금 검증 완료)
    - 잔여 보증금: 170,000,000원
    - 가압류: 없음
    """
    evidences = [
        EvidenceItemBrief(
            evidence_id="ev_e2e_01",
            evidence_label="E01",
            document_name="01_주택임대차계약서_수원.pdf",
            document_type="LEASE_CONTRACT",
        ),
        EvidenceItemBrief(
            evidence_id="ev_e2e_02",
            evidence_label="E02",
            document_name="02_주민등록표등본_확정일자.pdf",
            document_type="RESIDENT_REGISTRATION",
        ),
        EvidenceItemBrief(
            evidence_id="ev_e2e_03",
            evidence_label="E03",
            document_name="03_입금거래내역서_5000만원.pdf",
            document_type="BANK_STATEMENT",
        ),
    ]

    parties = [
        PartyItemBrief(party_id="pty_e2e_01", name="이서윤", role="임차인"),
        PartyItemBrief(party_id="pty_e2e_02", name="최성호", role="임대인"),
    ]

    facts = [
        FactItemBrief(
            fact_id="f_e2e_01",
            statement="임대인 최성호와 임차인 이서윤은 수원 다세대주택 502호에 대해 보증금 220,000,000원에 임대차계약을 체결하였다.",
            adjudication_status="EVIDENCE_SUPPORTED",
            evidence_label="E01",
        ),
        FactItemBrief(
            fact_id="f_e2e_02",
            statement="임차인은 2024년 9월 1일 전세보증금 220,000,000원을 완납하였다.",
            adjudication_status="EVIDENCE_SUPPORTED",
            evidence_label="E01",
        ),
        FactItemBrief(
            fact_id="f_e2e_03",
            statement="임차인은 2026년 6월 15일 만기(2026-08-31)로 계약을 종료하고 퇴거하겠다는 통지를 카카오톡 메시지로 발신하여 임대인에게 도달하였다.",
            adjudication_status="EVIDENCE_SUPPORTED",
            evidence_label="E04",
        ),
        FactItemBrief(
            fact_id="f_e2e_04",
            statement="임대인은 2026년 9월 2일 임차인의 계좌로 보증금 중 50,000,000원을 일부 반환 입금하였다.",
            adjudication_status="EVIDENCE_SUPPORTED",
            evidence_label="E03",
        ),
    ]

    timeline = [
        TimelineItemBrief(event_id="t2_1", title="임대차계약 시작 및 대항력/확정일자 취득", event_date="2024-09-01", event_type="CONTRACT_START"),
        TimelineItemBrief(event_id="t2_2", title="갱신거절 및 만기종료 통지 도달", event_date="2026-06-15", event_type="TERMINATION_NOTICE"),
        TimelineItemBrief(event_id="t2_3", title="임대차계약 만기 도래에 따른 종료", event_date="2026-08-31", event_type="CONTRACT_EXPIRE"),
        TimelineItemBrief(event_id="t2_4", title="임대인의 보증금 일부(5천만 원) 반환", event_date="2026-09-02", event_type="PARTIAL_PAYMENT"),
    ]

    return CaseEvidenceBriefing(
        case_id="case_e2e_lease_02",
        title="보증금 2억 2천만 원 반환 및 일부 변제 사건 (E2E-02)",
        evidences=evidences,
        parties=parties,
        facts=facts,
        timeline=timeline,
        gaps=[],
        source_registry={
            "E01": {"document_name": "01_주택임대차계약서_수원.pdf"},
            "E02": {"document_name": "02_주민등록표등본_확정일자.pdf"},
            "E03": {"document_name": "03_입금거래내역서_5000만원.pdf"},
        },
    )


# ===========================================================================
# 단위 테스트 함수 구현
# ===========================================================================

COMMON_STATUTE_SOURCES = [
    {
        "source_type": "STATUTE",
        "title": "주택임대차보호법",
        "article": "제3조",
        "content": "제3조(대항력 등) 임대차는 그 등기가 없는 경우에도 임차인이 주택의 인도와 주민등록을 마친 때에는 그 다음 날부터 제삼자에 대하여 효력이 생긴다.",
    },
    {
        "source_type": "STATUTE",
        "title": "주택임대차보호법",
        "article": "제3조의2",
        "content": "제3조의2(보증금의 회수) 대항요건과 임대차계약증서상의 확정일자를 갖춘 임차인은 경매 시 후순위권리자나 그 밖의 채권자보다 우선하여 보증금을 변제받을 권리가 있다.",
    },
    {
        "source_type": "STATUTE",
        "title": "주택임대차보호법",
        "article": "제6조의2",
        "content": "제6조의2(묵시적 갱신의 경우 계약의 해지) 임차인은 언제든지 임대인에게 계약해지를 통지할 수 있다. 임대인이 통지를 받은 날부터 3개월이 지나면 효력이 발생한다.",
    },
    {
        "source_type": "STATUTE",
        "title": "민법",
        "article": "제536조",
        "content": "제536조(동시이행의 항변권) 쌍무계약의 당사자 일방은 상대방이 그 채무이행을 제공할 때까지 자기의 채무이행을 거절할 수 있다.",
    },
]


def test_dynamic_context_sc001(briefing_sc001: CaseEvidenceBriefing):
    """SC-001 브리핑에서 보증금 3억 원, 묵시적 갱신, 가압류 2건이 정확하게 동적 추출되는지 검증."""
    ctx = extract_dynamic_case_context(briefing_sc001)

    assert ctx.contract_deposit_krw == 300_000_000
    assert ctx.contract_deposit_text == "3억 원"
    assert ctx.verified_repaid_krw == 0
    assert ctx.unrepaid_balance_krw == 300_000_000
    assert ctx.unrepaid_balance_text == "3억 원"
    assert ctx.is_implicit_renewal is True
    assert ctx.lease_start_date == "2022.03.01"
    assert ctx.lease_end_date == "2024.02.29"
    assert ctx.notice_date == "2026.06.30"
    assert ctx.has_attachment is True
    assert len(ctx.attachment_creditors) >= 2
    assert "동진은행" in ctx.attachment_creditors
    assert "가람오피스텔 503호" in ctx.property_name
    assert ctx.property_type == "오피스텔"


def test_dynamic_context_e2e_lease_02(briefing_e2e_02: CaseEvidenceBriefing):
    """E2E-LEASE-02 브리핑에서 보증금 2억 2천만 원, 일부반환 5천만 원, 잔액 1억 7천만 원이 정확하게 동적 추출되는지 검증."""
    ctx = extract_dynamic_case_context(briefing_e2e_02)

    assert ctx.contract_deposit_krw == 220_000_000
    assert ctx.contract_deposit_text == "2억 2천만 원"
    assert ctx.verified_repaid_krw == 50_000_000
    assert ctx.verified_repaid_text == "5천만 원"
    assert ctx.unrepaid_balance_krw == 170_000_000
    assert ctx.unrepaid_balance_text == "1억 7천만 원"
    assert ctx.is_implicit_renewal is False
    assert ctx.lease_start_date == "2024.09.01"
    assert ctx.lease_end_date == "2026.08.31"
    assert ctx.notice_date == "2026.06.15"
    assert ctx.has_attachment is False
    assert len(ctx.attachment_creditors) == 0
    assert "다세대주택 502호" in ctx.property_name
    assert ctx.property_type == "다세대주택"


def test_verifier_no_hardcoding_sc001(briefing_sc001: CaseEvidenceBriefing):
    """SC-001 사건에서 Verifier 검증 결과가 3억 원 및 해당 사실에 부합하고, 타 사건 수치(2억 2천만 원)가 침범하지 않음을 검증."""
    issues = plan_legal_issues(
        "계약이 만료되었는데 집주인이 전세금을 돌려주지 않습니다. 가압류도 걸려있는데 어떻게 해야 하나요?",
        briefing_sc001,
    )
    assert len(issues) > 0

    results = verify_all_issues(issues, "", briefing_sc001, COMMON_STATUTE_SOURCES)
    combined_rec = " ".join(" ".join(r.safe_recommendations) for r in results)

    # SC-001 고유 사실 포함 검증
    assert "3억 원" in combined_rec
    # E2E-LEASE-02 사실이 침범하지 않아야 함
    assert "2억 2천만 원" not in combined_rec
    assert "1억 7천만 원" not in combined_rec
    assert "이서윤" not in combined_rec
    assert "최성호" not in combined_rec


def test_verifier_no_hardcoding_e2e_02(briefing_e2e_02: CaseEvidenceBriefing):
    """E2E-LEASE-02 사건에서 Verifier 검증 결과가 2억 2천만 원 / 1억 7천만 원 잔액에 부합하고, 3억 원/가람오피스텔이 노출되지 않음을 검증."""
    issues = plan_legal_issues(
        "계약이 만료되었는데 집주인이 5천만 원만 주고 나머지 보증금을 돌려주지 않습니다. 어떤 조치를 해야 하나요?",
        briefing_e2e_02,
    )
    assert len(issues) > 0

    results = verify_all_issues(issues, "", briefing_e2e_02, COMMON_STATUTE_SOURCES)
    combined_rec = " ".join(" ".join(r.safe_recommendations) for r in results)

    # E2E-02 고유 사실 반영 검증 (전체 보증금 2억 2천만 원 또는 미반환 잔액 1억 7천만 원)
    assert ("2억 2천만 원" in combined_rec or "1억 7천만 원" in combined_rec)
    # SC-001 고유 정보(3억 원, 가람오피스텔, 동진은행)가 일체 포함되지 않아야 함
    assert "3억 원" not in combined_rec
    assert "가람오피스텔" not in combined_rec
    assert "동진은행" not in combined_rec


def test_fake_citation_dynamic_registry(briefing_e2e_02: CaseEvidenceBriefing):
    """존재하지 않는 가공의 증거 라벨(증거 99호증) 문의 시 실제 등록된 파일명을 동적으로 인용하고 허위 수치를 생성하지 않음을 검증."""
    q = "증거 99호증에 따르면 임대인이 전액 변제했다고 하는데 사실인가요?"
    issues = plan_legal_issues(q, briefing_e2e_02)

    fake_issues = [i for i in issues if i.issue_id == "ISSUE_FAKE_CITATION"]
    assert len(fake_issues) == 1, "가공 증거 식별 쟁점이 도출되어야 함"

    results = verify_all_issues(fake_issues, "", briefing_e2e_02, COMMON_STATUTE_SOURCES)
    rec_text = " ".join(results[0].safe_recommendations)

    # 실제 등록된 E2E-02 파일명(01_주택임대차계약서_수원.pdf 등)이 언급되어야 함
    assert "01_주택임대차계약서_수원.pdf" in rec_text
    # 증거 99호증 부존재 고지 확인
    assert "E99" in rec_text or "99" in rec_text
    # SC-001 파일명이나 3억 원이 생성되지 않아야 함
    assert "가람오피스텔" not in rec_text
    assert "3억 원" not in rec_text


def test_final_disposition_action_tailoring(
    briefing_sc001: CaseEvidenceBriefing,
    briefing_e2e_02: CaseEvidenceBriefing,
):
    """final_disposition의 단계별 행동 권고가 각 사건의 목적물, 잔액, 담보/가압류 상태에 맞게 동적 분기함을 검증."""
    # 1. SC-001 액션 가이드 검증
    q_sc01 = "가압류가 있어서 경매 배당이 불안합니다."
    issues_sc01 = plan_legal_issues(q_sc01, briefing_sc001)
    results_sc01 = verify_all_issues(issues_sc01, "", briefing_sc001, COMMON_STATUTE_SOURCES)
    ans_sc01 = assemble_grounded_answer(
        issue_results=results_sc01,
        briefing=briefing_sc001,
        draft_answer="",
        disposition="DELIVERED",
        current_question=q_sc01,
    )

    assert "오피스텔" in ans_sc01
    assert "가람오피스텔 503호" in ans_sc01
    assert "가압류" in ans_sc01

    # 2. E2E-02 액션 가이드 검증 (서류 보완 및 잔액 확인)
    q_e2e = "어떤 서류를 준비해야 하나요? 최신 등기사항전부증명서도 발급받아야 하나요?"
    issues_e2e = plan_legal_issues(q_e2e, briefing_e2e_02)
    results_e2e = verify_all_issues(issues_e2e, "", briefing_e2e_02, COMMON_STATUTE_SOURCES)
    ans_e2e = assemble_grounded_answer(
        issue_results=results_e2e,
        briefing=briefing_e2e_02,
        draft_answer="",
        disposition="DELIVERED",
        current_question=q_e2e,
    )

    assert "다세대주택 502호" in ans_e2e
    # SC-001 흔적 부존재 확인
    assert "가람오피스텔" not in ans_e2e
    assert "3억 원" not in ans_e2e
