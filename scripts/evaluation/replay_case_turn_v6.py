# -*- coding: utf-8 -*-
"""E2E V6 특정 상담 턴 재현: *항상 신규 사건*에서 1차부터 순차 실행.

예:
  python scripts/evaluation/replay_case_turn_v6.py --case SC-012 --through-turn 2

이 명령은 새 DB Case/Conversation을 만들고 1차 증거→1차 상담→2차 증거→
2차 상담까지만 실행한다. 3차 증거를 불러오지 않는다.

Gemini 인계:
- 기존 DB case_id를 직접 재사용해 같은 질문을 실행하면 이미 등록된 미래 증거
  (및 해당 문서에서 파생된 Fact/Claim)가 2차 답변에 혼입된다. 이 스크립트는
  조회 시점 필터링 대신 독립된 신규 사건을 만들어 그 원인을 피한다.
- 기존 전체 10건 E2E 엔트리포인트(main)는 변경하지 않는다. 이 스크립트는
  중앙 checkpoint, Excel KPI, 전체 Trace Catalog, 개선보고서를 업데이트하지 않는다.
- 답변의 PASS/INSUFFICIENT는 상담 워크플로우 자체의 판단이며, 증거 격리
  검사의 MATCHED와는 별개다. 이 단계에서 법률 답변 개선을 주장하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
import sys
from datetime import datetime, timezone
from pathlib import Path

# 직접 실행(python scripts/evaluation/replay_case_turn_v6.py)도 -m 실행과 동일하게 동작.
# 이 코드가 없다면 Python이 scripts/evaluation 폴더만 탐색해 프로젝트 패키지를 못 찾을 수 있다.
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.evaluation.create_complex_10cases_testset import TEST_CASES
from scripts.evaluation.run_complex_10cases_e2ev6_hitl_auto import (
    ARTIFACTS_DIR,
    get_langfuse,
    run_case_evaluation,
)

logger = logging.getLogger("E2E_V6_FRESH_REPLAY")


async def replay(case_code: str, through_turn: int) -> Path:
    matching = [case for case in TEST_CASES if case.get("case_id") == case_code]
    if len(matching) != 1:
        raise ValueError(f"unknown or duplicated test case: {case_code}")
    case_meta = matching[0]
    if not (1 <= through_turn <= len(case_meta.get("turns", []))):
        raise ValueError(f"through_turn outside scenario range: {through_turn}")

    # 인메모리 결과/카탈로그: 기존 E2E V6 checkpoint 파일은 읽거나 쓰지 않는다.
    results: dict = {}
    catalog: list = []
    anomalies: list = []
    result = await run_case_evaluation(
        case_meta=case_meta,
        results=results,
        catalog_entries=catalog,
        anomalies=anomalies,
        lf=get_langfuse(),
        stop_after_turn=through_turn,
    )
    if result is None or not result.get("replay_only"):
        raise RuntimeError("fresh replay did not return an isolated result")

    # 사용자에게 새 DB Case ID와 Trace ID를 명확히 전달한다. 원본 E2E KPI와 분리.
    out_dir = Path(ARTIFACTS_DIR) / "isolated_replays"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"{case_code}_turn{through_turn}_{uuid.uuid4().hex[:12]}.json"
    payload = {
        "replay_type": "NEW_CASE_SEQUENTIAL_THROUGH_TURN",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_code": case_code,
        "through_turn": through_turn,
        "db_case_id": result["db_case_id"],
        "user_testing_required": True,
        "not_full_e2e_result": True,
        "turns": result["turns"],
        "catalog": catalog,
        "anomalies": anomalies,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("격리 재현 완료 (수동 결과 확인 필요): %s", output)
    logger.info("신규 DB 사건 ID: %s", result["db_case_id"])
    for turn in result["turns"]:
        snapshot = turn.get("evidence_snapshot") or {}
        logger.info(
            "  턴 %s | evidence=%s | manifest=%s | trace=%s | answer_status=%s",
            turn["step"], snapshot.get("document_count"), snapshot.get("manifest_sha256"),
            turn.get("trace_id"), turn.get("verification_status"),
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SC-011~SC-020 until turn N using a brand-new DB case (no V6 KPI overwrite)."
    )
    parser.add_argument("--case", required=True, help="Scenario ID, e.g. SC-012")
    parser.add_argument("--through-turn", required=True, type=int, help="Replay turns 1..N")
    args = parser.parse_args()
    asyncio.run(replay(case_code=args.case, through_turn=args.through_turn))


if __name__ == "__main__":
    main()
