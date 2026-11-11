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
    assert "확정할 수 없습니다" in res["calculation_basis"]

def test_calculate_deadline_notice():
    events = [MockEvent(title="만기", event_date="2024-03-01")]
    engine = DeadlineEngine(events)
    res = engine.calculate_deadline("계약 종료 의사표시 및 도달 사실 확인")
    assert res["deadline_type"] == "UNKNOWN"
    # 2024-03-01 - 2 months = 2024-01-01
    assert res["deadline_date"] is None

def test_calculate_deadline_lawsuit():
    events = [MockEvent(title="계약 종료", event_date="2024-01-01")]
    engine = DeadlineEngine(events)
    res = engine.calculate_deadline("보증금 반환 청구 소송 검토")
    assert res["deadline_type"] == "UNKNOWN"
    assert res["deadline_date"] is None



def test_conflicting_end_dates_are_not_silently_selected():
    events = [MockEvent("계약 만기", "2024-01-01"), MockEvent("갱신 계약 만기", "2026-01-01")]
    engine = DeadlineEngine(events)
    assert engine.lease_end_date is None
    assert engine.calculate_deadline("갱신 거절")["deadline_type"] == "UNKNOWN"


def test_generic_content_certification_does_not_trigger_renewal_notice():
    engine = DeadlineEngine([MockEvent("계약 만기", "2026-09-30")])
    result = engine.calculate_deadline("보증금 반환 내용증명 발송")
    assert result["deadline_type"] == "UNKNOWN"
    assert result["deadline_date"] is None


def test_unmet_legal_condition_blocks_deadline():
    engine = DeadlineEngine([MockEvent("계약 만기", "2026-09-30")])
    result = engine.calculate_deadline("갱신 거절", requirements=[
        {"requirement_type": "LEGAL_CONDITION", "satisfaction_status": "UNKNOWN"}
    ])
    assert result["deadline_type"] == "UNKNOWN"
    assert "선행 요건" in result["calculation_basis"]


def test_verified_rule_calculates_lease_notice_date():
    engine = DeadlineEngine([MockEvent("계약 만기", "2026-09-30")])
    rule = {
        "rule_type": "LEASE_RENEWAL_REFUSAL_NOTICE",
        "basis_date": "2026-09-30",
        "basis_date_confirmed": True,
        "applicability_confirmed": True,
        "verification_status": "VERIFIED",
        "legal_source": "주택임대차보호법 제6조 제1항",
    }
    result = engine.calculate_deadline("갱신 거절 통지", verified_rule=rule)
    assert result["deadline_type"] == "LEGAL_DEADLINE"
    assert result["deadline_date"] == datetime(2026, 7, 30)
    assert result["verification_status"] == "VERIFIED"


def test_unverified_or_mismatched_rule_cannot_calculate_deadline():
    engine = DeadlineEngine([MockEvent("계약 만기", "2026-09-30")])
    rule = {
        "rule_type": "LEASE_RENEWAL_REFUSAL_NOTICE",
        "basis_date": "2026-09-30",
        "basis_date_confirmed": True,
        "applicability_confirmed": True,
        "verification_status": "UNVERIFIED",
        "legal_source": "주택임대차보호법 제6조 제1항",
    }
    assert engine.calculate_deadline("갱신 거절", verified_rule=rule)["deadline_date"] is None
    rule["verification_status"] = "VERIFIED"
    rule["basis_date"] = "2024-09-30"
    assert engine.calculate_deadline("갱신 거절", verified_rule=rule)["deadline_date"] is None
