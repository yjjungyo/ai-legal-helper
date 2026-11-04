# -*- coding: utf-8 -*-
"""P6: 기존 8개 Agent 앞에 넣는 공식 법령 시점 검색 계획(외부 호출 없음).

정식 법령명/약칭이 질문에 직접 등장하고 계약 등 사건 기준일이 단일하게
확인된 경우에만 HILT 선행 검색을 계획한다. 카탈로그 미적재/DB 장애/모호한
법령/날짜는 기존 RAG 경로에 안전하게 위임한다.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Optional

from ai_legal_helper.legal_knowledge.temporal_resolver import resolve_event

logger = logging.getLogger(__name__)
_LAW_HINT = re.compile(r"(법|시행령|시행규칙|령|규정)")


def _local_law_resolve(question: str) -> Any:
    """P2 PostgreSQL 로컬 카탈로그 전용. 절대 OpenLaw 원격 호출하지 않음."""
    from ai_legal_helper.database.session import SessionLocal
    from ai_legal_helper.legal_knowledge.catalog_store import LawCatalogStore
    from ai_legal_helper.legal_knowledge.law_resolver import LawResolver
    with SessionLocal() as session:
        return LawResolver(LawCatalogStore(session)).resolve(question)


def build_temporal_search_plan(
    question: str,
    *,
    event_date: Optional[str] = None,
    event_type: Optional[str] = None,
    resolver_fn: Optional[Callable[[str], Any]] = None,
    max_laws: int = 3,
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
    return {
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
