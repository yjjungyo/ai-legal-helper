"""문서 상담의 질문별 법령 검색 계획과 승인 범위·중복 검색을 관리한다.

검증 요청 → 현재 확보 조문 제외 → 승인 범위 대조 → 실제 검색 → 이력 저장 순서다.
법령 검색을 한 번 했다는 이유로 새로운 누락 조문까지 확보된 것으로 취급하지 않는다.
"""

import hashlib
import json
import os
from typing import Any

from ai_legal_helper.tools.official_statute_search import _prepare_search_targets, _article_references
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.rag.temporal_applicability import ApplicabilityStatus, evaluate_statute_applicability

logger = get_logger(__name__)


def law_names(references: list[str]) -> list[str]:
    """승인과 조회에 동일한 정식 법령명을 사용한다.

    Args:
        references: 조문·설명이 포함될 수 있는 후보 표현.

    Returns:
        정규화된 법령명 목록.
    """
    return [target.law_name for target in _prepare_search_targets(references)]


def _is_safe_question_match(part: str, question: str, resolved_query: str = "") -> bool:
    """question_part가 질문 원문 또는 해석 질문(resolved_query)의 부분 문자열이거나 질문과 직접 관련된 핵심 쟁점인지 안전하게 검증한다.

    Args:
        part: 검증기나 계획기가 반환한 질문 부분(question_part).
        question: 사용자 질문 원문.
        resolved_query: 문맥 보강된 해석 질문 (선택적).

    Returns:
        bool: 안전하게 부합할 경우 True, 무관한 외부 검색일 경우 False.
    """
    if not part:
        return False
    norm_p = " ".join(part.split())
    candidates = [q for q in (question, resolved_query) if q and q.strip()]
    if not candidates:
        return False

    # 원문 질문 또는 해석 질문과의 직접 포함 관계 검증
    for cand in candidates:
        norm_c = " ".join(cand.split())
        if norm_p in norm_c or norm_c in norm_p:
            return True

    from ai_legal_helper.tools.official_statute_search import extract_substantive_tokens
    part_tokens = extract_substantive_tokens(norm_p)
    if not part_tokens:
        return False

    for cand in candidates:
        norm_c = " ".join(cand.split())
        cand_tokens = set(extract_substantive_tokens(norm_c))
        if not cand_tokens:
            continue
        matched = [t for t in part_tokens if t in cand_tokens or any(t in ct or ct in t for ct in cand_tokens)]
        # part 토큰과 질문 토큰 중 짧은 쪽의 1/3 이상 일치하거나 3단어 이상 일치 시 정당한 질문 관련 요청으로 판정
        min_threshold = max(1, min(len(part_tokens), len(cand_tokens)) // 3)
        if len(matched) >= min_threshold or len(matched) >= 3:
            return True

    return False

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
    # 기존 검색 결과가 있더라도 사건일 적용성이 검증되지 않았다면 확보 조문으로 간주하지 않는다.
    reference_date = (
        (state.get("case_evidence_briefing") or {}).get("as_of_date")
        or (state.get("temporal_resolution") or {}).get("as_of_date")
    )
    known = {
        (src.get("statute_name"), src.get("article"))
        for src in state.get("retrieved_sources") or []
        if isinstance(src, dict) and src.get("source_type") == "STATUTE"
        and src.get("content")
        and evaluate_statute_applicability(src, reference_date).status
        is ApplicabilityStatus.APPLICABLE
    }
    history = set(state.get("statute_search_history") or [])
    norm_question = " ".join(str(state.get("question") or "").split())
    norm_resolved = " ".join(str(state.get("resolved_query") or "").split())
    pending = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        part, issue = request.get("question_part"), request.get("issue")
        # 판례 단독 구조화 검색 요청은 법령 이름이 없어도 유효하다.
        # pending_searches는 기존 법령 요청만 유지하고 별도 검색기에 전달한다.
        if str(request.get("source_type") or "STATUTE").upper() == "PRECEDENT":
            continue
        names = law_names([request.get("law_name", "")])
        articles_raw = request.get("articles", [])
        norm_part = " ".join(str(part or "").split()) if isinstance(part, str) else ""
        if (not names or not norm_part
                or not _is_safe_question_match(norm_part, norm_question, norm_resolved)
                or not isinstance(issue, str) or not issue.strip()
                or not isinstance(articles_raw, list) or not all(isinstance(a, str) for a in articles_raw)):
            continue
        articles = _article_references(" ".join(articles_raw))[:10]
        # 한 요청에 확보된 조문과 미확보 조문이 섞여도 새 조문만 다시 조회한다.
        # 조문 번호가 없는 쟁점 기반 요청의 경우 서로 다른 쟁점이 동일 법령이라는 이유로 탈락하지 않도록 쟁점명을 키에 반영한다.
        for article in articles or [""]:
            if article:
                key = hashlib.sha256(json.dumps([names[0], article], ensure_ascii=False).encode()).hexdigest()
            else:
                norm_iss = " ".join(issue.split())
                key = hashlib.sha256(json.dumps([names[0], "", norm_iss], ensure_ascii=False).encode()).hexdigest()
            if key in history or (article and (names[0], article) in known):
                continue
            history.add(key)
            pending.append({"law_name": names[0], "articles": [article] if article else [],
                            "issue": issue.strip(), "question_part": part.strip(), "key": key})
    return pending[:6]


def pending_precedent_searches(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Verifier가 *구조적으로* 요청한 판례만 검색한다 (SC 독립·동적 출처 유형).

    [PRECEDENT-04 / Gemini 인계] 문장 중 '판례' 키워드가 있는지 검사해
    법률 결론이나 검색 종류를 코드로 판정하지 않는다. 검증기가 LLM 1회
    출력에서 source_type=PRECEDENT/BOTH와 일반 법리 precedent_query를 준다.
    사용자 원질문에 연결되지 않거나 개인정보 없는 검색어가 불명확하면
    외부로 발송하지 않고, 법률 근거 부족 상태를 보존한다.
    """
    from ai_legal_helper.tools.official_precedent_search import normalize_precedent_query

    review = state.get("verification_result") or {}
    history = set(state.get("precedent_search_history") or [])
    question = str(state.get("question") or "")
    resolved = str(state.get("resolved_query") or "")
    pending: list[dict[str, Any]] = []
    for item in review.get("legal_search_requests") or []:
        if not isinstance(item, dict):
            continue
        stype = str(item.get("source_type") or "STATUTE").strip().upper()
        if stype not in ("PRECEDENT", "BOTH"):
            continue
        part = str(item.get("question_part") or "").strip()
        issue = str(item.get("issue") or "").strip()
        query = normalize_precedent_query(item.get("precedent_query") or "")
        # [PRECEDENT-04B] PII 중앙 마스커는 자유형식 한글 인명을 전부 식별할
        # 수 없다. 현재 사건 당사자 이름이 판례 검색어에 섞였다면 요청을
        # 거부한다. 구조화된 법률 개념 검색어를 다시 얻기 전에는 API 전송 금지.
        parties = (state.get("case_evidence_briefing") or {}).get("parties") or []
        party_names = [
            str(p.get("name") or "").strip()
            for p in parties if isinstance(p, dict) and len(str(p.get("name") or "").strip()) >= 2
        ]
        if any(name in query for name in party_names):
            logger.warning("[PRECEDENT] 개인 식별명이 검색어에 포함되어 공식 API 조회 차단")
            continue
        if not (part and issue and query and _is_safe_question_match(part, question, resolved)):
            continue
        key = hashlib.sha256(json.dumps(
            ["PRECEDENT", query], ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        if key in history:
            continue
        history.add(key)
        pending.append({
            "source_type": "PRECEDENT",
            "issue": issue,
            "question_part": part,
            "precedent_query": query,
            "key": key,
        })
    return pending[:3]


def precedent_search_is_approved(state: dict[str, Any], requests: list[dict[str, Any]]) -> bool:
    """HITL이 판례 검색까지 허용했을 때만 공식 API를 실행한다."""
    if not requests or state.get("approval_status") in ("DENIED", "REJECTED"):
        return False
    if state.get("auto_approve_statute_search") is not False and (
        state.get("auto_approve_statute_search")
        or os.getenv("AUTO_APPROVE_STATUTE_SEARCH", "").lower() in ("true", "1", "yes")
    ):
        return True
    approved_queries = set(state.get("approved_precedent_queries") or [])
    return (
        state.get("approval_status") == "APPROVED"
        and state.get("approved_precedent_search") is True
        and all(r["precedent_query"] in approved_queries for r in requests)
    )



def search_is_approved(state: dict[str, Any], requests: list[dict[str, Any]]) -> bool:
    """이번 검색의 모든 법령이 사용자가 승인한 범위 안에 있는지 확인한다.

    시나리오 평가 모드(AUTO_APPROVE_STATUTE_SEARCH) 활성화 시 자동 승인으로 판정한다.

    Args:
        state: 승인 상태와 승인 법령 목록.
        requests: 실제 실행할 새 요청.

    Returns:
        승인된 법령에 대한 요청만 있으면 True.
    """
    if state.get("approval_status") == "DENIED":
        return False
    if state.get("auto_approve_statute_search") is False:
        auto_approve = False
    else:
        auto_approve = bool(state.get("auto_approve_statute_search")) or os.getenv("AUTO_APPROVE_STATUTE_SEARCH", "").lower() in ("true", "1", "yes")
    if auto_approve:
        return bool(requests)
    approved = set(state.get("approved_statute_laws") or [])
    return (state.get("approval_status") == "APPROVED" and bool(requests)
            and all(r["law_name"] in approved for r in requests))


def _verified_local_fallback(state: dict[str, Any], requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """이미 확보된 공식 원문 중 요청 법령·조문·시점이 검증된 것만 재사용한다.

    일반 벡터 유사도 결과나 시행일 미확인 문서는 fallback으로 승격하지 않는다.
    """
    reference_date = (state.get("case_evidence_briefing") or {}).get("as_of_date")
    if not reference_date:
        return []
    matched = []
    for request in requests:
        candidates = []
        for src in state.get("retrieved_sources") or []:
            if not isinstance(src, dict) or src.get("source_type") != "STATUTE":
                continue
            if src.get("statute_name") != request["law_name"] or not src.get("content"):
                continue
            # 공식 원문이라는 사실이나 시행일 메타만으로 적용 확정하지 않는다.
            if evaluate_statute_applicability(src, reference_date).status is not ApplicabilityStatus.APPLICABLE:
                continue
            if not (src.get("version_id") and src.get("content_hash")):
                continue
            if src.get("version_lookup_status") in ("DATE_NOT_SPECIFIED", "UNCONFIRMED", "FAILED"):
                continue
            if src.get("version_date") and str(src["version_date"]) > str(reference_date):
                continue
            articles = request.get("articles") or []
            if articles and src.get("article") not in articles:
                continue
            candidates.append(src)
        if not candidates:
            return []
        matched.extend(candidates)
    return list({src["source_id"]: src for src in matched if src.get("source_id")}.values())


def _retrieve_from_domain_collections(
    client: Any,
    col_names: list[str],
    norm_name: str,
    law_name: str,
    target_articles: set[str],
    query: str,
    limit: int,
    require_all: bool,
) -> list[dict[str, Any]]:
    """law_docs_global에 미적재된 법령을 도메인별 ChromaDB 컬렉션(행정·형법·상법·노동 등)에서 보조 조회한다."""
    import urllib.parse
    from ai_legal_helper.rag.source_schema import build_source_from_chroma_doc
    from langchain_core.documents import Document

    domain_cols = [
        c for c in (
            "law_docs_administrative", "law_docs_criminal", "law_docs_commercial",
            "law_docs_civil", "law_docs_labor", "law_docs_tax",
            "law_docs_constitution", "law_docs_international",
        )
        if c in col_names
    ]
    # 법령명 표기(공백 포함 정식명칭 vs 공백 제거 정규화명칭) 및 메타데이터 필드(law_name vs statute_name)
    # 불일치로 인한 로컬 인덱스 검색 누락(Local-First Miss)을 원천 차단하기 위해 후보군을 구성하여 조회한다.
    target_law = norm_name or law_name
    candidate_laws = list(dict.fromkeys([
        law_name,
        norm_name,
        " ".join(law_name.split()) if law_name else "",
        "".join(law_name.split()) if law_name else "",
    ]))
    candidate_laws = [c for c in candidate_laws if c]

    for cname in domain_cols:
        try:
            col = client.get_collection(cname)
            if target_articles:
                ids, docs, metas = [], [], []
                for cand in candidate_laws:
                    for field in ("law_name", "statute_name"):
                        res = col.get(where={field: cand}, include=["documents", "metadatas"])
                        if res.get("ids"):
                            ids = res["ids"]
                            docs = res.get("documents") or []
                            metas = res.get("metadatas") or []
                            break
                    if ids:
                        break
                if not ids:
                    continue
                matched = []
                seen_art = set()
                for doc_id, text, meta in zip(ids, docs, metas):
                    meta_dict = dict(meta or {})
                    art = meta_dict.get("article")
                    if art in target_articles and art not in seen_art:
                        seen_art.add(art)
                        full_text = meta_dict.get("parent_content") or text
                        meta_dict.setdefault("statute_name", target_law)
                        d = Document(id=doc_id, page_content=full_text, metadata=meta_dict)
                        s_dict = build_source_from_chroma_doc(
                            d, category=cname.replace("law_docs_", ""), retrieval_method="OFFICIAL_STATUTE_SEARCH",
                        )
                        if not s_dict.get("source_url") and target_law and art:
                            s_dict["source_url"] = f"https://www.law.go.kr/법령/{urllib.parse.quote(target_law)}/{art}"
                        matched.append(s_dict)
                found_articles = {s.get("article") for s in matched}
                if require_all and not target_articles.issubset(found_articles):
                    continue
                if matched:
                    return _append_companion_addenda(matched, client, target_law)
            else:
                from ai_legal_helper.llm.gateway import get_embeddings
                emb = get_embeddings()
                search_query_text = f"{target_law} {query}".strip() if query else target_law
                q_vec = emb.embed_query(search_query_text)
                ids, docs, metas = [], [], []
                for cand in candidate_laws:
                    for field in ("statute_name", "law_name"):
                        res = col.query(
                            query_embeddings=[q_vec],
                            n_results=limit * 2,
                            where={field: cand},
                            include=["documents", "metadatas"],
                        )
                        if res.get("ids") and res["ids"][0]:
                            ids = res["ids"][0]
                            docs = (res.get("documents") or [[]])[0]
                            metas = (res.get("metadatas") or [[]])[0]
                            break
                    if ids:
                        break
                if not ids:
                    continue
                matched = []
                seen_art = set()
                for doc_id, text, meta in zip(ids, docs, metas):
                    meta_dict = dict(meta or {})
                    art = meta_dict.get("article") or doc_id
                    if art in seen_art:
                        continue
                    seen_art.add(art)
                    full_text = meta_dict.get("parent_content") or text
                    meta_dict.setdefault("statute_name", target_law)
                    d = Document(id=doc_id, page_content=full_text, metadata=meta_dict)
                    s_dict = build_source_from_chroma_doc(
                        d, category=cname.replace("law_docs_", ""), retrieval_method="OFFICIAL_STATUTE_SEARCH",
                    )
                    if not s_dict.get("source_url") and target_law and meta_dict.get("article"):
                        s_dict["source_url"] = f"https://www.law.go.kr/법령/{urllib.parse.quote(target_law)}/{meta_dict['article']}"
                    matched.append(s_dict)
                    if len(matched) >= limit:
                        break
                if matched:
                    return _append_companion_addenda(matched, client, target_law)
        except Exception as _ex:
            logger.debug("[DOMAIN_COLLECTION] 도메인 컬렉션(%s) 조회 예외: %s", cname, _ex)
            continue
    return []


def _append_companion_addenda(
    matched: list[dict[str, Any]], client: Any, law_name: str
) -> list[dict[str, Any]]:
    """로컬 검색된 법령 조문들에 대해 동일 법령의 부칙(Addenda)을 동반 조회하여 추가한다."""
    if not matched:
        return matched
    has_addendum = any(
        s.get("article") == "부칙" or "부칙" in str(s.get("title") or "") or s.get("part") == "부칙"
        for s in matched
    )
    if has_addendum:
        return matched
    from langchain_core.documents import Document
    from ai_legal_helper.rag.source_schema import build_source_from_chroma_doc
    from ai_legal_helper.legal_knowledge.law_catalog import normalize_law_name

    norm_name = normalize_law_name(law_name)
    candidate_names = list(dict.fromkeys([
        law_name,
        norm_name,
        *(s.get("statute_name") for s in matched if s.get("statute_name")),
        *(s.get("law_name") for s in matched if s.get("law_name")),
        " ".join(law_name.split()) if law_name else "",
        "".join(law_name.split()) if law_name else "",
    ]))
    candidate_names = [c for c in candidate_names if c and isinstance(c, str)]

    try:
        col_names = [getattr(c, "name", str(c)) for c in client.list_collections()]
        target_cols = [
            "law_docs_administrative", "law_docs_civil", "law_docs_commercial",
            "law_docs_criminal", "law_docs_labor", "law_docs_tax",
            "law_docs_constitution", "law_docs_global", "law_docs_international",
        ]
        for cname in target_cols:
            if cname not in col_names:
                continue
            col = client.get_collection(cname)
            for cand in candidate_names:
                for field in ("statute_name", "law_name"):
                    res = col.get(where={field: cand}, include=["documents", "metadatas"])
                    for doc_id, text, meta in zip(res.get("ids") or [], res.get("documents") or [], res.get("metadatas") or []):
                        m = dict(meta or {})
                        if m.get("article") == "부칙" or m.get("part") == "부칙" or "부칙" in str(m.get("title") or ""):
                            doc = Document(id=doc_id, page_content=text, metadata=m)
                            add_src = build_source_from_chroma_doc(
                                doc,
                                category=cname.replace("law_docs_", ""),
                                retrieval_method="CHROMA_COMPANION_ADDENDA",
                            )
                            matched.append(add_src)
                            return matched
    except Exception as _ex:
        logger.debug("[LOCAL_SEARCH] 부칙 동반 조회 예외: %s", _ex)
    return matched


def _retrieve_from_local_index(
    law_name: str,
    articles: list[str],
    query: str = "",
    as_of_date: str | None = None,
    limit: int = 4,
    require_all: bool = True,
) -> list[dict[str, Any]]:
    """ChromaDB law_docs_global 컬렉션에서 이미 영구 적재된 공식 법령 조문을 선조회한다 (Local-First).

    공식 법령 백그라운드 인덱싱(P9)으로 로컬 Chroma에 수록된 조문 원문을 네트워크 호출 없이
    즉각 재활용하여 실시간 검색 지연과 외부 API 의존도를 낮춘다.

    Args:
        law_name: 정식 법령명 (예: "주택임대차보호법", "민법").
        articles: 특정 조문 번호 리스트 (예: ["제3조", "제3조의2"]). 비어있을 경우 유사도 검색 수행.
        query: 조문 미지정 시 벡터 검색에 활용할 질문/쟁점 텍스트.
        as_of_date: 사건 기준일 (선택적).
        limit: 조문 미지정 시 반환할 최대 조문 개수.

    Returns:
        list[dict[str, Any]]: 표준 Source 스키마 규격으로 정규화된 법령 출처 딕셔너리 리스트.
            로컬 인덱스에 없거나 미완비된 경우 빈 리스트 반환 (OpenLaw API 폴백 유도).
    """
    from ai_legal_helper.rag.retrieval import _get_client
    from ai_legal_helper.rag.source_schema import build_source_from_chroma_doc
    from ai_legal_helper.legal_knowledge.law_catalog import normalize_law_name
    from langchain_core.documents import Document

    try:
        client = _get_client()
        col_names = [getattr(c, "name", str(c)) for c in client.list_collections()]
        if "law_docs_global" not in col_names:
            return []
        collection = client.get_collection("law_docs_global")

        norm_name = normalize_law_name(law_name)
        target_articles = set(articles) if articles else set()

        # 법령명 표기(공백 포함 vs 공백 제거) 및 메타데이터 필드(statute_name vs law_name) 후보군 생성
        candidate_laws = list(dict.fromkeys([
            law_name,
            norm_name,
            " ".join(law_name.split()) if law_name else "",
            "".join(law_name.split()) if law_name else "",
        ]))
        candidate_laws = [c for c in candidate_laws if c]

        if target_articles:
            # 명시 조문이 요청된 경우 법령명 표기 후보군으로 로드 후 선별
            ids, docs, metas = [], [], []
            for cand in candidate_laws:
                for field in ("statute_name", "law_name"):
                    res = collection.get(where={field: cand}, include=["documents", "metadatas"])
                    if res.get("ids"):
                        ids = res["ids"]
                        docs = res.get("documents") or []
                        metas = res.get("metadatas") or []
                        break
                if ids:
                    break
            if not ids:
                return _retrieve_from_domain_collections(
                    client, col_names, norm_name, law_name, target_articles, query, limit, require_all
                )
            if False:
                return []

            matched = []
            import urllib.parse
            for doc_id, text, meta in zip(ids, docs, metas):
                meta_dict = dict(meta or {})
                if meta_dict.get("article") in target_articles:
                    d = Document(id=doc_id, page_content=text, metadata=meta_dict)
                    s_dict = build_source_from_chroma_doc(
                        d, category="global", retrieval_method="OFFICIAL_STATUTE_SEARCH",
                    )
                    if meta_dict.get("vector_id"):
                        s_dict["source_id"] = meta_dict["vector_id"]
                    if not s_dict.get("source_url") and law_name and meta_dict.get("article"):
                        s_dict["source_url"] = f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}/{meta_dict['article']}"
                    matched.append(s_dict)

            # 요청된 모든 조문 구비 여부 판단 (require_all=True 시 미비 조문 존재 시 외부 폴백)
            found_articles = {s.get("article") for s in matched}
            if require_all and not target_articles.issubset(found_articles):
                return []
            if not matched:
                return _retrieve_from_domain_collections(
                    client, col_names, norm_name, law_name, target_articles, query, limit, require_all
                )
            return _append_companion_addenda(matched, client, norm_name or law_name)
        else:
            # 조문 번호가 특정되지 않은 경우 질의 기반 벡터 유사도 검색으로 상위 조문 추출
            if not query or not query.strip():
                return []
            from ai_legal_helper.llm.gateway import get_embeddings
            emb = get_embeddings()
            q_vec = emb.embed_query(f"{norm_name or law_name} {query}")
            res = collection.query(
                query_embeddings=[q_vec],
                n_results=limit,
                where={"statute_name": norm_name or law_name},
                include=["documents", "metadatas"],
            )
            matched = []
            import urllib.parse
            ids = (res.get("ids") or [[]])[0]
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            for doc_id, text, meta in zip(ids, docs, metas):
                meta_dict = dict(meta or {})
                d = Document(id=doc_id, page_content=text, metadata=meta_dict)
                s_dict = build_source_from_chroma_doc(
                    d, category="global", retrieval_method="OFFICIAL_STATUTE_SEARCH",
                )
                if meta_dict.get("vector_id"):
                    s_dict["source_id"] = meta_dict["vector_id"]
                if not s_dict.get("source_url") and law_name and meta_dict.get("article"):
                    s_dict["source_url"] = f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}/{meta_dict['article']}"
                matched.append(s_dict)
            if not matched:
                return _retrieve_from_domain_collections(
                    client, col_names, norm_name, law_name, target_articles, query, limit, require_all
                )
            return _append_companion_addenda(matched, client, norm_name or law_name)
    except Exception as exc:
        logger.warning("[LOCAL_FIRST_SEARCH] 로컬 인덱스 조회 중 예외 발생: %s", exc)
        return []



def can_satisfy_requests_locally(requests: list[dict[str, Any]]) -> bool:
    """법령 검색 요청들이 로컬 인덱스(law_docs_global)에서 모두 충족 가능한지 사전 검사한다.

    HITL 승인 팝업 이전에 로컬 영구 인덱스 적재 여부를 확인하여, 이미 확보된
    법령 조문에 대한 불필요한 사용자 인터럽트를 방지한다.

    Args:
        requests: 법령 검색 요청 목록 (law_name, articles 등 포함).

    Returns:
        bool: 모든 요청이 로컬 인덱스에서 완결될 수 있으면 True.
    """
    if not requests:
        return False
    for req in requests:
        law_name = req.get("law_name")
        articles = req.get("articles") or []
        issue = req.get("issue") or ""
        if not law_name:
            return False
        matched = _retrieve_from_local_index(
            law_name=law_name,
            articles=articles,
            query=issue,
            require_all=True,
        )
        if not matched:
            return False
    return True


def execute_document_search(state: dict[str, Any]) -> dict[str, Any]:
    """승인된 새 조문만 검색하고 결과·조회 이력을 상태 갱신값으로 반환한다.

    Args:
        state: 현재 출처, 검증 요청과 사용자의 승인 범위.

    Returns:
        새 출처, 누적 출처, 시도 이력과 검색 횟수. 승인 밖 호출은 실행하지 않는다.
    """
    from ai_legal_helper.tools.official_statute_search import search_official_statutes

    requests = pending_searches(state)
    precedent_requests = pending_precedent_searches(state)
    approved = search_is_approved(state, requests)
    precedent_approved = precedent_search_is_approved(state, precedent_requests)
    curr_count = state.get("statute_search_count") or 0
    logger.info(
        "[DOCUMENT_SEARCH] 법령 검색 계획 평가 (대기 요청: %d건 | 사용자 승인: %s | 이전 검색횟수: %d회)",
        len(requests),
        approved,
        curr_count,
    )
    if curr_count >= 2:
        logger.warning("[DOCUMENT_SEARCH] 최대 법령 검색 횟수(2회)에 도달하여 추가 검색을 중단합니다.")
        return {
            "statute_search_results": [],
            "statute_search_status": "MAX_COUNT_REACHED",
            "statute_search_count": curr_count + 1,
        }
    if not requests and not precedent_requests:
        return {
            "statute_search_results": [],
            "precedent_search_results": [],
            "statute_search_status": "NO_PENDING",
            "statute_search_count": curr_count + 1,
        }
    grouped: dict[str, list[dict]] = {}
    for request in requests:
        grouped.setdefault(request["law_name"], []).append(request)
    found = []
    diagnostics = []
    channels_used = set()
    local_matched_count = 0
    openlaw_matched_count = 0
    statute_search_items = []

    for name, items in grouped.items():
        articles = list(dict.fromkeys(a for r in items for a in r["articles"]))
        has_unnumbered = any(not r.get("articles") for r in items)
        references = [f"{name} {a}" for a in articles]
        if has_unnumbered or not references:
            references.append(name)

        # 0. 승인 여부 검사: 사용자가 거절(DENIED)했거나 승인 목록에 없는 법령은 로컬/외부 모두 검색을 차단한다.
        if state.get("approval_status") == "DENIED":
            logger.info("[DOCUMENT_SEARCH] 거절(DENIED) 상태이므로 검색을 생략합니다.")
            continue

        approved_laws = state.get("approved_statute_laws") or []
        is_law_approved = (
            approved  # search_is_approved() 결과 (auto_approve 등 반영)
            or not approved_laws
            or any(
                name == app or name in app or app in name
                for app in approved_laws
            )
        )
        if not is_law_approved:
            logger.info("[DOCUMENT_SEARCH] 미승인 법령('%s')이므로 검색을 생략합니다.", name)
            continue

        # 1. Local-First: 이미 영구 적재된 공식 법령 인덱스(law_docs_global)에서 선조회 시도
        local_matched = _retrieve_from_local_index(
            law_name=name,
            articles=articles if not has_unnumbered else [],
            query=" ".join(r["issue"] for r in items),
            as_of_date=(state.get("case_evidence_briefing") or {}).get("as_of_date"),
            limit=max(len(articles), 4),
        )
        if local_matched:
            logger.info(
                "[DOCUMENT_SEARCH] 로컬 공식 법령 인덱스(law_docs_global)에서 '%s' 조문 %d건 즉시 재사용 (Local-First Hit)",
                name, len(local_matched),
            )
            channels_used.add("VECTOR_DB")
            local_matched_count += len(local_matched)
            for doc in local_matched:
                s_name = doc.get("statute_name") or name
                s_art = doc.get("article") or ""
                s_title = doc.get("article_title") or ""
                disp = f"{s_name} {s_art}" + (f" ({s_title})" if s_title and s_title != "?" else "")
                statute_search_items.append({
                    "statute_name": s_name,
                    "article": s_art,
                    "title": s_title,
                    "display": disp.strip(),
                    "channel": "VECTOR_DB",
                })
            found.extend(local_matched)
            continue


        # 3. 승인된 경우에 한해 OpenLaw 실시간 공식 API 호출
        diagnostic = {}
        try:
            channels_used.add("OPENLAW_API")
            api_found = search_official_statutes(
                query=" ".join(r["issue"] for r in items), candidate_laws=references,
                missing_issues=[r["issue"] for r in items], max_articles_per_law=max(len(articles), 4),
                as_of_date=(state.get("case_evidence_briefing") or {}).get("as_of_date"),
                diagnostic=diagnostic,
            )
            if api_found:
                channels_used.add("OPENLAW_API")
                openlaw_matched_count += len(api_found)
                for doc in api_found:
                    s_name = doc.get("statute_name") or name
                    s_art = doc.get("article") or ""
                    s_title = doc.get("article_title") or ""
                    disp = f"{s_name} {s_art}" + (f" ({s_title})" if s_title and s_title != "?" else "")
                    statute_search_items.append({
                        "statute_name": s_name,
                        "article": s_art,
                        "title": s_title,
                        "display": disp.strip(),
                        "channel": "OPENLAW_API",
                    })
                found.extend(api_found)
        except Exception as exc:
            # 공식 API 장애를 그래프 전체 실패로 전파하지 않는다. 법령을 임의로 생성하지 않는다.
            diagnostic["api_error"] = True
            logger.warning("[DOCUMENT_SEARCH] 공식 검색 실패 law=%s error=%s", name, type(exc).__name__)
        diagnostics.append(diagnostic)
    # [PRECEDENT-05] 판례 조회는 법령 조회/Temporal Resolver와 독립한다.
    # 법령 API가 사용된 조문을 찾았더라도 PRECEDENT/BOTH 요청이 있으면
    # 판례를 별도로 검색한다. 과거 SC-012의 '민법만 재조회' 실패를 방지.
    precedent_sources: list[dict[str, Any]] = []
    precedent_diagnostic: dict[str, Any] = {}
    if precedent_requests and precedent_approved:
        from ai_legal_helper.tools.official_precedent_search import search_official_precedents
        try:
            precedent_sources = search_official_precedents(
                [r["precedent_query"] for r in precedent_requests],
                max_results=3,
                diagnostic=precedent_diagnostic,
            )
            if precedent_diagnostic.get("request_count", 0):
                channels_used.add("OPENLAW_PRECEDENT_API")
        except Exception as exc:
            precedent_diagnostic["status"] = "API_ERROR"
            logger.warning("[DOCUMENT_SEARCH] 판례 공식 조회 실패 type=%s", type(exc).__name__)
    elif precedent_requests:
        logger.warning("[DOCUMENT_SEARCH] 판례 조회가 승인되지 않아 원격 검색을 생략합니다.")

    fallback = []
    api_error = any(d.get("api_error") or any(
        entry.get("reason_code") not in ("", "LAW_NOT_FOUND", "NO_MATCH", "NO_VERSIONS", "MAINTENANCE_UNAVAILABLE")
        for entry in d.get("lookups", []) if entry.get("status") == "UNCONFIRMED"
    ) for d in diagnostics)
    if not found and not api_error:
        fallback = _verified_local_fallback(state, requests)
        if fallback:
            logger.info("[DOCUMENT_SEARCH] 공식 검색 실패 후 시점 검증된 기존 공식 원문 %d건 재사용", len(fallback))
    # 일부 법령만 확보했더라도 전체 검색 성공으로 오인하지 않는다.
    found_laws = {str(src.get("statute_name") or "") for src in found}
    requested_laws = set(grouped)
    # 법령명만 일치해도 요청 조문이 빠졌다면 부분 성공으로 표시한다.
    def _request_fulfilled(request: dict[str, Any]) -> bool:
        matches = [src for src in found if src.get("statute_name") == request["law_name"]]
        if not matches:
            return False
        articles = request.get("articles") or []
        if not articles:
            return True
        return all(any(src.get("article") == article for src in matches) for article in articles)

    partial = bool(found or precedent_sources) and (
        not all(_request_fulfilled(r) for r in requests)
        or (bool(precedent_requests) and not bool(precedent_sources))
    )
    if partial:
        logger.warning("[DOCUMENT_SEARCH] 일부 법령만 확보: %d/%d", len(found_laws & requested_laws), len(requested_laws))
    merged = list(state.get("retrieved_sources") or [])
    seen = {s.get("source_id") for s in merged}
    for source in found + precedent_sources:
        if source.get("source_id") not in seen:
            merged.append(source)
            seen.add(source.get("source_id"))
    logger.info(
        "[DOCUMENT_SEARCH] 법령 원문 검색 완료 (신규 확보 조문: %d건 | 총 출처: %d건)",
        len(found),
        len(merged),
    )
    # P9: 사용자 승인 하에 새로 확보된 공식 법령 조문 버전을 백그라운드 인덱싱 작업 큐에 등록.
    # 실시간 상담 스레드에서 무거운 임베딩이나 XML 저장을 직접 수행하지 않고 비동기 작업 큐로 격리한다.

    if found and os.getenv("LEGAL_BACKGROUND_INDEX_ENABLED", "1") in ("1", "true", "True"):
        try:
            from ai_legal_helper.legal_knowledge.index_worker import enqueue_approved_sources
            queue_result = enqueue_approved_sources(found)
            logger.info("[OFFICIAL_INDEX] document_search approved enqueue result=%s", queue_result)
        except Exception as exc:
            logger.warning("[OFFICIAL_INDEX] document_search 백그라운드 인덱스 등록 예외: %s", exc)

    if "OPENLAW_PRECEDENT_API" in channels_used:
        # 판례 조회는 공식 API지만 법령 조문 인덱싱이나 시행일 검증과 다르다.
        channels_used.add("OPENLAW_API")
    if "VECTOR_DB" in channels_used and "OPENLAW_API" in channels_used:
        channel_mode = "HYBRID"
    elif "VECTOR_DB" in channels_used:
        channel_mode = "VECTOR_DB"
    elif "OPENLAW_API" in channels_used:
        channel_mode = "OPENLAW_API"
    else:
        channel_mode = "NONE"

    is_auto = bool(state.get("auto_approve_statute_search") or os.getenv("AUTO_APPROVE_STATUTE_SEARCH", "").lower() in ("true", "1", "yes"))
    prefix = "[자동승인] " if is_auto else ""
    precedent_displays = [
        " ".join(filter(None, [p.get("court"), p.get("case_number")]))
        for p in precedent_sources
    ]
    items_str = " · ".join([item["display"] for item in statute_search_items] + precedent_displays)
    if channel_mode == "HYBRID":
        completion_desc = f"{prefix}로컬 벡터DB 및 OpenLaw API 병행 확보 | {items_str}"
    elif channel_mode == "VECTOR_DB":
        completion_desc = f"{prefix}로컬 벡터DB에서 {len(found)}건 확보 | {items_str}"
    elif channel_mode == "OPENLAW_API":
        completion_desc = f"{prefix}OpenLaw 공식 API에서 법령 {len(found)}건·판례 {len(precedent_sources)}건 확보 | {items_str}"
    else:
        completion_desc = f"{prefix}법령을 찾지 못했습니다."

    return {
        "statute_search_results": found or fallback,
        "precedent_search_results": precedent_sources,
        "precedent_search_status": (
            precedent_diagnostic.get("status")
            if precedent_requests and precedent_approved
            else "NOT_APPROVED" if precedent_requests else "NOT_REQUESTED"
        ),
        "retrieved_sources": merged,
        "statute_search_status": (
            "API_ERROR" if api_error and not (found or precedent_sources) else
            "PARTIAL_SUCCESS" if partial else
            "OFFICIAL_SUCCESS" if (found or precedent_sources) else
            "VERIFIED_LOCAL_FALLBACK" if fallback else "NOT_FOUND"
        ),
        "statute_search_count": (state.get("statute_search_count") or 0) + 1,
        "statute_search_history": list(dict.fromkeys(
            (state.get("statute_search_history") or []) + [r["key"] for r in requests]
        )),
        # 재시도 무한반복 방지: 승인된 요청을 시도했을 때만 기록한다.
        "precedent_search_history": list(dict.fromkeys(
            (state.get("precedent_search_history") or [])
            + ([r["key"] for r in precedent_requests] if precedent_approved else [])
        )),
        "statute_search_channels": sorted(list(channels_used)),
        "statute_search_channel_mode": channel_mode,
        "statute_search_channel_desc": completion_desc,
        "statute_search_stats": {
            "local_count": local_matched_count,
            "openlaw_count": openlaw_matched_count,
            "total_count": len(found),
        },
        "statute_search_items": statute_search_items,
        "precedent_search_items": [
            {
                "source_id": p.get("source_id"),
                "display": " ".join(filter(None, [p.get("court"), p.get("case_number")])),
                "channel": "OPENLAW_PRECEDENT_API",
            }
            for p in precedent_sources
        ],
    }
