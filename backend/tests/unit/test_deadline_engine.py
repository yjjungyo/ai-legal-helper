import pytest
from datetime import datetime
from ai_legal_helper.agents.deadline_engine import DeadlineEngine

class MockEvent:
    def __init__(self, title, event_date=None, description=""):
        self.title = title
        self.event_date = event_date
        self.description = description

def test_find_lease_end_date():
    events = [
        MockEvent(title="계약 체결", event_date="2022-01-01"),
        MockEvent(title="임대차 계약 종료", event_date="2024-01-01")
    ]
    engine = DeadlineEngine(events)
    assert engine.lease_end_date == datetime(2024, 1, 1)

def test_calculate_deadline_no_date():
    events = [MockEvent(title="일반 이벤트")]
    engine = DeadlineEngine(events)
    res = engine.calculate_deadline("계약 종료 의사표시")
    assert res["deadline_type"] == "UNKNOWN"
    assert res["deadline_date"] is None
    assert "확인되지 않아" in res["calculation_basis"]

def test_calculate_deadline_notice():
    events = [MockEvent(title="만기", event_date="2024-03-01")]
    engine = DeadlineEngine(events)
    res = engine.calculate_deadline("계약 종료 의사표시 및 도달 사실 확인")
    assert res["deadline_type"] == "LEGAL_DEADLINE"
    # 2024-03-01 - 2 months = 2024-01-01
    assert res["deadline_date"] == datetime(2024, 1, 1)

def test_calculate_deadline_lawsuit():
    events = [MockEvent(title="계약 종료", event_date="2024-01-01")]
    engine = DeadlineEngine(events)
    res = engine.calculate_deadline("보증금 반환 청구 소송 검토")
    assert res["deadline_type"] == "RECOMMENDED_DATE"
    assert res["deadline_date"] == datetime(2024, 1, 2)

