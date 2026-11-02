# -*- coding: utf-8 -*-
"""공식 법령 버전별 Chroma Worker 관리자 CLI.

기본은 DRY RUN이며 --execute가 있어야 공식 원문 조회 및 임베딩을 수행한다.
운영에는 별도 스케줄러/서비스 매니저에서 본 스크립트를 호출한다.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="공식 법령 백그라운드 인덱싱")
    parser.add_argument("--execute", action="store_true",
                        help="실제 DB 작업 선점·OpenLaw 조회·Chroma Upsert")
    args = parser.parse_args()
    if not args.execute:
        print("[DRY RUN] --execute를 지정해야 인덱싱합니다.")
        return 0
    load_dotenv(BACKEND / ".env")
    try:
        from ai_legal_helper.legal_knowledge.index_worker import run_worker_once
        output = run_worker_once()
    except Exception as exc:
        # URL 및 인증키가 실린 예외 본문을 출력하지 않는다.
        print(f"[INDEX_WORKER] failed: {type(exc).__name__}")
        return 2
    print(json.dumps(output, ensure_ascii=False))
    return 0 if output["status"] in ("EMPTY", "READY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
