# -*- coding: utf-8 -*-
"""
모듈명: config.py

[모듈 개요]
AI Legal Helper Evaluation Harness v1.0의 전역 환경 설정 및 격리 실행 보호 정책을 관리하는 모듈이다.

[주요 기능]
1. Python 실행 경로(`sys.path`)에 `backend/src`를 자동으로 등록하여 모듈 import를 보장한다.
2. PostgreSQL, ChromaDB, Langfuse, Azure OpenAI 등 평가 실행 환경변수를 안전하게 로드한다.
3. 운영 데이터베이스 파괴 방지 원칙(Non-destructive isolation)을 강제하여 실사용 DB 데이터 손실을 원천 차단한다.
"""

from dataclasses import dataclass, field
import os
import sys
from pathlib import Path
from typing import Optional

# backend/src 경로를 sys.path에 추가
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# .env 로드
try:
    from dotenv import load_dotenv
    env_path = REPO_ROOT / "backend" / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


@dataclass
class EvaluationHarnessConfig:
    """평가 하네스 전역 설정 모델."""

    # 경로 설정
    repo_root: Path = REPO_ROOT
    raw_evidence_dir: Path = Path(r"C:\myprjs\ai_master\SC-001_전세보증금미반환_사건자료\02_증거원문TXT")
    results_dir: Path = REPO_ROOT / "evaluation_results"
    gold_dir: Path = REPO_ROOT / "evaluation_harness" / "gold"

    # 기본 평가 대상 사건
    default_case_id: str = "fa8f215a-1c55-44e6-9af8-50f336a85717"
    default_dataset_name: str = "sc001_dev"

    # 데이터베이스 격리 설정
    prod_db_name: str = os.getenv("POSTGRES_DB", "ai_legal_helper")
    test_db_name: str = os.getenv("POSTGRES_TEST_DB", "ai_legal_helper_test")
    postgres_user: str = os.getenv("POSTGRES_USER", "ai_user")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "ai_password")
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))

    # 벡터 DB 및 API 설정
    chroma_host: str = os.getenv("CHROMA_HOST", "127.0.0.1")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8001"))
    law_openapi_key: Optional[str] = os.getenv("LAW_OPENAPI_KEY")

    # Langfuse 설정
    langfuse_host: str = os.getenv("LANGFUSE_HOST", "http://localhost:3001")
    langfuse_public_key: Optional[str] = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = os.getenv("LANGFUSE_SECRET_KEY")

    # LLM 및 모델 설정
    chat_deployment: str = os.getenv("AZURE_OPENAI_DEPLOYMENT_CHAT", "gpt-5.4")
    judge_model: str = "gpt-5.4"
    judge_temperature: float = 0.0

    # 안전 보호 스위치: 평가 러너가 실제 운영 DB를 DROP/TRUNCATE하려 할 경우 강제 차단
    allow_destructive_db_operations: bool = False

    @property
    def test_database_url(self) -> str:
        """격리된 테스트 데이터베이스 URL을 반환한다."""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.test_db_name}"

    @property
    def prod_database_url(self) -> str:
        """운영 데이터베이스 URL을 반환한다."""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.prod_db_name}"


# 전역 기본 설정 인스턴스
config = EvaluationHarnessConfig()

