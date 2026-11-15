# -*- coding: utf-8 -*-
"""E2E V6 단계별 증거 격리와 답변 출처(provenance) 감사.

개발 원칙 (Gemini/ChatGPT 공통):
- 사건/시나리오 ID가 무엇이든 동일하게 작동한다. SC-012용 정답·증거명을 하드코딩하지 않는다.
- 사용자가 실제로 받은 답변(API 응답)과 Langfuse 내부 finalize 출력은 서로 다른
  계층이다. 다르면 숨기거나 덮어쓰지 않고 해시/길이/상태를 양쪽 모두 기록한다.
- 이전 턴을 다시 검증하려면 기존 DB 사건에서 '미래 문서만 필터링'할 것이 아니라,
  새로운 사건을 생성하고 1차부터 해당 차수까지 순차 적재해야 한다. 후자는
  증거·파생 Fact·대화 메모리 전부의 재현 시점을 보존한다.
- 이 모듈은 Python 표준 라이브러리만 사용한다. DB/LLM과 독립된 단위 테스트가 가능하다.
"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def evidence_snapshot(
    *,
    case_id: str,
    turn_index: int,
    evidence_base: str,
    documents: Iterable[Any],
) -> dict[str, Any]:
    """사건 DB 문서와 '1차~현재 차수' 파일 목록/원본 SHA256의 정확한 일치를 검증.

    Fail-closed invariant:
      1) 현재 차수까지의 각 폴더가 존재해야 한다.
      2) 같은 이름의 증거가 두 번 나타나서는 안 된다.
      3) 해당 사건 DB에는 이 단계의 문서만 정확히 한 번씩 존재해야 한다.
      4) 소스 원본의 SHA256과 DB 증거의 SHA256이 일치해야 한다.
    따라서 미래 증거 E05 등은 이름을 전혀 모르는 경우에도 자동 차단된다.
    이 검사는 실제 LLM 상담 *직전* 수행한다. 답변 자체의 법률 정확도를 검증하는
    함수가 아니며, 결론이 PASS라는 의미로 사용해서는 안 된다.
    """
    if not case_id:
        raise ValueError("case_id is required for evidence isolation")
    if not isinstance(turn_index, int) or turn_index < 1:
        raise ValueError("turn_index must be a positive integer")

    expected: dict[str, str] = {}
    for stage in range(1, turn_index + 1):
        directory = Path(evidence_base) / f"{stage}차"
        if not directory.is_dir():
            raise ValueError(f"missing evidence stage directory: {directory}")
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            if path.name in expected:
                raise ValueError(f"duplicate staged evidence filename: {path.name}")
            expected[path.name] = sha256(path.read_bytes()).hexdigest()

    docs = list(documents)
    names = [str(getattr(doc, "original_filename", "") or "") for doc in docs]
    if Counter(names) != Counter(expected.keys()):
        missing = sorted(set(expected).difference(names))
        extra = sorted(set(names).difference(expected))
        duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
        raise ValueError(
            "EVIDENCE_STAGE_MISMATCH "
            f"case={case_id} turn={turn_index} missing={missing} "
            f"extra={extra} duplicates={duplicates}"
        )

    serialized = []
    for doc in sorted(docs, key=lambda item: str(item.original_filename)):
        name = str(doc.original_filename)
        actual_hash = str(getattr(doc, "sha256", "") or "")
        if actual_hash != expected[name]:
            raise ValueError(
                f"EVIDENCE_HASH_MISMATCH case={case_id} turn={turn_index} filename={name}"
            )
        serialized.append({
            "evidence_id": str(getattr(doc, "id", "")),
            "filename": name,
            "sha256": actual_hash,
            "review_status": str(getattr(doc, "status", "") or ""),
        })

    return {
        "scope_status": "MATCHED",
        "case_id": case_id,
        "turn_index": turn_index,
        "document_count": len(serialized),
        "documents": serialized,
        "expected_filenames": sorted(expected),
        # 재현 결과를 서로 비교할 때 파일이 같은지를 알 수 있는 감사 해시.
        "manifest_sha256": _digest("\n".join(
            f"{d['filename']}:{d['sha256']}" for d in serialized
        )),
    }


def answer_provenance(api_answer: Any, langfuse_trace: Any) -> dict[str, Any]:
    """API 실제 반환문과 Langfuse finalize_node 출력의 *비파괴적* 대조.

    Presentation/후처리에서 텍스트가 달라질 수 있으므로 DIFFERENT를 곧바로
    '오류'나 '환각'으로 판단하지 않는다. 다만 각 레이어 값을 뒤섞으면 감사가
    불가능하므로 문자열의 길이와 SHA256을 독립적으로 기록한다.
    Trace 누락이나 관측치가 불완전한 경우 일치했다고 간주하지 않는다.
    """
    result: dict[str, Any] = {
        "api_layer": "consultation_context.answer",
        "workflow_layer": "finalize_node.output.answer",
        "status": "UNAVAILABLE",
        "api_answer_length": len(api_answer) if isinstance(api_answer, str) else None,
        "api_answer_sha256": _digest(api_answer) if isinstance(api_answer, str) else None,
        "workflow_answer_length": None,
        "workflow_answer_sha256": None,
        "same_text": None,
    }
    if not isinstance(api_answer, str):
        result["reason"] = "NO_API_ANSWER"
        return result

    observations = langfuse_trace.get("observations") if isinstance(langfuse_trace, dict) else None
    if not isinstance(observations, list):
        result["reason"] = "TRACE_OBSERVATIONS_UNAVAILABLE"
        return result
    finals = [obs for obs in observations if isinstance(obs, dict) and obs.get("name") == "finalize_node"]
    if not finals:
        result["reason"] = "FINALIZE_NODE_UNAVAILABLE"
        return result
    final_output = finals[-1].get("output")
    workflow_answer = final_output.get("answer") if isinstance(final_output, dict) else None
    if not isinstance(workflow_answer, str):
        result["reason"] = "FINALIZE_ANSWER_UNAVAILABLE"
        return result

    result["workflow_answer_length"] = len(workflow_answer)
    result["workflow_answer_sha256"] = _digest(workflow_answer)
    result["same_text"] = api_answer == workflow_answer
    result["status"] = "MATCH" if result["same_text"] else "DIFFERENT"
    result["reason"] = "EXACT_TEXT_COMPARISON_ONLY"
    return result
