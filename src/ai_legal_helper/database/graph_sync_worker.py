# -*- coding: utf-8 -*-
"""
그래프 동기화 워커 (Graph Sync Worker)

PostgreSQL의 graph_sync_tasks 테이블을 폴링하여 Neo4j 동기화를 비동기 백그라운드에서 처리한다.
재시도 로직 및 중복 방지를 포함한다.
"""
import asyncio
import logging
import traceback
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import GraphSyncTask
from ai_legal_helper.database.graph_sync import safe_sync_case

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

async def graph_sync_worker_loop():
    """주기적으로 graph_sync_tasks 테이블을 폴링하여 동기화를 수행하는 백그라운드 워커."""
    logger.info("Graph Sync Worker started.")
    while True:
        try:
            # 동기적인 DB 작업을 쓰레드에서 실행
            await asyncio.to_thread(_process_pending_tasks)
        except Exception as e:
            logger.error(f"Graph Sync Worker error: {e}\n{traceback.format_exc()}")
        await asyncio.sleep(5)  # 5초 간격 폴링

def _process_pending_tasks():
    with SessionLocal() as db:
        # PENDING 이거나 FAILED(재시도 한도 미만) 작업 조회
        tasks = db.query(GraphSyncTask).filter(
            or_(
                GraphSyncTask.status == "PENDING",
                (GraphSyncTask.status == "FAILED") & (GraphSyncTask.retry_count < MAX_RETRIES)
            )
        ).order_by(GraphSyncTask.created_at.asc()).limit(10).with_for_update(skip_locked=True).all()
        
        if not tasks:
            return
            
        # 상태를 PROCESSING으로 변경하여 다른 워커(또는 다음 루프)가 잡지 않도록 함
        for task in tasks:
            task.status = "PROCESSING"
        db.commit()
        
        # 처리 대상 task 정보 복사
        task_info = [{"id": t.id, "case_id": t.case_id} for t in tasks]

    # 각 작업을 처리
    for info in task_info:
        task_id = info["id"]
        case_id = info["case_id"]
        logger.info(f"[GRAPH_WORKER] Processing sync task for case {case_id}")
        
        # 실제 동기화 로직 수행 (Neo4j 및 ChromaDB)
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
                logger.warning(f"[GRAPH_WORKER] Task failed for case {case_id}: {t.error_message}")
            tx.commit()

def queue_sync_task(db: Session, case_id: str):
    """트랜잭션 내에서 동기화 작업을 큐에 추가한다."""
    # 동일 case_id에 대해 이미 PENDING인 작업이 있으면 추가하지 않음(Debouncing)
    existing = db.query(GraphSyncTask).filter_by(case_id=case_id, status="PENDING").first()
    if not existing:
        task = GraphSyncTask(case_id=case_id)
        db.add(task)

