# -*- coding: utf-8 -*-
"""증거 문서 사실(Claim) 승인 범위 집계 및 LLM 인용 지침 생성 단위 테스트.

[역할]
사건에 첨부된 증거 문서 단위로 개별 주장(Claim)들의 승인/반려/보류 상태를 집계하고,
LLM이 상담 답변 작성 시 올바른 사실만을 채택하고 반려된 주장을 배제할 수 있도록
제공되는 approval_scope 분류 및 claim_review_guide 생성 로직을 검증한다.

[검증 항목]
1. compute_document_claim_review_summary: NO_CLAIMS (추출 사실 0건)
2. compute_document_claim_review_summary: FULL_APPROVED (전체 사실 승인)
3. compute_document_claim_review_summary: ALL_REJECTED (전체 사실 반려)
4. compute_document_claim_review_summary: PENDING (사실 검토 대기)
5. compute_document_claim_review_summary: PARTIAL_APPROVED (일부 사실 승인 혼재)
6. build_case_evidence_briefing 통합 연동: source_documents, evidence_items, source_registry, formatted_summary 일치성
"""

from unittest.mock import MagicMock
import pytest

from ai_legal_helper.case_intelligence.case_briefing import (
    compute_document_claim_review_summary,
    build_case_evidence_briefing,
    EvidenceItemBrief,
)
from ai_legal_helper.database.models import (
    Case,
    EvidenceDocument,
    EvidenceClaim,
    EvidenceSpan,
)


def test_compute_summary_no_claims():
    """추출된 Claim이 0건일 때 NO_CLAIMS와 빈 가이드가 반환되는지 검증한다."""
    res = compute_document_claim_review_summary([])
    assert res["approval_scope"] == "NO_CLAIMS"
    assert res["approval_scope_label"] == "추출 사실 없음"
    assert res["total_claim_count"] == 0
    assert res["approved_claim_count"] == 0
    assert res["rejected_claim_count"] == 0
    assert res["pending_claim_count"] == 0
    assert res["claim_review_guide"] == ""


def test_compute_summary_full_approved():
    """모든 Claim이 APPROVED 또는 EDITED일 때 FULL_APPROVED와 높은 신뢰도 지침이 반환되는지 검증한다."""
    claims = [
        {"statement": "2026년 3월 1일 전세계약 체결", "review_status": "APPROVED"},
        {"statement": "보증금 3억 원 중도금 5천만 원 지급 완료", "review_status": "EDITED"},
    ]
    res = compute_document_claim_review_summary(claims)
    assert res["approval_scope"] == "FULL_APPROVED"
    assert res["approval_scope_label"] == "전체 사실 승인"
    assert res["total_claim_count"] == 2
    assert res["approved_claim_count"] == 2
    assert res["rejected_claim_count"] == 0
    assert res["pending_claim_count"] == 0
    assert len(res["approved_claims"]) == 2
    assert "높은 신뢰도로 사실 인정 및 인용" in res["claim_review_guide"]


def test_compute_summary_all_rejected():
    """모든 Claim이 REJECTED일 때 ALL_REJECTED와 엄격한 배제 지침이 반환되는지 검증한다."""
    claims = [
        {"statement": "임차인이 원상복구 비용 1천만 원 지급을 구두 합의함", "review_status": "REJECTED"},
    ]
    res = compute_document_claim_review_summary(claims)
    assert res["approval_scope"] == "ALL_REJECTED"
    assert res["approval_scope_label"] == "전체 사실 반려"
    assert res["total_claim_count"] == 1
    assert res["approved_claim_count"] == 0
    assert res["rejected_claim_count"] == 1
    assert len(res["rejected_claims"]) == 1
    assert "절대 진실한 사실로 인정하거나" in res["claim_review_guide"]


def test_compute_summary_pending():
    """모든 Claim이 PENDING일 때 PENDING 상태와 조건부 취급 지침이 반환되는지 검증한다."""
    claims = [
        {"statement": "미확인 관리비 30만 원 미납 내역", "review_status": "PENDING"},
        {"statement": "퇴거 예정일자 메모", "review_status": None},  # None은 PENDING 취급
    ]
    res = compute_document_claim_review_summary(claims)
    assert res["approval_scope"] == "PENDING"
    assert res["approval_scope_label"] == "사실 검토 대기"
    assert res["total_claim_count"] == 2
    assert res["pending_claim_count"] == 2
    assert "조건부 정황으로만 취급하십시오" in res["claim_review_guide"]


def test_compute_summary_partial_approved():
    """승인, 반려, 대기 사실이 혼재된 경우 PARTIAL_APPROVED와 상태별 구분 지침이 생성되는지 검증한다."""
    claims = [
        {"statement": "2026-04-30 1차 중도금 24,000,000원 입금", "review_status": "APPROVED"},
        {"statement": "구두로 하자보수 비용 전액 포기 약정", "review_status": "REJECTED"},
        {"statement": "상대방 계좌 추가 송금 영수증 미확인분", "review_status": "PENDING"},
    ]
    res = compute_document_claim_review_summary(claims)
    assert res["approval_scope"] == "PARTIAL_APPROVED"
    assert res["approval_scope_label"] == "일부 사실 승인"
    assert res["total_claim_count"] == 3
    assert res["approved_claim_count"] == 1
    assert res["rejected_claim_count"] == 1
    assert res["pending_claim_count"] == 1
    assert "[승인된 사실 (APPROVED)]" in res["claim_review_guide"]
    assert "[반려된 주장 (REJECTED)]" in res["claim_review_guide"]
    assert "[보류/미확인 주장 (PENDING)]" in res["claim_review_guide"]


def test_build_case_evidence_briefing_claim_review_integration():
    """build_case_evidence_briefing 실행 시 각 증거 문서에 사실 승인 범위가 정확히 반영되는지 통합 검증한다."""
    db = MagicMock()

    case_obj = MagicMock(spec=Case)
    case_obj.id = "case-test-uuid"
    case_obj.title = "보증금 미반환 소송 사건"
    case_obj.case_type = "임대차분쟁"
    case_obj.status = "ACTIVE"
    case_obj.version = 1

    doc1 = MagicMock(spec=EvidenceDocument)
    doc1.id = "doc-1"
    doc1.original_filename = "E01_임대차계약서.pdf"
    doc1.source_kind = "CONTRACT"
    doc1.status = "APPROVED"
    doc1.sha256 = "hash1"
    doc1.extraction_version = "v1"
    doc1.extracted_at = None
    doc1.uploaded_at = None

    doc2 = MagicMock(spec=EvidenceDocument)
    doc2.id = "doc-2"
    doc2.original_filename = "E02_상대방주장_문자메시지.txt"
    doc2.source_kind = "MESSAGE"
    doc2.status = "REVIEW_REQUIRED"
    doc2.sha256 = "hash2"
    doc2.extraction_version = "v1"
    doc2.extracted_at = None
    doc2.uploaded_at = None

    claim1 = MagicMock(spec=EvidenceClaim)
    claim1.id = "c1"
    claim1.case_id = "case-test-uuid"
    claim1.evidence_id = "doc-1"
    claim1.statement = "보증금 3억 원 계약 체결"
    claim1.review_status = "APPROVED"

    claim2 = MagicMock(spec=EvidenceClaim)
    claim2.id = "c2"
    claim2.case_id = "case-test-uuid"
    claim2.evidence_id = "doc-2"
    claim2.statement = "보증금 전액 반환 완료했다는 상대방 문자"
    claim2.review_status = "REJECTED"

    def query_mock(model):
        m = MagicMock()
        if model == Case:
            m.filter.return_value.first.return_value = case_obj
        elif model == EvidenceDocument:
            m.filter.return_value.all.return_value = [doc1, doc2]
        elif model == EvidenceClaim:
            m.filter.return_value.all.return_value = [claim1, claim2]
        elif model == EvidenceSpan:
            m.filter.return_value.all.return_value = []
        else:
            m.filter.return_value.all.return_value = []
            m.filter.return_value.order_by.return_value.all.return_value = []
        return m

    db.query.side_effect = query_mock

    briefing = build_case_evidence_briefing(db=db, case_id="case-test-uuid")

    # 1. evidence_items 검증
    assert len(briefing.evidences) == 2
    ev1 = next(e for e in briefing.evidences if e.evidence_id == "doc-1")
    assert ev1.approval_scope == "FULL_APPROVED"
    assert ev1.approval_scope_label == "전체 사실 승인"
    assert ev1.claim_count == 1
    assert ev1.approved_claim_count == 1
    assert ev1.rejected_claim_count == 0

    ev2 = next(e for e in briefing.evidences if e.evidence_id == "doc-2")
    assert ev2.approval_scope == "ALL_REJECTED"
    assert ev2.approval_scope_label == "전체 사실 반려"
    assert ev2.claim_count == 1
    assert ev2.approved_claim_count == 0
    assert ev2.rejected_claim_count == 1

    # 2. source_documents 검증
    assert len(briefing.source_documents) == 2
    sdoc1 = next(d for d in briefing.source_documents if d["evidence_id"] == "doc-1")
    assert sdoc1["approval_scope"] == "FULL_APPROVED"
    assert "높은 신뢰도로 사실 인정" in sdoc1["claim_review_guide"]

    sdoc2 = next(d for d in briefing.source_documents if d["evidence_id"] == "doc-2")
    assert sdoc2["approval_scope"] == "ALL_REJECTED"
    assert "절대 진실한 사실로 인정하거나" in sdoc2["claim_review_guide"]

    # 3. source_registry 검증
    reg_entry = briefing.source_registry.get("E01")
    assert reg_entry is not None
    assert reg_entry["approval_scope"] == "FULL_APPROVED"
    assert reg_entry["approval_scope_label"] == "전체 사실 승인"

    # 4. formatted_summary 브리핑 텍스트 포함 여부 검증
    assert "사실검토: 전체 사실 승인" in briefing.formatted_summary
    assert "사실검토: 전체 사실 반려" in briefing.formatted_summary
