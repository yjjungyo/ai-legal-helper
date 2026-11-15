# -*- coding: utf-8 -*-
"""법률요건 포섭의 증거 연결 감사 (SUBSUMPTION-01 / Gemini 인계).

LLM은 기존 검증 호출에서 법률 요건, 판례 적용 차이, 예외를 *의미적으로*
검토한다. Python은 이 검토가 답변의 실제 법률효과별로 추적 가능하며
진짜 검색된 출처·현재 질문과 연결되는지만 검사한다. 특정 법률/사건
문자열이나 날짜 정규식으로 법률요건 충족 여부를 **판정하지 않는다**.

주의:
- 이 감사는 법리 적용의 충분조건이 아니다. 구조가 PASS여도 기존 LLM
  verifier의 실질 분석과 Temporal/Citation gate를 반드시 통과해야 한다.
- [방법 2: 참고 신호 전환] 포섭 감사의 진단 결과는 warning 및 revision_instructions로
  제공되며, 자연어 표기 차이나 말줄임표 인용 등으로 인한 오탐이 LLM의 유효한
  PASS 판정을 강제 강등(REVISE)시키거나 정상 답변을 WITHHELD로 폐기하지 않는다.
- 순수 LEGAL_RULE 설명이나 CASE_FACT, USER_STATEMENT는 포섭 감사를
  강제하지 않아 기존 일반법령 해설을 오탐으로 차단하지 않는다.
"""

from __future__ import annotations

from typing import Any


def _clean(s: Any) -> str:
    """문서 원문 인용의 공백·마크다운 강조만 정규화, 의미 변화는 허용하지 않음."""
    if not isinstance(s, str):
        return ""
    return " ".join(s.replace("**", "").replace("__", "").replace("`", "").split()).strip()


def audit_legal_applications(
    *,
    claims: list[Any],
    application_checks: list[dict[str, Any]],
    retrieved_sources: list[dict[str, Any]],
    question: str,
    answer: str,
) -> dict[str, Any]:
    """실제 답변의 법률효과 주장별 원문-규범-요건사실-예외-판례 대조 감사.

    반환값에 passable(구조적 증거 연결)이 있어도 법적 정답임을 뜻하지 않는다.
    unsupported_indices는 기존 LEGAL_APPLICATION 주장만 수정하는 지표다.
    """
    registry = {
        str(s.get("source_id")): s for s in retrieved_sources
        if isinstance(s, dict) and s.get("source_id")
    }
    normalized_checks = [
        c for c in (application_checks or [])[:16]
        if isinstance(c, dict) and isinstance(c.get("claim"), str)
    ]
    checks_by_claim: dict[str, list[dict[str, Any]]] = {}
    for check in normalized_checks:
        checks_by_claim.setdefault(_clean(check["claim"]), []).append(check)

    audited = 0
    passed = 0
    failed: list[int] = []
    findings: list[dict[str, Any]] = []
    for i, claim in enumerate(claims):
        claim_type = getattr(claim, "claim_type", None) if not isinstance(claim, dict) else claim.get("claim_type")
        grounding = getattr(claim, "grounding_status", None) if not isinstance(claim, dict) else claim.get("grounding_status")
        if claim_type != "LEGAL_APPLICATION" or grounding != "SUPPORTED":
            continue

        audited += 1
        text = getattr(claim, "claim", "") if not isinstance(claim, dict) else claim.get("claim", "")
        claim_key = _clean(text)
        errors: list[str] = []
        matching = checks_by_claim.get(claim_key) or []
        if len(matching) != 1:
            errors.append("MISSING_OR_AMBIGUOUS_APPLICATION_CHECK")
            check = {}
        else:
            check = matching[0]

        if not claim_key or claim_key not in _clean(answer):
            errors.append("CLAIM_NOT_IN_ANSWER")
        if not _clean(check.get("legal_effect")):
            errors.append("LEGAL_EFFECT_MISSING")

        raw_law = check.get("rule_source_ids")
        ids = raw_law if isinstance(raw_law, list) else []
        law_sources = []
        if not ids:
            errors.append("LEGAL_RULE_SOURCE_MISSING")
        for sid in ids:
            source = registry.get(sid) if isinstance(sid, str) else None
            if not source or source.get("source_type") not in ("STATUTE", "PRECEDENT") or not source.get("content"):
                errors.append("RULE_SOURCE_NOT_RETRIEVED")
            else:
                law_sources.append(source)

        # 해당 주장에 인용된 공식 법리와 포섭 근거가 실제로 이어지는지 확인.
        claim_source_ids = getattr(claim, "source_ids", []) if not isinstance(claim, dict) else claim.get("source_ids", [])
        if law_sources and not set(ids).intersection(set(claim_source_ids or [])):
            errors.append("CLAIM_RULE_SOURCE_DISCONNECTED")

        requirements = check.get("requirements")
        if not isinstance(requirements, list) or not requirements:
            errors.append("REQUIREMENTS_MISSING")
            requirements = []
        if len(requirements) > 12:
            errors.append("REQUIREMENTS_OVER_LIMIT")
        has_unknown = False
        for requirement in requirements[:12]:
            if not isinstance(requirement, dict) or not _clean(requirement.get("requirement")):
                errors.append("REQUIREMENT_UNNAMED")
                continue
            status = requirement.get("status")
            if status not in ("MET", "NOT_MET", "UNKNOWN"):
                errors.append("REQUIREMENT_STATUS_INVALID")
                continue
            if status == "UNKNOWN":
                has_unknown = True
                if not _clean(requirement.get("reason")):
                    errors.append("UNKNOWN_REQUIREMENT_UNEXPLAINED")
                continue
            # MET/NOT_MET 사실 충족·배제는 원문에서 실제 확인해야 한다.
            # 없는 사실을 MET로 쓰거나 단순 '출처 ID가 있음'만으로 충족 금지.
            fact_ids = requirement.get("fact_source_ids")
            fact_ids = fact_ids if isinstance(fact_ids, list) else []
            quote = _clean(requirement.get("fact_quote"))
            evidence_content = [_clean(registry[x].get("content")) for x in fact_ids
                                if isinstance(x, str) and x in registry
                                and registry[x].get("source_type") == "CASE_EVIDENCE"
                                and registry[x].get("content")]
            quote_in_evidence = bool(quote and len(quote) >= 4 and any(quote in content for content in evidence_content))
            # 사용자 질문에 직접 기재한 사실은 별도 문서 없이 상담 전제 가능.
            quote_in_question = bool(quote and len(quote) >= 4 and quote in _clean(question))
            if not (quote_in_evidence or quote_in_question):
                errors.append("FACT_PREMISE_UNGROUNDED")
            if not _clean(requirement.get("reason")):
                errors.append("REQUIREMENT_REASON_MISSING")

        if not _clean(check.get("exception_analysis")):
            errors.append("EXCEPTION_REVIEW_MISSING")
        conclusion = check.get("conclusion_status")
        if conclusion not in ("SUPPORTED", "CONDITIONAL", "UNSUPPORTED"):
            errors.append("CONCLUSION_STATUS_INVALID")
        if conclusion == "UNSUPPORTED":
            errors.append("MODEL_REJECTS_LEGAL_APPLICATION")
        if has_unknown:
            if conclusion != "CONDITIONAL":
                errors.append("UNKNOWN_REQUIREMENT_WITH_CATEGORICAL_CONCLUSION")
            condition = _clean(check.get("condition_in_answer"))
            if not condition or condition not in _clean(answer):
                errors.append("UNSTATED_CONDITION_IN_ANSWER")
        if conclusion == "CONDITIONAL":
            condition = _clean(check.get("condition_in_answer"))
            if not condition or condition not in _clean(answer):
                errors.append("CONDITIONAL_EFFECT_NOT_DISCLOSED")

        # 실제 공식 판례와 해당 사건이 주요 사실상 얼마나 유사한지를
        # 다른 법령 조문만으로 대체하지 않는다(반대 법리/구별 사유 포함).
        precedent_sources = [s for s in law_sources if s.get("source_type") == "PRECEDENT"]
        comparisons = check.get("precedent_analyses")
        comparisons = comparisons if isinstance(comparisons, list) else []
        for precedent in precedent_sources:
            sid = precedent["source_id"]
            matched = [p for p in comparisons if isinstance(p, dict) and p.get("source_id") == sid]
            if len(matched) != 1:
                errors.append("PRECEDENT_COMPARISON_MISSING")
                continue
            comp = matched[0]
            holding = _clean(comp.get("holding_quote"))
            if not holding or holding not in _clean(precedent.get("content", "")):
                errors.append("PRECEDENT_HOLDING_NOT_IN_SOURCE")
            if not _clean(comp.get("material_similarities")) or not _clean(comp.get("material_differences")):
                errors.append("PRECEDENT_FACT_COMPARISON_MISSING")
            applicability = comp.get("applicability")
            if applicability not in ("SIMILAR", "DISTINGUISHABLE", "UNCERTAIN"):
                errors.append("PRECEDENT_APPLICABILITY_UNKNOWN")
            if not _clean(comp.get("reason")):
                errors.append("PRECEDENT_APPLICABILITY_UNEXPLAINED")
            if applicability != "SIMILAR" and conclusion == "SUPPORTED":
                # 인용한 판례가 구별되거나 적용불명이면 그 판례만으로는
                # 해당 법률효과의 확정 결론을 뒷받침할 수 없다.
                other_rules = [s for s in law_sources if s["source_id"] != sid]
                if not other_rules:
                    errors.append("DISTINGUISHED_PRECEDENT_ONLY_SUPPORT")

        if errors:
            failed.append(i)
            findings.append({"claim_index": i, "reason_codes": list(dict.fromkeys(errors))})
        else:
            passed += 1

    return {
        "status": "PASS" if not failed else "REVISE",
        "audited_claims": audited,
        "passed_claims": passed,
        "failed_claims": len(failed),
        "unsupported_indices": failed,
        "findings": findings,
        # 진단에서 개인 사건 문장/본문은 다시 기록하지 않는다.
    }
