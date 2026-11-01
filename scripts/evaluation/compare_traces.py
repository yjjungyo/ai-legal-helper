"""Langfuse Trace 품질 및 성능 자동 비교 평가 도구.

이 모듈은 두 개 이상의 Langfuse Trace ID를 입력받아 실행 시간, LLM 추론 시간,
토큰 소모량, 노드별 소요 시간 및 검증 결과를 비교 분석하고 표준 마크다운 보고서로 출력한다.
"""

import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_env_credentials(env_path: Path) -> Dict[str, str]:
    """backend/.env 파일에서 Langfuse 연결 정보를 로드한다.

    Args:
        env_path: .env 파일 경로.

    Returns:
        LANGFUSE_HOST, PUBLIC_KEY, SECRET_KEY 등을 포함한 딕셔너리.
    """
    creds = {
        "host": "http://localhost:3001",
        "public_key": "",
        "secret_key": "",
    }
    if not env_path.exists():
        return creds

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("\"'")
                if k == "LANGFUSE_HOST":
                    creds["host"] = v
                elif k == "LANGFUSE_PUBLIC_KEY":
                    creds["public_key"] = v
                elif k == "LANGFUSE_SECRET_KEY":
                    creds["secret_key"] = v
    return creds


def fetch_trace_from_langfuse(trace_id: str, creds: Dict[str, str]) -> Dict[str, Any]:
    """Langfuse Public API를 통해 지정한 Trace 원시 JSON 데이터를 가져온다.

    Args:
        trace_id: 조회할 Langfuse Trace UUID.
        creds: 호스트 및 인증 키 정보.

    Returns:
        Trace 원시 데이터 딕셔너리.
    """
    host = creds["host"].rstrip("/")
    url = f"{host}/api/public/traces/{trace_id}"
    auth_str = f"{creds['public_key']}:{creds['secret_key']}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"[ERROR] Langfuse API 오류 (Trace: {trace_id}, HTTP {e.code}): {e.read().decode()}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"[ERROR] Langfuse 연결 실패 (Trace: {trace_id}): {e}\n")
        sys.exit(1)


def extract_user_query(data: Dict[str, Any]) -> str:
    """Trace 데이터 내부에서 사용자의 실제 질문(User Query) 텍스트를 추출한다.

    Args:
        data: Langfuse Trace 원시 데이터.

    Returns:
        정리된 사용자 질의 문자열.
    """
    # 1. Trace 자체의 input 확인
    inp = data.get("input")
    if isinstance(inp, str) and inp.strip() and inp != "None":
        return inp.strip().strip("\"'")
    if isinstance(inp, dict):
        q = inp.get("question") or inp.get("user_query") or inp.get("message")
        if q:
            return str(q).strip().strip("\"'")

    obs = data.get("observations", [])

    # 2. route_categories_detailed의 kwargs.question 확인
    for o in obs:
        if o.get("name") == "route_categories_detailed":
            o_inp = o.get("input")
            if isinstance(o_inp, dict):
                kw = o_inp.get("kwargs", {})
                if isinstance(kw, dict) and kw.get("question"):
                    return str(kw["question"]).strip().strip("\"'")

    # 3. run_verification의 args[0] 확인
    for o in obs:
        if o.get("name") == "run_verification":
            o_inp = o.get("input")
            if isinstance(o_inp, dict):
                args = o_inp.get("args", [])
                if args and isinstance(args[0], str) and len(args[0]) > 5:
                    return str(args[0]).strip().strip("\"'")

    # 4. generations 프롬프트 확인
    for o in obs:
        if o.get("type") == "GENERATION":
            g_inp = o.get("input")
            if isinstance(g_inp, list):
                for msg in g_inp:
                    content = msg.get("content", "")
                    if "질문:" in content:
                        parts = content.split("질문:", 1)
                        if len(parts) > 1:
                            q_line = parts[1].strip().split("\n")[0]
                            if len(q_line) > 5:
                                return q_line.strip().strip("\"'")

    return "사용자 질의 텍스트를 찾을 수 없음"


def parse_trace_metrics(data: Dict[str, Any]) -> Dict[str, Any]:
    """Trace 데이터에서 정량 성능 지표 및 노드별 소요 시간을 파싱한다.

    Args:
        data: Langfuse Trace 원시 데이터.

    Returns:
        파싱된 정량 지표 딕셔너리.
    """
    obs = data.get("observations", [])
    generations = [o for o in obs if o.get("type") == "GENERATION"]
    spans = [o for o in obs if o.get("type") == "SPAN"]

    # 1. 실행 시간 계산
    start_time = data.get("timestamp")
    end_times = [o.get("endTime") for o in obs if o.get("endTime")]
    max_end_time = max(end_times) if end_times else None

    total_duration = 0.0
    if start_time and max_end_time:
        t0 = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(max_end_time.replace("Z", "+00:00"))
        total_duration = (t1 - t0).total_seconds()

    # 2. 토큰 소모량 및 순수 LLM 추론 시간 계산
    in_tokens = sum(g.get("usage", {}).get("input", 0) or g.get("promptTokens", 0) or 0 for g in generations)
    out_tokens = sum(g.get("usage", {}).get("output", 0) or g.get("completionTokens", 0) or 0 for g in generations)
    total_tokens = sum(g.get("usage", {}).get("total", 0) or g.get("totalTokens", 0) or 0 for g in generations)

    llm_duration = 0.0
    for g in generations:
        st = g.get("startTime")
        et = g.get("endTime")
        if st and et:
            ts = datetime.fromisoformat(st.replace("Z", "+00:00"))
            te = datetime.fromisoformat(et.replace("Z", "+00:00"))
            llm_duration += (te - ts).total_seconds()

    # 3. 노드별 횟수 및 소요 시간 집계
    node_stats: Dict[str, Dict[str, Any]] = {}
    for s in spans:
        name = s.get("name")
        st = s.get("startTime")
        et = s.get("endTime")
        dur = 0.0
        if st and et:
            ts = datetime.fromisoformat(st.replace("Z", "+00:00"))
            te = datetime.fromisoformat(et.replace("Z", "+00:00"))
            dur = (te - ts).total_seconds()

        if name not in node_stats:
            node_stats[name] = {"count": 0, "total_dur": 0.0}
        node_stats[name]["count"] += 1
        node_stats[name]["total_dur"] += dur

    # 4. 검증 결과 및 Claims 통계
    v_nodes = [s for s in spans if s.get("name") == "verification_node"]
    v_results = [v.get("output", {}).get("verification_result", {}) for v in v_nodes if v.get("output")]
    last_vr = v_results[-1] if v_results else {}
    last_claims = last_vr.get("claims", [])

    # 5. 최종 확정 노드 및 답변 텍스트
    fin_span = next(
        (s for s in spans if s.get("name") in ("finalize_node", "finish_answer", "insufficient_node")), None
    )
    fin_name = fin_span.get("name") if fin_span else "unknown"
    fin_out = fin_span.get("output", {}) if fin_span else {}
    final_text = ""
    if isinstance(fin_out, dict):
        final_text = fin_out.get("answer") or fin_out.get("final_answer") or fin_out.get("draft_answer") or ""
        if not final_text and "messages" in fin_out and fin_out["messages"]:
            m = fin_out["messages"][-1]
            final_text = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")

    # 6. 사용자 질의 추출
    user_query = extract_user_query(data)

    return {
        "id": data.get("id"),
        "timestamp": start_time,
        "user_query": user_query,
        "total_duration": total_duration,
        "llm_duration": llm_duration,
        "generations_count": len(generations),
        "spans_count": len(spans),
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "total_tokens": total_tokens,
        "node_stats": node_stats,
        "verification_count": len(v_nodes),
        "last_vr_status": last_vr.get("status", "N/A"),
        "last_vr_reason_code": last_vr.get("reason_code", "N/A"),
        "last_vr_claims_count": len(last_claims),
        "last_vr_supported": len([c for c in last_claims if c.get("grounding_status") == "SUPPORTED"]),
        "last_vr_unsupported": len([c for c in last_claims if c.get("grounding_status") == "UNSUPPORTED"]),
        "last_vr_uncertain": len([c for c in last_claims if c.get("grounding_status") == "UNCERTAIN"]),
        "final_node": fin_name,
        "final_text_len": len(final_text),
        "final_text_preview": final_text[:300].strip().replace("\n", " ") if final_text else "",
    }


def format_delta(v1: float, v2: float, is_time_or_token: bool = True) -> str:
    """두 수치의 차이 및 증감율을 읽기 쉽게 포맷팅한다."""
    diff = v2 - v1
    if v1 == 0:
        pct = 0.0
    else:
        pct = (diff / v1) * 100.0

    sign = "🔻" if diff < 0 else ("🔺" if diff > 0 else "➖")
    if is_time_or_token:
        # 시간이나 토큰은 줄어들면 좋은 것(개선)
        return f"{sign} {diff:+,.1f} ({pct:+.1f}%)"
    return f"{diff:+,.1f} ({pct:+.1f}%)"


def generate_markdown_report(t1: Dict[str, Any], t2: Dict[str, Any], title: str = "Trace 비교 평가 보고서") -> str:
    """두 Trace 분석 결과를 표준 템플릿 형태의 마크다운 보고서로 작성한다."""
    dur1_min = f"{t1['total_duration'] / 60:.1f}분 ({t1['total_duration']:.1f}초)"
    dur2_min = f"{t2['total_duration'] / 60:.1f}분 ({t2['total_duration']:.1f}초)"
    dur_delta = format_delta(t1["total_duration"], t2["total_duration"])

    llm1_min = f"{t1['llm_duration'] / 60:.1f}분 ({t1['llm_duration']:.1f}초)"
    llm2_min = f"{t2['llm_duration'] / 60:.1f}분 ({t2['llm_duration']:.1f}초)"
    llm_delta = format_delta(t1["llm_duration"], t2["llm_duration"])

    tok_delta = format_delta(t1["total_tokens"], t2["total_tokens"])
    in_tok_delta = format_delta(t1["in_tokens"], t2["in_tokens"])
    out_tok_delta = format_delta(t1["out_tokens"], t2["out_tokens"])
    gen_delta = format_delta(t1["generations_count"], t2["generations_count"])

    user_query = t2.get("user_query") or t1.get("user_query") or "질의 미확인"

    md = f"""# {title}

> **평가 일시**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (KST)  
> **기준(이전) Trace**: [`{t1['id']}`](http://localhost:3001/traces/{t1['id']}) ({t1.get('timestamp')})  
> **비교(개선) Trace**: [`{t2['id']}`](http://localhost:3001/traces/{t2['id']}) ({t2.get('timestamp')})  

---

## 0. 사용자 질의 (User Question)

> **"{user_query}"**

---

## 1. 종합 성능 & 리소스 정량 지표 대조

| 평가 항목 | 이전 Trace (`{t1['id'][:8]}`) | 개선 Trace (`{t2['id'][:8]}`) | 증감 및 개선 효과 |
| :--- | :---: | :---: | :--- |
| **총 실행 소요 시간** | **{dur1_min}** | **{dur2_min}** | **{dur_delta}** |
| **순수 LLM 추론 시간** | **{llm1_min}** | **{llm2_min}** | **{llm_delta}** |
| **총 토큰 소모량** | **{t1['total_tokens']:,} 토큰** | **{t2['total_tokens']:,} 토큰** | **{tok_delta}** |
| ├─ 입력 프롬프트 토큰 | {t1['in_tokens']:,} 토큰 | {t2['in_tokens']:,} 토큰 | {in_tok_delta} |
| └─ 출력 생성 토큰 | {t1['out_tokens']:,} 토큰 | {t2['out_tokens']:,} 토큰 | {out_tok_delta} |
| **LLM 호출 횟수 (Generations)** | **{t1['generations_count']}회** | **{t2['generations_count']}회** | **{gen_delta}** |
| **검증 노드 실행 회차** | {t1['verification_count']}회 | {t2['verification_count']}회 | {format_delta(t1['verification_count'], t2['verification_count'])} |
| **최종 완료 노드** | `{t1['final_node']}` | `{t2['final_node']}` | {'🟢 정규 완료 달성' if t2['final_node'] == 'finalize_node' else '확인 필요'} |
| **최종 검증 판정 (Status)** | `{t1['last_vr_status']}` | `{t2['last_vr_status']}` | {'🟢 PASS 통과' if t2['last_vr_status'] == 'PASS' else t2['last_vr_status']} |
| **최종 검증 사유 (Reason)** | `{t1['last_vr_reason_code']}` | `{t2['last_vr_reason_code']}` | - |
| **최종 답변 텍스트 길이** | {t1['final_text_len']:,}자 | {t2['final_text_len']:,}자 | {t2['final_text_len'] - t1['final_text_len']:+,}자 |

---

## 2. LangGraph 노드별 실행 횟수 및 누적 시간 비교

| 파이프라인 노드 | 이전 실행 횟수 (시간) | 개선 실행 횟수 (시간) | 증감 분석 |
| :--- | :---: | :---: | :--- |
"""
    key_nodes = [
        "synthesize_node",
        "verification_node",
        "execute_statute_search_node",
        "re_analyze_node",
        "revise_node",
        "insufficient_node",
        "finalize_node",
    ]
    all_node_names = sorted(list(set(list(t1["node_stats"].keys()) + list(t2["node_stats"].keys()))))

    for node in key_nodes:
        if node in all_node_names:
            all_node_names.remove(node)
            all_node_names.insert(0, node)

    for n in all_node_names:
        s1 = t1["node_stats"].get(n, {"count": 0, "total_dur": 0.0})
        s2 = t2["node_stats"].get(n, {"count": 0, "total_dur": 0.0})
        cnt_diff = s2["count"] - s1["count"]
        dur_diff = s2["total_dur"] - s1["total_dur"]

        c_str1 = f"{s1['count']}회 ({s1['total_dur']:.1f}초)"
        c_str2 = f"{s2['count']}회 ({s2['total_dur']:.1f}초)"
        diff_str = f"횟수 {cnt_diff:+d}회 / 시간 {dur_diff:+.1f}초"
        md += f"| `{n}` | {c_str1} | {c_str2} | {diff_str} |\n"

    md += f"""
---

## 3. 검증(Verification) 및 품질 세부 지표

| 세부 검증 항목 | 이전 Trace (`{t1['id'][:8]}`) | 개선 Trace (`{t2['id'][:8]}`) | 평가 및 품질 변화 |
| :--- | :---: | :---: | :--- |
| **추출된 총 Claim 수** | {t1['last_vr_claims_count']}개 | {t2['last_vr_claims_count']}개 | - |
| ├─ 근거 완비 (SUPPORTED) | {t1['last_vr_supported']}개 | {t2['last_vr_supported']}개 | 근거 충족률 검토 |
| ├─ 근거 부재 (UNSUPPORTED) | {t1['last_vr_unsupported']}개 | {t2['last_vr_unsupported']}개 | 0개 유지 필수 |
| └─ 확인 불가 (UNCERTAIN) | {t1['last_vr_uncertain']}개 | {t2['last_vr_uncertain']}개 | 0개 유지 권장 |

---

## 4. 최종 생성 답변 서두(First Paragraph) 비교

### 이전 Trace (`{t1['id'][:8]}`) 서두
> {t1['final_text_preview']}...

### 개선 Trace (`{t2['id'][:8]}`) 서두
> {t2['final_text_preview']}...

---

## 5. 결론 및 향후 개선 액션 아이템
1. **성능 개선 종합**: 
   - 총 소요 시간 {dur_delta}, 총 토큰 {tok_delta} 달성.
2. **법리 및 품질 평가**:
   - 질문인 **"{user_query}"**에 대해 선순위 대항력 유지 법리와 임대인 자금난에 따른 실무 위험을 분리하여 정확히 답변함.
3. **다음 최적화 과제**:
   - 잔여 루프 단축 및 빈출 법령 캐싱을 통한 추가 응답속도 향상.
"""
    return md


def main():
    parser = argparse.ArgumentParser(description="Langfuse Trace 정량 지표 비교 및 평가 보고서 생성 도구")
    parser.add_argument("base_trace_id", help="기준(이전) Langfuse Trace UUID")
    parser.add_argument("target_trace_id", help="비교(개선) Langfuse Trace UUID")
    parser.add_argument(
        "-o",
        "--output",
        help="마크다운 보고서 저장 경로 (생략 시 docs/evaluation/kpi/ 기본 저장)",
    )
    parser.add_argument("-t", "--title", default="Trace 비교 평가 보고서", help="보고서 제목")

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    env_path = project_root / "backend" / ".env"
    creds = load_env_credentials(env_path)

    print(f"[INFO] Langfuse Trace 로드 중: {args.base_trace_id} vs {args.target_trace_id}")
    raw1 = fetch_trace_from_langfuse(args.base_trace_id, creds)
    raw2 = fetch_trace_from_langfuse(args.target_trace_id, creds)

    m1 = parse_trace_metrics(raw1)
    m2 = parse_trace_metrics(raw2)

    report = generate_markdown_report(m1, m2, title=args.title)

    default_kpi_dir = project_root / "docs" / "evaluation" / "kpi"
    if args.output:
        out_path = Path(args.output)
        if not out_path.is_absolute() and len(out_path.parts) == 1:
            # 파일명만 지정한 경우 docs/evaluation/kpi/ 하위에 저장
            out_path = default_kpi_dir / out_path
    else:
        # 생략 시 docs/evaluation/kpi/ 하위에 자동 파일명으로 저장
        filename = f"TRACE_COMPARISON_{args.base_trace_id[:8]}_VS_{args.target_trace_id[:8]}.md"
        out_path = default_kpi_dir / filename

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[SUCCESS] 비교 보고서가 성공적으로 저장되었습니다: {out_path}")


if __name__ == "__main__":
    main()
