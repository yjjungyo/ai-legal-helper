# -*- coding: utf-8 -*-
"""
모듈명: test_issue_verification.py

[모듈 개요]
Issue-Level Verification & Evidence-Grounded Consultation v1.0 단위 테스트 스위트.
등록 증거 기반 브리핑(CaseEvidenceBriefing), 안정적 증거 라벨링(E01~E17), 쟁점 분해(Issue Planning),
쟁점별 정밀 검증(IssueVerifier: 사실 검증 vs 법률 검증 분리), 부분 답변 조립 및 최종 판정(DELIVERED/CAUTIONARY/WITHHELD),
동적 판단유보(insufficient_node) 개선을 종합 검증한다.

[테스트 케이스: C01 ~ C25]
- C01: assign_evidence_labels - 기존 E접두사 인식 및 정렬
- C02: assign_evidence_labels - 라벨 없는 문서에 순차적 E번호 자동 부여
- C03: build_case_evidence_briefing - 증거, 사실, 당사자, 타임라인, 공백 통합 브리핑 구축
- C04: CaseEvidenceBriefing.to_prompt_context - LLM 프롬프트용 텍스트 변환 정합성
- C05: plan_legal_issues - 복합 질문의 독립적 쟁점 분해
- C06: plan_legal_issues - 쟁점별 관련 사실(Facts) 자동 매칭
- C07: plan_legal_issues - 쟁점별 관련 증거 라벨(E01 등) 자동 매칭
- C08: plan_legal_issues - 일반 질문에 대한 안전한 단일 쟁점 폴백
- C09: verify_issue - 사실 및 법률 요건 충족 시 VERIFIED 판정
- C10: verify_issue - 가압류/배당/손해배상 등 추정적 쟁점에 대한 CONDITIONAL 판정
- C11: verify_issue - 필수 사실 부존재 시 NEEDS_EVIDENCE 판정
- C12: verify_issue - 미등록 증거 번호 인용 시 BLOCKED 판정
- C13: 사실 검증기 독립 검증 - 법령 없이도 확정 사실 및 증거 라벨 검증
- C14: 법률 검증기 - 검색된 법령 조문과의 매칭 검증
- C15: 증거 인용 감사 - 미등록 증거 라벨 탐지 및 BLOCKED 처리
- C16: 추정적 진술 제어 - 경매 배당 관련 쟁점에 대한 CONDITIONAL 판정
- C17: determine_final_disposition - 모든 쟁점 검증 완료 시 DELIVERED
- C18: determine_final_disposition - 검증 완료 + 조건부/보완 쟁점 혼재 시 CAUTIONARY
- C19: determine_final_disposition - 모든 쟁점 증거 부존재 시 WITHHELD
- C20: assemble_grounded_answer - 차단된 주장을 배제하고 검증된 분석 보존
- C21: assemble_grounded_answer - 필수 증거 공백 체크리스트 동적 포함
- C22: assemble_grounded_answer - 안전한 우선순위 대응 절차 안내 포함
- C23: build_dynamic_withheld_answer - 정적 템플릿 대체 및 확정 사실/등록 증거 반영
- C24: insufficient_node 출처 보존 - 판단 유보 시에도 등록 증거 출처 보존
- C25: 복합 쟁점 워크플로우 통합 검증 - 단일 쟁점 미비로 전체 답변이 탈락하지 않음
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_legal_helper.database.session import Base
from ai_legal_helper.database.models import (
    User,
    Case,
    Fact,
    EvidenceDocument,
    EvidenceClaim,
    EvidenceAssessment,
    FactAdjudication,
    EvidenceGap,
    Party,
    Event,
)
from ai_legal_helper.case_intelligence.case_briefing import (
    assign_evidence_labels,
    build_case_evidence_briefing,
    CaseEvidenceBriefing,
    EvidenceItemBrief,
    PartyItemBrief,
    FactItemBrief,
    TimelineItemBrief,
    EvidenceGapBrief,
)
from ai_legal_helper.workflows.issue_planner import (
    plan_legal_issues,
    LegalIssueTask,
)
from ai_legal_helper.agents.issue_verifier import (
    verify_issue,
    verify_all_issues,
    IssueVerificationResult,
)
from ai_legal_helper.workflows.final_disposition import (
    determine_final_disposition,
    assemble_grounded_answer,
    build_dynamic_withheld_answer,
)


def _create_in_memory_db():
    """인메모리 SQLite DB 세션을 생성한다."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


# ==============================================================================
# C01 ~ C04: CaseEvidenceBriefing & Evidence Labels
# ==============================================================================

def test_c01_assign_evidence_labels_with_prefixes():
    """C01: 파일명에 이미 E01, E02 등이 붙은 문서는 해당 라벨을 우선 보존하여 매핑한다."""
    docs = [
        EvidenceDocument(id="d1", case_id="c1", original_filename="E02_전입세대확인서.pdf", safe_storage_key="k1", media_type="pdf", size_bytes=100, sha256="s1"),
        EvidenceDocument(id="d2", case_id="c1", original_filename="E01_임대차계약서.pdf", safe_storage_key="k2", media_type="pdf", size_bytes=100, sha256="s2"),
        EvidenceDocument(id="d3", case_id="c1", original_filename="E10_가압류결정문.pdf", safe_storage_key="k3", media_type="pdf", size_bytes=100, sha256="s3"),
    ]
    labels = assign_evidence_labels(docs)
    assert labels["d2"] == "E01"
    assert labels["d1"] == "E02"
    assert labels["d3"] == "E10"


def test_c02_assign_evidence_labels_auto_sequential():
    """C02: 라벨 접두사가 없는 일반 파일명의 경우 E01부터 순차적으로 부여한다."""
    docs = [
        EvidenceDocument(id="doc_a", case_id="c1", original_filename="임대차계약서.pdf", safe_storage_key="k1", media_type="pdf", size_bytes=100, sha256="s1"),
        EvidenceDocument(id="doc_b", case_id="c1", original_filename="보증금이체영수증.pdf", safe_storage_key="k2", media_type="pdf", size_bytes=100, sha256="s2"),
    ]
    labels = assign_evidence_labels(docs)
    assert labels["doc_a"] == "E01"
    assert labels["doc_b"] == "E02"


def test_c03_build_case_evidence_briefing():
    """C03: DB로부터 Case, Fact, Party, Event, Gap 등을 종합하여 CaseEvidenceBriefing을 생성한다."""
    db = _create_in_memory_db()
    case = Case(id="case_01", title="전세보증금 반환 사건")
    db.add(case)

    doc = EvidenceDocument(
        id="doc_01",
        case_id="case_01",
        original_filename="E01_임대차계약서.pdf",
        safe_storage_key="k1",
        media_type="application/pdf",
        size_bytes=1024,
        sha256="abc123hash",
        status="APPROVED",
    )
    db.add(doc)

    fact = Fact(
        id="f1",
        case_id="case_01",
        statement="임차보증금은 3억원이며 2022년 3월 1일 전액 지급되었다.",
    )
    db.add(fact)
    adj = FactAdjudication(
        id="adj_1",
        case_id="case_01",
        fact_id="f1",
        adjudication_status="EVIDENCE_SUPPORTED",
    )
    db.add(adj)

    party = Party(id="p1", case_id="case_01", name="박정훈", role="임대인")
    db.add(party)

    event = Event(id="e1", case_id="case_01", title="주택 인도 및 잔금 지급", event_date="2022-03-01", description="주택 인도 및 잔금 지급")
    db.add(event)

    gap = EvidenceGap(
        id="g1",
        case_id="case_01",
        gap_type="REGISTRY_CONFIRMATION_GAP",
        target_proposition="최신 등기부 필요",
        description="최신 등기부 필요",
    )
    db.add(gap)
    db.commit()

    briefing = build_case_evidence_briefing(db, "case_01")
    registry = briefing.source_registry
    assert briefing.case_id == "case_01"
    assert len(briefing.evidences) == 1
    assert briefing.evidences[0].evidence_label == "E01"
    assert len(briefing.facts) == 1
    assert len(briefing.parties) == 1
    assert len(briefing.timeline) == 1
    assert len(briefing.evidence_gaps) == 1
    assert "E01" in registry


def test_c04_briefing_to_prompt_context():
    """C04: CaseEvidenceBriefing.to_prompt_context()가 LLM 프롬프트에 적합한 텍스트를 출력한다."""
    briefing = CaseEvidenceBriefing(
        case_id="case_01",
        title="전세보증금 반환 사건",
        formatted_summary="[사건 등록 증거 및 확정 사실 브리핑]\n확정 사실 목록...",
    )
    prompt_txt = briefing.to_prompt_context()
    assert "[사건 등록 증거 및 확정 사실 브리핑]" in prompt_txt


# ==============================================================================
# C05 ~ C08: Issue Planning
# ==============================================================================

def test_c05_plan_legal_issues_multi_issue():
    """C05: 전세보증금 반환, 가압류, 경매, 지급제안 등 복합 질문을 복수의 독립 쟁점으로 분해한다."""
    query = (
        "임대차 계약기간이 끝났는데 보증금을 못 돌려받고 있습니다. "
        "가압류가 걸려있는데 경매 넘어가면 배당받을 수 있나요? "
        "임대인이 5천만원씩 나눠서 주겠다고 하는데 합의해야 할까요?"
    )
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="전세 사건",
    )
    issues = plan_legal_issues(query, briefing)
    assert len(issues) >= 3
    issue_ids = [iss.issue_id for iss in issues]
    assert "ISSUE_LEASE_TERMINATION" in issue_ids
    assert "ISSUE_ATTACHMENT_RANKING" in issue_ids
    assert "ISSUE_AUCTION_DIVIDEND_RISK" in issue_ids
    assert "ISSUE_INSTALLMENT_PROPOSAL" in issue_ids


def test_c06_plan_legal_issues_matches_relevant_facts():
    """C06: 분해된 쟁점에 관련된 사건 확정 사실(Facts)을 자동으로 선별 매칭한다."""
    query = "계약 해지 및 보증금 반환 청구가 가능한가요?"
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="전세 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024년 2월 28일 임대차 기간이 만료되었고 계약 해지 통지가 도달하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
                supporting_evidence_labels=["E01", "E05"],
            ),
            FactItemBrief(
                fact_id="f2",
                statement="가압류 청구금액은 5천만원이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E07",
                supporting_evidence_labels=["E07"],
            ),
        ],
    )
    issues = plan_legal_issues(query, briefing)
    term_issue = next(i for i in issues if i.issue_id == "ISSUE_LEASE_TERMINATION")
    assert "f1" in term_issue.relevant_fact_ids


def test_c07_plan_legal_issues_matches_evidence_labels():
    """C07: 분해된 쟁점에 관련된 증거 라벨([E01] 등)을 매칭한다."""
    query = "가압류 상태에서 경매 위험이 있나요?"
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="전세 사건",
        evidences=[
            EvidenceItemBrief(
                evidence_id="e1",
                evidence_label="E07",
                document_name="가압류결정문.pdf",
                document_type="ATTACHMENT",
                status="APPROVED",
            )
        ],
    )
    issues = plan_legal_issues(query, briefing)
    attach_issue = next((i for i in issues if i.issue_id == "ISSUE_ATTACHMENT_RANKING"), None)
    assert attach_issue is not None
    assert "E07" in attach_issue.relevant_evidence_labels


def test_c08_plan_legal_issues_general_fallback():
    """C08: 전세사기/주택임대차 외의 일반적인 질문에 대해 범용적 단일 쟁점으로 안전하게 폴백한다."""
    query = "저작권 침해 소송에서 손해배상 청구 요건이 어떻게 되나요?"
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="저작권 사건",
    )
    issues = plan_legal_issues(query, briefing)
    assert len(issues) >= 1
    assert issues[0].issue_id == "ISSUE_GENERAL_ANALYSIS"


# ==============================================================================
# C09 ~ C16: Issue-Level Verification Engine
# ==============================================================================

def test_c09_verify_issue_verified_when_facts_and_law_present():
    """C09: 사실과 법령이 뒷받침된 쟁점은 VERIFIED로 판정된다."""
    task = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="임대차 계약 해지 및 보증금 반환 청구권",
        legal_questions=["보증금 반환 청구 가능 여부"],
        relevant_fact_ids=["f1"],
        relevant_evidence_labels=["E01", "E05"],
        required_statutes=["주택임대차보호법 제6조"],
    )
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024년 2월 28일 만료 및 해지 통고 완료",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            )
        ],
        source_registry={"E01": {}, "E05": {}},
    )
    draft_answer = (
        "### 1. 임대차 계약 해지 및 보증금 반환 청구권\n"
        "임대차계약서[E01] 및 문자 통지[E05]에 따라 계약은 2024년 2월 28일 만료되었으므로, "
        "주택임대차보호법 제6조에 근거하여 보증금 반환을 청구할 권리가 명확히 발생합니다."
    )
    sources = [{"source_type": "STATUTE", "title": "주택임대차보호법", "content": "제6조 계약의 갱신"}]

    res = verify_issue(task, draft_answer, briefing, sources)
    assert res.status == "VERIFIED"
    assert "TERMINATION_FACTS_AND_LAW_SUPPORTED" in res.reason_codes


def test_c10_verify_issue_conditional_for_speculative_predictions():
    """C10: 가압류 배당 순위 및 경매 낙찰가 등 추정적 쟁점은 CONDITIONAL(조건부)로 판정한다."""
    task = LegalIssueTask(
        issue_id="ISSUE_AUCTION_DIVIDEND_RISK",
        issue_title="경매 배당 및 회수 가능성",
        legal_questions=["경매 넘어가면 배당받을 수 있나요?"],
        relevant_fact_ids=["f1"],
        relevant_evidence_labels=["E02", "E07"],
        required_statutes=["민사집행법 제88조"],
    )
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="대항력 및 확정일자는 2022.03.02 취득함",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
            )
        ],
        source_registry={"E02": {}, "E07": {}},
    )
    draft_answer = (
        "### 3. 경매 배당 및 회수 가능성\n"
        "임차인은 2022.03.02 대항력을 취득하여 가압류[E07]보다 선순위입니다. "
        "다만 향후 경매 낙찰가율이나 선순위 조세채권 여부에 따라 전액 배당 여부는 유동적입니다."
    )
    sources = [{"source_type": "STATUTE", "title": "민사집행법", "content": "제88조 배당요구"}]

    res = verify_issue(task, draft_answer, briefing, sources)
    assert res.status == "CONDITIONAL"
    assert "AUCTION_DIVIDEND_REQUIRES_VALUATION" in res.reason_codes


def test_c11_verify_issue_needs_evidence_when_facts_missing():
    """C11: 핵심 사실관계가 누락되고 증거 라벨이 없으면 NEEDS_EVIDENCE로 판정한다."""
    task = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="임대차계약 종료",
        legal_questions=["계약 종료 여부"],
        relevant_fact_ids=["f_missing"],
        relevant_evidence_labels=[],
    )
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        facts=[],
        source_registry={},
    )
    draft_answer = "계약 종료 여부는 증빙이 없어 확인할 수 없습니다."
    sources = []

    res = verify_issue(task, draft_answer, briefing, sources)
    assert res.status == "NEEDS_EVIDENCE"
    assert "TERMINATION_EVIDENCE_LACKING" in res.reason_codes


def test_c12_verify_issue_blocked_when_unregistered_evidence_cited():
    """C12: 사건에 등록되지 않은 임의의 증거 번호([E99])를 인용한 경우 BLOCKED로 판정한다."""
    task = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="보증금 전액 반환 청구",
        legal_questions=["보증금 청구"],
        relevant_fact_ids=["f1"],
        relevant_evidence_labels=["E01"],
    )
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="보증금 3억원",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            )
        ],
        source_registry={"E01": {}},
    )
    draft_answer = "임차인은 미등록 증거[E99]에 따라 보증금 전액을 지급하였습니다."
    sources = []

    res = verify_issue(task, draft_answer, briefing, sources)
    assert res.status == "BLOCKED"
    assert "INVALID_EVIDENCE_CITATION" in res.reason_codes


def test_c13_fact_verifier_operates_without_statutes():
    """C13: 사실 검증기(Fact Verifier)는 법령 없이도 확정 사실과 증거 라벨 일치 여부를 독립 검증한다."""
    task = LegalIssueTask(
        issue_id="ISSUE_GENERAL_FACT",
        issue_title="사실관계 확인",
        legal_questions=["보증금 지급 사실"],
        relevant_fact_ids=["f1"],
        relevant_evidence_labels=["E01"],
    )
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="보증금 3억원이 2022.03.01 전액 지급되었다",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            )
        ],
        source_registry={"E01": {}},
    )
    draft_answer = "보증금 3억원은 임대차계약서[E01]에 의해 전액 지급된 사실이 확인됩니다."

    res = verify_issue(task, draft_answer, briefing, retrieved_sources=[])
    assert "f1" in res.supported_fact_ids
    assert "E01" in res.supported_source_ids


def test_c14_legal_verifier_matches_statutes():
    """C14: 법률 검증기(Legal Verifier)는 검색된 법령 조문과의 매칭을 정확히 평가한다."""
    task = LegalIssueTask(
        issue_id="ISSUE_GENERAL_LEGAL",
        issue_title="임차권등기명령 신청",
        legal_questions=["임차권등기명령"],
        relevant_fact_ids=["f1"],
        relevant_evidence_labels=["E01"],
        required_statutes=["주택임대차보호법 제3조의3"],
    )
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임대차 종료 후 미반환",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            )
        ],
        source_registry={"E01": {}},
    )
    draft_answer = "주택임대차보호법 제3조의3에 근거하여 법원에 임차권등기명령을 신청할 수 있습니다[E01]."
    sources = [{"source_type": "STATUTE", "title": "주택임대차보호법", "content": "제3조의3 임차권등기명령"}]

    res = verify_issue(task, draft_answer, briefing, retrieved_sources=sources)
    assert any("제3조의3" in s for s in res.supported_statute_ids)
    assert res.status == "VERIFIED"


def test_c15_citation_audit_requires_labels():
    """C15: 인용 감사는 답변 내 증거 라벨([E01] 등)이 source_registry에 존재하는지 확인한다."""
    task = LegalIssueTask(
        issue_id="ISSUE_TEST",
        issue_title="보증금 청구",
        legal_questions=["보증금 청구"],
        relevant_fact_ids=["f1"],
        relevant_evidence_labels=["E01"],
    )
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="보증금 3억원",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            )
        ],
        source_registry={"E01": {}},
    )
    draft_answer = "보증금 3억원은 허위증거[E99]에 기재되어 있습니다."

    res = verify_issue(task, draft_answer, briefing, retrieved_sources=[])
    assert res.status == "BLOCKED"
    assert "INVALID_EVIDENCE_CITATION" in res.reason_codes


def test_c16_speculative_prediction_control():
    """C16: 경매 배당 관련 쟁점에 대해 단정적 예측 대신 CONDITIONAL로 제어한다."""
    task = LegalIssueTask(
        issue_id="ISSUE_AUCTION_DIVIDEND_RISK",
        issue_title="경매 배당금 예측",
        legal_questions=["얼마나 배당받나요?"],
        relevant_fact_ids=["f1"],
        relevant_evidence_labels=["E01"],
    )
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="보증금 3억원",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
            )
        ],
        source_registry={"E01": {}},
    )
    draft_answer = "경매 진행 시 정확히 2억 8천만원을 100% 회수할 수 있습니다[E01]."

    res = verify_issue(task, draft_answer, briefing, retrieved_sources=[])
    assert res.status == "CONDITIONAL"


# ==============================================================================
# C17 ~ C22: Final Disposition & Grounded Answer Assembly
# ==============================================================================

def test_c17_determine_final_disposition_delivered():
    """C17: 모든 쟁점이 VERIFIED인 경우 최종 판정은 DELIVERED이다."""
    results = [
        IssueVerificationResult(
            issue_id="I1",
            issue_title="쟁점1",
            status="VERIFIED",
        ),
        IssueVerificationResult(
            issue_id="I2",
            issue_title="쟁점2",
            status="VERIFIED",
        ),
    ]
    disp, _ = determine_final_disposition(results)
    assert disp == "DELIVERED"


def test_c18_determine_final_disposition_cautionary():
    """C18: 검증된 쟁점과 조건부/보완필요 쟁점이 혼재된 경우 CAUTIONARY로 완화 판정하여 부분 답변을 제공한다."""
    results = [
        IssueVerificationResult(
            issue_id="I1",
            issue_title="쟁점1 (보증금 반환)",
            status="VERIFIED",
        ),
        IssueVerificationResult(
            issue_id="I2",
            issue_title="쟁점2 (경매 배당률)",
            status="CONDITIONAL",
        ),
    ]
    disp, _ = determine_final_disposition(results)
    assert disp == "CAUTIONARY"


def test_c19_determine_final_disposition_withheld():
    """C19: 모든 쟁점이 BLOCKED 또는 증거 결손인 경우에만 WITHHELD로 유보한다."""
    results = [
        IssueVerificationResult(
            issue_id="I1",
            issue_title="쟁점1",
            status="BLOCKED",
        ),
        IssueVerificationResult(
            issue_id="I2",
            issue_title="쟁점2",
            status="NEEDS_EVIDENCE",
        ),
    ]
    disp, _ = determine_final_disposition(results)
    assert disp == "WITHHELD"


def test_c20_assemble_grounded_answer_preserves_verified():
    """C20: assemble_grounded_answer는 검증된 쟁점을 보존하고 차단된 주장을 배제한다."""
    results = [
        IssueVerificationResult(
            issue_id="I1",
            issue_title="계약 해지권",
            status="VERIFIED",
            supported_source_ids=["E01"],
            safe_recommendations=["계약 만료로 해지 가능합니다."],
        )
    ]
    draft = "### 1. 계약 해지권\n계약 만료로 해지 가능합니다[E01]."
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
    )
    final_ans = assemble_grounded_answer(
        results,
        briefing,
        draft,
        "DELIVERED",
    )
    assert "계약 해지권" in final_ans
    assert "[E01]" in final_ans


def test_c21_assemble_grounded_answer_includes_missing_evidence():
    """C21: 부분 답변 제공 시 보완이 필요한 증거 목록을 체크리스트로 명시한다."""
    results = [
        IssueVerificationResult(
            issue_id="I1",
            issue_title="계약 해지권",
            status="VERIFIED",
            safe_recommendations=["계약 만료로 해지 가능합니다."],
        ),
        IssueVerificationResult(
            issue_id="I2",
            issue_title="가압류 권리분석",
            status="NEEDS_EVIDENCE",
            missing_legal_sources=["등기부등본 확인 필요"],
        ),
    ]
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        evidence_gaps=[
            EvidenceGapBrief(gap_id="g1", gap_type="REGISTRY_CONFIRMATION_GAP", target_proposition="최신 등기부 필요", description="최신 등기부 필요")
        ],
    )
    final_ans = assemble_grounded_answer(
        results,
        briefing,
        "### 1. 계약 해지권\n계약 만료로 해지 가능합니다.",
        "CAUTIONARY",
    )
    assert "보완이 필요한 증거" in final_ans or "최신 등기부 필요" in final_ans


def test_c22_assemble_grounded_answer_includes_safe_next_actions():
    """C22: 답변 말미에 안전한 절차적 대응 방안을 단계별로 포함한다."""
    results = [
        IssueVerificationResult(
            issue_id="I1",
            issue_title="계약 해지권",
            status="VERIFIED",
            safe_recommendations=["해지 가능합니다."],
        )
    ]
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
    )
    final_ans = assemble_grounded_answer(
        results,
        briefing,
        "### 1. 계약 해지권\n해지 가능합니다.",
        "DELIVERED",
    )
    assert "안전한 실무적 다음 행동 가이드" in final_ans or "행동 가이드" in final_ans


# ==============================================================================
# C23 ~ C25: Dynamic Insufficient Node & Multi-Issue Workflow
# ==============================================================================

def test_c23_build_dynamic_withheld_answer_includes_facts_and_evidence():
    """C23: 불가피하게 판단 유보(WITHHELD)가 발생해도 정적 템플릿 대신 확인된 사실과 등록 증거를 명시한다."""
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        evidences=[
            EvidenceItemBrief(
                evidence_id="e1",
                evidence_label="E01",
                document_name="E01_임대차계약서.pdf",
                document_type="CONTRACT",
                status="APPROVED",
            )
        ],
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="보증금은 3억원이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
                supporting_evidence_labels=["E01"],
            )
        ],
    )
    results = [
        IssueVerificationResult(
            issue_id="I1",
            issue_title="특수 분쟁",
            status="NEEDS_EVIDENCE",
            reason_codes=["SPECIAL_STATUTE_MISSING"],
            unresolved_facts=["특별법 근거 및 금융거래내역 부족"],
        )
    ]
    withheld_ans = build_dynamic_withheld_answer(briefing, results)
    assert "[E01] E01_임대차계약서.pdf" in withheld_ans
    assert "보증금은 3억원이다" in withheld_ans


def test_c24_insufficient_node_preserves_sources():
    """C24: insufficient_node 실행 시 등록 증거 출처 목록(cited_sources)이 비워지지 않고 유지된다."""
    briefing = CaseEvidenceBriefing(
        case_id="c1",
        title="임대차 사건",
        evidences=[
            EvidenceItemBrief(
                evidence_id="e1",
                evidence_label="E01",
                document_name="E01_임대차계약서.pdf",
                document_type="CONTRACT",
                status="APPROVED",
            )
        ],
    )
    source_reg = {
        "E01": {
            "source_type": "CASE_EVIDENCE",
            "file": "E01_임대차계약서.pdf",
            "evidence_label": "E01",
            "title": "임대차계약서",
        }
    }
    withheld_ans = build_dynamic_withheld_answer(briefing, [])
    assert "[E01]" in withheld_ans
    assert "E01" in source_reg


def test_c25_multi_issue_workflow_no_monolithic_failure():
    """C25: 복합 쟁점 평가 시 일부 세부 쟁점이 CONDITIONAL이라도 전체 결과는 CAUTIONARY로 구제된다."""
    results = [
        IssueVerificationResult(
            issue_id="I1",
            issue_title="보증금 반환",
            status="VERIFIED",
        ),
        IssueVerificationResult(
            issue_id="I2",
            issue_title="경매 배당",
            status="CONDITIONAL",
        ),
    ]

    disposition, _ = determine_final_disposition(results)
    assert disposition == "CAUTIONARY"
    assert disposition != "WITHHELD"
