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
        if parsed is None or event_type not in _EVENT_TERMS:
            return EventResolution("UNCONFIRMED", reason_code="EXPLICIT_EVENT_INVALID")
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
        # 다른 날짜의 사건 동사가 현재 날짜에 연결되지 않도록 인접 날짜 경계에서
        # 구문을 자른다. 날짜 뒤의 명시 동사를 우선 사용하고, 없을 때만 앞을 본다.
        preceding_boundary = dates[index - 1].end() if index else 0
        following_boundary = dates[index + 1].start() if index + 1 < len(dates) else len(question)
        before = question[max(preceding_boundary, match.start()-28):match.start()]
        after = question[match.end():min(following_boundary, match.end()+28)]
        immediate = before[-6:] + after[:10]
        if any(term in immediate for term in ("공포", "시행일", "개정일")):
            continue
        local = after if any(token in after for terms in _EVENT_TERMS.values() for token in terms) else before
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


def evaluate_temporal_sources(
    question: str,
    sources: Iterable[Mapping[str, Any]],
    *,
    event_date: str | None = None,
    event_type: str | None = None,
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
            # 명시된 적용례 외에 동일 부칙에 과도규정/경과조치가 있으면
            # 이 조문에 불리한 조건이 있는지 자동 판정할 수 없으므로 보류.
            full_addendum = " ".join(str(a.get("content") or "") for a in related)
            if any(x in full_addendum for x in ("경과조치", "종전의 규정", "소급 적용")):
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
