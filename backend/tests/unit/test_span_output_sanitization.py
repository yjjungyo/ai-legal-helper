# -*- coding: utf-8 -*-
"""
테스트 모듈: test_span_output_sanitization.py

[테스트 목적]
1. `decorators.py`의 `_sanitize_span_output` 함수가 Langfuse Trace 덤프 및 KPI 측정을 위해
   사건 증거 문서, 브리핑 객체, 검색 출처, 단위 쟁점 검증 결과, 검증 클레임 리스트 등의 원본 데이터를
   일절 축약(strip/truncate/field omission)하지 않고 온전하게 100% 보존하는지 검증한다.
2. 관측용 Span Output 기록 과정에서 민감정보(주민등록번호, 전화번호 등 PII)는 안전하게 마스킹되는지 확인한다.
"""
import pytest
from ai_legal_helper.observability.decorators import _sanitize_span_output


def test_sanitize_span_output_none_and_primitives():
    """None, 숫자, 불리언 등 기본형 출력값은 원형을 유지해야 한다."""
    assert _sanitize_span_output("test_node", None) is None
    assert _sanitize_span_output("test_node", 123) == 123
    assert _sanitize_span_output("test_node", True) is True
    assert _sanitize_span_output("test_node", "짧은 문자열") == "짧은 문자열"


def test_sanitize_span_output_case_evidence_briefing_preserves_full_data():
    """사건 증거 브리핑 객체의 모든 사실, 타임라인, 원문 문서 리스트가 strip 없이 온전히 보존되는지 검증."""
    huge_briefing = {
        "case_id": "test-case-uuid-1234",
        "title": "보증금 반환 청구 소송",
        "case_type": "주택임대차",
        "facts": [{"fact_id": f"f_{i}", "statement": f"사실관계 {i} " + "A" * 500} for i in range(15)],
        "timeline": [{"event_date": "2024-01-01", "description": "계약 체결"} for _ in range(10)],
        "source_documents": [{"doc_id": f"doc_{i}", "content": "문서 전문 " * 100} for i in range(17)],
        "source_registry": {f"E{i:02d}": {"filename": f"doc_{i}.pdf", "content": "내용 " * 100} for i in range(17)},
        "formatted_summary": "사건 브리핑 상세 요약입니다. " * 50,
    }

    raw_output = {"case_evidence_briefing": huge_briefing, "status": "SUCCESS"}
    sanitized = _sanitize_span_output("intent_analysis_node", raw_output)

    assert "case_evidence_briefing" in sanitized
    brief = sanitized["case_evidence_briefing"]
    assert brief["case_id"] == "test-case-uuid-1234"
    # 원본 리스트와 딕셔너리가 strip 되지 않고 전체 보존되어야 함
    assert len(brief["facts"]) == 15
    assert len(brief["timeline"]) == 10
    assert len(brief["source_documents"]) == 17
    assert len(brief["source_registry"]) == 17
    assert brief["formatted_summary"] == huge_briefing["formatted_summary"]


def test_sanitize_span_output_case_evidence_sources_preserves_full_list_and_content():
    """case_evidence_sources가 상위 10개로 잘리지 않고 전체 항목 및 content 전문을 보존하는지 검증."""
    huge_sources = [
        {
            "evidence_label": f"E{i:02d}",
            "document_name": f"계약서_{i}.txt",
            "source_type": "CASE_EVIDENCE",
            "review_status": "APPROVED",
            "content": f"원문 텍스트 전문 {i} " * 50,
        }
        for i in range(20)
    ]

    raw_output = {"case_evidence_sources": huge_sources}
    sanitized = _sanitize_span_output("intent_analysis_node", raw_output)

    assert "case_evidence_sources" in sanitized
    sources = sanitized["case_evidence_sources"]
    # 20개 전체 보존 (strip 없음)
    assert len(sources) == 20
    assert sources[0]["content"].startswith("원문 텍스트 전문 0")
    assert sources[19]["document_name"] == "계약서_19.txt"


def test_sanitize_span_output_retrieved_sources_and_verification_result_preserves_all():
    """KPI 측정의 핵심인 verification_result.claims, issue_results, retrieved_sources 전문이 온전히 보존되는지 검증."""
    huge_retrieved = [
        {
            "source_id": f"STATUTE_LAW_{i}",
            "source_type": "STATUTE",
            "law_name": f"주택임대차보호법 제{i}조",
            "content": f"법령 조항 원문 전문 {i} " * 50,
        }
        for i in range(12)
    ]

    huge_issue_results = [
        {
            "task_id": f"task_{i}",
            "status": "VERIFIED",
            "core_issue": f"쟁점 {i} 대항력 충족 여부",
            "supported_statute_ids": [f"STATUTE_LAW_{i}"],
            "unsupported_claims": [],
            "full_claim_analysis_dump": f"분석 결과 덤프 {i} " * 50,
        }
        for i in range(5)
    ]

    huge_verification_result = {
        "status": "PASS",
        "reason_code": "ALL_VERIFIED",
        "candidate_laws": ["주택임대차보호법 제3조"],
        "claims": [{"claim_text": f"주장 {i}", "grounding_status": "SUPPORTED"} for i in range(25)],
        "warnings": [],
        "revision_instructions": [],
        "issue_results": huge_issue_results,
        "citation_audit": {
            "audit_status": "VALID",
            "verified_sources": [{"source_id": f"STATUTE_LAW_{i}"} for i in range(5)],
            "unverified_citations": [],
        },
    }

    raw_output = {
        "verification_result": huge_verification_result,
        "retrieved_sources": huge_retrieved,
        "issue_results": huge_issue_results,
    }

    sanitized = _sanitize_span_output("verification_node", raw_output)

    # 1. retrieved_sources 12건 전체 및 content 전문 보존 검증
    assert len(sanitized["retrieved_sources"]) == 12
    assert sanitized["retrieved_sources"][0]["content"].startswith("법령 조항 원문 전문 0")

    # 2. issue_results 5건 전체 및 세부 분석 덤프 보존 검증
    assert len(sanitized["issue_results"]) == 5
    assert "full_claim_analysis_dump" in sanitized["issue_results"][0]

    # 3. verification_result의 claims 25건 전체 리스트 온전 보존 검증 (claims_count로 축약되지 않음)
    assert "claims" in sanitized["verification_result"]
    assert len(sanitized["verification_result"]["claims"]) == 25
    assert sanitized["verification_result"]["claims"][0]["claim_text"] == "주장 0"
    assert len(sanitized["verification_result"]["issue_results"]) == 5


def test_sanitize_span_output_pii_masking_without_truncation():
    """case_context 및 긴 문자열 내 PII는 안전하게 마스킹되면서 문자열 길이는 잘리지(strip) 않는지 검증."""
    sensitive_context = "의뢰인 연락처는 010-1234-5678 이며 주민번호는 900101-1234567 입니다. 상세 사건 정황 " + "X" * 3500
    raw_output = {"case_context": sensitive_context}

    sanitized = _sanitize_span_output("intent_analysis_node", raw_output)

    # PII 마스킹 확인
    assert "010-1234-5678" not in sanitized["case_context"]
    assert "900101-1234567" not in sanitized["case_context"]
    assert "010-****-5678" in sanitized["case_context"]
    assert "900101-*******" in sanitized["case_context"]
    # 3000자 초과여도 strip(자르기)되지 않고 원문 길이가 온전히 유지되는지 확인
    assert len(sanitized["case_context"]) > 3500
    assert "원문 축약" not in sanitized["case_context"]

