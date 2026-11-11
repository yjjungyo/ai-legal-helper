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
        for event in self.events:
            # event는 DB 모델 인스턴스 또는 dict
            title = event.title if hasattr(event, "title") else event.get("title", "")
            desc = event.description if hasattr(event, "description") else event.get("description", "")
            if desc is None:
                desc = ""
                
            if "계약 종료" in title or "만기" in title or "계약 종료" in desc or "만기" in desc:
                event_date = event.event_date if hasattr(event, "event_date") else event.get("event_date", "")
                return self._parse_date(event_date)
        return None

    def calculate_deadline(self, action_title: str) -> Dict[str, Any]:
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
            result["calculation_basis"] = "계약 종료일(만기)이 확인되지 않아 기한을 계산할 수 없습니다."
            return result

        if "계약 종료 의사표시" in action_title or "갱신 거절" in action_title or "내용증명" in action_title:
            # 주택임대차보호법 제6조 제1항: 임대차기간이 끝나기 6개월 전부터 2개월 전까지
            deadline = self.lease_end_date - relativedelta(months=2)
            result["deadline_type"] = "LEGAL_DEADLINE"
            result["deadline_date"] = deadline
            result["calculation_basis"] = "주택임대차보호법 제6조 제1항: 계약 종료 2개월 전까지 갱신 거절 통지 도달 필요"
            result["verification_status"] = "VERIFIED"
            
        elif "임차권등기명령" in action_title:
            # 계약이 종료된 후 보증금을 반환받지 못한 경우 신청 가능
            result["deadline_type"] = "RECOMMENDED_DATE"
            result["deadline_date"] = self.lease_end_date + timedelta(days=1)
            result["calculation_basis"] = "주택임대차보호법 제3조의3: 임대차가 끝난 후 보증금이 반환되지 아니한 경우 임차권등기명령 신청 가능"
            result["verification_status"] = "VERIFIED"

        elif "지급명령" in action_title or "소송" in action_title or "보증금 반환 요구" in action_title or "손해배상" in action_title or "반환 청구" in action_title:
            # 법적 조치 권고일 (계약 종료 또는 채무불이행 발생 후)
            result["deadline_type"] = "RECOMMENDED_DATE"
            result["deadline_date"] = self.lease_end_date + timedelta(days=1)
            result["calculation_basis"] = "계약 종료 또는 채무불이행 발생 후 법적 조치(소송/지급명령/청구) 진행 권고"
            result["verification_status"] = "VERIFIED"
            
        return result

