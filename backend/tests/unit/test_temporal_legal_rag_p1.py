# -*- coding: utf-8 -*-
"""
Temporal Legal RAG P1: 조문별 시행일과 적용례 상태 판정 회귀 테스트.

[테스트 정책]
- 실제 날짜/법령명에 대한 결론을 하드코딩하지 않는다. 예시는 인공 법령 픽스처다.
- 공식 XML과 사건의 날짜가 다른 경우 조문별 시행일을 우선한다.
- 공포일·파일명 날짜·법령 공통 시행일만으로 'APPLICABLE'을 반환할 수 없다.
- 법령 출처가 아닌 문서, 날짜 누락, 미확인 경과규정은 'UNCONFIRMED'를 반환한다.
- Chroma/DB/LLM/OpenLaw 네트워크를 호출하지 않는다.
"""
from types import SimpleNamespace

from ai_legal_helper.rag.source_schema import (
    build_source_from_chroma_doc,
    is_statute_applicable_to_date,
    normalize_source_dict,
)
from ai_legal_helper.rag.temporal_applicability import (
    ApplicabilityStatus,
    evaluate_statute_applicability,
    parse_legal_date,
)


def verified_article(**overrides):
    """신뢰 가능하다고 명시한 인공 법령 픽스처 (일반법 하드코딩 금지)."""
    result = {
        "source_id": "TEST-LAW-V2-ARTICLE-4",
        "source_type": "STATUTE",
        "law_id": "TEST-LAW",
        "version_id": "TEST-V2",
        "statute_name": "테스트법",
        "article": "제4조",
        "law_effective_date": "2026-06-01",
        "article_effective_date": "2027-01-15",
        "effective_date": "2027-01-15",
        "effective_date_basis": "ARTICLE_EFFECTIVE_DATE",
        "temporal_status": "VERIFIED",
    }
    result.update(overrides)
    return result


def test_strict_date_parser_rejects_invalid_or_ambiguous_dates():
    assert parse_legal_date("20270115").isoformat() == "2027-01-15"
    assert parse_legal_date("2027-01-15").isoformat() == "2027-01-15"
    for raw in ("2027-02-30", "20271315", "2027/01/15", "", None, 20270115):
        assert parse_legal_date(raw) is None


def test_verified_article_before_effective_date_is_not_applicable():
    result = evaluate_statute_applicability(verified_article(), "2026-11-01")
    assert result.status is ApplicabilityStatus.NOT_APPLICABLE
    assert result.reason_code == "BEFORE_ARTICLE_EFFECTIVE_DATE"
    assert result.article_effective_date == "2027-01-15"
    assert result.as_dict()["status"] == "NOT_APPLICABLE"


def test_verified_article_after_effective_date_can_be_applicable():
    result = evaluate_statute_applicability(verified_article(), "2027-01-16")
    assert result.status is ApplicabilityStatus.APPLICABLE
    assert result.reason_code == "TEMPORAL_APPLICATION_VERIFIED"


def test_only_law_effective_date_does_not_prove_article_applicability():
    source = verified_article(
        article_effective_date=None,
        effective_date="2026-06-01",
        effective_date_basis="LAW_EFFECTIVE_DATE",
    )
    result = evaluate_statute_applicability(source, "2026-11-01")
    assert result.status is ApplicabilityStatus.UNCONFIRMED


def test_filename_date_does_not_prove_enactment_or_applicability():
    source = normalize_source_dict({
        "source_id": "OLD-PDF",
        "source_type": "STATUTE",
        "filename": "테스트법(법률)(제9999호)(20270115).pdf",
        "statute_name": "테스트법",
        "article": "제4조",
    })
    assert source["filename_date_hint"] == "2027-01-15"
    assert source["effective_date"] is None
    assert source["article_effective_date"] is None
    assert source["temporal_status"] == "UNCONFIRMED"
    assert evaluate_statute_applicability(source, "2027-02-01").status is ApplicabilityStatus.UNCONFIRMED
    assert is_statute_applicable_to_date(source, "2027-02-01") is False


def test_chroma_source_preserves_explicit_temporal_metadata():
    doc = SimpleNamespace(page_content="제4조(시험) 공식 본문", metadata={
        "law_name": "테스트법",
        "source_type": "STATUTE",
        "law_id": "TEST-LAW",
        "version_id": "TEST-V2",
        "article": "제4조",
        "law_effective_date": "2026-06-01",
        "article_effective_date": "2027-01-15",
        "effective_date": "2027-01-15",
        "effective_date_basis": "ARTICLE_EFFECTIVE_DATE",
        "temporal_status": "VERIFIED",
        "promulgation_date": "2026-01-01",
        "addendum_id": "TEST-V2:9999",
        "content_hash": "TEST-SHA256",
        "source": "테스트법(법률)(제9999호)(20270115).pdf",
    })
    result = build_source_from_chroma_doc(doc, category="civil")
    assert result["law_id"] == "TEST-LAW"
    assert result["version_id"] == "TEST-V2"
    assert result["law_effective_date"] == "2026-06-01"
    assert result["article_effective_date"] == "2027-01-15"
    assert result["effective_date_basis"] == "ARTICLE_EFFECTIVE_DATE"
    assert result["temporal_status"] == "VERIFIED"
    assert result["addendum_id"] == "TEST-V2:9999"
    assert result["content_hash"] == "TEST-SHA256"
    assert evaluate_statute_applicability(result, "2027-01-15").status is ApplicabilityStatus.APPLICABLE


def test_review_required_never_becomes_applicable_from_date_alone():
    for confidence in ("UNCONFIRMED", "EFFECTIVE_DATE_VERIFIED", "TRANSITIONAL_REVIEW_REQUIRED", ""):
        result = evaluate_statute_applicability(
            verified_article(temporal_status=confidence), "2027-02-01"
        )
        assert result.status is ApplicabilityStatus.UNCONFIRMED


def test_applicability_rule_requires_correct_event_type():
    source = verified_article(
        applicability_rule_id="RULE-1",
        applicability_event_type="CONTRACT_EXECUTED",
    )
    assert evaluate_statute_applicability(source, "2027-02-01").status is ApplicabilityStatus.UNCONFIRMED
    assert evaluate_statute_applicability(source, "2027-02-01", event_type="CONTRACT_RENEWED").status is ApplicabilityStatus.UNCONFIRMED
    assert evaluate_statute_applicability(source, "2027-02-01", event_type="CONTRACT_EXECUTED").status is ApplicabilityStatus.APPLICABLE


def test_verified_end_date_is_exclusive_and_invalid_interval_is_unconfirmed():
    source = verified_article(effective_to="2028-01-01")
    assert evaluate_statute_applicability(source, "2027-12-31").status is ApplicabilityStatus.APPLICABLE
    assert evaluate_statute_applicability(source, "2028-01-01").status is ApplicabilityStatus.NOT_APPLICABLE
    invalid = verified_article(effective_to="2027-01-15")
    assert evaluate_statute_applicability(invalid, "2028-01-01").status is ApplicabilityStatus.UNCONFIRMED


def test_retroactivity_review_and_missing_event_do_not_make_positive_claims():
    source = verified_article(retroactivity_review_required=True)
    assert evaluate_statute_applicability(source, "2026-11-01").status is ApplicabilityStatus.UNCONFIRMED
    assert evaluate_statute_applicability(source, "").status is ApplicabilityStatus.UNCONFIRMED
    assert evaluate_statute_applicability({"source_type": "DOCUMENT"}, "2027-01-20").status is ApplicabilityStatus.UNCONFIRMED


def test_official_source_with_only_legacy_effective_date_is_unconfirmed():
    source = normalize_source_dict({
        "source_id": "OFFICIAL:LEGACY",
        "source_type": "STATUTE",
        "retrieval_method": "OFFICIAL_STATUTE_SEARCH",
        "law_id": "TEST-LAW",
        "article": "제4조",
        "effective_date": "2027-01-15",
    })
    assert source["effective_date"] == "2027-01-15"
    assert source["effective_date_basis"] == "LEGACY_UNVERIFIED"
    assert evaluate_statute_applicability(source, "2027-02-01").status is ApplicabilityStatus.UNCONFIRMED
