# -*- coding: utf-8 -*-
"""
테스트 설정 모듈: conftest.py

[역할]
evaluation_harness 및 backend/src 모듈 경로를 sys.path에 추가하여
테스트 실행 시 ImportError를 방지한다.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_SRC = REPO_ROOT / "backend" / "src"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))
