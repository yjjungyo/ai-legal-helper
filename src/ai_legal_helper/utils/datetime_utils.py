# -*- coding: utf-8 -*-
"""
모듈명: datetime_utils.py

[모듈 개요]
대한민국 표준시(KST, Asia/Seoul, UTC+9) 처리를 위한 공통 날짜/시간 유틸리티 모듈이다.

[주요 기능]
1. get_kst_now(): PostgreSQL timestamp without time zone 컬럼 저장을 위한 naive KST datetime 객체 반환
2. get_kst_now_aware(): 타임존 정보(+09:00)가 포함된 timezone-aware datetime 객체 반환
3. get_kst_iso(): KST 기준 ISO 8601 포맷 문자열 반환

[주의사항]
- PostgreSQL 데이터베이스의 컬럼이 `timestamp without time zone`으로 설정되어 있으므로,
  ORM 모델의 default 및 onupdate에는 tzinfo가 없는 naive datetime(`get_kst_now()`)을 사용해야
  정확한 한국 현지 시간이 데이터베이스에 직접 저장된다.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

# 대한민국 표준시 (UTC+9)
KST = ZoneInfo("Asia/Seoul")


def get_kst_now() -> datetime:
    """현재 한국 표준시(KST, Asia/Seoul)의 naive datetime 객체를 반환한다.

    Returns:
        datetime: tzinfo가 제거된 KST 기준 현재 일시 (DB 저장용)
    """
    return datetime.now(KST).replace(tzinfo=None)


def get_kst_now_aware() -> datetime:
    """현재 한국 표준시(KST, Asia/Seoul)의 timezone-aware datetime 객체를 반환한다.

    Returns:
        datetime: tzinfo=ZoneInfo('Asia/Seoul')이 포함된 KST 기준 현재 일시
    """
    return datetime.now(KST)


def get_kst_iso(dt: Optional[datetime] = None) -> str:
    """지정된 datetime 또는 현재 시각을 KST 기준 ISO 8601 문자열로 변환한다.

    Args:
        dt: 변환할 datetime 객체 (None인 경우 현재 시각 사용)

    Returns:
        str: ISO 8601 형식의 일시 문자열 (예: '2026-10-13T01:55:00+09:00')
    """
    if dt is None:
        return datetime.now(KST).isoformat()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST).isoformat()
    return dt.astimezone(KST).isoformat()

