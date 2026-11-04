"""LLM 사건일 추출은 원문 일치·날짜 검증을 통과해야만 승인된다."""
import json
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
