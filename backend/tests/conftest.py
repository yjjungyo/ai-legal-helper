# -*- coding: utf-8 -*-
"""
모듈명: conftest.py

[모듈 개요]
pytest 테스트 실행 환경 공통 설정을 정의한다.
Windows 환경에서 psycopg 비동기 지원을 위한 WindowsSelectorEventLoopPolicy를 구성한다.
"""
import sys
import asyncio
import pytest

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass


@pytest.fixture(scope="session")
def event_loop_policy():
    """Windows 환경에서 ProactorEventLoop 대신 SelectorEventLoop를 사용하도록 강제한다."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()

