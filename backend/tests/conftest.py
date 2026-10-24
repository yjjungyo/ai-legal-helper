# -*- coding: utf-8 -*-
"""
모듈명: conftest.py

[모듈 개요]
pytest 테스트 실행 환경 공통 설정을 정의한다.
Windows 환경에서 psycopg 비동기 지원을 위한 WindowsSelectorEventLoopPolicy를 구성한다.
"""
import sys
import asyncio
from pathlib import Path
import pytest

# 저장소 루트 및 backend/src를 sys.path에 추가
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

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

