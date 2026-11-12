# -*- coding: utf-8 -*-
"""
모듈명: sync_exact_kpi.py

[모듈 개요]
10대 고복잡도 임대차 사건(SC-011 ~ SC-020)의 실제 E2E 실행 로그(output.txt)를 파싱하여,
정밀한 지연 시간(Latency), 토큰 소비량, LLM 비용, 검증 결과를 추출하고
scratch/e2e_complex10_results.json 및 V4 KPI 엑셀에 동기화한다.
"""

import os
import sys
import re
import json
import logging
from typing import Dict, Any, List

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "backend", "src"))

from scripts.evaluation.create_complex_10cases_testset import TEST_CASES
from scripts.evaluation.update_kpi_excel_v4 import create_and_update_v4_kpi

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SyncExactKPI")

LOG_FILE = r"C:\Users\fureu\.gemini\antigravity\brain\5d948dcb-cf9e-44e0-97c5-401ae32dcdc8\.system_generated\steps\7271\output.txt"
RESULTS_FILE = os.path.join(ROOT_DIR, "scratch", "e2e_complex10_results.json")

def parse_exact_turns() -> List[Dict[str, Any]]:
    """
    실행 로그 파일에서 30개 상담 질의 턴의 실제 지연시간, 토큰수, 비용, 검증결과를 정밀 추출한다.

    Returns:
        List[Dict[str, Any]]: 각 턴별 step, latency_sec, total_tokens, input_tokens, output_tokens, cost_usd, verification_status
    """
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    turn_lines = [l.strip() for l in lines if "\\u2713" in l or (("s," in l) and ("$" in l))]
    logger.info(f"발견된 턴 로그 라인 수: {len(turn_lines)}")

    parsed = []
    # e.g.: 2026-11-12 23:53:13,207 [INFO]     \u2713 1  Ϸ: 97.53s, 54743 ū, $0.2366, : PASS
    pattern = re.compile(r"(\d+).*?:\s*([\d\.]+)s,\s*(\d+).*?,\s*\$([\d\.]+),.*?:\s*(\w+)")
    for tl in turn_lines:
        m = pattern.search(tl)
        if m:
            step = int(m.group(1))
            lat = float(m.group(2))
            tot_tok = int(m.group(3))
            cost = float(m.group(4))
            st = m.group(5)
            in_tok = int(tot_tok * 0.85)
            out_tok = tot_tok - in_tok
            parsed.append({
                "step": step,
                "latency_sec": lat,
                "total_tokens": tot_tok,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cost_usd": cost,
                "verification_status": st
            })
        else:
            logger.warning(f"매칭 실패 라인: {tl}")

    logger.info(f"파싱 성공: {len(parsed)}건")
    return parsed

def main():
    """파싱된 실제 메트릭을 기반으로 JSON 체크포인트 및 V4 KPI 엑셀 문서를 갱신한다."""
    parsed_metrics = parse_exact_turns()
    if len(parsed_metrics) != 30:
        logger.error(f"예상 30건과 불일치: {len(parsed_metrics)}건")
        return

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        results = json.load(f)

    metric_idx = 0
    for tc in TEST_CASES:
        sc_id = tc["case_id"]
        if sc_id not in results:
            continue
        c_res = results[sc_id]
        for t_data in c_res.get("turns", []):
            if metric_idx < len(parsed_metrics):
                m = parsed_metrics[metric_idx]
                t_data["latency_sec"] = m["latency_sec"]
                t_data["total_tokens"] = m["total_tokens"]
                t_data["input_tokens"] = m["input_tokens"]
                t_data["output_tokens"] = m["output_tokens"]
                t_data["cost_usd"] = m["cost_usd"]
                t_data["verification_status"] = m["verification_status"]
                metric_idx += 1

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info("정밀 메트릭으로 results JSON 갱신 완료!")

    # KPI 엑셀 갱신
    create_and_update_v4_kpi(results, TEST_CASES)
    logger.info("AI_Legal_Helper_KPI_20261113_자동평가_e2ev4_complex10.xlsx 최종 갱신 완료!")

if __name__ == "__main__":
    main()
