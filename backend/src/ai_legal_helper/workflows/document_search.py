"""문서 상담의 질문별 법령 검색 계획과 승인 범위·중복 검색을 관리한다.

검증 요청 → 현재 확보 조문 제외 → 승인 범위 대조 → 실제 검색 → 이력 저장 순서다.
법령 검색을 한 번 했다는 이유로 새로운 누락 조문까지 확보된 것으로 취급하지 않는다.
"""

import hashlib
import json
from typing import Any

from ai_legal_helper.tools.official_statute_search import _prepare_search_targets, _article_references


def law_names(references: list[str]) -> list[str]:
    """승인과 조회에 동일한 정식 법령명을 사용한다.

    Args:
        references: 조문·설명이 포함될 수 있는 후보 표현.

    Returns:
        정규화된 법령명 목록.
    """
    return [target.law_name for target in _prepare_search_targets(references)]


def pending_searches(state: dict[str, Any]) -> list[dict[str, Any]]:
    """질문에 연결된 새 검색만 선택하며 이미 확보·시도한 조문을 제외한다.

    Args:
        state: 질문, 검증 요청, 검색 출처와 검색 이력.

    Returns:
        법령명, 조문, 쟁점, 중복 방지 키가 있는 최대 여섯 요청.
    """
    review = state.get("verification_result") or {}
    requests = review.get("legal_search_requests") or []
    if not requests and (state.get("statute_search_count") or 0) == 0 and review.get("reason_code") in (
        "LEGAL_SOURCE_MISSING", "LEGAL_SOURCE_INSUFFICIENT"
    ):
        # 구버전 검증 결과는 최초 승인 요청에만 호환한다. 재검색은 구조화 요청을 요구한다.
        all_issues = [
            str(iss).strip()
            for iss in (review.get("missing_legal_issues") or review.get("missing_issues") or [])
            if str(iss).strip()
        ]
        question_str = state.get("question", "") or "법령 확인"
        requests = []
        for name in review.get("candidate_laws") or []:
            norm_names = law_names([name])
            target_law = norm_names[0] if norm_names else str(name).strip()
            law_specific_issues = [iss for iss in all_issues if target_law and target_law in iss]
            selected_issues = law_specific_issues or all_issues
            issue_str = " ".join(selected_issues).strip() or question_str
            explicit_articles = _article_references(f"{name} {' '.join(law_specific_issues)}")
            requests.append({
                "law_name": name,
                "articles": explicit_articles,
                "issue": issue_str,
                "question_part": question_str,
            })
    known = {(s.get("statute_name"), s.get("article")) for s in state.get("retrieved_sources") or []
             if s.get("source_type") == "STATUTE" and s.get("content")}
    history = set(state.get("statute_search_history") or [])
    norm_question = " ".join(str(state.get("question") or "").split())
    pending = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        part, issue = request.get("question_part"), request.get("issue")
        names = law_names([request.get("law_name", "")])
        articles_raw = request.get("articles", [])
        norm_part = " ".join(str(part or "").split()) if isinstance(part, str) else ""
        if (not names or not norm_part
                or norm_part not in norm_question
                or not isinstance(issue, str) or not issue.strip()
                or not isinstance(articles_raw, list) or not all(isinstance(a, str) for a in articles_raw)):
            continue
        articles = _article_references(" ".join(articles_raw))[:10]
        # 한 요청에 확보된 조문과 미확보 조문이 섞여도 새 조문만 다시 조회한다.
        for article in articles or [""]:
            key = hashlib.sha256(json.dumps([names[0], article], ensure_ascii=False).encode()).hexdigest()
            if key in history or (article and (names[0], article) in known):
                continue
            history.add(key)
            pending.append({"law_name": names[0], "articles": [article] if article else [],
                            "issue": issue.strip(), "question_part": part.strip(), "key": key})
    return pending[:6]


def search_is_approved(state: dict[str, Any], requests: list[dict[str, Any]]) -> bool:
    """이번 검색의 모든 법령이 사용자가 승인한 범위 안에 있는지 확인한다.

    Args:
        state: 승인 상태와 승인 법령 목록.
        requests: 실제 실행할 새 요청.

    Returns:
        승인된 법령에 대한 요청만 있으면 True.
    """
    approved = set(state.get("approved_statute_laws") or [])
    return (state.get("approval_status") == "APPROVED" and bool(requests)
            and all(r["law_name"] in approved for r in requests))


def execute_document_search(state: dict[str, Any]) -> dict[str, Any]:
    """승인된 새 조문만 검색하고 결과·조회 이력을 상태 갱신값으로 반환한다.

    Args:
        state: 현재 출처, 검증 요청과 사용자의 승인 범위.

    Returns:
        새 출처, 누적 출처, 시도 이력과 검색 횟수. 승인 밖 호출은 실행하지 않는다.
    """
    from ai_legal_helper.tools.official_statute_search import search_official_statutes

    requests = pending_searches(state)
    if not search_is_approved(state, requests) or (state.get("statute_search_count") or 0) >= 2:
        return {"statute_search_results": []}
    grouped: dict[str, list[dict]] = {}
    for request in requests:
        grouped.setdefault(request["law_name"], []).append(request)
    found = []
    for name, items in grouped.items():
        articles = list(dict.fromkeys(a for r in items for a in r["articles"]))
        references = [f"{name} {a}" for a in articles] or [name]
        # 쟁점별 검색으로 다른 법·인물·일반 질문 어휘가 관련성 점수를 오염시키지 않게 한다.
        found.extend(search_official_statutes(
            query=" ".join(r["issue"] for r in items), candidate_laws=references,
            missing_issues=[r["issue"] for r in items], max_articles_per_law=max(len(articles), 4),
        ))
    merged = list(state.get("retrieved_sources") or [])
    seen = {s.get("source_id") for s in merged}
    for source in found:
        if source.get("source_id") not in seen:
            merged.append(source)
            seen.add(source.get("source_id"))
    return {"statute_search_results": found, "retrieved_sources": merged,
            "statute_search_count": (state.get("statute_search_count") or 0) + 1,
            "statute_search_history": list(dict.fromkeys(
                (state.get("statute_search_history") or []) + [r["key"] for r in requests]))}
