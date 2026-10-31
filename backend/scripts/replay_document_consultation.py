"""기존 실패 trace의 공식 법령과 사건 문서로 수정된 답변 경로를 재현한다.

현재 DB는 읽기만 하며 상담/증거를 생성하거나 변경하지 않는다. 법령 검색 단계는
기존 승인 검색 결과를 재사용하므로 브라우저 전체 E2E 검사와 구분하여 보고한다.
실제 모델 호출은 기존 Gateway를 사용하고 결과는 지정한 Markdown에 기록한다.
"""

import argparse
import base64
from collections import Counter
import json
import hashlib
import os
from pathlib import Path
import sys
import urllib.request
from urllib.parse import urlsplit
import uuid

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))
load_dotenv(REPO_ROOT / "backend" / ".env")


def load_official_sources(trace_id: str) -> list[dict]:
    """로컬 Langfuse에서 기존에 승인되어 검색된 공식 법령만 읽는다.

    Args:
        trace_id: 법령 검색 관측값이 저장된 기존 실패 trace ID.

    Returns:
        공식 법령 검색 결과 전체 목록.

    Raises:
        ValueError: 로컬 서버가 아니거나 기존 공식 법령 결과가 없는 경우.
    """
    host = os.environ["LANGFUSE_HOST"].rstrip("/")
    if urlsplit(host).hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("LOCAL_LANGFUSE_REQUIRED")
    credential = (os.environ["LANGFUSE_PUBLIC_KEY"] + ":" + os.environ["LANGFUSE_SECRET_KEY"]).encode()
    request = urllib.request.Request(host + "/api/public/traces/" + trace_id, headers={
        "Authorization": "Basic " + base64.b64encode(credential).decode(),
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        trace = json.load(response)
    for observation in trace.get("observations", []):
        if observation.get("name") != "execute_statute_search_node":
            continue
        output = observation.get("output") or {}
        if isinstance(output, str):
            output = json.loads(output)
        sources = output.get("statute_search_results") or []
        if sources:
            return sources
    raise ValueError("NO_CACHED_OFFICIAL_STATUTES")


def main() -> None:
    """문서 수별 실제 작성·검증·최종 출력을 실행하고 재현 범위를 보고한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--scenario", choices=["overview", "renewal"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from langchain_core.messages import HumanMessage
    from ai_legal_helper.case_intelligence.case_briefing import build_case_evidence_briefing
    from ai_legal_helper.database.session import SessionLocal
    from ai_legal_helper.observability.context import set_trace_id, set_case_id, set_request_id
    from ai_legal_helper.observability.langfuse_client import start_trace, end_trace, flush_langfuse
    from ai_legal_helper.workflows import legal_workflow as workflow
    from ai_legal_helper.workflows.document_consultation import DOCUMENT_MODE

    question = (
        "등록된 계약서와 입금·전입 자료를 기준으로 현재까지 확인되는 계약 사실, 당사자, "
        "보증금 지급 여부, 임차인의 권리 및 앞으로 확인할 사항을 분석해 주세요."
        if args.scenario == "overview" else
        "최초 계약기간이 지났지만 갱신계약서를 새로 작성하지 않았습니다. "
        "기존 계약은 현재 어떤 상태인가요? 앞으로 계약을 종료하려면 어떻게 해야 하나요?"
    )
    count = 3 if args.scenario == "overview" else 4
    with SessionLocal() as db:
        briefing = build_case_evidence_briefing(db, args.case_id, question).model_dump()
    briefing["source_documents"] = sorted(briefing["source_documents"], key=lambda d: d["evidence_label"])[:count]
    if len(briefing["source_documents"]) != count:
        raise ValueError("REPLAY_DOCUMENT_COUNT_MISMATCH")
    sources = load_official_sources(args.trace_id)
    implementation_files = (
        "agents/document_answer.py", "agents/verification.py", "agents/document_verification_prompt.py", "workflows/document_consultation.py",
        "workflows/legal_workflow.py", "rag/grounding_context.py", "case_intelligence/case_briefing.py",
    )
    implementation_hash = hashlib.sha256(b"".join(
        (REPO_ROOT / "backend/src/ai_legal_helper" / name).read_bytes() for name in implementation_files
    )).hexdigest()
    trace_id = str(uuid.uuid4())
    set_trace_id(trace_id)
    set_case_id(args.case_id)
    set_request_id("document-replay-" + trace_id)
    start_trace(trace_id=trace_id, name="DocumentGroundingReplay", metadata={
        "scenario": args.scenario, "replay_of": args.trace_id,
        "cached_official_statutes": len(sources), "document_count": count,
        "is_browser_e2e": False,
        "implementation_sha256": implementation_hash,
    })
    state = {"question": question, "messages": [HumanMessage(content=question)],
             "answer_mode": DOCUMENT_MODE, "case_evidence_briefing": briefing,
             "retrieved_sources": sources, "revision_count": 0,
             "hilt_executed": True, "warnings": []}
    records = []
    try:
        for step in range(3):
            # 추적 SDK가 이전 입력을 비동기로 직렬화하므로 전달한 상태 객체를 뒤에서 변경하지 않는다.
            state = {**state, **(workflow.synthesize_node(state) if step == 0 else workflow.revise_node(state))}
            state = {**state, **workflow.verification_node(state)}
            result = state["verification_result"]
            route = workflow.verification_condition(state)
            records.append({"iteration": step + 1, "status": result.get("status"),
                            "answer_generation_error": state.get("answer_generation_error"),
                            "reason_code": result.get("reason_code"), "next": route,
                            "claim_grounding": dict(Counter(c.get("grounding_status") for c in result.get("claims", []))),
                            "question_coverage": result.get("question_coverage", []),
                            "consistency_checks": result.get("consistency_checks", {}),
                            "source_manifest": result.get("source_manifest"),
                            "missing_issues": result.get("missing_issues", []),
                            "revision_instructions": result.get("revision_instructions", [])})
            print(json.dumps({"iteration": step + 1, "status": result.get("status"), "next": route}), flush=True)
            if route != "revise":
                break
        state = {**state, **(workflow.finalize_node(state) if route == "finalize" else workflow.insufficient_node(state))}
        report = ["# 문서 원문 기반 상담 실제 모델 재현", "",
                  f"- 실행 상태: {'모델 호출 실패 — 실제 답변 품질 미확인' if state.get('answer_generation_error') else '모델 호출 완료 — 아래 검증 결과 참조'}",
                  f"- 시나리오: {args.scenario}, 사건 문서 {count}개, 기존 공식 법령 {len(sources)}개",
                  f"- 기준 실패 trace: `{args.trace_id}`", f"- 재현 trace: `{trace_id}`",
                  f"- 모델 배포: `{os.getenv('AZURE_OPENAI_DEPLOYMENT_CHAT', '미지정')}`",
                  f"- 답변 경로 소스 SHA-256: `{implementation_hash}`",
                  f"- 최종 처분: `{state['final_disposition']}`, 검증: `{state['verification_result'].get('status')}`",
                  "- 범위: 실제 저장 문서 + 기존 승인 법령을 이용한 실제 모델 작성·검증·최종 출력 재현.",
                  "- 제외: 신규 법령 검색, 브라우저 화면, 승인 UI, 상담 저장의 전체 E2E 검증.", "",
                  "## 질문", "", question, "", "## 최종 사용자 답변", "", state["final_answer"], "",
                  "## 검증 실행 기록", "", "```json", json.dumps(records, ensure_ascii=False, indent=2), "```", ""]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(report), encoding="utf-8")
        print(json.dumps({"trace_id": trace_id, "disposition": state["final_disposition"],
                          "report": str(args.output)}, ensure_ascii=False), flush=True)
    finally:
        end_trace(trace_id)
        flush_langfuse()


if __name__ == "__main__":
    main()
