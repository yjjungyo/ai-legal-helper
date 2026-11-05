"""LLM 사건일 추출은 원문 일치·날짜 검증을 통과해야만 승인된다."""
import json
import pytest
from ai_legal_helper.workflows.temporal_search_plan import extract_event_with_llm


def _invoke(data):
    return lambda prompt: json.dumps(data, ensure_ascii=False)


def test_grounded_multiple_date_event():
    q = "2026년 10월 27일 공포된 시행령이 2026년 11월 1일 체결한 계약에 적용되나요?"
    result = extract_event_with_llm(q, _invoke({
        "date": "2026-11-01", "event_type": "CONTRACT_SIGNED",
        "evidence": "2026년 11월 1일 체결한 계약",
    }))
    assert result.status == "RESOLVED"
    assert result.selected.date == "2026-11-01"


def test_hallucinated_date_is_rejected():
    q = "2026년 11월 1일 계약을 체결했습니다."
    result = extract_event_with_llm(q, _invoke({
        "date": "2027-11-01", "event_type": "CONTRACT_SIGNED",
        "evidence": q,
    }))
    assert result.status == "UNCONFIRMED"


def test_ungrounded_evidence_is_rejected():
    result = extract_event_with_llm("계약일을 모르겠습니다.", _invoke({
        "date": "2026-11-01", "event_type": "CONTRACT_SIGNED",
        "evidence": "2026년 11월 1일 체결",
    }))
    assert result.status == "UNCONFIRMED"


def test_invalid_json_fails_closed():
    result = extract_event_with_llm("2026년 11월 1일 계약 체결", lambda prompt: "not json")
    assert result.status == "UNCONFIRMED"


def test_sc003_contract_date_not_promulgation_date():
    q = (
        "저는 120세대 규모의 등록 민간임대주택을 운영하는 임대사업자입니다. "
        "2026년 11월 1일 임차인과 새로운 계약을 체결하려고 합니다. "
        "2026년 10월 27일 개정된 시행령에 따라 관리비와 전기·수도료의 "
        "부과금액 또는 산정방식을 임대차계약 신고에 반드시 포함해야 하나요?"
    )
    result = extract_event_with_llm(q, _invoke({
        "date": "2026-11-01", "event_type": "CONTRACT_SIGNED",
        "evidence": "2026년 11월 1일 임차인과 새로운 계약을 체결하려고 합니다.",
    }))
    assert result.status == "RESOLVED"
    assert result.selected.date == "2026-11-01"


def test_promulgation_date_rejected_even_when_contract_appears_later():
    q = "2026년 10월 27일 개정된 시행령에 따라 2026년 11월 1일 계약을 체결합니다."
    result = extract_event_with_llm(q, _invoke({
        "date": "2026-10-27", "event_type": "CONTRACT_SIGNED",
        "evidence": q,
    }))
    assert result.status == "UNCONFIRMED"


def test_two_digit_year_llm_grounded_event():
    q = "26.11.06 신규 계약을 체결합니다. 개정 시행령 적용 여부를 알려주세요."
    result = extract_event_with_llm(q, _invoke({
        "date": "2026-11-06", "event_type": "CONTRACT_SIGNED",
        "evidence": "26.11.06 신규 계약을 체결합니다.",
    }))
    assert result.status == "RESOLVED"
    assert result.selected.date == "2026-11-06"


def test_mismatched_month_day_is_rejected():
    q = "26.11.06 계약을 체결합니다."
    result = extract_event_with_llm(q, _invoke({
        "date": "2026-11-07", "event_type": "CONTRACT_SIGNED",
        "evidence": q,
    }))
    assert result.status == "UNCONFIRMED"


@pytest.mark.parametrize("date_text", [
    "2026-11-06", "2026.11.06", "2026/11/06", "2026년 11월 6일", "2026년11월6일",
])
def test_supported_date_notations_resolve(date_text):
    """구분자와 공백이 달라도 인용된 사건일의 숫자를 올바르게 검증한다."""
    question = f"{date_text} 계약을 체결했습니다."
    result = extract_event_with_llm(question, _invoke({
        "date": "2026-11-06", "event_type": "CONTRACT_SIGNED", "evidence": question,
    }))
    assert result.status == "RESOLVED"
    assert result.selected.date == "2026-11-06"


@pytest.mark.parametrize("question, extracted", [
    ("2026년 11월 6일 계약 체결", "2026-12-06"),
    ("2026년 11월 6일 계약 체결", "2025-11-06"),
    ("2026년 2월 30일 계약 체결", "2026-02-30"),
    ("2026년 10월 27일 공포된 시행령", "2026-10-27"),
    ("계약 체결 날짜는 모릅니다.", "2026-11-06"),
    ("2026년 11월 6일 또는 2026년 11월 7일 계약 체결", "2026-11-06"),
])
def test_date_validation_still_rejects_unsupported_events(question, extracted):
    """정상 날짜 인식 복구 후에도 불일치·불가능·공포일·모호한 근거는 거부한다."""
    result = extract_event_with_llm(question, _invoke({
        "date": extracted, "event_type": "CONTRACT_SIGNED", "evidence": question,
    }))
    assert result.status == "UNCONFIRMED"
