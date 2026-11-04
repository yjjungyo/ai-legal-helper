"""초안 작성 전 법령 검색 완전성 점검. 특정 법령명이나 사건 유형을 고정하지 않는다."""
import json
import logging

logger = logging.getLogger(__name__)


def check_legal_coverage(state: dict) -> dict:
    """LLM은 누락 법령 후보만 제안한다. API 검색은 별도 승인 노드에서 수행한다."""
    if state.get("answer_mode") != "DOCUMENT_GROUNDED" or state.get("pre_coverage_checked"):
        return {}
    question = str(state.get("resolved_query") or state.get("question") or "")
    sources = state.get("retrieved_sources") or []
    statutes = [s for s in sources if isinstance(s, dict) and (
        s.get("source_type") == "STATUTE" or s.get("statute_name")
    )]
    inventory = [{
        "law": s.get("statute_name") or s.get("law_name") or s.get("title"),
        "article": s.get("article"),
        "text_excerpt": str(s.get("content") or s.get("article_text") or "")[:400],
    } for s in statutes[:16]]
    # 사건 브리핑은 이미 DB에서 판정한 사실만 재사용하며 증거 원문은 전송하지 않는다.
    briefing = state.get("case_evidence_briefing") or {}
    facts = briefing.get("facts") or []
    timeline = briefing.get("timeline") or []
    issues = state.get("issue_tasks") or []
    def compact(items, limit, size):
        return [json.dumps(x, ensure_ascii=False, default=str)[:size] for x in items[:limit] if isinstance(x, dict)]
    case_input = {
        "case_type": briefing.get("case_type"),
        "reference_date": briefing.get("as_of_date"),
        "facts": compact(facts, 12, 360),
        "timeline": compact(timeline, 8, 220),
        "legal_issues": compact(issues, 8, 300),
        "evidence_gaps": compact(briefing.get("evidence_gaps") or [], 5, 200),
    }
    from ai_legal_helper.llm.gateway import get_llm
    prompt = (
        "당신은 법률 상담의 초안 작성 전 법령 검색 충분성 점검자입니다. "
        "답변을 작성하지 말고 질문의 핵심 법률 쟁점에 필요한 법령 원문이 "
        "현재 검색 결과에 빠져 있는지만 판단하세요. 특정 분야에 한정하지 마세요. "
        "추측성 법령이나 부수 쟁점은 추가하지 마세요. "
        "순수 JSON만 반환하세요: "
        '{"missing_laws":[{"law_name":"정확한 법령명","issue":"누락 법률 쟁점","question_part":"질문 중 해당 부분","articles":[]}]} '
        "누락이 없다면 missing_laws는 빈 배열입니다. "
        f"\\n질문: {question}\\n사건 사실·쟁점(미확정은 확정하지 말 것): {json.dumps(case_input, ensure_ascii=False)}"
        f"\\n현재 법령 출처: {json.dumps(inventory, ensure_ascii=False)}"
    )
    try:
        response = get_llm(temperature=0.0).invoke(prompt)
        raw = str(getattr(response, "content", response)).strip()
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        items = data.get("missing_laws", [])
        if not isinstance(items, list):
            raise ValueError("missing_laws must be list")
        requests = []
        for item in items[:4]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("law_name") or "").strip()
            issue = str(item.get("issue") or "").strip()
            part = str(item.get("question_part") or "").strip()
            articles = item.get("articles") or []
            if name and issue and part and isinstance(articles, list) and all(isinstance(a, str) for a in articles):
                requests.append({"law_name": name, "issue": issue, "question_part": str(state.get("question") or question),
                                 "articles": [str(a) for a in articles if isinstance(a, str)]})
        if items and not requests:
            raise ValueError("Invalid statute search requests")
        if not requests:
            return {"pre_coverage_checked": True}
        return {"pre_coverage_checked": True, "statute_search_phase": "PRE_ANALYSIS",
                "verification_result": {
                    "status": "INSUFFICIENT", "reason_code": "LEGAL_SOURCE_MISSING",
                    "candidate_laws": list(dict.fromkeys(r["law_name"] for r in requests)),
                    "missing_legal_issues": [r["issue"] for r in requests],
                    "legal_search_requests": requests,
                    "explanation": "답변 작성 전 핵심 법률 근거를 추가 확인해야 합니다.",
                }}
    except Exception as exc:
        logger.warning("[PRE_COVERAGE] 사전 법령 점검 실패: %s", type(exc).__name__)
        return {"pre_coverage_checked": True, "warnings": list(state.get("warnings") or []) +
                ["사전 법령 충분성 검사를 완료하지 못해 사후 검증에서 확인합니다."]}


def coverage_next(state: dict) -> str:
    result = state.get("verification_result") or {}
    if (state.get("statute_search_phase") == "PRE_ANALYSIS"
            and result.get("reason_code") == "LEGAL_SOURCE_MISSING"
            and result.get("candidate_laws") and not state.get("hilt_executed")):
        return "statute_search_approval"
    return "legal_evidence_bundle"
