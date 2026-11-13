# -*- coding: utf-8 -*-
"""
테스트 모듈: test_stage4_multi_case_regression.py

[테스트 개요]
SC-013 근본 원인 수정 4단계: 다수 케이스 법률 포섭 회귀 테스트 (Multi-case Legal Subsumption Regression).

[검증 케이스]
1. 후순위 임차인(선순위 근저당권 후 대항력 취득) 사건:
   - 쟁점 계획의 중립성 및 분리 검토
   - 민사집행법 제91조, 제88조 및 주택임대차보호법 조문 로컬 RAG 확보
   - 경매 소멸주의(민사집행법 제91조 제3항) 포섭 및 낙찰자 대항 결론 차단
2. 선순위 임차인(선순위 근저당권 전 대항력 취득) 사건:
   - 선순위 대항력에 따른 낙찰자 대항 및 보증금 인수(주택임대차보호법 제3조의5 단서) 정당성 보존
3. 날짜·사실관계 누락 사건:
   - 근저당권 설정일 또는 대항요건 구비일이 결여된 경우 증거 공백 식별 및 조건부 안내
4. 법령 검색 장애/누락 처리 안전성:
   - 외부 API 점검/오류 상황에서도 로컬 인덱스 폴백 및 비정상 크래시 없는 안전한 처리
5. 일반 임대차 분쟁 회귀 테스트:
   - 경매가 없는 일반 보증금 반환/계약 해지 상담에서 경매 쟁점이 오탐되지 않고 기존 로직 100% 유지
"""

import pytest
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing,
    FactItemBrief,
    EvidenceItemBrief,
    EvidenceGapBrief,
)
from ai_legal_helper.workflows.issue_planner import plan_legal_issues
from ai_legal_helper.workflows.document_search import _retrieve_from_local_index
from ai_legal_helper.agents.qa_checker import check_deterministic_qa


def test_case1_subordinate_tenant_auction_subsumption():
    """Case 1: 후순위 임차인(근저당권 2021.03.10 vs 대항력 2023.05.20) 경매 매각 포섭 검증."""
    question = (
        "선순위 근저당권(2021.03.10 설정)이 있는 상태에서 제가 2023.05.20에 전입신고와 확정일자를 받았습니다. "
        "경매가 진행되면 보증금 1억 5천만 원 중 일부를 못 받게 되면 어떻게 회수해야 하나요?"
    )
    briefing = CaseEvidenceBriefing(
        case_id="case_subordinate_01",
        title="선순위 근저당권 후순위 임차인 경매 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2021년 3월 10일 신한은행 근저당권 채권최고액 2억원이 설정되었다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="임차인은 2023년 5월 20일 주택을 인도받고 전입신고 및 확정일자를 마쳤다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            ),
        ],
        evidences=[
            EvidenceItemBrief(
                evidence_id="e1", evidence_label="E01", document_name="등기사항전부증명서_을구.pdf",
                document_type="REGISTRY", status="APPROVED"
            ),
            EvidenceItemBrief(
                evidence_id="e2", evidence_label="E02", document_name="임대차계약서_및_주민등록초본.pdf",
                document_type="CONTRACT", status="APPROVED"
            ),
        ],
    )

    # 1. 쟁점 계획 검증
    issues = plan_legal_issues(question, briefing)
    issue_ids = [iss.issue_id for iss in issues]
    assert "ISSUE_AUCTION_STRATEGY" in issue_ids
    assert "ISSUE_AUCTION_DIVIDEND_RISK" in issue_ids

    # 2. 로컬 법령 검색 검증
    retrieved_execution = _retrieve_from_local_index("민사집행법", ["제91조", "제88조"])
    retrieved_lease = _retrieve_from_local_index("주택임대차보호법", ["제3조의5"])
    assert len(retrieved_execution) == 2, "민사집행법 제91조와 제88조가 로컬 RAG에서 모두 확보되어야 함"
    all_sources = retrieved_execution + retrieved_lease

    # 3. 잘못된 결론(낙찰자 인수 주장) 차단 검증
    bad_draft = (
        "주택임대차보호법 제3조의5 단서에 따라 배당받지 못한 잔여 보증금은 매수인에게 대항할 수 있으며, "
        "낙찰자가 보증금을 인수해야 합니다."
    )
    qa_bad = check_deterministic_qa(
        question=question,
        draft_answer=bad_draft,
        retrieved_sources=all_sources,
        case_context="선순위 근저당권 2021.03.10, 임차인 대항요건 2023.05.20",
    )
    assert qa_bad.status == "REPAIR"
    assert qa_bad.reason_code == "LEGAL_APPLICATION_ERROR"

    # 4. 올바른 결론(소멸 및 배당요구 회수) 통과 검증
    good_draft = (
        "민사집행법 제91조 제3항에 따라 선순위 근저당권보다 늦게 대항력을 취득한 임차권은 경매 매각으로 소멸합니다. "
        "따라서 낙찰자에게 대항할 수 없으며, 배당요구 종기까지 배당요구를 신청하여 매각대금에서 우선변제받아야 합니다."
    )
    qa_good = check_deterministic_qa(
        question=question,
        draft_answer=good_draft,
        retrieved_sources=all_sources,
        case_context="선순위 근저당권 2021.03.10, 임차인 대항요건 2023.05.20",
    )
    assert not any("소멸주의" in rt.repair_reason for rt in qa_good.repair_targets)


def test_case2_senior_tenant_auction_subsumption():
    """Case 2: 선순위 임차인(대항력 2020.04.15 vs 근저당권 2022.08.10) 인수 정당성 검증."""
    question = (
        "제가 2020.04.15에 전입신고와 확정일자를 받았고 집주인이 2022.08.10에 은행 근저당을 잡았습니다. "
        "경매가 실행되면 제 보증금은 어떻게 되나요?"
    )
    briefing = CaseEvidenceBriefing(
        case_id="case_senior_02",
        title="선순위 대항력 임차인 경매 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임차인은 2020년 4월 15일 주택 인도 및 전입신고를 마쳤다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2022년 8월 10일 국민은행 근저당권 채권최고액 1억원이 설정되었다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            ),
        ],
    )

    issues = plan_legal_issues(question, briefing)
    issue_ids = [iss.issue_id for iss in issues]
    assert "ISSUE_AUCTION_STRATEGY" in issue_ids

    # 선순위 임차인이 낙찰자에게 대항하여 보증금 인수를 주장하는 올바른 초안
    senior_draft = (
        "임차인은 근저당권 설정일(2022.08.10)보다 앞선 2020.04.16에 선순위 대항력을 취득하였습니다. "
        "따라서 주택임대차보호법 제3조의5 단서에 따라 매각으로 임차권이 소멸하지 않으며, "
        "배당받지 못한 잔여 보증금에 대하여 낙찰자에게 대항할 수 있고 낙찰자가 이를 인수해야 합니다."
    )
    qa_res = check_deterministic_qa(
        question=question,
        draft_answer=senior_draft,
        retrieved_sources=[
            {"source_id": "STATUTE:001248:current:제3조의5:h1", "source_type": "STATUTE", "statute_name": "주택임대차보호법", "article": "제3조의5", "content": "보증금 미변제 대항력 있는 임차권은 소멸하지 아니한다."}
        ],
        case_context="선순위 대항력 2020.04.15, 후순위 근저당권 2022.08.10",
    )
    # 선순위 임차인의 정당한 대항력 인수가 오탐으로 차단되지 않아야 함
    assert not any("소멸주의" in rt.repair_reason for rt in qa_res.repair_targets)


def test_case3_missing_date_facts_withholding():
    """Case 3: 근저당권과 임차인의 설정/전입 일자가 누락된 경우 입증 보완 식별 검증."""
    question = "경매가 진행 중인데 보증금을 돌려받을 수 있나요?"
    briefing = CaseEvidenceBriefing(
        case_id="case_missing_dates_03",
        title="일자 미확정 경매 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="부동산에 근저당권이 설정되어 있고 현재 임의경매가 진행 중이다.",
                adjudication_status="PARTY_ALLEGED",
                evidence_label="E01",
            ),
        ],
        evidence_gaps=[
            EvidenceGapBrief(
                gap_id="g1",
                gap_type="REGISTRY_CONFIRMATION_GAP",
                target_proposition="등기부상 근저당권 접수일자 및 임차인 전입일자 선후 확인 필요",
                description="등기부 최신본 확인 필요",
            )
        ],
    )

    issues = plan_legal_issues(question, briefing)
    auction_issue = next(i for i in issues if i.issue_id == "ISSUE_AUCTION_STRATEGY")
    assert "선순위담보권설정일" in auction_issue.required_fact_keys
    assert "대항요건구비일" in auction_issue.required_fact_keys


def test_case4_statute_search_resilience_when_external_api_down():
    """Case 4: 외부 OpenLaw API가 오프라인/점검 상태여도 로컬 인덱스(Local-First)로 완결 검증."""
    # 민사집행법 제91조는 로컬 law_docs_global에 존재하므로 API 통신 없이 즉시 반환
    res = _retrieve_from_local_index("민사집행법", ["제91조"])
    assert len(res) >= 1
    assert res[0]["statute_name"] == "민사집행법"
    assert res[0]["article"] == "제91조"
    assert "매각부동산 위의 모든 저당권은 매각으로 소멸된다" in res[0]["content"]


def test_case5_standard_lease_regression_without_auction():
    """Case 5: 경매가 없는 일반 임대차 분쟁에서 경매 쟁점이 오탐되지 않고 정상 계획되는지 검증."""
    question = "임대차 계약기간이 지난달에 끝났는데 집주인이 보증금을 안 줍니다. 어떻게 해야 하나요?"
    briefing = CaseEvidenceBriefing(
        case_id="case_normal_lease_05",
        title="일반 전세보증금 반환 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024년 2월 28일 임대차 기간이 만료되었고 갱신거절 통지가 임대인에게 도달하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
        ],
        evidences=[
            EvidenceItemBrief(
                evidence_id="e1", evidence_label="E01", document_name="임대차계약서.pdf",
                document_type="CONTRACT", status="APPROVED"
            ),
        ],
    )

    issues = plan_legal_issues(question, briefing)
    issue_ids = [iss.issue_id for iss in issues]

    # 계약 종료 및 권리보전 쟁점은 포함되되, 경매 관련 쟁점은 발생하지 않아야 함
    assert "ISSUE_LEASE_TERMINATION" in issue_ids
    assert "ISSUE_AUCTION_STRATEGY" not in issue_ids
    assert "ISSUE_AUCTION_DIVIDEND_RISK" not in issue_ids
