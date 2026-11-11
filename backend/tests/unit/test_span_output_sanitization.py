# -*- coding: utf-8 -*-
"""
테스트 모듈: test_span_output_sanitization.py

[테스트 목적]
1. `decorators.py`의 `_sanitize_span_output` 함수가 대용량 증거 문서, 브리핑 객체, 검색 출처,
   단위 쟁점 검증 결과 등의 거대 페이로드를 안전하고 간결한 관측 요약본으로 축약하는지 검증한다.
2. 관측용 Span Output 기록 과정에서 민감정보(PII)가 마스킹되는지 확인한다.
3. `legal_workflow.py`의 `case_evidence_sources`가 중복 원문(content)을 배제하고 경량화되는지 검증한다.
"""
import pytest
from ai_legal_helper.observability.decorators import _sanitize_span_output


def test_sanitize_span_output_none_and_primitives():
    """None, 숫자, 불리언 등 기본형 출력값은 원형을 유지해야 한다."""
    assert _sanitize_span_output("test_node", None) is None
    assert _sanitize_span_output("test_node", 123) == 123
    assert _sanitize_span_output("test_node", True) is True
    assert _sanitize_span_output("test_node", "짧은 문자열") == "짧은 문자열"


def test_sanitize_span_output_case_evidence_briefing():
    """수백 KB에 달하는 사건 증거 브리핑 객체가 통계 요약 및 프리뷰로 경량화되는지 검증."""
    huge_briefing = {
        "case_id": "test-case-uuid-1234",
        "title": "보증금 반환 청구 소송",
        "case_type": "주택임대차",
        "facts": [{"fact_id": f"f_{i}", "statement": f"사실관계 {i} " + "A" * 500} for i in range(15)],
        "timeline": [{"event_date": "2024-01-01", "description": "계약 체결"} for _ in range(10)],
        "source_documents": [{"doc_id": f"doc_{i}", "content": "문서 전문 " * 1000} for i in range(17)],
        "source_registry": {f"E{i:02d}": {"filename": f"doc_{i}.pdf", "content": "내용 " * 1000} for i in range(17)},
        "formatted_summary": "사건 브리핑 상세 요약입니다. " * 50,
    }

    raw_output = {"case_evidence_briefing": huge_briefing, "status": "SUCCESS"}
    sanitized = _sanitize_span_output("intent_analysis_node", raw_output)

    assert "case_evidence_briefing" in sanitized
    brief_summary = sanitized["case_evidence_briefing"]
    assert brief_summary["case_id"] == "test-case-uuid-1234"
    assert brief_summary["facts_count"] == 15
    assert brief_summary["timeline_count"] == 10
    assert brief_summary["documents_count"] == 17
    assert brief_summary["source_registry_count"] == 17
    assert len(brief_summary["summary_preview"]) <= 300
    assert brief_summary["summary_preview"].endswith("...")


def test_sanitize_span_output_case_evidence_sources():
    """원문 텍스트 전문이 포함된 case_evidence_sources가 메타데이터 아이템으로 경량화되는지 검증."""
    huge_sources = [
        {
            "evidence_label": f"E{i:02d}",
            "document_name": f"계약서_{i}.txt",
            "source_type": "CASE_EVIDENCE",
            "review_status": "APPROVED",
            "content": "대용량 원문 텍스트 " * 500,
        }
        for i in range(20)
    ]

    raw_output = {"case_evidence_sources": huge_sources}
    sanitized = _sanitize_span_output("intent_analysis_node", raw_output)

    assert "case_evidence_sources" in sanitized
    sources_summary = sanitized["case_evidence_sources"]
    assert sources_summary["total_count"] == 20
    assert len(sources_summary["items"]) == 10  # 상위 10개만 보존
    # 원문 content 키가 제외되었는지 확인
    for item in sources_summary["items"]:
        assert "content" not in item
        assert "document_name" in item


def test_sanitize_span_output_retrieved_sources_and_issue_results():
    """검증 노드의 510KB 대용량 출처 및 중복 쟁점 결과가 컴팩트하게 정제되는지 검증."""
    huge_retrieved = [
        {
            "source_id": f"STATUTE_LAW_{i}",
            "source_type": "STATUTE",
            "law_name": f"주택임대차보호법 제{i}조",
            "content": "법령 원문 텍스트 조항 전체 " * 200,
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
            "full_claim_analysis_dump": "수십 킬로바이트 분석 결과 덤프 " * 500,
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

    # 1. retrieved_sources 검증
    assert sanitized["retrieved_sources"]["total_count"] == 12
    assert len(sanitized["retrieved_sources"]["items"]) == 10
    assert "법령 원문" in sanitized["retrieved_sources"]["items"][0]["content_preview"]
    assert len(sanitized["retrieved_sources"]["items"][0]["content_preview"]) <= 150

    # 2. issue_results 검증
    assert len(sanitized["issue_results"]) == 5
    for r in sanitized["issue_results"]:
        assert "full_claim_analysis_dump" not in r
        assert r["status"] == "VERIFIED"
        assert "core_issue" in r

    # 3. verification_result 검증
    ver_sanitized = sanitized["verification_result"]
    assert ver_sanitized["status"] == "PASS"
    assert ver_sanitized["claims_count"] == 25
    assert ver_sanitized["issue_results_count"] == 5
    assert ver_sanitized["citation_audit"]["verified_count"] == 5


def test_sanitize_span_output_pii_masking_in_context():
    """case_context 및 긴 문자열 내 전화번호/주민번호 등 PII가 안전하게 마스킹되는지 검증."""
    sensitive_context = "의뢰인 연락처는 010-1234-5678 이며 주민번호는 900101-1234567 입니다." * 10
    raw_output = {"case_context": sensitive_context}

    sanitized = _sanitize_span_output("intent_analysis_node", raw_output)

    assert "010-1234-5678" not in sanitized["case_context"]
    assert "900101-1234567" not in sanitized["case_context"]
    assert "010-****-5678" in sanitized["case_context"]
    assert "900101-*******" in sanitized["case_context"]
