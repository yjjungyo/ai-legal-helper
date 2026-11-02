# -*- coding: utf-8 -*-
"""P10 레거시 법령 Vector 감사 및 격리 스테이징 관리자 명령.

기본 Dry Run은 read-only. --execute 지정 시에만 별도 Staging Collection 생성.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))


def main():
    parser = argparse.ArgumentParser(description="레거시 법령 인덱스 무손실 감사·이관")
    parser.add_argument("--execute", action="store_true",
                        help="검토용 격리 Staging Collection으로 복사")
    parser.add_argument("--max-rows", type=int, default=100000)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    load_dotenv(BACKEND / ".env")
    try:
        from ai_legal_helper.rag.retrieval import _get_client
        from ai_legal_helper.legal_knowledge.legacy_migration import audit_and_stage
        embeddings = None
        if args.execute:
            from ai_legal_helper.llm.gateway import get_embeddings
            embeddings = get_embeddings()
        report = audit_and_stage(
            _get_client(), execute=args.execute,
            embeddings=embeddings,
            batch_size=args.batch_size,
            max_rows=args.max_rows,
        )
    except Exception as exc:
        print(f"[P10] ERROR: {type(exc).__name__}")
        return 2
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if not args.execute:
        print("[P10] DRY RUN: 기존 컬렉션 변경 및 새 컬렉션 생성 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
