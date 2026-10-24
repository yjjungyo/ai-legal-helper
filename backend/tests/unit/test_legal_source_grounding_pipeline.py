# -*- coding: utf-8 -*-
"""
모듈명: test_legal_source_grounding_pipeline.py

[테스트 개요]
Legal Source Grounding & Verified Answer Pipeline v1.0 개발지시서에 따른 핵심 기능 검증:
1. Fact 신뢰 상태 기본값 UNASSESSED 및 허위 입증 승격 방지 (P0-07)
2. Issue Verifier 3단계 분리 검증 및 하드코딩된 VERIFIED 제거 (P0-01, P0-02)
3. 원자적 법률 주장 검증 모델 (VerifiedLegalClaim) 생성 검증 (P0-04)
4. 부차적 메타데이터 배제 및 질문 연관 핵심 요건사실 우선 선별 (P0-08)
5. Final Disposition 동적 답변 조립 및 고정 템플릿 제거 (P0-05)
6. 본문 실제 인용 기반 cited_sources 사후 필터링 (P0-10)
"""

import pytest
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing,
    FactItemBrief,
    EvidenceItemBrief,
)
from ai_legal_helper.workflows.issue_planner import LegalIssueTask
from ai_legal_helper.agents.issue_verifier import (
    verify_issue,
    VerifiedLegalClaim,
    IssueVerificationResult,
)
from ai_legal_helper.workflows.final_disposition import (
    is_trivial_metadata_fact,
    score_fact_legal_importance,
    select_grounded_facts_for_display,
    assemble_grounded_answer,
    build_dynamic_withheld_answer,
)


def test_fact_item_brief_default_status_is_unassessed():
    """FactItemBrief 생성 시 기본 adjudication_status가 UNASSESSED인지 검증한다 (P0-07)."""
    fact = FactItemBrief(
        fact_id="fact-001",
        statement="임차인은 주거용으로 목적물을 사용한다.",
    )
    assert fact.adjudication_status == "UNASSESSED"


def test_trivial_metadata_fact_exclusion():
    """문서 제목, 단순 연락처, 단순 서명란 서식 등 부차적 메타데이터가 정확히 제외되는지 검증한다 (P0-08)."""
    assert is_trivial_metadata_fact("문서 제목은 '주택임대차계약서'이다.") is True
    assert is_trivial_metadata_fact("이 문서는 주택임대차계약서이다.") is True
    assert is_trivial_metadata_fact("임대인은 박정훈이며 연락처는 010-4826-1357이다.") is True
    assert is_trivial_metadata_fact("문서에는 임대인 서명란이 존재한다.") is True
    assert is_trivial_metadata_fact("임대차 목적물의 전용면적은 42.30㎡이다.") is True

    # 핵심 법률 요건사실은 제외되지 않아야 함
    assert is_trivial_metadata_fact("보증금은 300,000,000원이다.") is False
    assert is_trivial_metadata_fact("임차인은 2022년 3월 2일 전입신고를 마치고 확정일자를 부여받았다.") is False
    assert is_trivial_metadata_fact("HUG 및 동진은행의 가압류 2건이 등재되어 있다.") is False


def test_select_grounded_facts_for_display_prioritization_and_diversity():
    """부차적 메타데이터를 배제하고 보증금, 대항력, 가압류 등 핵심 요건사실을 우선 선별하며 다양성을 보장하는지 검증한다 (P0-08)."""
    facts = [
        FactItemBrief(fact_id="f1", statement="문서 제목은 '주택임대차계약서'이다.", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E01"),
        FactItemBrief(fact_id="f2", statement="임대인 연락처는 010-1234-5678이다.", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E01"),
        FactItemBrief(fact_id="f3", statement="보증금은 300,000,000원이다.", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E01"),
        FactItemBrief(fact_id="f4", statement="임대차 기간은 2022.03.01부터 2024.02.28까지이다.", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E01"),
        FactItemBrief(fact_id="f5", statement="잔금 270,000,000원을 계좌 이체 지급하였다.", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E02"),
        FactItemBrief(fact_id="f6", statement="2022년 3월 2일 전입신고 및 확정일자를 받았다.", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E03"),
        FactItemBrief(fact_id="f7", statement="2026년 4월 1일 퇴거 및 보증금 반환을 요청하는 내용증명을 발송하였다.", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E05"),
        FactItemBrief(fact_id="f8", statement="주택도시보증공사(HUG)의 가압류 결정이 등재되었다.", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E09"),
        FactItemBrief(fact_id="f9", statement="동진은행의 가압류 청구금액 50,000,000원이 등재되었다.", adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E10"),
    ]
    briefing = CaseEvidenceBriefing(
        case_id="case-100",
        title="전세보증금 반환 사건",
        facts=facts,
        evidences=[],
        source_registry={},
    )

    selected = select_grounded_facts_for_display(briefing, query="보증금 3억 반환 및 가압류 경매 위험", max_facts=6)
    selected_stmts = [f.statement for f in selected]

    # 부차적 메타데이터(제목, 전화번호)는 선별 결과에 포함되지 않아야 함
    assert "문서 제목은 '주택임대차계약서'이다." not in selected_stmts
    assert "임대인 연락처는 010-1234-5678이다." not in selected_stmts

    # 핵심 요건사실(보증금, 전입, 가압류 등)이 정상 선별되어야 함
    assert any("보증금" in s for s in selected_stmts)
    assert any("전입신고" in s for s in selected_stmts)
    assert any("가압류" in s for s in selected_stmts)


def test_issue_verifier_hardcoded_verified_eliminated():
    """권리보전 절차(ISSUE_RIGHT_PRESERVATION)에서 법령 조문 본문이 없으면 VERIFIED로 하드코딩되지 않고 CONDITIONAL로 판정되는지 검증한다 (P0-01, P0-02)."""
    task = LegalIssueTask(
        issue_id="ISSUE_RIGHT_PRESERVATION",
        issue_title="이사 전 대항력 유지 및 임차권등기명령 등 권리보전 절차",
        relevant_fact_ids=["f_residence"],
        required_statutes=["주택임대차보호법 제3조", "주택임대차보호법 제3조의3"],
    )
    briefing = CaseEvidenceBriefing(
        case_id="case-101",
        title="전세보증금 반환 사건",
        facts=[
            FactItemBrief(
                fact_id="f_residence",
                statement="전입신고를 유지한 채 거주 중이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
            )
        ],
        evidences=[
            EvidenceItemBrief(evidence_id="ev_03", evidence_label="E03", document_name="주민등록등본.pdf", document_type="RESIDENCE")
        ],
        source_registry={"E03": {"file": "주민등록등본.pdf"}},
    )

    # 1. 검색된 법령 출처가 비어 있는 경우 -> 하드코딩된 VERIFIED가 아니라 CONDITIONAL로 강등되어야 함
    result_empty_law = verify_issue(task, draft_answer="임차권등기명령 [E03]", briefing=briefing, retrieved_sources=[])
    assert result_empty_law.status == "CONDITIONAL"
    assert "RIGHT_PRESERVATION_LAW_CONDITIONAL" in result_empty_law.reason_codes

    # 2. 실제 법령 조문 본문이 검색 출처에 존재하는 경우 -> VERIFIED 정상 부여
    grounded_law_sources = [
        {
            "title": "주택임대차보호법",
            "article": "제3조",
            "content": "제3조(대항력 등) 임대차는 그 등기가 없는 경우에도 임차인이 주택의 인도와 주민등록을 마친 때에는 그 다음 날부터 제삼자에 대하여 효력이 생긴다.",
        },
        {
            "title": "주택임대차보호법",
            "article": "제3조의3",
            "content": "제3조의3(임차권등기명령) 임대차가 끝난 후 보증금이 반환되지 아니한 경우 임차인은 임차주택의 소재지를 관할하는 법원에 임차권등기명령을 신청할 수 있다.",
        },
    ]
    result_with_law = verify_issue(task, draft_answer="임차권등기명령 [E03]", briefing=briefing, retrieved_sources=grounded_law_sources)
    assert result_with_law.status == "VERIFIED"
    assert "RIGHT_PRESERVATION_FACTS_AND_LAW_VERIFIED" in result_with_law.reason_codes
    assert len(result_with_law.supported_statute_ids) >= 1


def test_verified_legal_claims_structure_in_verification_result():
    """IssueVerificationResult 내에 VerifiedLegalClaim 형태의 원자적 주장이 생성되는지 검증한다 (P0-04)."""
    task = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="임대차계약 종료 시점 및 보증금 반환의무",
        relevant_fact_ids=["f_term"],
        required_statutes=["주택임대차보호법 제6조"],
    )
    briefing = CaseEvidenceBriefing(
        case_id="case-102",
        title="전세보증금 반환 사건",
        facts=[
            FactItemBrief(
                fact_id="f_term",
                statement="임대차 계약 만료일은 2026년 9월 30일이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            )
        ],
        evidences=[
            EvidenceItemBrief(evidence_id="ev_01", evidence_label="E01", document_name="주택임대차계약서.txt", document_type="CONTRACT")
        ],
        source_registry={"E01": {"file": "주택임대차계약서.txt"}},
    )
    law_sources = [{
        "title": "주택임대차보호법",
        "article": "제6조",
        "content": "제6조(계약의 갱신) 임대인이 임대차기간이 끝나기 6개월 전부터 2개월 전까지의 기간에 임차인에게 갱신거절의 통지를 하지 아니한 경우에는...",
    }]

    res = verify_issue(task, draft_answer="계약 종료 [E01]", briefing=briefing, retrieved_sources=law_sources)
    assert len(res.verified_claims) >= 2

    # FACTUAL 주장 확인
    fact_claims = [c for c in res.verified_claims if c.get("claim_type") == "FACTUAL"]
    assert len(fact_claims) >= 1
    assert fact_claims[0]["grounding_status"] == "GROUNDED"

    # LEGAL_RULE 주장 확인
    law_claims = [c for c in res.verified_claims if c.get("claim_type") == "LEGAL_RULE"]
    assert len(law_claims) >= 1
    assert "주택임대차보호법 제6조" in law_claims[0]["statute_source_ids"]


def test_assemble_grounded_answer_dynamic_synthesis_without_fixed_boilerplate():
    """assemble_grounded_answer에서 정적 고정 문구 대신 검증된 쟁점 기반 동적 결론 및 맞춤형 행동 가이드가 생성되는지 검증한다 (P0-05)."""
    task_res_1 = IssueVerificationResult(
        issue_id="ISSUE_RIGHT_PRESERVATION",
        issue_title="이사 전 권리보전 절차",
        status="VERIFIED",
        supported_source_ids=["E03"],
        supported_statute_ids=["주택임대차보호법 제3조"],
        safe_recommendations=["임차권등기명령이 등기부에 기재되기 전까지 절대 주택 점유를 인도하지 마십시오."],
    )
    task_res_2 = IssueVerificationResult(
        issue_id="ISSUE_ATTACHMENT_RANKING",
        issue_title="가압류 등재와 권리 순위",
        status="CONDITIONAL",
        supported_source_ids=["E03", "E09"],
        safe_recommendations=["인터넷등기소를 통해 최신 말소사항 포함 등기부등본을 발급받아 중간 권리를 대조하십시오."],
    )

    briefing = CaseEvidenceBriefing(
        case_id="case-103",
        title="전세보증금 반환 사건",
        facts=[
            FactItemBrief(
                fact_id="f_dep",
                statement="보증금은 300,000,000원이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
                document_name="E01_주택임대차계약서.txt",
            )
        ],
        evidences=[
            EvidenceItemBrief(evidence_id="ev_01", evidence_label="E01", document_name="E01_주택임대차계약서.txt", document_type="CONTRACT")
        ],
        source_registry={"E01": {"file": "E01_주택임대차계약서.txt"}},
    )

    answer = assemble_grounded_answer(
        issue_results=[task_res_1, task_res_2],
        briefing=briefing,
        draft_answer="보증금 반환 [E01]",
        disposition="CAUTIONARY",
    )

    # 1. 고정 하드코딩 문구 제거 확인 ("임대차계약 종료 및 임차인의 대항력... 명확히 확인되었습니다")
    assert "임차인의 대항력·우선변제권 관련 주요 법률관계가 명확히 확인되었습니다" not in answer

    # 2. 동적 결론 확인 (검증된 쟁점과 조건부 쟁점의 명칭이 결론에 반영)
    assert "'이사 전 권리보전 절차'" in answer
    assert "'가압류 등재와 권리 순위'" in answer

    # 3. 5번 행동 가이드가 쟁점별 safe_recommendations 기반으로 동적 생성됨을 확인
    assert "임차권등기명령이 등기부에 기재되기 전까지 절대 주택 점유를 인도하지 마십시오" in answer
    assert "인터넷등기소를 통해 최신 말소사항 포함 등기부등본을 발급받아 중간 권리를 대조하십시오" in answer


def test_different_document_creation_dates_are_not_contradictory():
    """서로 다른 문서의 작성일자(2026-10-10 vs 2026-10-15)는 개별 문서의 고유 시점이므로 모순(CONTRADICTS)이 아님을 검증한다."""
    from ai_legal_helper.case_intelligence.fact_semantics import (
        extract_semantic_proposition,
        check_proposition_comparability,
    )
    from ai_legal_helper.case_intelligence.fact_adjudicator import adjudicate_fact
    from ai_legal_helper.case_intelligence.evidence_reliability import evaluate_evidence_reliability
    from unittest.mock import MagicMock

    # E15 문서의 작성일 사실
    prop_e15 = extract_semantic_proposition(
        "문서 작성일은 2026년 10월 10일이다.",
        context={"evidence_id": "ev_15", "document_name": "E15_내용증명_통고서.txt"},
    )
    # E16 문서의 작성일 사실
    prop_e16 = extract_semantic_proposition(
        "문서 작성일은 2026년 10월 15일이다.",
        context={"evidence_id": "ev_16", "document_name": "E16_임차인_현거주_및_인도_상태_확인.txt"},
    )

    # 1. Comparability Gate 검증: 서로 다른 문서의 메타데이터이므로 비교 불가(DIFFERENT_CONTEXT)여야 함
    comp_res = check_proposition_comparability(prop_e16, prop_e15)
    assert comp_res.is_comparable is False
    assert comp_res.status == "DIFFERENT_CONTEXT"
    assert comp_res.reason_code == "DOCUMENT_LOCAL_METADATA"

    # 2. Fact Adjudication 검증: E15 사실이 기 등록된 상태에서 E16 사실을 심리할 때 모순(GENUINELY_DISPUTED)이 되지 않아야 함
    existing_fact = MagicMock()
    existing_fact.id = "fact_15"
    existing_fact.statement = "문서 작성일은 2026년 10월 10일이다."
    existing_fact.source_ref = "ev_15"

    assessment = evaluate_evidence_reliability(
        document_name="E16_임차인_현거주_및_인도_상태_확인.txt",
        proposition=prop_e16,
    )

    result = adjudicate_fact(
        proposition=prop_e16,
        candidate_facts=[existing_fact],
        assessment=assessment,
        fact_doc_names={"fact_15": "E15_내용증명_통고서.txt"},
    )

    # 모순(GENUINELY_DISPUTED/CONTRADICTS)이 완전히 해소되고 정상 상태(EVIDENCE_SUPPORTED 또는 PARTY_ALLEGED)여야 함
    assert result.adjudication_status != "GENUINELY_DISPUTED"
    assert result.primary_relation != "CONTRADICTS"
    assert result.adjudication_status in ("EVIDENCE_SUPPORTED", "PARTY_ALLEGED")

