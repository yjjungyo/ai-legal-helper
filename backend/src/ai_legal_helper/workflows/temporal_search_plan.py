# -*- coding: utf-8 -*-
"""P6: 기존 8개 Agent 앞에 넣는 공식 법령 시점 검색 계획(외부 호출 없음).

정식 법령명/약칭이 질문에 직접 등장하고 계약 등 사건 기준일이 단일하게
확인된 경우에만 HILT 선행 검색을 계획한다. 카탈로그 미적재/DB 장애/모호한
법령/날짜는 기존 RAG 경로에 안전하게 위임한다.
"""
from __future__ import annotations

import logging
import re
import json
from typing import Any, Callable, Optional

from ai_legal_helper.legal_knowledge.temporal_resolver import resolve_event, EventResolution, LegalEvent
from ai_legal_helper.rag.temporal_applicability import parse_legal_date

logger = logging.getLogger(__name__)
_LAW_HINT = re.compile(r"(법|시행령|시행규칙|령|규정)")


def extract_event_with_llm(question: str, invoke_fn: Optional[Callable[[str], str]] = None) -> EventResolution:
    """질문의 사건일 의미를 LLM으로 추출하되 원문·날짜·타입을 코드로 검증한다.

    불확실하거나 기존 판정 엔진이 지원하지 않는 유형은 UNCONFIRMED.
    법령의 공포/시행일은 사건일로 선택하지 않는다.
    """
    prompt = (
        "다음 법률 질문에서 사건 당사자의 실제 행위 날짜 하나만 식별하세요. "
        "법령 공포일, 개정일, 시행일은 사건일이 아닙니다. "
        "날짜가 여러 개이고 기준 행위가 모호하면 선택하지 마세요. "
        "JSON만 출력: "
        '{"date":"YYYY-MM-DD 또는 null","event_type":"CONTRACT_SIGNED|CONTRACT_RENEWED|'
        'CONTRACT_MODIFIED|NOTICE_GIVEN|MOVE_OUT 또는 null","evidence":"질문 원문의 정확한 인용"}'
        "\n질문: " + question
    )
    try:
        if invoke_fn is None:
            from ai_legal_helper.llm.gateway import get_llm
            from langchain_core.messages import HumanMessage, SystemMessage
            response = get_llm(temperature=0.0).invoke([
                SystemMessage(content="법률 사건의 날짜·행위 추출기입니다. 추측하지 말고 JSON만 반환하세요."),
                HumanMessage(content=prompt),
            ])
            raw = response.content
        else:
            raw = invoke_fn(prompt)
        if not isinstance(raw, str):
            raise ValueError("NON_TEXT_RESPONSE")
        parsed = json.loads(raw.strip())
        if not isinstance(parsed, dict):
            raise ValueError("NOT_OBJECT")
        date_text, kind, evidence = parsed.get("date"), parsed.get("event_type"), parsed.get("evidence")
        if not isinstance(date_text, str) or not isinstance(kind, str) or not isinstance(evidence, str):
            raise ValueError("MISSING_FIELDS")
        if not evidence.strip() or evidence not in question:
            raise ValueError("UNGROUNDED_EVENT_SPAN")
        parsed_date = parse_legal_date(date_text)
        if parsed_date is None:
            raise ValueError("INVALID_DATE")
        supported = {"CONTRACT_SIGNED", "CONTRACT_RENEWED", "CONTRACT_MODIFIED", "NOTICE_GIVEN", "MOVE_OUT"}
        if kind not in supported:
            raise ValueError("UNSUPPORTED_EVENT_TYPE")
        # 날짜 의미는 LLM이 해석한다. Python은 근거의 존재와 명백한 모순만 검사한다.
        # 근거의 날짜 표기를 재파싱하여 특정 연도 형식으로 제한하지 않는다.
        # raw 정규식의 숫자·공백 클래스는 단일 역슬래시로 지정한다.
        # 다만 근거에 명시된 4자리 연도와 결과 연도가 다르면 확정할 수 없다.
        explicit_years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?=\s*(?:년|[-./]))", evidence))
        if explicit_years and str(parsed_date.year) not in explicit_years:
            raise ValueError("YEAR_CONFLICT_IN_EVIDENCE")
        # 공포·시행일만을 근거로 사건일을 만들지 않는다.
        if re.search(r"(?:공포일|시행일|개정일|공포된|시행되는|개정된)", evidence) and not re.search(
            r"(?:계약|체결|갱신|재계약|통지|퇴거|이사|변경)", evidence
        ):
            raise ValueError("STATUTE_DATE_NOT_EVENT")
        # 복수 날짜를 포함한 인용 전체는 날짜별 근거를 특정할 수 없으므로 보류.
        # LLM이 해당 행위에 연결된 짧은 원문 구간을 인용하도록 한다.
        date_mentions = re.findall(
            r"(?<!\d)\d{2,4}\s*(?:년|[-./])\s*\d{1,2}\s*(?:월|[-./])\s*\d{1,2}\s*일?",
            evidence,
        )
        if len(date_mentions) != 1:
            raise ValueError("AMBIGUOUS_EVENT_EVIDENCE")
        # 2자리 연도의 세기 해석은 LLM이 담당하며, 날짜가 모호하면 보류한다.
        # 근거에 있는 월/일 숫자만 확인하여 명백한 환각을 차단한다.
        numeric_parts = re.findall(r"\d+", date_mentions[0])
        if len(numeric_parts) != 3 or (int(numeric_parts[1]), int(numeric_parts[2])) != (
            parsed_date.month, parsed_date.day
        ):
            raise ValueError("DATE_COMPONENT_CONFLICT")
        event = LegalEvent(parsed_date.isoformat(), kind, "LLM_EXTRACTED")
        return EventResolution("RESOLVED", events=[event], selected=event)
    except Exception as exc:
        logger.warning("[TEMPORAL_EVENT_LLM] 추출 미확정 | reason=%s", type(exc).__name__)
        return EventResolution("UNCONFIRMED", reason_code="LLM_EVENT_EXTRACTION_UNCONFIRMED")


def _local_law_resolve(question: str) -> Any:
    """P2 PostgreSQL 로컬 카탈로그 전용. 절대 OpenLaw 원격 호출하지 않음."""
    from ai_legal_helper.database.session import SessionLocal
    from ai_legal_helper.legal_knowledge.catalog_store import LawCatalogStore
    from ai_legal_helper.legal_knowledge.law_resolver import LawResolver
    with SessionLocal() as session:
        return LawResolver(LawCatalogStore(session)).resolve(question)


def _index_preflight(law_ids: list[str], event_date: str, event_type: str,
                     question: str, index_fn: Optional[Callable[..., Any]] = None) -> dict[str, Any]:
    """DB-only diagnostics for HILT planning; does not waive official-search approval.

    A local hit remains a *candidate* until downstream event-specific verification.
    """
    from ai_legal_helper.legal_knowledge.retrieval_service import _normalized_article, _ARTICLE_PATTERN
    from ai_legal_helper.legal_knowledge.retrieval_service import _resolve_index_locally
    articles = list(dict.fromkeys(
        _normalized_article(x) for x in _ARTICLE_PATTERN.findall(question)
        if _normalized_article(x)
    ))
    decisions = []
    for law_id in law_ids:
        try:
            decision = (index_fn or _resolve_index_locally)(
                law_id=law_id, event_date=event_date, event_type=event_type,
                article_ids=articles,
            )
            decisions.append(decision.as_dict())
        except Exception as exc:
            logger.warning("[TEMPORAL_PLAN] index preflight failed type=%s",
                           type(exc).__name__)
            decisions.append({
                "law_id": law_id, "status": "INDEX_UNAVAILABLE",
                "official_lookup_required": True,
                "reason_codes": ["LAW_INDEX_UNAVAILABLE"],
            })
    return {
        "index_decisions": decisions,
        "index_status": ("ALL_LOCAL_CANDIDATES" if decisions and all(
            d.get("status") == "INDEX_READY_CANDIDATE" for d in decisions
        ) else "OFFICIAL_REVIEW_REQUIRED"),
        "index_article_ids": articles,
    }


def build_temporal_search_plan(
    question: str,
    *,
    event_date: Optional[str] = None,
    event_type: Optional[str] = None,
    resolver_fn: Optional[Callable[[str], Any]] = None,
    max_laws: int = 3,
    llm_event_extraction: bool = False,
    event_invoke_fn: Optional[Callable[[str], str]] = None,
    index_fn: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """사건일/공식 법령ID가 명시된 질의를 '검색 후보'로만 정규화한다.

    Returns:
        READY: HILT 승인 대상으로 제시할 법령명·사건일 확정
        SKIP: 기존 Agent 흐름으로 진행, 새 외부 호출 없음
    """
    empty: dict[str, Any] = {
        "status": "SKIP", "phase": "PRE_ANALYSIS", "candidate_laws": [],
        "law_ids": [], "as_of_date": None, "event_type": None,
        "reason_code": "NOT_TEMPORAL_LAW_QUESTION",
    }
    if not isinstance(question, str) or not _LAW_HINT.search(question):
        return empty
    # 법령 적용 시점 질문은 규칙의 오확정을 피하기 위해 LLM 의미 추출을 우선한다.
    # 명시적으로 확인된 사건일/유형 쌍은 재추출하지 않는다.
    # 날짜 표기는 LLM이 해석하므로 정규식으로 사전 차단하지 않는다.
    explicit_pair = event_date is not None and event_type is not None
    if llm_event_extraction and not explicit_pair:
        event = extract_event_with_llm(question, invoke_fn=event_invoke_fn)
        if event.selected is not None and event_date is not None:
            explicit_date = parse_legal_date(event_date)
            if explicit_date is None or event.selected.date != explicit_date.isoformat():
                event = EventResolution("UNCONFIRMED", reason_code="EXPLICIT_DATE_MISMATCH")
        if event.selected is not None and event_type is not None and event.selected.event_type != event_type:
            event = EventResolution("UNCONFIRMED", reason_code="EXPLICIT_EVENT_TYPE_MISMATCH")
    else:
        event = resolve_event(question, event_date=event_date, event_type=event_type)
    if event.selected is None:
        return {**empty, "reason_code": event.reason_code}
    try:
        resolution = (resolver_fn or _local_law_resolve)(question)
    except Exception as exc:
        logger.warning("[TEMPORAL_PLAN] 로컬 법령 카탈로그 조회 실패 | type=%s",
                       type(exc).__name__)
        return {**empty, "reason_code": "CATALOG_UNAVAILABLE"}
    if str(getattr(resolution, "status", "")) not in ("FOUND", "MULTIPLE"):
        return {**empty, "reason_code": "OFFICIAL_LAW_ID_UNCONFIRMED"}
    laws = list(getattr(resolution, "laws", []) or [])
    if not laws or len(laws) > max_laws:
        return {**empty, "reason_code": "AMBIGUOUS_OR_TOO_MANY_LAWS"}
    if any(not getattr(law, "law_id", "") or not getattr(law, "law_name", "") for law in laws):
        return {**empty, "reason_code": "OFFICIAL_LAW_ID_UNCONFIRMED"}
    index_info = _index_preflight(
        [law.law_id for law in laws], event.selected.date,
        event.selected.event_type, question, index_fn=index_fn,
    )
    return {
        **index_info,
        "status": "READY",
        "phase": "PRE_ANALYSIS",
        "candidate_laws": [law.law_name for law in laws],
        "law_ids": [law.law_id for law in laws],
        "as_of_date": event.selected.date,
        "event_type": event.selected.event_type,
        "reason_code": "DATE_AND_OFFICIAL_LAW_IDENTIFIED",
    }


def authorized_plan(
    state: dict[str, Any],
    *,
    phase: str = "PRE_ANALYSIS",
) -> dict[str, Any] | None:
    """사용자가 승인한 법령 목록이 계획의 법령명과 정확히 일치하는지 확인."""
    plan = state.get("law_search_plan") or {}
    approved = set(state.get("approved_statute_laws") or [])
    if (plan.get("status") != "READY" or plan.get("phase") != phase
            or state.get("approval_status") != "APPROVED"):
        return None
    planned = list(plan.get("candidate_laws") or [])
    if not planned or not approved or not set(planned).issubset(approved):
        return None
    return plan
