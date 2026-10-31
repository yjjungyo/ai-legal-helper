# -*- coding: utf-8 -*-
"""
그래프 동기화 워커 (Graph Sync Worker)

PostgreSQL의 graph_sync_tasks 테이블을 폴링하여 Neo4j 사건 서브그래프 동기화를 비동기 백그라운드에서 처리한다.
재시도 로직(최대 3회), 중복 방지(Debouncing), 프로세스 비정상 종료 시 PROCESSING 고착 작업 자동 복구를 포함한다.
"""
import asyncio
import logging
import traceback
from datetime import timedelta
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import GraphSyncTask
from ai_legal_helper.database.graph_sync import safe_sync_case
from ai_legal_helper.utils.datetime_utils import get_kst_now

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
STALE_PROCESSING_TIMEOUT_MINUTES = 5


def recover_stale_processing_tasks(
    db: Session,
    timeout_minutes: int = STALE_PROCESSING_TIMEOUT_MINUTES,
) -> int:
    """PROCESSING 상태에서 장시간 멈춰 있는 고착(Stale) 작업을 감지하여 재시도 가능 상태로 복구한다.

    워커 프로세스가 동기화 도중 강제 종료되었을 때 작업이 영구히 PROCESSING에 머무는 현상을 방지한다.
    재시도 횟수가 MAX_RETRIES 미만이면 PENDING으로 복구하고, 이상이면 FAILED로 마감한다.

    Args:
        db: SQLAlchemy 세션.
        timeout_minutes: PROCESSING 고착 판단 기준 시간(분).

    Returns:
        int: 복구 처리된 작업 건수.
    """
    cutoff = get_kst_now() - timedelta(minutes=timeout_minutes)
    stale_tasks = (
        db.query(GraphSyncTask)
        .filter(
            GraphSyncTask.status == "PROCESSING",
            or_(
                GraphSyncTask.updated_at < cutoff,
                (GraphSyncTask.updated_at.is_(None)) & (GraphSyncTask.created_at < cutoff),
            ),
        )
        .with_for_update(skip_locked=True)
        .all()
    )
    if not stale_tasks:
        return 0

    for task in stale_tasks:
        task.retry_count = (task.retry_count or 0) + 1
        if task.retry_count < MAX_RETRIES:
            task.status = "PENDING"
            task.error_message = "Recovered from stale PROCESSING state (worker interrupted)"
        else:
            task.status = "FAILED"
            task.error_message = "Max retries exceeded after stale PROCESSING state"
        task.updated_at = get_kst_now()

    db.commit()
    logger.warning(f"[그래프 동기화 워커] 중단된 동기화 작업 {len(stale_tasks)}건을 대기 상태로 복구했습니다.")
    return len(stale_tasks)


async def graph_sync_worker_loop():
    """주기적으로 graph_sync_tasks 테이블을 폴링하여 동기화를 수행하는 백그라운드 워커."""
    logger.info("[그래프 동기화 워커] 백그라운드 그래프 동기화 워커가 시작되었습니다.")
    while True:
        try:
            # 동기적인 DB 작업을 쓰레드에서 실행
            await asyncio.to_thread(_process_pending_tasks)
        except Exception as e:
            logger.error(f"[그래프 동기화 워커] 오류 발생: {e}\n{traceback.format_exc()}")
        await asyncio.sleep(5)  # 5초 간격 폴링


def _process_pending_tasks():
    """대기 중이거나 재시도 대상인 GraphSyncTask를 조회하여 Neo4j 동기화를 수행한다."""
    with SessionLocal() as db:
        # 1. 비정상 종료로 PROCESSING에 멈춘 오래된 작업 복구
        recover_stale_processing_tasks(db)

        # 2. PENDING 이거나 FAILED(재시도 한도 미만) 작업 조회
        tasks = db.query(GraphSyncTask).filter(
            or_(
                GraphSyncTask.status == "PENDING",
                (GraphSyncTask.status == "FAILED") & (GraphSyncTask.retry_count < MAX_RETRIES)
            )
        ).order_by(GraphSyncTask.created_at.asc()).limit(10).with_for_update(skip_locked=True).all()

        if not tasks:
            return

        # 상태를 PROCESSING으로 변경하여 다른 워커(또는 다음 루프)가 잡지 않도록 함
        now = get_kst_now()
        for task in tasks:
            task.status = "PROCESSING"
            task.updated_at = now
        db.commit()

        # 처리 대상 task 정보 복사
        task_info = [{"id": t.id, "case_id": t.case_id} for t in tasks]

    # 각 작업을 처리
    for info in task_info:
        task_id = info["id"]
        case_id = info["case_id"]
        logger.info(f"[그래프 동기화 워커] 사건({case_id}) 그래프 동기화 작업 시작")

        # 실제 동기화 로직 수행 (PostgreSQL 스냅샷 -> Neo4j 단독 동기화, ChromaDB 미사용)
        result = safe_sync_case(case_id)

        # 결과 업데이트
        with SessionLocal() as tx:
            t = tx.query(GraphSyncTask).filter_by(id=task_id).first()
            if not t:
                continue

            if result.get("status") in ("SYNCED", "CASE_NOT_FOUND"):
                t.status = "COMPLETED"
                t.error_message = None
            else:
                t.status = "FAILED"
                t.retry_count += 1
                t.error_message = str(result.get("error", result.get("status")))
                logger.warning(f"[그래프 동기화 워커] 사건({case_id}) 동기화 작업 실패: {t.error_message}")
            t.updated_at = get_kst_now()
            tx.commit()


def queue_sync_task(db: Session, case_id: str) -> GraphSyncTask:
    """트랜잭션 내에서 동기화 작업을 큐에 추가하고 해당 작업 엔티티를 반환한다."""
    # 동일 case_id에 대해 이미 PENDING인 작업이 있으면 추가하지 않음(Debouncing)
    existing = db.query(GraphSyncTask).filter_by(case_id=case_id, status="PENDING").first()
    if existing:
        return existing
    task = GraphSyncTask(case_id=case_id)
    db.add(task)
    db.flush()
    return task
