# -*- coding: utf-8 -*-
"""P11 Temporal Law RAG 정량 평가·A/B/C 비교 하네스.

[목적]
하나의 평가 시나리오 실행을 1회로 세고, 실제 Trace/상담 출력 JSONL을 이용해
출처 접지·법령 시점·판단유보·지연·토큰량을 자동 집계한다.

[평가 신뢰 정책]
- Gold Set 정답은 법률전문가 검토로 확정한다. 샘플 문서의 값은 운영
  법률 정답으로 간주하지 않는다.
- 시점 판정 상태 일치와 법률 답변 자체의 실질적 정답은 구별한다.
- citation_source_id가 검색 source_id에 존재하는지만 확인한 값은
  '출처 참조 무결성'이며 claim-to-source 법률적 정답률이 아니다.
- LLM/Chroma/OpenLaw 호출 없이 입력 파일을 재현가능하게 분석한다.
- 미실행 결과를 0ms/0토큰/정답으로 임의 채우지 않는다.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


VALID_TEMPORAL = frozenset(("APPLICABLE", "NOT_APPLICABLE", "UNCONFIRMED"))
VALID_SYSTEMS = frozenset(("LLMCHAT", "LLMRAG", "LEGALAGENT"))


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """빈 줄 제외 JSON Lines, 객체가 아닌 데이터와 중복 식별자를 이후 검증."""
    out = []
    with open(path, encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"INVALID_JSONL_LINE_{line_no}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"NON_OBJECT_JSONL_LINE_{line_no}")
            out.append(item)
    return out


def percentile(values: list[float], p: float) -> float | None:
    """측정값이 없는 경우 None. 0으로 허위 보고하지 않는다."""
    if not values:
        return None
    ordered = sorted(values)
    idx = (len(ordered) - 1) * p
    lo = math.floor(idx)
    hi = math.ceil(idx)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo), 3)


def validate_gold(cases: list[dict]) -> dict[str, dict]:
    """Gold 정답은 scenario_id/시점 판정 3상/실제 기준일을 명시한다."""
    indexed = {}
    for item in cases:
        sid = str(item.get("scenario_id") or "").strip()
        status = item.get("expected_temporal_status")
        if not sid or sid in indexed:
            raise ValueError("INVALID_OR_DUPLICATE_GOLD_SCENARIO")
        if status not in VALID_TEMPORAL:
            raise ValueError(f"INVALID_GOLD_TEMPORAL_STATUS:{sid}")
        if not item.get("question"):
            raise ValueError(f"MISSING_GOLD_QUESTION:{sid}")
        indexed[sid] = item
    if not indexed:
        raise ValueError("EMPTY_GOLD_SET")
    return indexed


def _source_ids(row: dict, field_name: str) -> set[str]:
    raw = row.get(field_name) or []
    if not isinstance(raw, list):
        raise ValueError("SOURCES_MUST_BE_LIST")
    result = set()
    for value in raw:
        if isinstance(value, dict):
            ident = value.get("source_id")
        else:
            ident = value
        if ident:
            result.add(str(ident))
    return result


def evaluate_system(
    gold: list[dict], runs: list[dict], system: str,
) -> dict[str, Any]:
    """시나리오 1회 실행=단일 결과 원칙으로 품질/성능을 동시에 측정."""
    if system not in VALID_SYSTEMS:
        raise ValueError("INVALID_SYSTEM")
    gold_map = validate_gold(gold)
    chosen = {}
    for run in runs:
        if run.get("system") != system:
            continue
        sid = str(run.get("scenario_id") or "").strip()
        if sid not in gold_map:
            raise ValueError(f"UNKNOWN_SCENARIO:{sid}")
        if sid in chosen:
            raise ValueError(f"DUPLICATE_SCENARIO_RUN:{system}:{sid}")
        if not run.get("run_id"):
            raise ValueError(f"RUN_ID_REQUIRED:{sid}")
        chosen[sid] = run

    measured = len(chosen)
    temporal_correct = 0
    grounding_pass = 0
    grounding_evaluable = 0
    unsafe_count = 0
    manually_reviewed = 0
    manual_correct = 0
    latency = []
    input_tokens = []
    output_tokens = []
    rows = []
    for sid, entry in gold_map.items():
        run = chosen.get(sid)
        if run is None:
            rows.append({"scenario_id": sid, "status": "NOT_RUN"})
            continue
        expected = entry["expected_temporal_status"]
        predicted = run.get("temporal_status")
        if predicted not in VALID_TEMPORAL:
            raise ValueError(f"INVALID_PREDICTED_TEMPORAL_STATUS:{sid}")
        correct = predicted == expected
        temporal_correct += int(correct)
        seen = _source_ids(run, "retrieved_sources")
        cited = _source_ids(run, "cited_sources")
        if cited:
            grounding_evaluable += 1
            grounding_pass += int(cited.issubset(seen))
        if "manual_legal_correct" in run and run["manual_legal_correct"] is not None:
            if not isinstance(run["manual_legal_correct"], bool):
                raise ValueError("MANUAL_LEGAL_CORRECT_MUST_BE_BOOL")
            manually_reviewed += 1
            manual_correct += int(run["manual_legal_correct"])
        if run.get("manual_unsafe") is True:
            unsafe_count += 1
        for field, store in (
            ("latency_ms", latency),
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
        ):
            val = run.get(field)
            if val is None:
                continue
            if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0:
                raise ValueError(f"INVALID_MEASUREMENT:{sid}:{field}")
            store.append(val)
        rows.append({
            "scenario_id": sid, "status": "MEASURED",
            "temporal_match": correct,
            "expected": expected, "predicted": predicted,
            "citations_total": len(cited),
            "citation_ids_in_retrieval": cited.issubset(seen) if cited else None,
            "manual_legal_correct": run.get("manual_legal_correct"),
            "manual_unsafe": run.get("manual_unsafe"),
        })

    return {
        "system": system,
        "scenario_count": len(gold_map),
        "measured_count": measured,
        "missing_count": len(gold_map) - measured,
        "temporal_status_accuracy": round(temporal_correct / measured, 4) if measured else None,
        "temporal_status_pass_rate_all": round(temporal_correct / len(gold_map), 4),
        "citation_id_integrity": round(grounding_pass / grounding_evaluable, 4)
        if grounding_evaluable else None,
        "citation_evaluable_count": grounding_evaluable,
        "manual_legal_accuracy": round(manual_correct / manually_reviewed, 4)
        if manually_reviewed else None,
        "manual_review_count": manually_reviewed,
        "manual_unsafe_count": unsafe_count,
        "latency_ms_p50": percentile(latency, .5),
        "latency_ms_p95": percentile(latency, .95),
        "latency_sample_count": len(latency),
        "input_tokens_sum": sum(input_tokens) if input_tokens else None,
        "output_tokens_sum": sum(output_tokens) if output_tokens else None,
        "token_sample_count": min(len(input_tokens), len(output_tokens)),
        "cases": rows,
    }


def compare_systems(gold: list[dict], runs: list[dict]) -> dict:
    """A/B/C 시스템별 결과, 동일 샘플 측정 여부를 구분해 비교."""
    results = {
        system: evaluate_system(gold, runs, system)
        for system in ("LLMCHAT", "LLMRAG", "LEGALAGENT")
    }
    for system in results:
        results[system]["comparison_ready"] = (
            results[system]["measured_count"] == len(gold)
            and results[system]["manual_review_count"] == len(gold)
        )
    return {
        "gold_scenarios": len(gold),
        "results": results,
        "full_abc_comparison_ready": all(
            r["comparison_ready"] for r in results.values()
        ),
    }


def to_markdown(result: dict) -> str:
    """평가문서/발표용 통합 요약표. 데이터 미측정 항목은 '-'로 표시."""
    lines = [
        "# Temporal RAG P11 A/B/C 측정 보고",
        "",
        "미측정/미검증 값은 0으로 간주하지 않고 '-'로 표시한다.",
        "",
        "| 시스템 | 측정/전체 | 시점 판정 정확도 | 법률 정답률(수동검수) | 인용ID 무결성 | P50(ms) | P95(ms) | 입력토큰 | 출력토큰 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    def fmt(value):
        return "-" if value is None else str(value)
    for system, r in result["results"].items():
        lines.append(
            f"| {system} | {r['measured_count']}/{r['scenario_count']} | "
            f"{fmt(r['temporal_status_accuracy'])} | {fmt(r['manual_legal_accuracy'])} | "
            f"{fmt(r['citation_id_integrity'])} | {fmt(r['latency_ms_p50'])} | "
            f"{fmt(r['latency_ms_p95'])} | {fmt(r['input_tokens_sum'])} | "
            f"{fmt(r['output_tokens_sum'])} |"
        )
    lines.extend([
        "",
        f"A/B/C 전체 검수 및 측정 완료: {result['full_abc_comparison_ready']}",
        "",
        "주의: 인용ID 무결성은 법률 명제의 정답을 검증하지 않는다. "
        "법률 정답률은 수동검수 데이터가 있을 때만 계산한다.",
    ])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="P11 법령 시점 Gold Set 평가")
    parser.add_argument("--gold", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--md-out")
    args = parser.parse_args()
    result = compare_systems(read_jsonl(args.gold), read_jsonl(args.runs))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.md_out:
        Path(args.md_out).write_text(to_markdown(result), encoding="utf-8")
    print(to_markdown(result))


if __name__ == "__main__":
    main()
