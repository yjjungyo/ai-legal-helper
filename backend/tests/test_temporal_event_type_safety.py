"""사건일만으로 계약 체결을 가정하지 않는 회귀 테스트."""
from ai_legal_helper.legal_knowledge.temporal_resolver import resolve_event


def test_date_only_does_not_default_to_contract():
    result = resolve_event("법령의 적용 여부를 확인해 주세요.", event_date="2026-11-01")
    assert result.status == "UNCONFIRMED"
    assert result.reason_code == "EXPLICIT_EVENT_TYPE_MISSING"
    assert result.selected is None


def test_explicit_event_type_is_preserved():
    result = resolve_event("해지 통지의 효력은?", event_date="2026-11-01", event_type="NOTICE_GIVEN")
    assert result.status == "RESOLVED"
    assert result.selected.event_type == "NOTICE_GIVEN"


def test_matching_question_event_can_supply_type():
    result = resolve_event("2026년 11월 1일 계약을 체결했습니다.", event_date="2026-11-01")
    assert result.status == "RESOLVED"
    assert result.selected.event_type == "CONTRACT_SIGNED"


def test_unrelated_date_does_not_supply_type():
    result = resolve_event("2026년 10월 27일 계약을 체결했습니다.", event_date="2026-11-01")
    assert result.status == "UNCONFIRMED"
