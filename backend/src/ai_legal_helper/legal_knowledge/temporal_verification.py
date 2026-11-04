# -*- coding: utf-8 -*-
"""P8 — 법령 시행일·부칙 적용례에 대한 비LLM Verification 최종 안전 게이트.

목적:
    일반 LLM이 근거와 상관없이 '2026 계약에 2027 시행 개정규정 적용'
    같은 긍정 단정을 생성하더라도 최종 고객 답변 확정 전에 차단한다.

범위:
    사건일과 법령 개정·시행·적용 문제가 함께 등장한 질문에만 적용.
    문장 수준의 전반적 법률 해석, 모든 부칙의 요건 판정은 수행하지 않는다.
    명시적 적용례를 검증하지 못한 경우 근거 없는 확정 결론을 전달하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ai_legal_helper.rag.temporal_applicability import parse_legal_date
from ai_legal_helper.legal_knowledge.temporal_resolver import (
    evaluate_temporal_sources, resolve_event,
)

_TEMPORAL_TERMS = ("개정", "시행", "적용", "신법", "최신 법", "언제부터")
_POSITIVE = re.compile(
    r"(?:적용\s*(?:됩니까|되나요|됩니다|된다|함|해야|한다|하므로|하여)|"
    r"포함해야\s*(?:합니다|한다)|신고해야\s*(?:합니다|한다)|"
    r"의무가\s*(?:있습니다|있다))"
)
# 신법·개정 규정의 미적용, 시행 전, 신고 비대상 등을 나타내는 자연스러운 법률 표현을 포괄
_NEGATIVE = re.compile(
    r"(?:적용(?:되지|하지)\s*않|적용\s*불가|미적용|적용할\s*수\s*없|적용\s*대상이\s*(?:아니|아님)|"
    r"시행(?:되지|하지)\s*않|시행\s*전|"
    r"아직\s*(?:아닙니다|아니|시행\s*전)|시행\s*전이|보기\s*어렵|"
    r"신고사항(?:이\s*아닙니다|이라고\s*보기\s*어렵|이\s*아닌)|신고\s*대상이\s*(?:아닙니다|아니|아님)|"
    r"의무가?\s*(?:없|아니|아님)|의무는\s*(?:없|아니)|"
    r"포함(?:되지|하지)\s*않|포함할\s*필요가?\s*없|신고할\s*필요가?\s*없|"
    r"해당하지\s*않|부과(?:되지|하지)\s*않)"
)
# 미확인 조항 또는 실무적 안내에 따른 확인·점검 표현을 포괄
_CAUTION = re.compile(
    r"(?:확인\s*(?:이\s*)?필요|검토\s*필요|판단\s*유보|미확인|"
    r"단정할\s*수\s*없|적용\s*여부가\s*불명|결론을\s*낼\s*수\s*없|"
    r"주의|유의|유의사항|주의사항|"
    r"확인(?:하십시오|하시기|바랍|사항|해\s*두|점검|권장)|"
    r"점검해야|점검\s*필요|문의(?:하십시오|하시기|바랍))"
)
# 장래 시행일, 공포 경과일 등 미래 시점 적용 조건을 나타내는 표현을 포괄
_FUTURE_CONDITION = re.compile(
    r"(?:향후|시행\s*(?:일)?\s*(?:이후|후|부터)|공포\s*(?:일\s*)?(?:이후|후|부터)|경과한\s*날|앞으로|장래)"
)


@dataclass(frozen=True)
class TemporalGateResult:
    status: str
    reason_codes: tuple[str, ...] = ()
    affected_source_ids: tuple[str, ...] = ()
    event_date: str | None = None
    decisions: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "affected_source_ids": list(self.affected_source_ids),
            "event_date": self.event_date,
            "decisions": list(self.decisions),
        }


def _temporal_question(question: str) -> bool:
    return bool(question and any(term in question for term in _TEMPORAL_TERMS))


def evaluate_temporal_answer_gate(
    question: str,
    draft: str,
    sources: Iterable[Mapping[str, Any]] | None,
    *,
    event_date: str | None = None,
    event_type: str | None = None,
    temporal_resolution: Mapping[str, Any] | None = None,
    verification_result: Mapping[str, Any] | None = None,
) -> TemporalGateResult:
    """공포일을 시행일로 오인한 긍정/부정 단정을 재현 가능한 규칙으로 검사한다."""
    if not _temporal_question(question):
        return TemporalGateResult("NOT_REQUIRED")
    provided = temporal_resolution if isinstance(temporal_resolution, Mapping) else None
    recorded_event = provided.get("event") if provided else None
    selected = recorded_event.get("selected") if isinstance(recorded_event, Mapping) else None
    verified_selected = selected if isinstance(selected, Mapping) else None
    recorded_date = verified_selected.get("date") if verified_selected else None
    recorded_type = verified_selected.get("event_type") if verified_selected else None
    # 공식 검색 단계의 동일 판정을 재사용한다. 원문을 키워드로 재해석하면
    # LLM 추출 사건일과 Verification 사건일이 달라질 수 있다.
    if provided and isinstance(provided.get("decisions"), list):
        decisions = [d for d in provided["decisions"] if isinstance(d, dict)]
        event_date = recorded_date if parse_legal_date(recorded_date) else None
        event_type = recorded_type if isinstance(recorded_type, str) else None
        if not event_date:
            # 판정 스냅샷에 사건일이 없으면 호출자 날짜로 임의 보충하지 않는다.
            event_date = None
    else:
        events = resolve_event(question, event_date=event_date, event_type=event_type)
        event_date = events.selected.date if events.selected else None
        event_type = events.selected.event_type if events.selected else None
        decisions = evaluate_temporal_sources(
            question, sources, event_date=event_date, event_type=event_type,
        ).as_dict()["decisions"]
    # 질의 또는 답변 초안에서 다루어지는 조문 및 인용 출처와 관련된 판정을 선별한다.
    # 키워드 검색으로 대량 수집된 비관련 조문(본문·질의에 미언급)의 미확인 상태가
    # 적법하게 검증된 답변의 게이트 차단을 유발하지 않도록 격리한다.
    relevant_decisions = [
        d for d in decisions
        if not d.get("article")
        or (d.get("article") in (draft or "") or d.get("article") in (question or ""))
    ]
    eval_decisions = relevant_decisions if relevant_decisions else decisions

    claims_positive = bool(_POSITIVE.search(draft or ""))
    claims_negative = bool(_NEGATIVE.search(draft or ""))
    cautious = bool(_CAUTION.search(draft or ""))
    future_only = bool(_FUTURE_CONDITION.search(draft or ""))
    statuses = {str(d.get("status") or "") for d in eval_decisions}
    future_not_applicable = [
        d for d in eval_decisions if d.get("status") == "NOT_APPLICABLE"
    ]
    uncertain = [
        d for d in eval_decisions if d.get("status") == "UNCONFIRMED"
    ]
    reasons: list[str] = []
    affected: list[str] = []

    if not event_date:
        if claims_positive or claims_negative:
            reasons.append("LEGAL_EVENT_DATE_UNCONFIRMED")
    elif not eval_decisions:
        if claims_positive or claims_negative:
            reasons.append("TEMPORAL_OFFICIAL_EVIDENCE_MISSING")
    elif future_not_applicable and claims_positive:
        # 시행예정 개정 규정 관련 질문에서 현재의 긍정 적용을 주장하면 차단.
        # 다만 '현재는 불적용, 시행 이후 체결 시 적용'이라는 명시적 대비는
        # 긍정/부정 문구가 함께 있어도 확정 오판으로 간주하지 않는다.
        if not (claims_negative and future_only):
            reasons.append("FUTURE_AMENDMENT_MISAPPLIED")
            affected.extend(str(d.get("source_id") or "") for d in future_not_applicable)
    elif uncertain and (claims_positive or (claims_negative and not future_not_applicable)):
        # 조건부로 설명하는 경우에도 완전 검증 PASS를 주장할 수 없으나
        # 위험한 단정이 없으면 차단 대신 CAUTIONARY 표시.
        # 단, 시행예정 개정법의 불적용(future_not_applicable)이 확인되어 '신법 미적용'을
        # 답변하는 경우에는 불적용 근거가 확정되었으므로 차단하지 않는다.
        if not cautious:
            reasons.append("APPLICABILITY_PROVISION_UNCONFIRMED")
            affected.extend(str(d.get("source_id") or "") for d in uncertain)
    elif eval_decisions and statuses == {"APPLICABLE"} and claims_negative and not cautious:
        reasons.append("VERIFIED_APPLICABILITY_CONTRADICTED")
        affected.extend(str(d.get("source_id") or "") for d in eval_decisions)

    if reasons:
        return TemporalGateResult(
            "BLOCK", tuple(dict.fromkeys(reasons)),
            tuple(dict.fromkeys(x for x in affected if x)),
            event_date, tuple(eval_decisions),
        )
    if not eval_decisions or (uncertain and not future_not_applicable) or not event_date:
        return TemporalGateResult(
            "CAUTION", ("TEMPORAL_REVIEW_INCOMPLETE",),
            tuple(str(d.get("source_id") or "") for d in uncertain if d.get("source_id")),
            event_date, tuple(eval_decisions),
        )
    return TemporalGateResult("PASS", event_date=event_date, decisions=tuple(eval_decisions))


def apply_temporal_gate_to_verification(
    result: Mapping[str, Any],
    gate: TemporalGateResult,
) -> dict[str, Any]:
    """LLM 및 쟁점별 Verification PASS보다 시점 안전 게이트를 우선한다."""
    output = dict(result or {})
    output["temporal_gate"] = gate.as_dict()
    if gate.status == "BLOCK":
        output["status"] = "INSUFFICIENT"
        output["reason_code"] = "TEMPORAL_APPLICABILITY_UNCONFIRMED"
        warnings = list(output.get("warnings") or [])
        msg = "계약·사건 기준일에 적용되는 법령 개정 조항과 부칙을 충분히 확인하지 못했습니다."
        if msg not in warnings:
            warnings.append(msg)
        output["warnings"] = warnings
    elif gate.status == "CAUTION" and output.get("status") == "PASS":
        # 미확인 적용례를 '검증 PASS'로 단정하지 않는다.
        output["status"] = "REVISE"
        output["reason_code"] = "TEMPORAL_REVIEW_REQUIRED"
        output.setdefault("warnings", []).append(
            "적용 시점이 확인되지 않은 규정은 조건부 설명으로 확인해야 합니다."
        )
    return output
