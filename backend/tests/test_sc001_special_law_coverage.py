# -*- coding: utf-8 -*-
"""SC-001 민법만 검색된 경우 특별법 누락 검증."""
from ai_legal_helper.workflows.document_consultation import enforce_housing_special_law_coverage


CIVIL = [{"source_type": "STATUTE", "statute_name": "민법", "content": "제623조"}]
HOUSING = [{"source_type": "STATUTE", "statute_name": "주택임대차보호법", "content": "제6조의2"}]


def test_civil_law_only_cannot_pass_lease_termination():
    result = enforce_housing_special_law_coverage(
        "전세보증금 반환과 계약 해지는 어떻게 되나요?", CIVIL, {"status": "PASS", "reason_code": "NONE"}
    )
    assert result["status"] == "INSUFFICIENT"
    assert result["reason_code"] == "LEGAL_SOURCE_MISSING"
    assert result["candidate_laws"] == ["주택임대차보호법"]


def test_special_law_source_keeps_existing_verification():
    original = {"status": "PASS", "reason_code": "NONE"}
    assert enforce_housing_special_law_coverage(
        "전세보증금 반환과 계약 해지는 어떻게 되나요?", CIVIL + HOUSING, original
    ) == original


def test_simple_evidence_calculation_does_not_force_statute_search():
    original = {"status": "PASS", "reason_code": "NONE"}
    assert enforce_housing_special_law_coverage(
        "보증금 중 이체된 금액은 얼마인가요?", CIVIL, original
    ) == original


def test_technical_error_is_not_masked_as_missing_law():
    result = enforce_housing_special_law_coverage(
        "전세보증금 반환", CIVIL, {"status": "INSUFFICIENT", "reason_code": "VERIFICATION_ERROR"}
    )
    assert result["reason_code"] == "VERIFICATION_ERROR"
