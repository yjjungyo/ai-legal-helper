# -*- coding: utf-8 -*-
"""
모듈명: graph_rag.py

[모듈 개요]
PostgreSQL(Source of Truth) 구조화·텍스트 증거 검색과 Neo4j 사건 Knowledge Graph 관계 탐색을 결합한
Structured Evidence GraphRAG 검색 모듈이다.
기존 ChromaDB 사건 증거 Embedding/Vector 검색 의존성을 완전히 제거하고,
PostgreSQL 시드 검색 → Neo4j 관계 확장 → PostgreSQL 원본·승인상태 대조 검증의 3단계 파이프라인을 수행한다.

[주요 기능]
1. Baseline 검색       : Neo4j 내 질문 키워드와 노드 텍스트 매칭
2. Traversal 검색      : PostgreSQL 시드(Claim/Fact/Span) 또는 키워드로부터 근거 원문 경로 역추적
3. Structured Hybrid   : PostgreSQL Evidence Search 시드 확보 → Neo4j Traversal 확장 + 공백·상충 분석
4. PostgreSQL Fallback : Neo4j 장애/미연결 시 ChromaDB 없이 PostgreSQL 구조화 검색 결과만으로 즉시 대응
5. 경로 원본 검증      : validate_graph_paths()를 통해 PostgreSQL 실존·승인상태·문서소속·사건일치 검증
6. 통합 검색 인터페이스: retrieve_structured_evidence() -> EvidenceRetrievalResult 반환
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.context import get_current_span_id
from ai_legal_helper.observability.langfuse_client import update_span

logger = logging.getLogger(__name__)

# 근거로 인정하는 Claim 검토 상태 (graph_sync 와 동일 정책)
_APPROVED = ["APPROVED", "EDITED"]

# 키워드 추출 시 제외할 한국어 기능어/일반어
_STOPWORDS = {
    "그리고", "그런데", "하지만", "어떻게", "무엇", "있나요", "있습니까", "합니까", "해야",
    "하나요", "인가요", "되나요", "경우", "관련", "대해", "대한", "제가", "저는", "우리",
    "이번", "지금", "혹시", "정말", "가능", "방법", "문제", "사건", "질문",
}
_JOSA = re.compile(r"(으로|에서|에게|까지|부터|이나|이랑|하고|은|는|이|가|을|를|에|의|도|만|로|와|과)$")


class EvidenceRetrievalResult(BaseModel):
    """사건 증거 통합 검색 결과 모델 (PostgreSQL 구조화 검색 + Neo4j Graph Traversal + 원본 검증).

    지시서 제5·6·7·9절의 표준 반환 인터페이스를 정의한다.
    """
    case_id: str
    strategy: str = "structured_graph_hybrid"
    search_mode: str = "POSTGRESQL_PLUS_NEO4J"
    matched_claims: List[Dict[str, Any]] = Field(default_factory=list)
    matched_facts: List[Dict[str, Any]] = Field(default_factory=list)
    matched_spans: List[Dict[str, Any]] = Field(default_factory=list)
    structured_matches: List[Dict[str, Any]] = Field(default_factory=list)
    graph_paths: List[Dict[str, Any]] = Field(default_factory=list)
    invalid_graph_count: int = 0
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_gaps: List[Dict[str, Any]] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    graph_available: bool = False
    context_text: str = ""


def extract_keywords(query: str, max_keywords: int = 8) -> List[str]:
    """질문에서 그래프 매칭용 키워드를 추출한다.

    Args:
        query: 사용자 질문.
        max_keywords: 최대 키워드 수.

    Returns:
        2글자 이상, 중복 제거된 키워드 목록(입력 순서 유지).
    """
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", query or "")
    out: List[str] = []
    for t in tokens:
        t = _JOSA.sub("", t)
        if len(t) < 2 or t in _STOPWORDS or t in out:
            continue
        out.append(t.lower())
        if len(out) >= max_keywords:
            break
    return out


def _open_default_db_session():
    """호출자가 DB 세션을 전달하지 않은 경우 사용할 기본(또는 테스트 오버라이드) 세션을 생성한다."""
    from ai_legal_helper.database import graph_sync
    if graph_sync.session_factory is not None:
        return graph_sync.session_factory()
    from ai_legal_helper.database.session import SessionLocal
    return SessionLocal()


class GraphRAGRetriever:
    """사건 Structured Evidence GraphRAG 검색기.

    Attributes:
        driver: Neo4j Driver. None 이면 그래프 탐색을 생략하고 PostgreSQL 검색만으로 Fallback 한다.
    """

    def __init__(self, driver) -> None:
        self.driver = driver

    # ------------------------------------------------------------------ 내부 유틸
    def _run(self, cypher: str, **params) -> List[Dict[str, Any]]:
        """읽기 쿼리를 실행하고 레코드를 dict 목록으로 반환한다. 오류 시 빈 목록."""
        if self.driver is None:
            return []
        try:
            with self.driver.session() as session:
                return [r.data() for r in session.run(cypher, **params)]
        except Exception as e:
            # 그래프 장애는 상담 전체를 실패시키지 않는다. 유형만 기록한다.
            logger.warning(f"[GRAPH_RAG] 쿼리 실패: {type(e).__name__}")
            return []

    # ------------------------------------------------------------------ 전략 1: Baseline
    def search_baseline(self, case_id: str, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """키워드가 포함된 사건 내 노드를 매칭 키워드 수 순으로 반환한다(Baseline).

        Returns:
            [{node_type, node_id, content, score}] — score 는 매칭된 키워드 수.
        """
        kws = extract_keywords(query)
        if not kws:
            return []
        return self._run("""
            MATCH (n {case_id: $case_id})
            WHERE n:Fact OR n:LegalIssue OR n:Event OR n:EvidenceClaim OR n:EvidenceSpan
            WITH n, toLower(coalesce(n.statement, '') + ' ' + coalesce(n.title, '') + ' ' +
                            coalesce(n.description, '') + ' ' + coalesce(n.text_excerpt, '')) AS txt
            WITH n, size([k IN $kws WHERE txt CONTAINS k]) AS score
            WHERE score > 0
              AND (NOT n:EvidenceClaim OR n.review_status IN $approved)
            RETURN labels(n)[0] AS node_type, n.id AS node_id,
                   coalesce(n.statement, n.title, n.text_excerpt) AS content, score
            ORDER BY score DESC LIMIT $limit
        """, case_id=case_id, kws=kws, approved=_APPROVED, limit=limit)

    # ------------------------------------------------------------------ 전략 2: Traversal
    @trace
    def search_traversal(
        self,
        case_id: str,
        query: Optional[str] = None,
        seed_ids: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """대상(Fact/Event/LegalIssue) 또는 시드(Claim/Span/Fact)에서 근거 원문까지의 경로를 탐색한다.

        탐색 경로:
          (Span)-[:SUPPORTS]->(Claim)-[:SUPPORTS|CONTRADICTS]->(Fact|Event)  (직접)
          (Span)-[:SUPPORTS]->(Claim)-[:SUPPORTS|CONTRADICTS]->(Fact)-[:RELATED_TO]->(LegalIssue)  (쟁점 경유)

        Args:
            case_id: 사건 ID.
            query: 대상 노드 키워드 필터(선택).
            seed_ids: PostgreSQL Evidence Search에서 확보한 시드 노드 ID 목록(Claim/Fact/Span).
            limit: 최대 경로 수.

        Returns:
            [{target_type, target_id, target_content, relation, claim_id, claim_statement,
              review_status, assertion_status, evidence_id, span_id, page_number, paragraph_index,
              evidence_text, filename, via_fact_id}]
        """
        kws = extract_keywords(query or "")
        if not kws and not seed_ids:
            return []
        return self._run("""
            MATCH (d:EvidenceDocument {case_id: $case_id})-[:HAS_CLAIM]->(cl:EvidenceClaim)
                  -[rel:SUPPORTS|CONTRADICTS]->(t)
            WHERE cl.review_status IN $approved AND (t:Fact OR t:Event OR t:LegalIssue)
            OPTIONAL MATCH (s:EvidenceSpan {case_id: $case_id})-[:SUPPORTS]->(cl)
            OPTIONAL MATCH (t)-[:RELATED_TO]->(issue:LegalIssue {case_id: $case_id})
            WITH d, cl, rel, t, s, issue
            UNWIND (CASE WHEN issue IS NULL THEN [null] ELSE [null, issue] END) AS via
            WITH d, cl, rel, t, s, via,
                 CASE WHEN via IS NULL THEN t ELSE via END AS target
            WITH d, cl, rel, t, s, via, target,
                 toLower(coalesce(target.statement,'') + ' ' + coalesce(target.title,'') + ' ' +
                         coalesce(target.description,'') + ' ' + coalesce(cl.statement,'') + ' ' +
                         coalesce(s.text_excerpt,'')) AS txt
            WHERE ($seed_ids IS NOT NULL AND (
                     target.id IN $seed_ids OR cl.id IN $seed_ids OR t.id IN $seed_ids
                     OR (s IS NOT NULL AND s.id IN $seed_ids)
                  ))
               OR (size($kws) > 0 AND any(k IN $kws WHERE txt CONTAINS k))
            RETURN DISTINCT labels(target)[0] AS target_type, target.id AS target_id,
                   coalesce(target.statement, target.title) AS target_content,
                   type(rel) AS relation, cl.id AS claim_id, cl.statement AS claim_statement,
                   cl.review_status AS review_status, cl.assertion_status AS assertion_status,
                   d.id AS evidence_id, d.filename AS filename,
                   s.id AS span_id, s.text_excerpt AS evidence_text,
                   s.page_number AS page_number, s.paragraph_index AS paragraph_index,
                   CASE WHEN via IS NULL THEN null ELSE t.id END AS via_fact_id
            LIMIT $limit
        """, case_id=case_id, approved=_APPROVED, kws=kws, seed_ids=seed_ids, limit=limit)

    # ------------------------------------------------------------------ 분석
    def find_evidence_gaps(self, case_id: str) -> List[Dict[str, Any]]:
        """승인된 근거가 연결되지 않은 쟁점/사실(증거 공백)을 찾는다."""
        return self._run("""
            MATCH (n {case_id: $case_id})
            WHERE n:Fact OR n:LegalIssue
            OPTIONAL MATCH (cl:EvidenceClaim)-[:SUPPORTS]->(n)
            WHERE cl.review_status IN $approved
            OPTIONAL MATCH (cl2:EvidenceClaim)-[:SUPPORTS]->(:Fact)-[:RELATED_TO]->(n)
            WHERE n:LegalIssue AND cl2.review_status IN $approved
            WITH n, count(DISTINCT cl) + count(DISTINCT cl2) AS support_count
            WHERE support_count = 0
            RETURN labels(n)[0] AS node_type, n.id AS node_id,
                   coalesce(n.statement, n.title) AS content
            LIMIT 30
        """, case_id=case_id, approved=_APPROVED)

    def find_contradictions(self, case_id: str) -> List[Dict[str, Any]]:
        """승인된 Claim의 CONTRADICTS 관계와, 같은 대상에 대한 SUPPORTS 근거를 함께 반환한다."""
        return self._run("""
            MATCH (src)-[:CONTRADICTS]->(t {case_id: $case_id})
            WHERE NOT src:EvidenceClaim OR src.review_status IN $approved
            OPTIONAL MATCH (sup:EvidenceClaim)-[:SUPPORTS]->(t)
            WHERE sup.review_status IN $approved
            RETURN labels(t)[0] AS target_type, t.id AS target_id,
                   coalesce(t.statement, t.title) AS target_content,
                   src.id AS contradicting_id, labels(src)[0] AS contradicting_type,
                   src.statement AS contradicting_statement,
                   collect(DISTINCT sup.id) AS supporting_claim_ids
            LIMIT 30
        """, case_id=case_id, approved=_APPROVED)

    # ------------------------------------------------------------------ 전략 3: Structured Hybrid (PostgreSQL + Neo4j)
    @trace
    def search_hybrid(
        self,
        case_id: str,
        query: str,
        db: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """PostgreSQL Evidence Search 결과를 시드로 Neo4j Graph Traversal 확장 및 공백·상충 분석을 결합한다.

        - ChromaDB Vector Search는 일절 호출하지 않는다.
        - Neo4j가 비활성이거나 연결 불가능한 경우(driver is None), PostgreSQL 구조화 검색 결과와
          PostgreSQL 기반 상충·공백 분석 결과를 Fallback으로 반환한다.

        Args:
            case_id: 대상 사건 ID.
            query: 사용자 질문.
            db: SQLAlchemy 세션(선택, 미전달 시 내부에서 단기 세션 생성).

        Returns:
            Dict[str, Any]: 검색 전략, 가용 여부, structured_matches, traversal_paths,
                            evidence_gaps, contradictions 포함 딕셔너리.
        """
        from ai_legal_helper.rag.evidence_search import search_evidence_in_postgres

        owns_session = False
        session = db
        pg_res = None
        try:
            if session is None:
                session = _open_default_db_session()
                owns_session = True
            pg_res = search_evidence_in_postgres(
                db=session,
                case_id=case_id,
                query=query,
                strategy="hybrid_pg",
                include_pending=False,
            )
        except Exception as e:
            logger.warning(f"[GRAPH_RAG] PostgreSQL evidence search error: {type(e).__name__}: {e}")
        finally:
            if owns_session and session is not None:
                try:
                    session.close()
                except Exception:
                    pass

        structured_matches: List[Dict[str, Any]] = []
        seeds: Optional[List[str]] = None
        pg_gaps: List[Dict[str, Any]] = []
        pg_contradictions: List[Dict[str, Any]] = []

        if pg_res is not None:
            structured_matches = [h.model_dump() for h in pg_res.hits]
            seed_set: List[str] = []
            for sid in (pg_res.matched_claim_ids + pg_res.matched_fact_ids + pg_res.matched_span_ids):
                if sid and sid not in seed_set:
                    seed_set.append(sid)
            seeds = seed_set or None
            pg_gaps = pg_res.evidence_gaps
            pg_contradictions = pg_res.contradictions

        # 2. Neo4j GraphDB Fallback 검사
        if self.driver is None:
            cur_span = get_current_span_id()
            if cur_span:
                try:
                    update_span(cur_span, {
                        "fallback": True,
                        "search_mode": "POSTGRESQL_ONLY",
                        "structured_matches_count": len(structured_matches),
                    })
                except Exception:
                    pass
            return {
                "strategy": "postgresql_fallback",
                "search_mode": "POSTGRESQL_ONLY",
                "available": False,
                "graph_available": False,
                "keywords": extract_keywords(query),
                "baseline_matches": [],
                "structured_matches": structured_matches,
                "traversal_paths": [],
                "evidence_gaps": pg_gaps,
                "contradictions": pg_contradictions,
            }

        # 3. Neo4j Graph Traversal 실행 (PostgreSQL 시드 + 질문 키워드 결합)
        traversal = self.search_traversal(case_id, query=query, seed_ids=seeds)
        g_gaps = self.find_evidence_gaps(case_id)
        g_contra = self.find_contradictions(case_id)

        cur_span = get_current_span_id()
        if cur_span:
            try:
                update_span(cur_span, {
                    "fallback": False,
                    "search_mode": "POSTGRESQL_PLUS_NEO4J",
                    "structured_matches_count": len(structured_matches),
                    "traversal_paths_count": len(traversal),
                })
            except Exception:
                pass

        return {
            "strategy": "hybrid",
            "search_mode": "POSTGRESQL_PLUS_NEO4J",
            "available": True,
            "graph_available": True,
            "keywords": extract_keywords(query),
            "baseline_matches": [],
            "structured_matches": structured_matches,
            "traversal_paths": traversal,
            "evidence_gaps": g_gaps if g_gaps else pg_gaps,
            "contradictions": g_contra if g_contra else pg_contradictions,
        }

    # ------------------------------------------------------------------ UI
    def get_case_graph(self, case_id: str, include_pending: bool = False) -> Dict[str, Any]:
        """React Evidence Graph 탭용 노드/엣지 목록을 반환한다."""
        nodes = self._run("""
            MATCH (n {case_id: $case_id})
            WHERE $include_pending OR NOT n:EvidenceClaim OR n.review_status IN $approved
            RETURN n.id AS id, labels(n)[0] AS type,
                   coalesce(n.title, n.statement, n.name, n.filename, n.text_excerpt) AS label,
                   properties(n) AS props
        """, case_id=case_id, include_pending=include_pending, approved=_APPROVED)
        ids = [n["id"] for n in nodes]
        edges = self._run("""
            MATCH (a {case_id: $case_id})-[r]->(b {case_id: $case_id})
            WHERE a.id IN $ids AND b.id IN $ids
            RETURN a.id AS source, b.id AS target, type(r) AS type,
                   coalesce(r.is_ai_inferred, false) AS is_ai_inferred
        """, case_id=case_id, ids=ids)
        return {"case_id": case_id, "nodes": nodes, "edges": edges}


def validate_graph_paths(db, case_id: str, paths: List[Dict[str, Any]]) -> Dict[str, Any]:
    """그래프 경로를 PostgreSQL(Source of Truth)과 대조하여 코드 레벨로 검증하고 원문 위치를 보강한다.

    검증 항목:
      1. claim_id 가 존재하고 동일 case_id 에 속하는가
      2. claim 이 APPROVED/EDITED 상태인가 (PENDING/REJECTED 차단)
      3. evidence_id 가 존재하고 claim 의 문서와 일치하며 동일 사건인가
      4. span_id 가 있다면 해당 evidence 문서에 속하는가
      5. target(Fact/Event/LegalIssue)이 동일 사건에 존재하는가

    검증 통과 시 PostgreSQL 원본의 filename, page_number, paragraph_index, assertion_status를
    경로 딕셔너리에 보강하여 정확한 출처 인용을 보장한다.
    """
    from ai_legal_helper.database.models import (
        EvidenceClaim, EvidenceDocument, EvidenceSpan, Fact, Event, LegalIssue,
    )
    target_models = {"Fact": Fact, "Event": Event, "LegalIssue": LegalIssue}

    valid, invalid = [], []
    for p in paths:
        reasons: List[str] = []
        claim = db.get(EvidenceClaim, p.get("claim_id")) if p.get("claim_id") else None
        if claim is None:
            reasons.append("CLAIM_NOT_FOUND")
        else:
            if claim.case_id != case_id:
                reasons.append("CLAIM_CASE_MISMATCH")
            if claim.review_status not in _APPROVED:
                reasons.append(f"CLAIM_NOT_APPROVED:{claim.review_status}")
            if p.get("evidence_id") and claim.evidence_id != p.get("evidence_id"):
                reasons.append("EVIDENCE_MISMATCH")

        doc = db.get(EvidenceDocument, p.get("evidence_id")) if p.get("evidence_id") else None
        if doc is None or doc.case_id != case_id:
            reasons.append("EVIDENCE_NOT_FOUND")

        span = None
        if p.get("span_id"):
            span = db.get(EvidenceSpan, p["span_id"])
            if span is None or span.evidence_id != p.get("evidence_id"):
                reasons.append("SPAN_NOT_FOUND")

        model = target_models.get(p.get("target_type"))
        target = db.get(model, p.get("target_id")) if model and p.get("target_id") else None
        if target is None or target.case_id != case_id:
            reasons.append("TARGET_NOT_FOUND")

        if reasons:
            invalid.append({"path": p, "reasons": reasons})
        else:
            enriched = dict(p)
            if doc and not enriched.get("filename"):
                enriched["filename"] = doc.original_filename
            if span:
                if enriched.get("page_number") is None:
                    enriched["page_number"] = span.page_number
                if enriched.get("paragraph_index") is None:
                    enriched["paragraph_index"] = span.paragraph_index
                if not enriched.get("evidence_text"):
                    enriched["evidence_text"] = span.text_excerpt
            if claim and not enriched.get("assertion_status"):
                enriched["assertion_status"] = claim.assertion_status
            if target and hasattr(target, "verification_status"):
                enriched["target_verification_status"] = getattr(target, "verification_status", None)
            valid.append(enriched)

    return {"valid": valid, "invalid": invalid, "checked": len(paths)}


def format_graph_context(result: Dict[str, Any], valid_paths: List[Dict[str, Any]]) -> str:
    """검증된 GraphRAG 경로 및 PostgreSQL 구조화 증거 검색 결과를 프롬프트용 텍스트로 변환한다.

    - Neo4j 비활성(available=False) 시 PostgreSQL 구조화 검색 결과만 표시하며,
      사용되지 않은 그래프 경로를 실제 검색한 것처럼 표시하지 않는다.
    - 실제 문서명, 페이지 번호, 승인 상태, 신뢰 수준(assertion_status)을 명확히 표기한다.
    """
    structured_matches = result.get("structured_matches") or []
    gaps = result.get("evidence_gaps") or []
    contra = result.get("contradictions") or []

    if not result.get("available") and not structured_matches and not gaps and not contra:
        return ""

    lines: List[str] = []

    # 1. GraphDB 비활성 시 PostgreSQL 구조화 증거 검색 Fallback 컨텍스트
    if not result.get("available"):
        if structured_matches:
            lines.append("[사건 증거 검색 결과 (PostgreSQL 구조화·원문 검색 — GraphDB 비활성 Fallback)]")
            for m in structured_matches[:10]:
                sid = m.get("span_id") or m.get("claim_id") or m.get("fact_id") or m.get("node_id")
                fn = m.get("document_name") or m.get("evidence_id") or "사건내역"
                pg = f", p.{m['page_number']}" if m.get("page_number") else ""
                stmt = m.get("claim_statement") or m.get("statement") or ""
                excerpt = (m.get("source_excerpt") or "")[:80]
                ast_status = m.get("assertion_status") or "DOCUMENT_STATES"
                lines.append(
                    f"- [EVIDENCE:{sid}] 문서({fn}{pg}) [{ast_status}] {stmt}"
                    + (f" (원문: '{excerpt}')" if excerpt and excerpt != stmt else "")
                )
    else:
        # 2. Neo4j 활성 시 검증된 GraphRAG 경로 표시
        if valid_paths:
            lines.append("[증거 그래프 경로 (Structured Evidence GraphRAG) — 연결 관계이며 법률적 증명이 아님]")
            for p in valid_paths[:10]:
                sid = p.get("span_id") or p.get("claim_id")
                fn = p.get("filename") or p.get("evidence_id")
                pg = f", p.{p['page_number']}" if p.get("page_number") else ""
                excerpt = (p.get("evidence_text") or p.get("claim_statement") or "")[:80]
                ast = p.get("assertion_status") or "DOCUMENT_STATES"
                lines.append(
                    f"- [GRAPH:{sid}] 증거({fn}{pg}) [{ast}] '{excerpt}' "
                    f"-{p.get('relation')}-> {p.get('target_type')}: {p.get('target_content')}"
                )
        # 그래프 경로에 포함되지 않은 PostgreSQL 직접 매칭 증거 보충
        path_claim_ids = {p.get("claim_id") for p in valid_paths if p.get("claim_id")}
        path_span_ids = {p.get("span_id") for p in valid_paths if p.get("span_id")}
        extra_pg = [
            m for m in structured_matches
            if (m.get("claim_id") not in path_claim_ids) and (m.get("span_id") not in path_span_ids)
        ]
        if extra_pg:
            lines.append("\n[추가 매칭된 사건 증거 원문 (PostgreSQL Structured Search)]")
            for m in extra_pg[:5]:
                sid = m.get("span_id") or m.get("claim_id") or m.get("fact_id")
                fn = m.get("document_name") or m.get("evidence_id") or "사건증거"
                pg = f", p.{m['page_number']}" if m.get("page_number") else ""
                stmt = m.get("claim_statement") or m.get("statement") or ""
                lines.append(f"- [EVIDENCE:{sid}] 문서({fn}{pg}): {stmt}")

    if gaps:
        lines.append("\n[증거 공백 — 승인된 증거가 연결되지 않은 항목]")
        lines += [f"- {g.get('node_type', 'Fact')}: {g.get('content') or g.get('text') or ''}" for g in gaps[:10]]
    if contra:
        lines.append("\n[상충 증거 — 반박 관계가 존재하는 항목 (불확실성 주의)]")
        lines += [f"- {c.get('target_type', 'Fact')}: {c.get('target_content') or c.get('target_text') or ''}" for c in contra[:10]]

    return "\n".join(lines)


def graph_paths_to_sources(valid_paths: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """검증된 그래프 경로를 표준 Source 스키마(CASE_EVIDENCE, NEO4J_GRAPH) 형식으로 변환한다."""
    from ai_legal_helper.rag.source_schema import build_source_from_graph_path

    return [build_source_from_graph_path(p) for p in valid_paths]


def evidence_hits_to_sources(structured_matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """PostgreSQL 구조화 증거 검색 결과를 표준 Source 스키마(CASE_EVIDENCE, POSTGRES_EVIDENCE_SEARCH)로 변환한다."""
    from ai_legal_helper.rag.source_schema import build_source_from_evidence_search_result

    sources: List[Dict[str, Any]] = []
    seen_ids = set()
    for hit in structured_matches:
        # 실제 증거 문서(evidence_id)가 있는 항목만 CASE_EVIDENCE 출처로 등록 (단순 사용자 진술 Fact 제외)
        if not hit.get("evidence_id") and not hit.get("document_name"):
            continue
        src = build_source_from_evidence_search_result(hit)
        sid = src.get("source_id")
        if sid and sid not in seen_ids:
            seen_ids.add(sid)
            sources.append(src)
    return sources


_AUTO_DRIVER = object()


@trace
def retrieve_structured_evidence(
    db,
    case_id: str,
    query: str,
    driver: Any = _AUTO_DRIVER,
) -> EvidenceRetrievalResult:
    """사건 증거에 대해 PostgreSQL 구조화 검색 + Neo4j Graph Traversal + 원본 검증을 수행한다.

    Args:
        db: SQLAlchemy 세션.
        case_id: 대상 사건 ID.
        query: 검색 질문(resolved_query 또는 사용자 질문).
        driver: Neo4j 드라이버 (생략 시 get_neo4j_driver()로 자동 조회, 명시적으로 None 전달 시 오프라인 폴백).

    Returns:
        EvidenceRetrievalResult: 검증된 증거, 그래프 경로, 표준 출처, 프롬프트 컨텍스트를 담은 모델.
    """
    if not case_id:
        return EvidenceRetrievalResult(case_id="")

    if driver is _AUTO_DRIVER:
        try:
            from ai_legal_helper.database.neo4j import get_neo4j_driver
            driver = get_neo4j_driver()
        except Exception:
            driver = None

    retriever = GraphRAGRetriever(driver)
    raw_hybrid = retriever.search_hybrid(case_id=case_id, query=query, db=db)

    traversal_paths = raw_hybrid.get("traversal_paths", [])
    checked = (
        validate_graph_paths(db, case_id, traversal_paths)
        if traversal_paths
        else {"valid": [], "invalid": [], "checked": 0}
    )
    if checked["invalid"]:
        logger.warning(f"[GRAPH_RAG] 검증 실패 경로 {len(checked['invalid'])}건 제외")

    valid_paths = checked["valid"]
    structured_matches = raw_hybrid.get("structured_matches", [])

    matched_claims = [m for m in structured_matches if m.get("claim_id")]
    matched_facts = [m for m in structured_matches if m.get("fact_id")]
    matched_spans = [m for m in structured_matches if m.get("span_id")]

    graph_sources = graph_paths_to_sources(valid_paths)
    pg_sources = evidence_hits_to_sources(structured_matches)

    combined_sources: List[Dict[str, Any]] = []
    seen_sids = set()
    for s in (graph_sources + pg_sources):
        sid = s.get("source_id")
        if sid and sid not in seen_sids:
            seen_sids.add(sid)
            combined_sources.append(s)

    context_text = format_graph_context(raw_hybrid, valid_paths)

    return EvidenceRetrievalResult(
        case_id=case_id,
        strategy=raw_hybrid.get("strategy", "structured_graph_hybrid"),
        search_mode=raw_hybrid.get("search_mode", "POSTGRESQL_ONLY"),
        matched_claims=matched_claims,
        matched_facts=matched_facts,
        matched_spans=matched_spans,
        structured_matches=structured_matches,
        graph_paths=valid_paths,
        invalid_graph_count=len(checked["invalid"]),
        contradictions=raw_hybrid.get("contradictions", []),
        evidence_gaps=raw_hybrid.get("evidence_gaps", []),
        source_ids=list(seen_sids),
        sources=combined_sources,
        graph_available=bool(raw_hybrid.get("available", False)),
        context_text=context_text,
    )



def evaluate_evidence_strategies(
    db,
    case_id: str,
    benchmark_queries: List[Dict[str, Any]],
    driver: Optional[Any] = None,
) -> Dict[str, Dict[str, float]]:
    """4가지 증거 검색 전략(E1: PG Text, E2: PG Structured, E3: Neo4j Traversal, E4: Structured GraphRAG)을 정량 평가한다.

    평가 지표:
    - hit_at_3: 상위 3개 결과 내 정답(claim_id, fact_id, issue_id) 포함 비율
    - mrr: Mean Reciprocal Rank
    - span_traceability_rate: 결과 중 evidence_id와 span_id(또는 page_number)가 모두 추적 가능한 비율
    - invalid_claim_leak_rate: PENDING 또는 REJECTED 상태의 Claim이 결과에 노출된 비율 (목표: 0.0)
    - contradiction_detection_rate: 상충 질의에서 상충 관계(contradictions 또는 CONTRADICTS 링크)를 탐지한 비율

    Args:
        db: SQLAlchemy 세션.
        case_id: 평가 대상 사건 ID.
        benchmark_queries: 평가 질의 목록.
        driver: Neo4j 드라이버 (선택).

    Returns:
        Dict[str, Dict[str, float]]: 전략별 정량 지표 딕셔너리.
    """
    from ai_legal_helper.rag.evidence_search import search_evidence_in_postgres
    from ai_legal_helper.database.models import EvidenceClaim

    invalid_claim_ids = {
        c.id
        for c in db.query(EvidenceClaim)
        .filter(
            EvidenceClaim.case_id == case_id,
            EvidenceClaim.review_status.in_(["PENDING", "REJECTED"]),
        )
        .all()
    }

    strategies = [
        "E1_PG_TEXT",
        "E2_PG_STRUCTURED",
        "E3_NEO4J_TRAVERSAL",
        "E4_STRUCTURED_GRAPHRAG",
    ]
    report: Dict[str, Dict[str, float]] = {}

    for strat in strategies:
        hits_at_3 = 0
        rr_sum = 0.0
        total_items = 0
        traceable_items = 0
        leaked_items = 0
        contra_expected = 0
        contra_detected = 0

        for q_item in benchmark_queries:
            q_text = q_item["query"]
            exp_claim = q_item.get("expected_claim_id")
            exp_fact = q_item.get("expected_fact_id")
            exp_issue = q_item.get("expected_issue_id")
            exp_contra = bool(q_item.get("expects_contradiction", False))

            items: List[Dict[str, Any]] = []
            has_contra = False

            if strat == "E1_PG_TEXT":
                res = search_evidence_in_postgres(db, case_id, q_text, strategy="text", top_k=10)
                items = [h.model_dump() for h in res.hits]
                has_contra = any(
                    i.get("link_type") == "CONTRADICTS" or i.get("assertion_status") == "CONTRADICTION_CANDIDATE"
                    for i in items
                )
            elif strat == "E2_PG_STRUCTURED":
                res = search_evidence_in_postgres(db, case_id, q_text, strategy="structured", top_k=10)
                items = [h.model_dump() for h in res.hits]
                has_contra = any(
                    i.get("link_type") == "CONTRADICTS" or i.get("assertion_status") == "CONTRADICTION_CANDIDATE"
                    for i in items
                )
            elif strat == "E3_NEO4J_TRAVERSAL":
                retriever = GraphRAGRetriever(driver)
                paths = retriever.search_traversal(case_id, query=q_text) if driver else []
                checked = validate_graph_paths(db, case_id, paths) if paths else {"valid": []}
                items = checked["valid"]
                contras = retriever.find_contradictions(case_id) if driver else []
                has_contra = bool(contras) or any(i.get("relation") == "CONTRADICTS" for i in items)
            elif strat == "E4_STRUCTURED_GRAPHRAG":
                ev_res = retrieve_structured_evidence(db, case_id, q_text, driver=driver)
                # E4 combines validated graph paths (enriched with PG metadata) + PG structured matches
                items = list(ev_res.graph_paths) + list(ev_res.structured_matches)
                has_contra = bool(ev_res.contradictions) or any(
                    i.get("relation") == "CONTRADICTS"
                    or i.get("link_type") == "CONTRADICTS"
                    or i.get("assertion_status") == "CONTRADICTION_CANDIDATE"
                    for i in items
                )

            # Evaluate rank of expected target
            matched_rank = None
            for idx, item in enumerate(items, start=1):
                c_id = item.get("claim_id")
                f_id = item.get("fact_id") or item.get("via_fact_id") or (
                    item.get("target_id") if item.get("target_type") == "Fact" else None
                )
                iss_id = item.get("issue_id") or (
                    item.get("target_id") if item.get("target_type") == "LegalIssue" else None
                )
                if (
                    (exp_claim and c_id == exp_claim)
                    or (exp_fact and f_id == exp_fact)
                    or (exp_issue and iss_id == exp_issue)
                ):
                    matched_rank = idx
                    break

            if matched_rank is not None:
                if matched_rank <= 3:
                    hits_at_3 += 1
                rr_sum += 1.0 / matched_rank

            for item in items:
                total_items += 1
                if item.get("evidence_id") and (item.get("span_id") or item.get("page_number") is not None):
                    traceable_items += 1
                if item.get("claim_id") in invalid_claim_ids:
                    leaked_items += 1

            if exp_contra:
                contra_expected += 1
                if has_contra:
                    contra_detected += 1

        n_q = max(len(benchmark_queries), 1)
        report[strat] = {
            "hit_at_3": round(hits_at_3 / n_q, 4),
            "mrr": round(rr_sum / n_q, 4),
            "span_traceability_rate": round(traceable_items / total_items, 4) if total_items > 0 else 0.0,
            "invalid_claim_leak_rate": round(leaked_items / total_items, 4) if total_items > 0 else 0.0,
            "contradiction_detection_rate": round(contra_detected / contra_expected, 4) if contra_expected > 0 else 1.0,
            "avg_results_count": round(total_items / n_q, 2),
        }

    return report
