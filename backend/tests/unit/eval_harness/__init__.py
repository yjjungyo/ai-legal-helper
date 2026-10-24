# -*- coding: utf-8 -*-
"""
패키지: backend.tests.unit.evaluation_harness

[역할]
Evaluation Harness 단위 테스트 패키지 초기화.
저장소 루트(REPO_ROOT)를 sys.path에 등록하여 evaluation_harness 모듈 임포트를 보장한다.
"""

import sys
from pathlib import Path

# C:\myprjs\ai-legal-helper 저장소 루트 등록
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
