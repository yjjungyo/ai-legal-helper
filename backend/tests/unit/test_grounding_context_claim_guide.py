# -*- coding: utf-8 -*-
"""출처 접지 컨텍스트(format_grounding_sources)의 사실 승인 지침 결합 단위 테스트.

[역할]
사건 증거(CASE_EVIDENCE)를 LLM 프롬프트에 주입할 때, 단순 문서 본문만 통째로 넣는 것이 아니라
사용자가 검토한 사실 승인 범위(approval_scope) 및 승인/반려 지침(claim_review_guide)이
정확하게 원문 상단에 결합되어 LLM에 전달되는지 검증한다.

[검증 항목]
1. FULL_APPROVED 증거 문서: 메타데이터에 approval_scope 포함 및 서두 지침 주입
2. PARTIAL_APPROVED 증거 문서: 반려된 주장(REJECTED) 배제 경고 및 승인 사실 분리 주입
3. Source 및 StandardSource 스키마: approval_scope, claim_review_guide 필드 보존
"""

import pytest
from ai_legal_helper.rag.grounding_context import format_grounding_sources
from ai_legal_helper.rag.source_schema import normalize_source_dict
from ai_legal_helper.api.schemas.consultation import Source


def test_format_grounding_sources_with_full_approved_guide():
    """전체 사실 승인 문서에 대해 메타데이터와 승인 지침이 본문 상단에 결합되는지 검증한다."""
    sources = [
        {
            "source_id": "E01_임대차계약서.txt",
            "source_type": "CASE_EVIDENCE",
            "evidence_id": "doc-uuid-1",
            "document_name": "E01_임대차계약서.txt",
            "approval_scope": "FULL_APPROVED",
            "approval_scope_label": "전체 사실 승인",
            "approved_claim_count": 2,
            "rejected_claim_count": 0,
            "pending_claim_count": 0,
            "claim_review_guide": "■ 사실 승인 구분: [전체 사실 승인] (총 2건 전원 승인 완료)\n- 확인된 승인 사실 목록:\n  * \"보증금 3억 원\"\n👉 지침: 문서에서 추출된 모든 주요 사실이 사용자에 의해 검증·승인되었습니다.",
            "content": "임대차계약서 원문 본문 내용입니다. 보증금 3억 원.",
        }
    ]

    context, manifest = format_grounding_sources(sources)

    # 1. 메타데이터에 approval_scope 및 approval_scope_label 포함 여부
    assert '"approval_scope": "FULL_APPROVED"' in context
    assert '"approval_scope_label": "전체 사실 승인"' in context

    # 2. 본문 상단에 사실 검토 및 인용 지침 섹션 결합 여부
    assert "[사실 검토 및 인용 지침]" in context
    assert "■ 사실 승인 구분: [전체 사실 승인]" in context
    assert "👉 지침: 문서에서 추출된 모든 주요 사실이 사용자에 의해 검증·승인되었습니다." in context

    # 3. 본문 텍스트 유지 여부
    assert "본문:\n임대차계약서 원문 본문 내용입니다." in context
    assert manifest["source_count"] == 1


def test_format_grounding_sources_with_partial_approved_and_rejected_claims():
    """반려된 주장이 포함된 문서에 대해 배제 경고 지침이 본문 상단에 명시되는지 검증한다."""
    sources = [
        {
            "source_id": "E02_상대방_문자메시지.txt",
            "source_type": "CASE_EVIDENCE",
            "evidence_id": "doc-uuid-2",
            "document_name": "E02_상대방_문자메시지.txt",
            "approval_scope": "PARTIAL_APPROVED",
            "approval_scope_label": "일부 사실 승인",
            "approved_claim_count": 1,
            "rejected_claim_count": 1,
            "pending_claim_count": 0,
            "claim_review_guide": "■ 사실 승인 구분: [일부 사실 승인]\n- [승인된 사실 (APPROVED)]:\n  * \"2026.04.01 퇴거 통지 수신\"\n- [반려된 주장 (REJECTED)] (주의: 의뢰인이 배제/기각한 내용. 절대 사실로 채택하거나 불리한 근거로 쓰지 마십시오):\n  * \"보증금 전액 반환 합의 완료\"",
            "content": "상대방 문자 원문입니다. 4월 1일 퇴거 통지 받았고 합의 완료되었다고 주장함.",
        }
    ]

    context, manifest = format_grounding_sources(sources)

    # 1. 메타데이터 확인
    assert '"approval_scope": "PARTIAL_APPROVED"' in context

    # 2. 반려된 주장 배제 경고문이 프롬프트 context에 명시적으로 주입되었는지 확인
    assert "[반려된 주장 (REJECTED)]" in context
    assert "절대 사실로 채택하거나 불리한 근거로 쓰지 마십시오" in context
    assert "[승인된 사실 (APPROVED)]" in context


def test_source_schemas_preserve_claim_review_fields():
    """Source 및 StandardSource 스키마 정규화 시 approval_scope와 claim_review_guide가 누락 없이 보존되는지 검증한다."""
    raw = {
        "source_id": "E01_임대차계약서.txt",
        "source_type": "CASE_EVIDENCE",
        "evidence_id": "doc-uuid-1",
        "filename": "E01_임대차계약서.txt",
        "approval_scope": "FULL_APPROVED",
        "approval_scope_label": "전체 사실 승인",
        "claim_review_guide": "지침 텍스트",
        "approved_claim_count": 5,
        "rejected_claim_count": 0,
        "pending_claim_count": 0,
    }

    norm = normalize_source_dict(raw)
    assert norm["approval_scope"] == "FULL_APPROVED"
    assert norm["approval_scope_label"] == "전체 사실 승인"
    assert norm["claim_review_guide"] == "지침 텍스트"
    assert norm["approved_claim_count"] == 5

    source_obj = Source(**norm)
    assert source_obj.approval_scope == "FULL_APPROVED"
    assert source_obj.approval_scope_label == "전체 사실 승인"
    assert source_obj.claim_review_guide == "지침 텍스트"
