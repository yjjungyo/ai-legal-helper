# -*- coding: utf-8 -*-
"""
모듈명: deadline_engine.py

[모듈 개요]
사건의 타임라인(Event) 데이터를 기반으로 법률상 기한(Deadline)을
결정론적으로 계산하는 엔진.

[주요 기능]
1. 계약 만료일 등 기준일(Basis Date) 추출
2. 행동 유형(Action Type)에 따른 기한 계산 (예: 계약 종료 2개월 전)
3. 계산 결과(ActionDeadline 모델과 유사한 딕셔너리 구조) 반환

[주의사항]
- LLM에 의한 날짜 계산의 오류(환각)를 방지하기 위해 순수 Python 로직으로 구현.
- 명확한 날짜(YYYY-MM-DD)가 없거나 조건이 불충분할 경우 UNKNOWN으로 처리.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dateutil.relativedelta import relativedelta
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

class DeadlineEngine:
    def __init__(self, events: List[Any]):
        """
        Args:
            events: 데이터베이스의 Event 모델 객체 리스트
        """
        self.events = events
        self.contract_end_date = self._find_lease_end_date()
        # 하위 호환성을 위해 lease_end_date 속성 유지
        self.lease_end_date = self.contract_end_date
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            # 기본적으로 YYYY-MM-DD 처리
            return datetime.strptime(date_str[:10], "%Y-%m-%d")
        except ValueError:
            return None

    def _find_lease_end_date(self) -> Optional[datetime]:
        """계약 종료일/만기일을 Event 목록에서 탐색한다."""
        candidates = []
        for event in self.events:
            # event는 DB 모델 인스턴스 또는 dict
            title = event.title if hasattr(event, "title") else event.get("title", "")
            desc = event.description if hasattr(event, "description") else event.get("description", "")
            if desc is None:
                desc = ""
                
            if "계약 종료" in title or "만기" in title or "계약 종료" in desc or "만기" in desc:
                event_date = event.event_date if hasattr(event, "event_date") else event.get("event_date", "")
                parsed = self._parse_date(event_date)
                if parsed is not None:
                    candidates.append(parsed)
        # Distinct end dates may reflect renewal, termination or contradictory evidence.
        # Event order or the latest date alone cannot establish the legally effective term.
        return candidates[0] if len(set(candidates)) == 1 else None

    def calculate_deadline(self, action_title: str, *, requirements: Optional[List[Any]] = None) -> Dict[str, Any]:
        """
        행동 제목(action_title)에 따라 기한을 계산하여 반환한다.
        
        Returns:
            Dict: {
                "deadline_type": "LEGAL_DEADLINE" | "RECOMMENDED_DATE" | "UNKNOWN",
                "deadline_date": datetime 객체 또는 None,
                "calculation_basis": 문자열 또는 None,
                "verification_status": "VERIFIED" | "UNVERIFIED"
            }
        """
        result = {
            "deadline_type": "UNKNOWN",
            "deadline_date": None,
            "calculation_basis": None,
            "verification_status": "UNVERIFIED"
        }

        if not self.lease_end_date:
            result["calculation_basis"] = "계약 종료일이 없거나 복수의 종료일이 상충하여 유효한 기준일을 확정할 수 없습니다."
            return result

        # The planner's legal prerequisites must not be treated as satisfied by a title.
        # This engine calculates dates only; legal applicability needs independent review.
        legal_conditions = [r for r in (requirements or [])
                            if (getattr(r, "requirement_type", None) if not isinstance(r, dict)
                                else r.get("requirement_type")) == "LEGAL_CONDITION"]
        if any((getattr(r, "satisfaction_status", None) if not isinstance(r, dict)
                else r.get("satisfaction_status")) != "SATISFIED" for r in legal_conditions):
            result["calculation_basis"] = "법률상 선행 요건이 확인되지 않아 기한을 확정하지 않았습니다."
            return result

        if "갱신 거절" in action_title or "계약 종료 의사표시" in action_title:
            # Conditional calculation only: statute applicability, notice delivery and
            # lease type must be verified independently before treating this as a deadline.
            result["deadline_type"] = "UNKNOWN"
            result["deadline_date"] = None
            result["calculation_basis"] = (
                "갱신 거절 통지 검토: 주택임대차보호법 제6조 제1항의 적용 여부와 "
                "통지 도달 요건을 확인한 뒤 만료 2개월 전 날짜를 산정해야 합니다."
            )
        elif "임차권등기명령" in action_title:
            result["deadline_type"] = "UNKNOWN"
            result["calculation_basis"] = (
                "임대차 종료 및 보증금 미반환 확인 후 신청 가능 여부 검토 필요 "
                "(주택임대차보호법 제3조의3). 계약 만료 다음 날은 법정 신청 기한이 아닙니다."
            )
        elif any(term in action_title for term in (
            "지급명령", "소송", "보증금 반환 요구", "손해배상", "반환 청구"
        )):
            result["deadline_type"] = "UNKNOWN"
            result["calculation_basis"] = (
                "청구권 발생 요건과 소멸시효 등 개별 기한 확인 필요. "
                "계약 종료 다음 날은 법정 기한이 아닙니다."
            )
        return result
