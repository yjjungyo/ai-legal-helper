# -*- coding: utf-8 -*-
"""
P2 공식 법령명 카탈로그 관리자 동기화 명령.

[사용]
    cd backend
    python scripts/sync_law_catalog.py --execute --max-pages 1
    python scripts/sync_law_catalog.py --execute --max-pages 0

[주의]
- --execute 없이는 공식 API, DB 쓰기를 수행하지 않는다.
- max-pages=0은 공식 목록 totalCnt를 기준으로 마지막 페이지까지 수집하되
  과도한 요청 방지를 위해 1000페이지를 넘기지 않는다.
- 수집 대상은 법령명·약칭 메타데이터이며 법률 본문이나 개인정보가 아니다.
- 실패/중단은 PARTIAL 또는 FAILED로 기록한다. 전체 수집으로 보고하지 않는다.
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
SRC = BACKEND / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.legal_knowledge.catalog_store import sync_official_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="법제처 공식 법령명 카탈로그 수집")
    parser.add_argument("--execute", action="store_true", help="실제 공식 API 조회 및 DB 기록")
    parser.add_argument("--max-pages", type=int, default=1,
                        help="1: 100건 시험 수집, 0: 전체 페이지 수집")
    parser.add_argument("--query", default=None, help="법령명 부분 조회(관리용)")
    args = parser.parse_args()
    if not 0 <= args.max_pages <= 1000:
        parser.error("--max-pages 값은 0~1000이어야 합니다.")
    if not args.execute:
        print("[DRY RUN] 동기화 실행하지 않음. --execute 명시 시에만 API와 DB를 사용합니다.")
        return 0

    load_dotenv(BACKEND / ".env")
    api_key = os.getenv("LAW_OPENAPI_KEY", "").strip()
    if not api_key:
        print("LAW_OPENAPI_KEY 미설정: 공식 목록을 조회하지 않았습니다.")
        return 2
    try:
        with SessionLocal() as session:
            summary = sync_official_catalog(
                session, api_key=api_key, max_pages=args.max_pages, query=args.query
            )
    except Exception as exc:
        # 예외 객체에는 URL(API 인증값)이 포함될 수 있으므로 유형만 출력.
        print(f"[LAW_CATALOG] 동기화 작업 실패: {type(exc).__name__}")
        return 2
    print(
        f"[LAW_CATALOG] {summary.status} | "
        f"pages={summary.pages_completed} seen={summary.items_seen} "
        f"expected={summary.total_expected} error={summary.error_code or '-'} "
        f"run_id={summary.run_id}"
    )
    return 0 if summary.status == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
