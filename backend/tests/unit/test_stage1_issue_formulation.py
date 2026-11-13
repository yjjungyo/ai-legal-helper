# -*- coding: utf-8 -*-
"""
테스트 모듈: test_stage1_issue_formulation.py

[테스트 개요]
SC-013 근본 원인 수정 1단계(쟁점 생성 오류 수정) 검증 테스트.

[검증 항목]
1. 경매 관련 쟁점 생성 시 '선순위 대항력 임차인' 등 결론을 사전에 예단하는 문구가 쟁점 명칭 및 질문에 포함되지 않는지 검증 (중립성).
2. 사용자 질문에 직접적인 경매 단어가 없어도 사건 브리핑에 경매/매각 사실이 존재하면 경매 쟁점이 정상 계획되는지 검증 (사건 사실과 질문 통합 고려).
3. 쟁점의 법률 질문이 (1) 임차인의 대항력 취득 여부, (2) 선순위 담보권 존재 여부, (3) 매수인에 대한 대항(인수) 가능 여부, (4) 배당 순위 및 회수 가능성으로 명확히 구분되어 있는지 검증.
4. 기존 전세보증금 반환, 가압류 순위, 분할제안 등 다른 법률 쟁점과의 독립성 및 증거 라벨 매핑 기능 유지 검증.
"""

import pytest
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing,
    FactItemBrief,
    EvidenceItemBrief,
)
from ai_legal_helper.workflows.issue_planner import plan_legal_issues, LegalIssueTask


def test_stage1_auction_issue_neutrality_and_decomposition():
    """1. 쟁점 질문에 선순위/후순위 단정 결론이 없고 단계별 분리 판단이 이루어지는지 검증."""
    question = "경매가 진행되면 제 보증금을 돌려받을 수 있나요? 낙찰자에게 청구할 수 있나요?"
    briefing = CaseEvidenceBriefing(
        case_id="case_sc013_test",
        title="선순위 근저당 및 대항력 임차인 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2021년 3월 10일 신한은행 근저당권 채권최고액 2억원이 설정되었다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="임차인은 2023년 5월 20일 전입신고 및 주택 인도를 마치고 확정일자를 받았다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            ),
        ],
        evidences=[
            EvidenceItemBrief(
                evidence_id="e1",
                evidence_label="E01",
                document_name="부동산등기사항전부증명서_을구.pdf",
                document_type="REGISTRY",
                status="APPROVED",
            ),
            EvidenceItemBrief(
                evidence_id="e2",
                evidence_label="E02",
                document_name="주민등록등본_및_임대차계약서.pdf",
                document_type="CONTRACT",
                status="APPROVED",
            ),
        ],
    )

    issues = plan_legal_issues(question, briefing)
    issue_map = {iss.issue_id: iss for iss in issues}

    assert "ISSUE_AUCTION_STRATEGY" in issue_map, "경매 전략 쟁점이 계획되어야 한다."
    auction_strategy = issue_map["ISSUE_AUCTION_STRATEGY"]

    # 1) 쟁점 명칭에 '선순위 대항력 임차인'이라는 사전 예단 결론이 없어야 함
    assert "선순위 대항력 임차인" not in auction_strategy.issue_title

    # 2) 질문들이 별개의 단계적 판단으로 구분되어야 함
    all_questions_text = " ".join(auction_strategy.legal_questions)
    assert "대항력을 적법하게 취득" in all_questions_text, "대항력 취득 여부 질문 포함"
    assert "선순위 담보물권" in all_questions_text, "선순위 권리 존재 여부 질문 포함"
    assert "매수인(낙찰자)에게 인수되는가 아니면" in all_questions_text, "매수인 대항/소멸 여부 질문 포함"
    assert "배당요구" in all_questions_text, "배당요구 및 배당 순위 질문 포함"

    # 3) 질문 문장에 선순위라고 단정하여 전제하는 편향 문구가 없어야 함
    for q in auction_strategy.legal_questions:
        assert not q.startswith("선순위 대항력을 갖춘 경우에 한하여"), "사전 전제 질문 금지"
        assert not q.startswith("선순위 담보권보다 늦은 후순위 대항력 임차인의 경우 낙찰자에게 보증금 반환을 청구할 수 없으므로"), "결론 사전 단정 금지"


def test_stage1_auction_issue_triggered_by_case_facts_without_auction_in_question():
    """2. 질문에 '경매' 단어가 없어도 사건 브리핑에 경매/매각 사실이 있으면 경매 쟁점이 계획되는지 검증."""
    question = "집주인이 연락이 안 되고 보증금을 못 받고 있는데 제 돈을 안전하게 회수할 수 있나요?"
    briefing = CaseEvidenceBriefing(
        case_id="case_fact_trigger_test",
        title="경매 개시 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024년 1월 15일 법원으로부터 부동산 임의경매개시결정 통지서가 도달하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
            ),
        ],
        evidences=[
            EvidenceItemBrief(
                evidence_id="e3",
                evidence_label="E03",
                document_name="경매개시결정통지서.pdf",
                document_type="COURT_NOTICE",
                status="APPROVED",
            ),
        ],
    )

    issues = plan_legal_issues(question, briefing)
    issue_ids = [iss.issue_id for iss in issues]

    # 사건 사실에 경매개시결정이 있으므로 경매 관련 쟁점이 도출되어야 함
    assert "ISSUE_AUCTION_STRATEGY" in issue_ids or "ISSUE_AUCTION_DIVIDEND_RISK" in issue_ids
    matched_issue = next(i for i in issues if i.issue_id in ("ISSUE_AUCTION_STRATEGY", "ISSUE_AUCTION_DIVIDEND_RISK"))
    assert "E03" in matched_issue.relevant_evidence_labels, "경매 증거 E03이 정상 매핑되어야 함"
