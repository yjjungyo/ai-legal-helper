# -*- coding: utf-8 -*-
"""
법령의 시간적 적용 가능성을 판단하는 독립적인 3상 판정 API (Temporal Legal RAG P1).

[설계 배경]
기존의 bool 판정은 시행일을 확인하지 못한 경우에도 True를 반환할 수 있었다.
또한 공포일/파일명 날짜/법령 전체의 시행일을 조문의 시행일로 오인할 위험이 있었다.
따라서 공식 근거가 없는 날짜와 적용례 미검증 상태를 명시적으로 구분한다.

[적용 범위와 한계]
- 이 모듈은 법령의 **적용 여부를 추정하지 않고** 구조화된 공식 시행일 및 적용례 검증 상태를 평가한다.
- 법령 전문의 해석, 소급효, 경과규정 충돌의 해결은 이 함수가 자동 보장하지 않는다.
- 'APPLICABLE'은 조문 시행일과 관련 적용례 검토가 모두 검증된 출처에 한한다.
- 파일명에서 추출한 날짜, 단순 공포일, 검증되지 않은 법령 공통 시행일은 확정 근거가 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Mapping, Optional


class ApplicabilityStatus(str, Enum):
    """법령의 사건 기준일 적용 여부. 날짜·근거 미확인은 반드시 별도 상태로 남긴다."""

    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNCONFIRMED = "UNCONFIRMED"


# 공식 XML의 조문시행일자 또는 해당 공포번호 부칙을 계산해 확인한 날짜만 허용한다.
_VERIFIED_ARTICLE_DATE_BASES = frozenset({
    "ARTICLE_EFFECTIVE_DATE",
    "ADDENDUM_EFFECTIVE_DATE",
})


@dataclass(frozen=True)
class ApplicabilityDecision:
    """추후 Verification 및 Langfuse에서 재현 가능한 시행일 판정 결과."""

    status: ApplicabilityStatus
    reason_code: str
    event_date: Optional[str] = None
    article_effective_date: Optional[str] = None
    effective_to: Optional[str] = None
    law_id: Optional[str] = None
    version_id: Optional[str] = None
    source_id: Optional[str] = None
    effective_date_basis: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        """JSON/State 저장에 사용할 수 있도록 Enum을 문자열로 직렬화한다."""
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "event_date": self.event_date,
            "article_effective_date": self.article_effective_date,
            "effective_to": self.effective_to,
            "law_id": self.law_id,
            "version_id": self.version_id,
            "source_id": self.source_id,
            "effective_date_basis": self.effective_date_basis,
        }


def parse_legal_date(raw: Any) -> Optional[date]:
    """YYYY-MM-DD, YYYYMMDD 및 datetime/date만 허용하고 유효하지 않은 날짜는 거부한다."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if len(value) == 8 and value.isascii() and value.isdigit():
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def evaluate_statute_applicability(
    source: Mapping[str, Any],
    event_date: Any,
    *,
    event_type: Optional[str] = None,
) -> ApplicabilityDecision:
    """공식 조문 시행일 및 적용례 검증 상태로 3상 판정한다.

    'NOT_APPLICABLE'은 검증된 조문 시행일 이전, 또는 검증된 적용 종료 시점 이후에만 반환한다.
    'APPLICABLE'은 명시적 조문 시행일과 적용례 검증 완료를 모두 요구한다.

    Args:
        source: 단일 조문 버전의 정규화된 Source. 법령명만 있는 자료는 사용할 수 없다.
        event_date: 사건 법률효과 판단에 사용되는 날짜. 단순 현재 날짜를 자동 사용하지 않는다.
        event_type: 계약 체결·갱신 등 날짜의 법률적 역할. 적용례에 요구 역할이 있으면 일치 필요.

    Returns:
        ApplicabilityDecision: 판정 상태와 재검증 가능한 근거 코드.
    """
    source = source or {}
    parsed_event = parse_legal_date(event_date)
    basis = str(source.get("effective_date_basis") or "").strip()
    recorded = source.get("article_effective_date")
    parsed_effective = parse_legal_date(recorded)
    parsed_end = parse_legal_date(source.get("effective_to"))
    expected_event_type = source.get("applicability_event_type")
    confidence = str(source.get("temporal_status") or "").strip().upper()

    def decision(status: ApplicabilityStatus, reason_code: str) -> ApplicabilityDecision:
        return ApplicabilityDecision(
            status=status,
            reason_code=reason_code,
            event_date=parsed_event.isoformat() if parsed_event else None,
            article_effective_date=parsed_effective.isoformat() if parsed_effective else None,
            effective_to=parsed_end.isoformat() if parsed_end else None,
            law_id=source.get("law_id"),
            version_id=source.get("version_id"),
            source_id=source.get("source_id"),
            effective_date_basis=basis or None,
        )

    if source.get("source_type") != "STATUTE":
        return decision(ApplicabilityStatus.UNCONFIRMED, "NOT_A_STATUTE")
    if parsed_event is None:
        return decision(ApplicabilityStatus.UNCONFIRMED, "EVENT_DATE_UNCONFIRMED")
    if basis not in _VERIFIED_ARTICLE_DATE_BASES or parsed_effective is None:
        return decision(ApplicabilityStatus.UNCONFIRMED, "ARTICLE_EFFECTIVE_DATE_UNCONFIRMED")

    # 명확히 확인한 조문의 시행일 이전에는 그 개정 조문을 현재 시행 규정으로 단정할 수 없다.
    # 다만 적용례가 소급 적용을 시사하거나 검토되지 않은 경우에는 미확인으로 보류한다.
    if parsed_event < parsed_effective:
        if source.get("retroactivity_review_required"):
            return decision(ApplicabilityStatus.UNCONFIRMED, "RETROACTIVITY_REVIEW_REQUIRED")
        return decision(ApplicabilityStatus.NOT_APPLICABLE, "BEFORE_ARTICLE_EFFECTIVE_DATE")

    # 적용기간의 종료일은 **공식 확인된 경우**에만 사용한다. 계산한 추정 날짜는 사용 금지.
    if source.get("effective_to") and parsed_end is None:
        return decision(ApplicabilityStatus.UNCONFIRMED, "EFFECTIVE_TO_INVALID")
    if parsed_end is not None and parsed_end <= parsed_effective:
        return decision(ApplicabilityStatus.UNCONFIRMED, "EFFECTIVE_INTERVAL_INVALID")

    # 단순 '시행일 확인'은 곧 '사건 적용례 확인'이 아니다.
    # 부칙·경과규정에 대한 검토가 완료되지 않았다면 긍정 적용 판정을 내리지 않는다.
    if confidence != "VERIFIED":
        return decision(ApplicabilityStatus.UNCONFIRMED, "APPLICABILITY_REVIEW_REQUIRED")
    if expected_event_type and (not event_type or expected_event_type != event_type):
        return decision(ApplicabilityStatus.UNCONFIRMED, "EVENT_TYPE_NOT_VERIFIED")

    # 과거 버전 종료일 역시 법률 적용례가 검증된 경우에만 불적용 판정 가능.
    if parsed_end is not None and parsed_event >= parsed_end:
        return decision(ApplicabilityStatus.NOT_APPLICABLE, "AFTER_VERIFIED_EFFECTIVE_TO")

    return decision(ApplicabilityStatus.APPLICABLE, "TEMPORAL_APPLICATION_VERIFIED")
