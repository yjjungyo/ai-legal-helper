# -*- coding: utf-8 -*-
"""Temporal Legal RAG P5 — 사건 기준일·적용례·경과규정의 보수적 판단 엔진.

목적:
    동일 사건에서 계약 체결일, 갱신일, 계약 변경일, 해지 통지일은 법률 효과가
    서로 다를 수 있다. 공포일·법령 전체 시행일·오늘 날짜를 질문의 사건일로
    추정하지 않는다. 공식 MST별 조문과 동일 공포번호 부칙을 함께 확인한다.

안전:
    * 이 로직은 실제 법률 판단 전체를 대체하지 않는다.
    * 단순 공식 메타데이터 및 LLM 주장만으로 VERIFIED 상태를 만들지 않는다.
    * 명백한 단일 적용례 패턴과 조문/버전/사건일/이벤트/부칙 식별이 맞을 때만
      한정된 적용례 검증 상태를 기록한다. 다른 적용례·경과규정이 있으면 보류한다.
    * 입력 원문을 변경하지 않고 구조화된 판정과 추가 확인 사유를 제공한다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from ai_legal_helper.rag.temporal_applicability import (
    ApplicabilityStatus, evaluate_statute_applicability, parse_legal_date,
)

_DATE = re.compile(
    r"(?<!\d)(20\d{2})\s*(?:년|[-./])\s*(\d{1,2})\s*(?:월|[-./])\s*(\d{1,2})\s*일?(?!\d)"
)
_ART = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?")
# 입력 질문의 행사일·계약일 등을 분리하되 공포·개정·시행이라는 법령 날짜를 거르기 위한 식별어
_EVENT_TERMS = {
    "CONTRACT_SIGNED": ("체결", "계약일", "계약을", "신규계약"),
    "CONTRACT_RENEWED": ("갱신", "재계약"),
    "CONTRACT_MODIFIED": ("변경", "변경계약"),
    "NOTICE_GIVEN": ("통지", "해지통보", "해지 통보"),
    "MOVE_OUT": ("퇴거", "인도", "이사"),
}
_LEGAL_DATE_TERMS = ("공포", "시행", "개정", "법령", "시행령", "시행규칙")
_STRICT_EVENT_TERMS = {
    "CONTRACT_SIGNED": ("체결", "계약 체결"),
    "CONTRACT_RENEWED": ("갱신", "재계약"),
    "CONTRACT_MODIFIED": ("변경",),
    "NOTICE_GIVEN": ("해지통보", "통지"),
}


@dataclass(frozen=True)
class LegalEvent:
    date: str
    event_type: str
    origin: str = "QUESTION_EXPLICIT"


@dataclass
class EventResolution:
    status: str
    events: list[LegalEvent] = field(default_factory=list)
    selected: Optional[LegalEvent] = None
    reason_code: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "events": [vars(e).copy() for e in self.events],
            "selected": vars(self.selected).copy() if self.selected else None,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class TemporalSourceDecision:
    status: str
    reason_code: str
    law_id: str
    version_id: str
    article: str
    source_id: str
    event_type: str | None
    event_date: str | None
    matched_addendum_id: str | None = None
    applicability_rule_id: str | None = None
    rule_span: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return vars(self).copy()


@dataclass
class TemporalResolution:
    status: str
    event: EventResolution
    decisions: list[TemporalSourceDecision] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "event": self.event.as_dict(),
            "decisions": [x.as_dict() for x in self.decisions],
            "missing_evidence": list(self.missing_evidence),
        }


def resolve_event(
    question: str,
    *,
    event_date: str | None = None,
    event_type: str | None = None,
) -> EventResolution:
    """사건일 후보 추출. 모호함이 있으면 자동 '오늘' 사용 금지.

    이벤트 키워드가 날짜의 앞·뒤에 쓰인 경우를 모두 검사한다. 하나의 문장에
    공포일과 계약일이 동시에 나오면 법령 공포일을 제외하고 계약일만 선별한다.
    사건의 의미가 확정되지 않은 날짜는 사건 적용 판정 근거로 사용하지 않는다.
    """
    if event_date is not None:
        parsed = parse_legal_date(event_date)
        if parsed is None or (event_type is not None and event_type not in _EVENT_TERMS):
            return EventResolution("UNCONFIRMED", reason_code="EXPLICIT_EVENT_INVALID")
        # 날짜만 전달된 경우 사건 유형을 '계약 체결'로 추정하지 않는다.
        # 호출자가 사건 유형을 구조화해 제공하거나 질문에서 명확하게
        # 확인할 수 있는 경우에만 RESOLVED로 승격한다.
        if event_type is None:
            extracted = resolve_event(question)
            matches = [e for e in extracted.events if e.date == parsed.isoformat()]
            if len(matches) != 1:
                return EventResolution("UNCONFIRMED", events=matches,
                                       reason_code="EXPLICIT_EVENT_TYPE_MISSING")
            event_type = matches[0].event_type
        event = LegalEvent(parsed.isoformat(), event_type, "CALLER_VERIFIED")
        return EventResolution("RESOLVED", events=[event], selected=event)

    candidates: list[LegalEvent] = []
    question = question or ""
    # 줄/절 중심 짧은 구문에서 날짜와 대응 사건을 확인한다.
    dates = list(_DATE.finditer(question))
    for index, match in enumerate(dates):
        try:
            parsed = parse_legal_date(
                f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
            )
        except ValueError:
            parsed = None
        if parsed is None:
            continue
        # 다른 날짜나 다른 문장의 사건 동사가 현재 날짜에 오염 연결되지 않도록
        # 인접 날짜 및 문장 종결 부호(마침표, 물음표, 느낌표, 개행) 경계에서 구문을 자른다.
        preceding_boundary = dates[index - 1].end() if index else 0
        following_boundary = dates[index + 1].start() if index + 1 < len(dates) else len(question)

        last_sent_break = max(
            question.rfind('.', 0, match.start()),
            question.rfind('!', 0, match.start()),
            question.rfind('?', 0, match.start()),
            question.rfind('\n', 0, match.start()),
        )
        start_pos = max(preceding_boundary, last_sent_break + 1, match.start() - 28)
        before = question[start_pos:match.start()]

        next_sent_break = len(question)
        for p in (
            question.find('.', match.end(), following_boundary),
            question.find('!', match.end(), following_boundary),
            question.find('?', match.end(), following_boundary),
            question.find('\n', match.end(), following_boundary),
        ):
            if p != -1 and p < next_sent_break:
                next_sent_break = p
        end_pos = min(following_boundary, next_sent_break, match.end() + 28)
        after = question[match.end():end_pos]

        # 법령 시점 수식어 식별:
        # 날짜 바로 뒤 또는 앞에 개정/공포/시행일/제정/신설/고시/발효 등 법령의 시점 변경 동사/수식어가 결합된 경우,
        # 사건 발생일(계약일 등)이 아닌 법령 시점이므로 사건일 후보에서 제외한다.
        # 주의: 날짜 뒤에 사건 행위(예: '계약 체결')가 먼저 나오고 그 뒤에 법령이 언급된 경우는 사건일이므로 제외하지 않는다.
        _STATUTE_ACTION_MARKER = re.compile(
            r'(?:공포|개정|제정|폐지|신설|고시|발효|바뀐|입법예고|시행일|시행된|시행(?:일|된|한|하는|하기))'
        )
        statute_match = _STATUTE_ACTION_MARKER.search(after[:10])
        event_match_pos = None
        for terms in _EVENT_TERMS.values():
            for token in terms:
                pos = after.find(token)
                if pos != -1 and (event_match_pos is None or pos < event_match_pos):
                    event_match_pos = pos

        following_event = event_match_pos is not None
        # 법령 시점 수식어가 사건 행위 단어보다 먼저 나오면 법령 시점으로 스킵
        if statute_match and (event_match_pos is None or statute_match.start() < event_match_pos):
            continue
        # 날짜 뒤에 사건 행위가 없고, 날짜 직전에 법령 시점 수식어가 붙어있는 경우 스킵
        if not following_event and _STATUTE_ACTION_MARKER.search(before[-6:]):
            continue

        local = after if following_event else before
        hits = [name for name, terms in _EVENT_TERMS.items()
                if any(term in local for term in terms)]
        # 복수 이벤트가 하나의 날짜에 섞인 경우 자동 선정하지 않는다.
        if len(hits) == 1:
            candidates.append(LegalEvent(parsed.isoformat(), hits[0]))
    candidates = list({(e.date, e.event_type): e for e in candidates}.values())
    if event_type:
        candidates = [e for e in candidates if e.event_type == event_type]
    if not candidates:
        return EventResolution("UNCONFIRMED", reason_code="EVENT_DATE_OR_TYPE_MISSING")
    if len(candidates) != 1:
        return EventResolution("AMBIGUOUS", events=candidates, reason_code="MULTIPLE_EVENT_DATES")
    return EventResolution("RESOLVED", events=candidates, selected=candidates[0])


def _norm_article(value: Any) -> str:
    match = _ART.search(str(value or ""))
    return re.sub(r"\s+", "", match.group(0)) if match else ""


def _same_version(source: Mapping[str, Any], addon: Mapping[str, Any]) -> bool:
    """부칙·조문 출처가 공식 동일 법령ID+MST인지 확인한다."""
    if str(source.get("version_relation") or "") and str(addon.get("version_relation") or ""):
        if source.get("version_relation") != addon.get("version_relation"):
            return False
    return (
        bool(source.get("law_id")) and bool(source.get("version_id"))
        and str(source["law_id"]) == str(addon.get("law_id") or "")
        and str(source["version_id"]) == str(addon.get("version_id") or "")
        and str(addon.get("article") or "") == "부칙"
        and bool(str(addon.get("content") or "").strip())
        and bool(str(addon.get("addendum_id") or "").strip())
    )


def _split_provisions(text: str) -> list[str]:
    """부칙 제N조 단위로 분리한다. 본문 중 조문 인용은 괄호 제목이 없으면 경계가 아니다."""
    text = re.sub(r"\s+", " ", text or "").strip()
    parts = re.split(r"(?=제\s*\d+\s*조\s*\([^)]{1,80}\))", text)
    return [p.strip() for p in parts if p.strip()]


def _related_rules(content: str, article: str) -> list[str]:
    """특정 개정 조문을 명시한 적용례/경과조치 문구만 분리."""
    target = _norm_article(article)
    if not target:
        return []
    output = []
    for provision in _split_provisions(content):
        title = provision.split(")", 1)[0]
        # 부칙 제1조 '시행일'은 일반 적용례가 아니다.
        if "시행일" in title:
            continue
        if target not in {_norm_article(m.group(0)) for m in _ART.finditer(provision)}:
            continue
        output.append(provision)
    return output


def _machine_rule(provision: str) -> tuple[str | None, str]:
    """단일한 '시행 이후 [체결/갱신/변경]하는 경우부터 적용' 규칙만 인정.

    다양한 형태의 적용례·기산점·경과조치를 규칙 기반으로 모두 해석하려고
    하지 않는다. 지원하지 않는 패턴은 UNCONFIRMED 상태로 법률 전문가 검토.
    """
    normalized = re.sub(r"\s+", " ", provision)
    if any(x in normalized for x in ("종전의 규정", "경과조치", "불구하고", "소급", "다만", "예외")):
        return None, "COMPLEX_TRANSITIONAL_PROVISION"
    if not re.search(r"(?:시행\s*(?:일)?\s*(?:이후|후)|시행한 날부터)", normalized):
        return None, "UNSUPPORTED_APPLICATION_START"
    if not re.search(r"경우부터\s*적용", normalized):
        return None, "UNSUPPORTED_APPLICATION_RULE"
    types = [e for e, tokens in _STRICT_EVENT_TERMS.items()
             if any(token in normalized for token in tokens)]
    if len(types) != 1:
        # 복수 사건 유형을 포괄하는 적용례는 추가 확인을 요구한다.
        return None, "MULTI_EVENT_APPLICATION_RULE"
    return types[0], "SIMPLE_EVENT_APPLICATION_RULE"


def interpret_addendum_with_llm(
    provision: str,
    article: str,
    *,
    invoke_fn: Optional[Any] = None,
) -> tuple[dict[str, Any] | None, str]:
    """부칙의 적용 조건을 구조화한다. LLM 출력은 검증 전 후보일 뿐이다."""
    import json
    prompt = (
        "부칙의 적용례를 원문에만 근거하여 JSON으로 구조화하세요. "
        "event_types는 CONTRACT_SIGNED, CONTRACT_RENEWED, CONTRACT_MODIFIED, "
        "NOTICE_GIVEN, MOVE_OUT 중 해당하는 모든 유형의 배열입니다. "
        "condition은 ON_OR_AFTER_EFFECTIVE_DATE, AFTER_EFFECTIVE_DATE, "
        "ON_EFFECTIVE_DATE 중 하나 또는 null입니다. "
        "event_evidence와 condition_evidence는 부칙 원문의 연속된 정확한 인용입니다. "
        "예외·소급·경과조치 또는 조건이 불명확하면 has_exception/has_transition을 true로 표시하세요. "
        'JSON: {"event_types":[],"condition":null,"event_evidence":"","condition_evidence":"",'
        '"has_exception":true,"has_transition":true}'
        "\\n대상 조문: " + article + "\\n부칙: " + provision
    )
    try:
        if invoke_fn is None:
            from ai_legal_helper.llm.gateway import get_llm
            from langchain_core.messages import SystemMessage, HumanMessage
            response = get_llm(temperature=0.0).invoke([
                SystemMessage(content="법률 부칙 구조화 추출기입니다. 원문에 없는 법적 효과를 추측하지 마세요."),
                HumanMessage(content=prompt),
            ])
            raw = response.content
        else:
            raw = invoke_fn(prompt)
        data = json.loads(raw) if isinstance(raw, str) else None
        if not isinstance(data, dict):
            return None, "LLM_ADDENDUM_INVALID_OUTPUT"
        types = data.get("event_types")
        condition = data.get("condition")
        event_span = data.get("event_evidence")
        condition_span = data.get("condition_evidence")
        supported = set(_EVENT_TERMS)
        if (not isinstance(types, list) or not types or len(types) != len(set(map(str, types)))
                or any(not isinstance(t, str) or t not in supported for t in types)):
            return None, "LLM_ADDENDUM_UNSUPPORTED_EVENT"
        if condition not in ("ON_OR_AFTER_EFFECTIVE_DATE", "AFTER_EFFECTIVE_DATE", "ON_EFFECTIVE_DATE"):
            return None, "LLM_ADDENDUM_UNSUPPORTED_CONDITION"
        if any(not isinstance(x, str) or not x.strip() or x not in provision
               for x in (event_span, condition_span)):
            return None, "LLM_ADDENDUM_UNGROUNDED"
        if data.get("has_exception") is not False or data.get("has_transition") is not False:
            return None, "LLM_ADDENDUM_COMPLEX_RULE"
        # 구조화 결과가 원문에서 지지되는지 별도 검사한다. LLM의 선언만 신뢰하지 않는다.
        if any(x in provision for x in ("종전의 규정", "경과조치", "불구하고", "소급", "다만", "예외")):
            return None, "COMPLEX_TRANSITIONAL_PROVISION"
        if not re.search(r"경우부터\\s*적용", provision):
            return None, "UNSUPPORTED_APPLICATION_RULE"
        if condition == "AFTER_EFFECTIVE_DATE":
            if not re.search(r"시행\\s*(?:일)?\\s*(?:이후|후)", condition_span):
                return None, "LLM_ADDENDUM_CONDITION_MISMATCH"
        elif condition == "ON_OR_AFTER_EFFECTIVE_DATE":
            if not re.search(r"시행(?:한 날부터|일?\\s*이후)", condition_span):
                return None, "LLM_ADDENDUM_CONDITION_MISMATCH"
        else:
            return None, "LLM_ADDENDUM_CONDITION_REVIEW_REQUIRED"
        for kind in types:
            if not any(token in event_span for token in _STRICT_EVENT_TERMS.get(kind, ())):
                return None, "LLM_ADDENDUM_EVENT_MISMATCH"
        return {
            "event_types": types,
            "condition": condition,
            "event_evidence": event_span,
            "condition_evidence": condition_span,
        }, "LLM_ADDENDUM_STRUCTURED"
    except Exception:
        return None, "LLM_ADDENDUM_EXTRACTION_FAILED"


def evaluate_temporal_sources(
    question: str,
    sources: Iterable[Mapping[str, Any]],
    *,
    event_date: str | None = None,
    event_type: str | None = None,
    llm_addendum_interpretation: bool = False,
    addendum_invoke_fn: Optional[Any] = None,
) -> TemporalResolution:
    """공식 버전별 조문·부칙과 사건일을 매칭하고 3상 판정한다.

    * P4의 버전 후보가 실제 시점 법령으로 적합한지는 부칙 적용례 및 개정
      문구에 따라 달라질 수 있다. 이 함수는 해당 조문별 *한정된* 규칙만 확인.
    * 날짜가 없으면 무조건 UNCONFIRMED.
    * 공식 신뢰 출처라도 조문 본문 자체가 없으면 판정을 만들지 않는다.
    """
    event = resolve_event(question, event_date=event_date, event_type=event_type)
    documents = [dict(s) for s in sources or [] if isinstance(s, Mapping)]
    articles = [s for s in documents if s.get("source_type") == "STATUTE"
                and s.get("article") not in (None, "", "부칙")]
    addenda = [s for s in documents if s.get("source_type") == "STATUTE"
               and s.get("article") == "부칙"]
    decisions: list[TemporalSourceDecision] = []
    gaps: list[str] = []
    for src in articles:
        reason = ""
        effective = parse_legal_date(src.get("article_effective_date"))
        s_id = str(src.get("source_id") or "")
        law_id = str(src.get("law_id") or "")
        version = str(src.get("version_id") or "")
        article = str(src.get("article") or "")
        related = [a for a in addenda if _same_version(src, a)]
        matching_rules = [
            (a, rule)
            for a in related
            for rule in _related_rules(str(a.get("content") or ""), article)
        ]
        selected_addendum: Mapping[str, Any] | None = None
        rule_id = None
        span = None
        current_type = event.selected.event_type if event.selected else None
        current_date = event.selected.date if event.selected else None
        enriched = dict(src)
        enriched["temporal_status"] = "UNCONFIRMED"
        # 최종 적용례 검토 전에 소급효가 개입할 수 있으므로 날짜만으로
        # NOT_APPLICABLE을 허용하는 P1 분기도 함부로 사용하지 않는다.
        enriched["retroactivity_review_required"] = True

        if event.selected is None:
            reason = event.reason_code
        elif not law_id or not version or not s_id or not src.get("content"):
            reason = "SOURCE_IDENTITY_OR_TEXT_MISSING"
        elif src.get("version_lookup_status") != "HISTORY_COMPLETE":
            reason = "HISTORICAL_VERSION_NOT_VERIFIED"
        elif not effective or src.get("effective_date_basis") not in (
            "ARTICLE_EFFECTIVE_DATE", "ADDENDUM_EFFECTIVE_DATE",
        ):
            reason = "ARTICLE_EFFECTIVE_DATE_UNCONFIRMED"
        elif not related:
            reason = "MATCHING_ADDENDUM_MISSING"
        elif len(matching_rules) != 1:
            reason = "APPLICATION_PROVISION_NOT_UNIQUE"
        else:
            selected_addendum, span = matching_rules[0]
            rule_type, reason = _machine_rule(span)
            # 미지원 문장만 LLM으로 해석하되, LLM의 의미 추출만으로
            # 법적 적용 여부를 VERIFIED로 승격시키지 않는다.
            structured_rule = None
            if (rule_type is None and llm_addendum_interpretation
                    and reason not in ("COMPLEX_TRANSITIONAL_PROVISION",)):
                structured_rule, extraction_reason = interpret_addendum_with_llm(
                    span, article, invoke_fn=addendum_invoke_fn,
                )
                reason = extraction_reason
                # LLM 해석은 검증 가능한 후보만 제공한다.
                # 복수 사건 유형은 기존 단일 유형 기반 엔진에서 확정하지 않는다.
                if structured_rule and current_type in structured_rule["event_types"]:
                    # 복수 사건 유형도 해당 사건 유형이 근거에 명시되어 있으면 처리한다.
                    # 단, 시행일 당일 포함이 확인된 조건만 기존 날짜 판정기에 전달한다.
                    if structured_rule["condition"] == "ON_OR_AFTER_EFFECTIVE_DATE":
                        rule_type = current_type
                        reason = "LLM_ADDENDUM_CONDITION_GROUNDED"
            parsed_cur_date = parse_legal_date(current_date)
            is_before_effective = bool(parsed_cur_date and effective and parsed_cur_date < effective)

            # 복수 사건 유형(예: 체결하거나 갱신하는 경우)을 포괄하는 적용례라도
            # 사건일이 시행일 이전(current_date < effective)이고 '시행 이후' 체결/갱신/변경 적용 규정이면
            # 해당 모든 사건 유형에 대해 시행일 전 불적용(NOT_APPLICABLE)임이 명백하다.
            if reason == "MULTI_EVENT_APPLICATION_RULE" and is_before_effective:
                types = [e for e, tokens in _STRICT_EVENT_TERMS.items()
                         if any(token in span for token in tokens)]
                if current_type in types:
                    rule_type = current_type
                    reason = "MATCHED_EVENT_APPLICATION_RULE"

            # 명시된 적용례 외에 동일 부칙에 과도규정/경과조치가 있으면
            # 이 조문에 불리한 조건이 있는지 자동 판정할 수 없으므로 보류한다.
            # 단, 사건일이 시행일 이전(current_date < effective)이고 부칙에 소급적용 규정이 없으며
            # 적용례가 '시행 이후'로 한정된 경우, 통상적인 경과조치(과태료·벌칙 등)는
            # 미시행 법령의 사전 효력을 발생시키지 않으므로 시행일 전 불적용 판정을 차단하지 않는다.
            full_addendum = " ".join(str(a.get("content") or "") for a in related)
            has_retro = "소급" in full_addendum
            has_transitional = any(x in full_addendum for x in ("경과조치", "종전의 규정"))

            if has_retro:
                reason = "TRANSITIONAL_REVIEW_REQUIRED"
            elif has_transitional and not is_before_effective:
                reason = "TRANSITIONAL_REVIEW_REQUIRED"
            elif rule_type and current_type != rule_type:
                reason = "EVENT_TYPE_MISMATCH"
            elif rule_type:
                rule_id = hashlib.sha256(
                    (law_id + "|" + version + "|" + article + "|" + span).encode("utf-8")
                ).hexdigest()[:20]
                enriched.update(
                    temporal_status="VERIFIED",
                    applicability_event_type=rule_type,
                    applicability_rule_id=rule_id,
                    retroactivity_review_required=False,
                )

        if enriched.get("temporal_status") == "VERIFIED":
            d = evaluate_statute_applicability(
                enriched, current_date, event_type=current_type,
            )
            status = d.status.value
            reason = d.reason_code
        else:
            status = ApplicabilityStatus.UNCONFIRMED.value
            gaps.append(f"{law_id or 'LAW_UNKNOWN'}:{article}:{reason}")

        decisions.append(TemporalSourceDecision(
            status=status,
            reason_code=reason,
            law_id=law_id, version_id=version,
            article=article, source_id=s_id,
            event_type=current_type, event_date=current_date,
            matched_addendum_id=str(selected_addendum.get("addendum_id")) if selected_addendum else None,
            applicability_rule_id=rule_id, rule_span=span,
        ))
    if not decisions:
        gaps.append("OFFICIAL_ARTICLE_SOURCE_MISSING")
    if any(d.status == "UNCONFIRMED" for d in decisions) or not decisions:
        overall = "UNCONFIRMED"
    elif len({d.status for d in decisions}) == 1:
        overall = decisions[0].status
    else:
        # 구버전 적용/미래 신버전 불적용이 섞인 것은 정상일 수 있으나
        # 전체 상담 결론은 출처 별 판단을 보고 결정해야 한다.
        overall = "MIXED_VERSION_RESULTS"
    return TemporalResolution(overall, event, decisions, gaps)
