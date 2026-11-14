# -*- coding: utf-8 -*-
"""공식 법령 버전별 Chroma Worker 관리자 및 상시 데몬 CLI.

국가법령정보센터(OpenLaw API)에서 온디맨드로 조회되어 PostgreSQL 작업 큐(OfficialLawIndexJob)에
등록된 법령 조문/부칙 데이터를 백그라운드에서 비동기로 파싱, 임베딩 및 ChromaDB에 영구 적재한다.

주요 실행 모드:
- 단일 1회 실행: `python run_official_law_index_worker.py --execute`
- 큐 전량 일괄 처리: `python run_official_law_index_worker.py --execute --all`
- 상시 데몬 폴링 모드: `python run_official_law_index_worker.py --execute --loop --interval 5`
"""
import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("official_law_index_worker")

# 상시 루프 중단 신호 플래그
_SHUTDOWN_REQUESTED = False


def _signal_handler(signum, frame):
    """프로세스 종료 신호(SIGINT, SIGTERM) 수신 시 안전한 중단을 요청한다."""
    global _SHUTDOWN_REQUESTED
    logger.info("[INDEX_WORKER] 종료 신호 수신(%s). 현재 작업 완료 후 안전하게 종료합니다...", signum)
    _SHUTDOWN_REQUESTED = True


def run_drain_queue(run_worker_func) -> int:
    """큐에 대기 중인 모든 법령 인덱싱 작업을 순차 처리한다.

    Args:
        run_worker_func: 단일 작업을 처리하고 결과를 반환하는 함수 (run_worker_once).

    Returns:
        int: 성공적으로 처리된 작업 수.
    """
    processed = 0
    while not _SHUTDOWN_REQUESTED:
        try:
            output = run_worker_func()
        except Exception as exc:
            logger.error("[INDEX_WORKER] 작업 실행 중 예외 발생: %s", type(exc).__name__)
            break

        status = output.get("status")
        if status == "EMPTY":
            logger.info("[INDEX_WORKER] 작업 큐가 비어 있습니다. (총 %d건 완료)", processed)
            break
        elif status == "READY":
            processed += 1
            logger.info(
                "[INDEX_WORKER] 법령 인덱싱 완료 (job_id=%s, chunk_count=%d)",
                output.get("job_id"),
                output.get("chunk_count", 0),
            )
        else:
            logger.warning("[INDEX_WORKER] 작업 미완료 상태 반환: %s", output)
    return processed


def run_daemon_loop(run_worker_func, interval_seconds: float) -> None:
    """작업 큐를 주기적으로 감시(Polling)하며 대기 작업을 처리하는 상시 데몬 루프.

    Args:
        run_worker_func: 단일 작업을 처리하는 함수.
        interval_seconds: 큐가 비었을 때 대기할 시간 (초).
    """
    logger.info(
        "[INDEX_WORKER] 상시 임베딩 워커 데몬 시작 (폴링 주기: %.1f초 | 종료: Ctrl+C)",
        interval_seconds,
    )
    while not _SHUTDOWN_REQUESTED:
        try:
            output = run_worker_func()
            status = output.get("status")
            if status == "READY":
                logger.info(
                    "[INDEX_WORKER] 법령 인덱싱 성공 (job_id=%s, chunk_count=%d)",
                    output.get("job_id"),
                    output.get("chunk_count", 0),
                )
                # 처리할 작업이 남아있을 수 있으므로 대기 없이 다음 작업 즉시 점유 시도
                continue
            elif status == "EMPTY":
                # 큐가 비어있으면 지정된 주기만큼 대기
                time.sleep(interval_seconds)
            else:
                logger.warning("[INDEX_WORKER] 작업 처리 결과: %s", output)
                time.sleep(interval_seconds)
        except Exception as exc:
            logger.error("[INDEX_WORKER] 워커 루프 예외: %s", type(exc).__name__)
            time.sleep(interval_seconds)

    logger.info("[INDEX_WORKER] 워커 데몬이 정상 종료되었습니다.")


def main() -> int:
    """CLI 인자를 파싱하고 요청된 모드(1회, 전체 일괄, 상시 데몬)로 워커를 구동한다.

    Returns:
        int: 종료 코드 (0: 성공, 1: 미완료, 2: 예외/오류).
    """
    parser = argparse.ArgumentParser(description="공식 법령 백그라운드 인덱싱 관리자")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 DB 작업 선점·OpenLaw 조회·Chroma Upsert 수행",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="큐에 대기 중인 모든 작업을 소진(EMPTY)될 때까지 연속 처리",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="큐를 주기적으로 폴링하며 대기하는 상시 데몬 모드로 실행",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="상시 데몬 모드에서 큐가 비었을 때 대기할 주기(초, 기본값: 5.0)",
    )
    args = parser.parse_args()

    if not args.execute:
        print("[DRY RUN] --execute를 지정해야 실제 임베딩 및 Chroma Upsert를 수행합니다.")
        return 0

    load_dotenv(BACKEND / ".env")

    # 종료 시그널 등록
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        from ai_legal_helper.legal_knowledge.index_worker import run_worker_once
    except Exception as exc:
        print(f"[INDEX_WORKER] 모듈 로드 실패: {type(exc).__name__}")
        return 2

    if args.loop:
        run_daemon_loop(run_worker_once, args.interval)
        return 0

    if args.all:
        count = run_drain_queue(run_worker_once)
        print(f"[INDEX_WORKER] 전체 큐 일괄 처리 완료: {count}건")
        return 0

    # 기본 1회 실행 모드
    try:
        output = run_worker_once()
        print(json.dumps(output, ensure_ascii=False))
        return 0 if output.get("status") in ("EMPTY", "READY") else 1
    except Exception as exc:
        print(f"[INDEX_WORKER] 실행 실패: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
