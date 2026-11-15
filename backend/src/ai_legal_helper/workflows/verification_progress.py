# -*- coding: utf-8 -*-
"""상담 검증/검색/재작성 진행 상태 측정 — 5단계 / Gemini 협업.

법률요건 충족, 판례 적용, 시행일의 옳고 그름을 판단하는 모듈이 아니다.
비싼 검증 LLM을 다시 호출할 필요가 있는 *객관적인 입력/결과 변화*만
SHA256으로 비교한다. 모든 해시는 민감한 원문을 Checkpointer에 복사하지
않도록 단방향으로 기록한다.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _digest(payload: Any) -> str:
    """값을 직렬화하여 안전한 고정 길이 해시로 저장. 원문은 로그에 남기지 않음."""
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       default=str, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def added_legal_source_ids(
    before: list[dict[str, Any]] | None,
    after: list[dict[str, Any]] | None,
) -> list[str]:
    """실제로 Source Registry에 새로 결합된 법령·판례 source_id만 반환.

    검색 API가 기존 출처를 재반환한 경우 실질적으로 새 원문이 아니므로
    재작성/재검증의 이유가 되지 않는다. 같은 ID에 다른 본문을 덮어쓰는
    행위는 신규 출처로 위장하지 않고 기존 Registry 충돌 검사에 맡긴다.
    """
    existing = {
        str(item.get("source_id")) for item in (before or [])
        if isinstance(item, dict) and item.get("source_id")
    }
    result: list[str] = []
    for item in after or []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("source_id") or "")
        if (not sid or sid in existing or sid in result
                or item.get("source_type") not in ("STATUTE", "PRECEDENT")
                or not str(item.get("content") or "").strip()):
            continue
        result.append(sid)
    return result


def verification_input_hash(
    *,
    question: str,
    draft_answer: str,
    manifest: dict[str, Any],
    as_of_date: str,
    require_question_coverage: bool,
) -> str:
    """질문, 답변, 원문 등록 버전, 검토기준일, 검증 강도가 모두 같을 때만 동일."""
    return _digest({
        "question": question,
        "draft_sha256": hashlib.sha256(draft_answer.encode("utf-8")).hexdigest(),
        "sources_sha256": manifest.get("content_sha256"),
        # 추가 원문 개수 변화나 registry 버전 변화가 digest 해시와
        # 우연히 같더라도 원문 출처 목록 변경을 놓치지 않도록 포함.
        "sources_count": manifest.get("source_count"),
        "as_of_date": as_of_date,
        "require_question_coverage": bool(require_question_coverage),
    })


def verification_defect_signature(
    result: dict[str, Any],
    *,
    question: str,
    sources_sha256: str,
) -> str:
    """검증 실패를 구성하는 *구조화된* 결함 종류를 비교하는 서명.

    모델이 안내 문장을 조금 다르게 썼을 뿐 동일한 법리·인용 결함이라면
    추가 재작성이 법률 근거를 늘리지 못한다. 그러나 오류 개수·출처·
    요건별 포섭·질문 충족 내역이 달라졌다면 진행으로 간주한다.

    주장/법률 판단을 regex로 채점하지 않고 LLM의 검증 결과를 입력으로
    사용하므로 시나리오/법령별 하드코딩이 없다.
    """
    claims = [
        (
            str(c.get("claim_type") or ""),
            str(c.get("grounding_status") or ""),
            tuple(sorted(str(x) for x in (c.get("source_ids") or []))),
        )
        for c in (result.get("claims") or [])
        if isinstance(c, dict)
        and c.get("claim_type") in ("LEGAL_RULE", "LEGAL_APPLICATION", "CASE_FACT", "CASE_INFERENCE")
    ]
    # claims는 모델의 제시 순서가 바뀌어도 동일한 결함으로 판단한다.
    application = result.get("application_audit") or {}
    app_failures = [
        (int(entry.get("claim_index") or 0),
         tuple(sorted(str(x) for x in (entry.get("reason_codes") or []))))
        for entry in (application.get("findings") or [])
        if isinstance(entry, dict)
    ]
    coverage = [
        (bool(c.get("answered") is True),
         bool(c.get("answerable") is False),
         bool(c.get("limitation_disclosed") is True))
        for c in (result.get("question_coverage") or []) if isinstance(c, dict)
    ]
    checks = result.get("consistency_checks") or {}
    issues = {
        # string content stored only inside digest, never in state/log output
        "missing_legal_issues": sorted(str(i) for i in result.get("missing_legal_issues") or []),
        "missing_issues": sorted(str(i) for i in result.get("missing_issues") or []),
        "contradictions": sorted(str(i) for i in result.get("contradictions") or []),
    }
    citations = result.get("citation_audit") or {}
    return _digest({
        "question_hash": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "source_manifest_sha256": sources_sha256,
        "status": result.get("status"),
        "reason_code": result.get("reason_code"),
        "claims": sorted(claims),
        "application_failures": sorted(app_failures),
        "coverage": sorted(coverage),
        "consistency": sorted(
            (key, check.get("passed"))
            for key, check in checks.items()
            if isinstance(check, dict)
        ),
        "unverified_citations": sorted(citations.get("unverified_citations") or []),
        "unsupported_citations": sorted(citations.get("unsupported_citations") or []),
        "issues": issues,
        "temporal_gate": (result.get("temporal_gate") or {}).get("status"),
    })


def can_reuse_verification(
    *,
    previous: dict[str, Any],
    expected_input_hash: str,
    current_draft: str,
    current_manifest: dict[str, Any],
) -> bool:
    """일절 추가 LLM 없이 이전 검증을 재사용해도 되는 엄격한 조건.

    동일 초안만으로는 불충분하다. 같은 승인 원문, 동일 사용자 질문,
    동일 검토일/검증범위를 포함한 input hash가 먼저 일치해야 한다.
    임시 오류와 Temporal 의미 재심사 등은 캐시하지 않는다.
    """
    if not isinstance(previous, dict) or previous.get("status") not in ("REVISE", "INSUFFICIENT"):
        return False
    if previous.get("reason_code") in ("VERIFICATION_ERROR", "OFFICIAL_STATUTE_API_ERROR",
                                       "TEMPORAL_SEMANTIC_CONTRADICTION"):
        return False
    if previous.get("temporal_recheck_only") or previous.get("temporal_repair_only"):
        return False
    if (previous.get("temporal_gate") or {}).get("status") == "BLOCK":
        return False
    if previous.get("verification_input_hash") != expected_input_hash:
        return False
    if (previous.get("source_manifest") or {}).get("content_sha256") != current_manifest.get("content_sha256"):
        return False
    return (
        bool(current_draft.strip())
        and previous.get("verified_answer_sha256") ==
            hashlib.sha256(current_draft.encode("utf-8")).hexdigest()
    )
