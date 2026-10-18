# -*- coding: utf-8 -*-
"""P2 결함 재현 및 품질 고도화 단위 테스트 스위트 (P2 Defects & Quality Tests)

이 모듈은 P2(품질 및 평가 고도화 — P2-01 ~ P2-03) 단계의 요구사항을 검증한다:
1. P2-01: Vector + Keyword Hybrid RAG, 조문 번호 직접 매칭 가중치 및 중복 청크 제거
2. P2-02: Langfuse Observability 심층 추적 메타데이터 구성 및 PII(주민번호/전화번호/API키) 마스킹
3. P2-03: 최종 답변 3계층 상태 배지 매핑 및 안전한 구조화 마크다운 데이터 모델
"""

import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from ai_legal_helper.rag.retrieval import (
    RetrievalStatus,
    RetrievalResult,
    deduplicate_chunks,
    rerank_with_article_and_keywords,
)
from ai_legal_helper.observability.langfuse_client import (
    mask_pii,
    build_consultation_trace_summary,
)
from ai_legal_helper.api.schemas.consultation import ConsultationResponse


def test_p2_01_article_boost_and_chunk_deduplication():
    """P2-01: 조문 번호 직접 매칭 가중치 부여 및 중복 청크 제거 검증."""
    # 1. 중복 청크 제거 검증: 동일한 조문/내용의 중복 청크(유사도 90% 이상)가 걸러지는지 검증
    doc1 = SimpleNamespace(
        page_content="주택임대차보호법 제6조의2(묵시적 갱신의 경우 계약의 해지) 임차인은 언제든지 임대인에게 계약해지를 통지할 수 있다.",
        metadata={"file_name": "주택임대차보호법.pdf", "page": 1, "article": "제6조의2"},
    )
    doc1_dup = SimpleNamespace(
        page_content="주택임대차보호법 제6조의2(묵시적 갱신의 경우 계약의 해지) 임차인은 언제든지 임대인에게 계약해지를 통지할 수 있다. (중복)",
        metadata={"file_name": "주택임대차보호법.pdf", "page": 1, "article": "제6조의2"},
    )
    doc2 = SimpleNamespace(
        page_content="주택임대차보호법 제7조(차임 등의 증감청구권) 당사자는 약정한 차임이나 보증금이 임차주택에 관한 조세 등의 증감으로 적절하지 아니하게 된 때에는 증감을 청구할 수 있다.",
        metadata={"file_name": "주택임대차보호법.pdf", "page": 2, "article": "제7조"},
    )

    deduped = deduplicate_chunks([doc1, doc1_dup, doc2])
    assert len(deduped) == 2, f"중복 청크가 제거되어 2건이어야 하나 {len(deduped)}건 반환됨"
    contents = [d.page_content for d in deduped]
    assert doc1.page_content in contents
    assert doc2.page_content in contents

    # 2. 질의에 명시된 조문 번호(제6조의2) 가중치 부여 검증
    # doc2(제7조)가 벡터 점수가 약간 더 높더라도(0.85 vs 0.80), 질의가 "제6조의2 해지효력"이면 doc1이 1위로 리랭킹되어야 함
    ranked = rerank_with_article_and_keywords(
        query="주택임대차보호법 제6조의2 묵시적 갱신 해지 효력",
        scored_docs=[(doc2, 0.85), (doc1, 0.80)],
        top_k=2,
    )
    assert ranked[0][0].metadata["article"] == "제6조의2", "조문 번호가 일치하는 doc1이 1위로 승격되어야 함"


def test_p2_02_pii_masking_and_trace_summary():
    """P2-02: 주민등록번호/전화번호/API키 마스킹 및 Langfuse 종합 Trace 요약 검증."""
    # 1. 민감정보(PII) 마스킹 검증
    raw_text = "제 주민번호는 900515-1234567 이고 전화번호는 010-9876-5432, API 키는 sk-abc12345678901234567890 입니다."
    masked = mask_pii(raw_text)

    assert "900515-1234567" not in masked
    assert "900515-*******" in masked or "1234567" not in masked
    assert "010-9876-5432" not in masked
    assert "010-****-5432" in masked
    assert "sk-abc12345678901234567890" not in masked
    assert "[MASKED_API_KEY]" in masked or "[MASKED]" in masked

    # 2. Trace 요약 메타데이터 구성 검증
    trace_summary = build_consultation_trace_summary(
        request_id="REQ-TEST-123",
        case_id="CASE-456",
        execution_status="COMPLETED",
        verification_status="PASS",
        answer_status="DELIVERED",
        selected_agents=["civil_agent", "verification_agent"],
        revision_count=1,
        retrieval_info={
            "used_index": "LOCAL_PERSISTENT",
            "methods": ["CHROMA_VECTOR", "OFFICIAL_STATUTE_SEARCH"],
            "hits_count": 3,
            "source_ids": ["주택임대차보호법_제6조의2"],
            "error_detail": None,
        },
        verification_info={
            "status": "PASS",
            "reason_code": "NONE",
            "citation_existence_rate": 1.0,
            "citation_support_rate": 1.0,
            "citation_coverage_rate": 0.9,
            "rejected_citations": [],
        },
        usage_info={
            "total_calls": 3,
            "total_tokens": 1250,
            "elapsed_ms": 1540.2,
        },
    )

    assert trace_summary["request_id"] == "REQ-TEST-123"
    assert trace_summary["case_id"] == "CASE-456"
    assert trace_summary["execution_status"] == "COMPLETED"
    assert trace_summary["verification_status"] == "PASS"
    assert trace_summary["answer_status"] == "DELIVERED"
    assert trace_summary["selected_agents"] == ["civil_agent", "verification_agent"]
    assert trace_summary["retrieval"]["used_index"] == "LOCAL_PERSISTENT"
    assert trace_summary["verification"]["reason_code"] == "NONE"


def test_p2_03_structured_answer_and_state_differentiation():
    """P2-03: 사용자 응답 3계층 상태 분리 및 구조화 답변 무결성 검증."""
    # 판단 유보(INSUFFICIENT/WITHHELD) 응답 객체
    resp_withheld = ConsultationResponse(
        request_id="REQ-P2-03-A",
        trace_id="TRACE-P2-03-A",
        status="SUCCESS",
        execution_status="COMPLETED",
        verification_status="INSUFFICIENT",
        answer_status="WITHHELD",
        answer="[안내: 법률적 근거 부족으로 인한 검증 안내 - INSUFFICIENT]\n관련 특별법 근거가 부족하여 확정 조언을 유보합니다.",
    )
    # 검증 완료(PASS/DELIVERED) 응답 객체
    resp_delivered = ConsultationResponse(
        request_id="REQ-P2-03-B",
        trace_id="TRACE-P2-03-B",
        status="SUCCESS",
        execution_status="COMPLETED",
        verification_status="PASS",
        answer_status="DELIVERED",
        answer="[1. 사건 요약]\n임차인이 계약 해지를 통보한 사안입니다.\n\n[2. 적용 법령 및 근거]\n주택임대차보호법 제6조의2",
    )

    # 1. 3계층 상태가 정상 분리되어 프론트엔드가 '답변 완료'와 '판단 유보'를 명확히 구분할 수 있는지 검증
    assert resp_withheld.answer_status == "WITHHELD"
    assert resp_withheld.verification_status == "INSUFFICIENT"
    assert resp_delivered.answer_status == "DELIVERED"
    assert resp_delivered.verification_status == "PASS"

