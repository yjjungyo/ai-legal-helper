# -*- coding: utf-8 -*-
"""P11 실제 LEGALAGENT 단일 실행 평가 수집기 (사용자 PC 백엔드용).

본 명령은 벤치마크 질문을 순차 실행하고 실행/소요시간/법령 출처/Trace를
JSONL로 출력한다. LLMCHAT/LLMRAG는 별도 결과를 같은 표준 형식으로 import.
법령 공식 검색에 대한 사용자 동의는 --approve-official 옵션을 명시한
해당 실험 실행에서만 발생한다. 기본값은 승인하지 않으며 HILT 대기 사례를
완료된 정확도 표본으로 취급하지 않는다.

주의:
- 인증 키, 원문 사건 개인정보, 답변 전문을 기본 결과 파일에 저장하지 않는다.
- 실제 프로그램/LLM/PostgreSQL/Chroma가 연결된 사용자 환경에서만 실행한다.
- Token 값은 반환 결과에 직접 없는 경우 null로 기록한다 (0으로 위조 금지).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND / "src"))

from temporal_rag_eval import read_jsonl, validate_gold


def _status(resolution: dict | None) -> str:
    """P5의 조문별 복수 판정이 서로 다르면 법령 적용상태 단일 확정 불가."""
    decisions = resolution.get("decisions") or [] if isinstance(resolution, dict) else []
    statuses = {d.get("status") for d in decisions if isinstance(d, dict)}
    if len(statuses) == 1 and next(iter(statuses)) in (
        "APPLICABLE", "NOT_APPLICABLE", "UNCONFIRMED"
    ):
        return next(iter(statuses))
    return "UNCONFIRMED"


async def run_single(case: dict, *, approve_official: bool = False) -> dict:
    """벤치마크 시나리오당 하나의 LangGraph 완료 결과만 저장."""
    from langgraph.checkpoint.memory import MemorySaver
    from ai_legal_helper.workflows.legal_workflow import run_legal_consultation

    thread = "p11:" + case["scenario_id"] + ":" + str(uuid.uuid4())
    saver = MemorySaver()
    start = time.perf_counter()
    output = await run_legal_consultation(
        question=case["question"], thread_id=thread, checkpointer=saver,
    )
    if output.get("status") == "APPROVAL_REQUIRED" and approve_official:
        # --approve-official은 사용자 PC에서 실험 목적의 공식 검색 승인을
        # 명시적으로 허가한 경우에만 활용한다.
        output = await run_legal_consultation(
            question="", thread_id=thread, checkpointer=saver,
            resume_data={"approved": True, "reason": "P11 명시 실험 승인"},
        )
    duration = round((time.perf_counter() - start) * 1000, 3)
    if output.get("status") != "SUCCESS":
        return {
            "scenario_id": case["scenario_id"],
            "status": "INCOMPLETE",
            "reason": output.get("status"),
            "trace_id": output.get("trace_id"),
            "run_id": thread,
            "latency_ms": duration,
        }

    ver = output.get("verification_result") or {}
    resolution = output.get("temporal_resolution") or {}
    retrieved = output.get("retrieved_sources") or []
    cited = output.get("cited_sources") or []

    return {
        "system": "LEGALAGENT",
        "scenario_id": case["scenario_id"],
        "run_id": thread,
        "trace_id": output.get("trace_id"),
        "temporal_status": _status(resolution),
        "temporal_gate": (ver.get("temporal_gate") or {}).get("status"),
        "verification_status": ver.get("status"),
        "final_disposition": output.get("final_disposition"),
        "retrieved_sources": [{"source_id": x.get("source_id")}
                              for x in retrieved if isinstance(x, dict)],
        "cited_sources": [{"source_id": x.get("source_id")}
                          for x in cited if isinstance(x, dict)],
        "latency_ms": duration,
        "input_tokens": None,
        "output_tokens": None,
        "manual_legal_correct": None,
        "manual_unsafe": None,
    }


async def run_cases(cases, *, approve_official=False):
    rows, incomplete = [], []
    for case in cases:
        try:
            output = await run_single(case, approve_official=approve_official)
        except Exception as exc:
            # 사용자 질문/키/에러 텍스트는 기록하지 않는다.
            incomplete.append({
                "scenario_id": case["scenario_id"],
                "status": "ERROR", "error_type": type(exc).__name__,
            })
            continue
        if output.get("status") == "INCOMPLETE":
            incomplete.append(output)
        else:
            rows.append(output)
    return rows, incomplete


def main():
    parser = argparse.ArgumentParser(description="P11 LEGALAGENT 시나리오 실제 실행")
    parser.add_argument("--gold", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--incomplete-out", required=True)
    parser.add_argument("--approve-official", action="store_true",
                        help="실험의 외부 공식 법령 검색 HILT를 명시적으로 승인")
    args = parser.parse_args()
    cases = read_jsonl(args.gold)
    validate_gold(cases)
    rows, incomplete = asyncio.run(
        run_cases(cases, approve_official=args.approve_official)
    )
    Path(args.out).write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows),
        encoding="utf-8",
    )
    Path(args.incomplete_out).write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in incomplete),
        encoding="utf-8",
    )
    print(
        f"P11 LEGALAGENT complete={len(rows)}/{len(cases)} "
        f"incomplete={len(incomplete)}; manual legal review still required"
    )


if __name__ == "__main__":
    main()
