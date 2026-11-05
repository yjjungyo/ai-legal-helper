# -*- coding: utf-8 -*-
"""P5 독립 Temporal Law Resolver 안전회귀. 외부 법령/DB/LLM 사용 안 함."""
import copy
import json

import pytest

from ai_legal_helper.legal_knowledge.temporal_resolver import (
    resolve_event, evaluate_temporal_sources as _evaluate_temporal_sources,
)


def _semantic_mock(prompt: str) -> str:
    if prompt.startswith("독립 검증자입니다"):
        return json.dumps({
            "supported": True, "complete": True,
            "exceptions_accounted_for": True,
        })
    if '"target_article": "제37조"' in prompt:
        return json.dumps({
            "is_relevant": False, "coverage_complete": True,
            "event_types": [], "condition": None,
            "event_evidence": "", "condition_evidence": "",
            "has_exception": False, "has_transition": False,
            "has_retroactivity": False,
        })
    transitional = "제3조(경과조치)" in prompt
    unsupported = "공포일 이후에 시행할 수 있다" in prompt
    multi = "갱신 또는 변경" in prompt
    short_contract = "계약부터 적용한다" in prompt
    if multi:
        events = ["CONTRACT_SIGNED", "CONTRACT_RENEWED", "CONTRACT_MODIFIED"]
        event_quote = "계약을 체결하거나 갱신 또는 변경하는 경우부터 적용한다"
    elif short_contract:
        events = ["CONTRACT_SIGNED"]
        event_quote = "계약부터 적용한다"
    else:
        events = ["CONTRACT_SIGNED"]
        event_quote = "계약을 체결하는 경우부터 적용한다"
    return json.dumps({
        "is_relevant": True, "coverage_complete": not unsupported,
        "event_types": events, "condition": "ON_OR_AFTER_EFFECTIVE_DATE",
        "event_evidence": event_quote,
        "condition_evidence": "이 영 시행 이후",
        "has_exception": False, "has_transition": transitional,
        "has_retroactivity": False,
    })


def evaluate_temporal_sources(*args, **kwargs):
    kwargs.setdefault("llm_addendum_interpretation", True)
    kwargs.setdefault("addendum_invoke_fn", _semantic_mock)
    kwargs.setdefault("addendum_review_fn", _semantic_mock)
    return _evaluate_temporal_sources(*args, **kwargs)


def article(version="200", when="2027-04-28", article_name="제36조"):
    return {
        "source_type": "STATUTE", "source_id": f"OFFICIAL:110:{version}:{article_name}",
        "law_id": "110", "version_id": version, "statute_name": "가상법 시행령",
        "article": article_name, "content": f"{article_name}(계약신고) 본문",
        "article_effective_date": when,
        "effective_date_basis": "ARTICLE_EFFECTIVE_DATE",
        "version_lookup_status": "HISTORY_COMPLETE",
        "temporal_status": "EFFECTIVE_DATE_VERIFIED",
    }


def addendum(content, version="200", number="9999"):
    return {
        "source_type": "STATUTE", "source_id": f"ADDENDUM:{version}",
        "law_id": "110", "version_id": version, "statute_name": "가상법 시행령",
        "article": "부칙", "content": content,
        "addendum_id": f"{version}:{number}:0",
    }


SIMPLE = (
    "제1조(시행일) 이 영은 공포 후 6개월이 경과한 날부터 시행한다. "
    "제2조(적용례) 제36조의 개정규정은 이 영 시행 이후 계약을 체결하는 경우부터 적용한다."
)
MULTI = (
    "제1조(시행일) 이 영은 공포 후 6개월이 경과한 날부터 시행한다. "
    "제2조(적용례) 제36조의 개정규정은 이 영 시행 이후 계약을 체결하거나 갱신 또는 변경하는 경우부터 적용한다."
)


def test_explicit_event_resolves_contract_without_todays_date():
    result = resolve_event("", event_date="2027-04-28", event_type="CONTRACT_SIGNED")
    assert result.status == "RESOLVED"
    assert result.selected.date == "2027-04-28"
    assert result.selected.origin == "CALLER_VERIFIED"


def test_multiple_events_requires_clarification():
    result = resolve_event(
        "2026년 11월 1일 계약 체결, 2027년 6월 3일 갱신했습니다."
    )
    assert result.status == "AMBIGUOUS"
    assert result.selected is None


def test_promulgation_date_is_not_treated_as_contract_date():
    result = resolve_event(
        "개정령은 2026년 10월 27일 공포, 2026년 11월 1일 계약 체결했습니다."
    )
    assert result.status == "RESOLVED"
    assert result.selected.date == "2026-11-01"


def test_no_event_date_does_not_fallback_to_now():
    result = resolve_event("이 규정은 언제부터 적용됩니까?")
    assert result.selected is None
    assert result.status == "UNCONFIRMED"


def test_simple_rule_after_effective_and_event_confirmed_can_be_applied():
    result = evaluate_temporal_sources(
        "", [article(), addendum(SIMPLE)],
        event_date="2027-06-01", event_type="CONTRACT_SIGNED",
    )
    assert result.status == "APPLICABLE"
    decision = result.decisions[0]
    assert decision.applicability_rule_id
    assert decision.matched_addendum_id == "200:9999:0"
    assert "시행 이후" in decision.rule_span


def test_simple_rule_before_effective_is_not_applicable():
    result = evaluate_temporal_sources(
        "", [article(), addendum(SIMPLE)],
        event_date="2026-11-01", event_type="CONTRACT_SIGNED",
    )
    assert result.status == "NOT_APPLICABLE"
    assert result.decisions[0].reason_code == "BEFORE_ARTICLE_EFFECTIVE_DATE"


def test_multi_event_application_rule_is_supported_when_semantically_verified():
    result = evaluate_temporal_sources(
        "", [article(), addendum(MULTI)],
        event_date="2027-05-01", event_type="CONTRACT_SIGNED",
    )
    assert result.status == "APPLICABLE"
    assert result.decisions[0].reason_code == "TEMPORAL_APPLICATION_VERIFIED"


def test_transitional_provision_blocks_simple_rule():
    payload = SIMPLE + " 제3조(경과조치) 종전의 규정에 따른 신청은 종전의 규정에 따른다."
    out = evaluate_temporal_sources(
        "", [article(), addendum(payload)],
        event_date="2027-05-01", event_type="CONTRACT_SIGNED",
    )
    assert out.status == "UNCONFIRMED"
    assert out.decisions[0].reason_code == "TRANSITIONAL_REVIEW_REQUIRED"


def test_source_version_and_addendum_must_be_exactly_linked():
    out = evaluate_temporal_sources(
        "", [article(version="200"), addendum(SIMPLE, version="201")],
        event_date="2027-05-01", event_type="CONTRACT_SIGNED",
    )
    assert out.status == "UNCONFIRMED"
    assert out.decisions[0].reason_code == "MATCHING_ADDENDUM_MISSING"


def test_date_metadata_alone_does_not_count_as_verified():
    source = article()
    source["version_lookup_status"] = "DATE_NOT_SPECIFIED"
    out = evaluate_temporal_sources(
        "", [source, addendum(SIMPLE)],
        event_date="2027-05-01", event_type="CONTRACT_SIGNED",
    )
    assert out.status == "UNCONFIRMED"
    assert out.decisions[0].reason_code == "HISTORICAL_VERSION_NOT_VERIFIED"


def test_missing_article_date_does_not_inherit_law_wide_date():
    source = article()
    source["article_effective_date"] = None
    source["law_effective_date"] = "2027-04-28"
    out = evaluate_temporal_sources(
        "", [source, addendum(SIMPLE)],
        event_date="2027-05-01", event_type="CONTRACT_SIGNED",
    )
    assert out.status == "UNCONFIRMED"
    assert out.decisions[0].reason_code == "ARTICLE_EFFECTIVE_DATE_UNCONFIRMED"


def test_wrong_event_type_cannot_pass_verified():
    out = evaluate_temporal_sources(
        "", [article(), addendum(SIMPLE)],
        event_date="2027-05-01", event_type="CONTRACT_RENEWED",
    )
    assert out.status == "UNCONFIRMED"
    assert out.decisions[0].reason_code == "EVENT_TYPE_MISMATCH"


def test_unsupported_complex_rules_are_not_assumed_simple():
    out = evaluate_temporal_sources(
        "", [article(), addendum("제2조(적용례) 제36조의 규정은 공포일 이후에 시행할 수 있다.")],
        event_date="2027-05-01", event_type="CONTRACT_SIGNED",
    )
    assert out.status == "UNCONFIRMED"


def test_original_sources_not_mutated():
    original = [article(), addendum(SIMPLE)]
    baseline = copy.deepcopy(original)
    evaluate_temporal_sources(
        "", original, event_date="2027-05-01", event_type="CONTRACT_SIGNED",
    )
    assert original == baseline


def test_statute_without_article_is_unconfirmed():
    result = evaluate_temporal_sources(
        "", [addendum(SIMPLE)], event_date="2027-05-01", event_type="CONTRACT_SIGNED",
    )
    assert result.status == "UNCONFIRMED"
    assert result.missing_evidence == ["OFFICIAL_ARTICLE_SOURCE_MISSING"]


def test_incorrect_explicit_event_date_fails_closed():
    result = resolve_event("", event_date="2027-02-30", event_type="CONTRACT_SIGNED")
    assert result.status == "UNCONFIRMED"


def test_unrelated_addendum_rule_does_not_qualify_another_article():
    out = evaluate_temporal_sources(
        "", [article(article_name="제37조"), addendum(SIMPLE)],
        event_date="2027-05-01", event_type="CONTRACT_SIGNED",
    )
    assert out.status == "UNCONFIRMED"
    assert out.decisions[0].reason_code == "APPLICATION_PROVISION_NOT_FOUND"



def test_real_addendum_wording_contract_from_apply_not_regex_dependent():
    wording = (
        "제1조(시행일) 이 영은 2027년 4월 28일부터 시행한다. "
        "제2조(적용례) 제36조의 개정규정은 이 영 시행 이후 체결하는 계약부터 적용한다."
    )
    def mock(prompt):
        if prompt.startswith("독립 검증자입니다"):
            return _semantic_mock(prompt)
        return json.dumps({
            "is_relevant": True, "coverage_complete": True,
            "event_types": ["CONTRACT_SIGNED"],
            "condition": "ON_OR_AFTER_EFFECTIVE_DATE",
            "event_evidence": "체결하는 계약부터 적용한다",
            "condition_evidence": "이 영 시행 이후",
            "has_exception": False, "has_transition": False,
            "has_retroactivity": False,
        })
    before = evaluate_temporal_sources(
        "", [article(), addendum(wording)],
        event_date="2026-11-01", event_type="CONTRACT_SIGNED",
        addendum_invoke_fn=mock,
    )
    assert before.status == "NOT_APPLICABLE"
    after = evaluate_temporal_sources(
        "", [article(), addendum(wording)],
        event_date="2027-05-01", event_type="CONTRACT_SIGNED",
        addendum_invoke_fn=mock,
    )
    assert after.status == "APPLICABLE"


def test_independent_reviewer_rejection_never_claims_applicable():
    rejected = lambda _: json.dumps({
        "supported": False, "complete": True,
        "exceptions_accounted_for": True,
    })
    out = evaluate_temporal_sources(
        "", [article(), addendum(SIMPLE)],
        event_date="2027-05-01", event_type="CONTRACT_SIGNED",
        addendum_review_fn=rejected,
    )
    assert out.status == "UNCONFIRMED"
    assert out.decisions[0].reason_code == "LLM_ADDENDUM_REVIEW_REJECTED"


def test_no_semantic_model_never_uses_regex_as_legal_fallback():
    out = _evaluate_temporal_sources(
        "", [article(), addendum(SIMPLE)],
        event_date="2027-05-01", event_type="CONTRACT_SIGNED",
        llm_addendum_interpretation=False,
    )
    assert out.status == "UNCONFIRMED"
    assert out.decisions[0].reason_code == "LLM_ADDENDUM_DISABLED"



def test_actual_multi_event_contract_from_apply_wording():
    """Regression: 체결/갱신/변경하는 계약부터 적용한다 (no '경우부터')."""
    addendum_text = (
        "제1조(시행일) 이 영은 2027년 4월 28일부터 시행한다. "
        "제2조(임대차신고에 관한 적용례) 제36조의 개정규정은 이 영 시행 이후 "
        "체결하거나 갱신 또는 변경하는 계약부터 적용한다."
    )
    def interpret(prompt):
        if prompt.startswith("독립 검증자입니다"):
            return _semantic_mock(prompt)
        return json.dumps({
            "is_relevant": True, "coverage_complete": True,
            "event_types": [
                "CONTRACT_SIGNED", "CONTRACT_RENEWED", "CONTRACT_MODIFIED",
            ],
            "condition": "ON_OR_AFTER_EFFECTIVE_DATE",
            "event_evidence": "체결하거나 갱신 또는 변경하는 계약부터 적용한다",
            "condition_evidence": "이 영 시행 이후",
            "has_exception": False, "has_transition": False,
            "has_retroactivity": False,
        })
    for kind, event_date, expected in (
        ("CONTRACT_SIGNED", "2026-11-01", "NOT_APPLICABLE"),
        ("CONTRACT_SIGNED", "2027-04-28", "APPLICABLE"),
        ("CONTRACT_RENEWED", "2027-05-01", "APPLICABLE"),
        ("CONTRACT_MODIFIED", "2027-06-01", "APPLICABLE"),
    ):
        result = evaluate_temporal_sources(
            "", [article(), addendum(addendum_text)],
            event_date=event_date, event_type=kind,
            addendum_invoke_fn=interpret,
        )
        assert result.status == expected, (kind, event_date, result.as_dict())
