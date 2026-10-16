# -*- coding: utf-8 -*-
"""
Timeline Engine (타임라인 빌더)

추출된 사실관계 중 날짜나 순서 정보가 있는 것을 기반으로 시계열 이벤트(Event)를 생성한다.
"""
from typing import List
from ai_legal_helper.database.models import Fact, Event
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

@trace
def build_timeline_from_facts(facts: List[Fact]) -> List[Event]:
    """
    사실관계 리스트를 분석하여 타임라인 이벤트 목록을 구축한다.
    
    발생 시점(occurred_at)이 명시된 Fact들을 모아 Event 객체로 변환하며, 
    여기서는 단순화를 위해 각 날짜별로 이벤트를 묶거나 1:1로 변환한다.
    
    Args:
        facts (List[Fact]): 사건에 속한 모든 사실관계 객체 목록
        
    Returns:
        List[Event]: 생성되거나 갱신될 이벤트 목록 (메모리 객체 상태, 아직 DB 커밋 안됨)
    """
    events = []
    
    # 날짜가 있는 사실들 필터링
    dated_facts = [f for f in facts if f.occurred_at and f.occurred_at.strip()]
    
    # 딕셔너리로 날짜별 그룹핑 (간단한 구현)
    from typing import Dict
    grouped: Dict[str, List[Fact]] = {}
    for f in dated_facts:
        date_str = f.occurred_at.strip()
        if date_str not in grouped:
            grouped[date_str] = []
        grouped[date_str].append(f)
        
    for date_str, group in grouped.items():
        # 이벤트 요약 제목은 첫 번째 사실의 내용 사용 (너무 길면 자름)
        title_fact = group[0].statement
        title = title_fact[:30] + "..." if len(title_fact) > 30 else title_fact
        
        # 전체 설명을 합침
        desc = "\n".join([f"- {f.statement}" for f in group])
        
        # '초', '말', '무렵' 등의 단어가 있으면 APPROXIMATE 처리
        precision = "APPROXIMATE" if any(x in date_str for x in ["초", "중순", "말", "경", "무렵", "쯤"]) else "EXACT"
        
        event = Event(
            title=title,
            description=desc,
            event_date=date_str,
            date_precision=precision,
            event_type="사실 발생",
            related_fact_ids=[f.id for f in group if f.id]
        )
        events.append(event)
        
    # 날짜순 정렬 시도 (문자열 정렬이므로 '2024년 4월'과 '2024-04-01' 같은 혼합은 완벽하지 않으나 단순화함)
    events.sort(key=lambda e: e.event_date or "")
    return events
