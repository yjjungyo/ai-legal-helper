# -*- coding: utf-8 -*-
"""FastAPI 백그라운드 법령 증분 인덱싱 워커 루프(law_index_worker_loop) 단위 테스트."""
import asyncio
import os
import pytest
from unittest.mock import patch, MagicMock

from ai_legal_helper.legal_knowledge.index_worker import law_index_worker_loop


@pytest.mark.asyncio
async def test_worker_loop_disabled_by_env():
    """LEGAL_BACKGROUND_INDEX_ENABLED가 0이면 루프가 즉시 반환된다."""
    with patch.dict(os.environ, {"LEGAL_BACKGROUND_INDEX_ENABLED": "0"}):
        task = asyncio.create_task(law_index_worker_loop(interval_seconds=0.01))
        await asyncio.wait_for(task, timeout=1.0)
        assert task.done()


@pytest.mark.asyncio
async def test_worker_loop_drains_jobs_and_handles_cancellation():
    """대기 중인 작업이 있으면 run_worker_once를 호출하고 취소 신호 수신 시 안전하게 종료된다."""
    call_count = 0

    def mock_run_worker():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"status": "READY", "law_name": "주택임대차보호법", "mst": "276291", "chunk_count": 43}
        return {"status": "EMPTY"}

    with patch.dict(os.environ, {
        "LEGAL_BACKGROUND_INDEX_ENABLED": "1",
        "LAW_OPENAPI_KEY": "test-key",
    }):
        with patch("ai_legal_helper.legal_knowledge.index_worker.run_worker_once", side_effect=mock_run_worker):
            task = asyncio.create_task(law_index_worker_loop(interval_seconds=0.05))
            # 1회 이상 실행될 수 있도록 잠시 대기
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert call_count >= 1
