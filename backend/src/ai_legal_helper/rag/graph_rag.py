# -*- coding: utf-8 -*-
"""
모듈명: graph_rag.py

[모듈 개요]
Neo4j 사건 Knowledge Graph 위에서 Evidence GraphRAG 검색을 수행한다.
법령 RAG(ChromaDB)를 대체하지 않고, '사건 증거 맥락'을 보강하는 보조 검색기이다.

[주요 기능]
1. Baseline 검색   : 질문 키워드와 노드 텍스트의 단순 매칭
2. Traversal 검색  : 쟁점/사실 → 근거 Claim → 원문 Span → 증거 문서 경로 탐색
3. Hybrid 검색     : Baseline 결과를 시드로 Traversal 확장 + 증거 공백·상충 분석
4. 증거 공백 탐지  : 승인된 근거가 연결되지 않은 Fact/LegalIssue
5. 상충 탐지       : CONTRADICTS 관계
6. UI용 사건 그래프 조회 (노드/엣지 목록)
7. 그래프 경로의 코드 레벨 검증 (PostgreSQL 실존·상태·사건 일치)

[처리 흐름]
질문 → extract_keywords → Baseline(시드) → Traversal(경로) → gaps/contradictions
     → validate_graph_paths(PostgreSQL 대조) → Supervisor 컨텍스트

[주요 의존성]
- neo4j Driver
- SQLAlchemy 세션 (검증 단계)

[주의사항]
- 모든 Cypher는 $case_id 조건을 포함한다. 다른 사건 데이터 노출을 막는 핵심 장치이다.
- 사용자 입력은 항상 파라미터로 전달하며 Cypher 문자열에 삽입하지 않는다(인젝션 방지).
- 그래프 경로는 '증거 간 연결 관계'일 뿐 법률적 사실의 증명이 아니다.
  결과에는 항상 evidence_id/span_id/claim_id 를 포함하여 원본 추적이 가능해야 한다.
- 승인되지 않은(PENDING) Claim은 근거로 반환하지 않는다.
"""

import re
import logging
from typing import Any, Dict, List, Optional

from ai_legal_helper.observability.decorators import trace

logger = logging.getLogger(__name__)

# 근거로 인정하는 Claim 검토 상태 (graph_sync 와 동일 정책)
_APPROVED = ["APPROVED", "EDITED"]

# 키워드 추출 시 제외할 한국어 기능어/일반어. 매칭 노이즈를 줄이기 위한 최소 목록이다.
_STOPWORDS = {
    "그리고", "그런데", "하지만", "어떻게", "무엇", "있나요", "있습니까", "합니까", "해야",
    "하나요", "인가요", "되나요", "경우", "관련", "대해", "대한", "제가", "저는", "우리",
    "이번", "지금", "혹시", "정말", "가능", "방법", "문제", "사건", "질문",
}
# 흔한 조사 어미. 토큰 끝에서 제거하여 '보증금을' → '보증금' 으로 정규화한다.
_JOSA = re.compile(r"(으로|에서|에게|까지|부터|이나|이랑|하고|은|는|이|가|을|를|에|의|도|만|로|와|과)$")


def extract_keywords(query: str, max_keywords: int = 8) -> List[str]:
    """질문에서 그래프 매칭용 키워드를 추출한다.

    형태소 분석기를 도입하지 않고(신규 의존성 최소화) 공백 분리 + 조사 제거 + 불용어 제거로
    처리한다. 질문 전체 문자열을 CONTAINS 로 비교하면 거의 매칭되지 않기 때문에 필요하다.

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


class GraphRAGRetriever:
    """사건 Knowledge Graph 검색기.

    Attributes:
        driver: Neo4j Driver. None 이면 모든 검색이 빈 결과를 반환한다(Fallback).
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

    # ------------------------------------------------------------------ 전략 1
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
              // 승인되지 않은 Claim 은 근거 후보에서 제외한다
              AND (NOT n:EvidenceClaim OR n.review_status IN $approved)
            RETURN labels(n)[0] AS node_type, n.id AS node_id,
                   coalesce(n.statement, n.title, n.text_excerpt) AS content, score
            ORDER BY score DESC LIMIT $limit
        """, case_id=case_id, kws=kws, approved=_APPROVED, limit=limit)

    # ------------------------------------------------------------------ 전략 2
    @trace
    def search_traversal(self, case_id: str, query: Optional[str] = None,
                         seed_ids: Optional[List[str]] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """대상(Fact/Event/LegalIssue)에서 근거 원문까지의 경로를 탐색한다.

        탐색 경로:
          (Span)-[:SUPPORTS]->(Claim)-[:SUPPORTS|CONTRADICTS]->(Fact|Event)  (직접)
          (Span)-[:SUPPORTS]->(Claim)-[:SUPPORTS|CONTRADICTS]->(Fact)-[:RELATED_TO]->(LegalIssue)  (쟁점 경유)

        Args:
            case_id: 사건 ID.
            query: 대상 노드 키워드 필터(선택).
            seed_ids: Baseline 결과 노드 ID. 주어지면 해당 노드에서 출발/도착하는 경로만 반환.
            limit: 최대 경로 수.

        Returns:
            [{target_type, target_id, target_content, relation, claim_id, claim_statement,
              review_status, evidence_id, span_id, evidence_text, filename, via_fact_id}]
        """
        kws = extract_keywords(query or "")
        if not kws and not seed_ids:
            return []
        return self._run("""
            MATCH (d:EvidenceDocument {case_id: $case_id})-[:HAS_CLAIM]->(cl:EvidenceClaim)
                  -[rel:SUPPORTS|CONTRADICTS]->(t)
            WHERE cl.review_status IN $approved AND (t:Fact OR t:Event OR t:LegalIssue)
            OPTIONAL MATCH (t)-[:RELATED_TO]->(issue:LegalIssue {case_id: $case_id})
            WITH d, cl, rel, t, issue
            UNWIND (CASE WHEN issue IS NULL THEN [null] ELSE [null, issue] END) AS via
            WITH d, cl, rel, t, via,
                 CASE WHEN via IS NULL THEN t ELSE via END AS target
            WITH d, cl, rel, t, via, target,
                 toLower(coalesce(target.statement,'') + ' ' + coalesce(target.title,'') + ' ' +
                         coalesce(target.description,'') + ' ' + coalesce(cl.statement,'')) AS txt
            WHERE ($seed_ids IS NOT NULL AND (target.id IN $seed_ids OR cl.id IN $seed_ids OR t.id IN $seed_ids))
               OR (size($kws) > 0 AND any(k IN $kws WHERE txt CONTAINS k))
            OPTIONAL MATCH (s:EvidenceSpan)-[:SUPPORTS]->(cl)
            RETURN DISTINCT labels(target)[0] AS target_type, target.id AS target_id,
                   coalesce(target.statement, target.title) AS target_content,
                   type(rel) AS relation, cl.id AS claim_id, cl.statement AS claim_statement,
                   cl.review_status AS review_status, d.id AS evidence_id, d.filename AS filename,
                   s.id AS span_id, s.text_excerpt AS evidence_text,
                   CASE WHEN via IS NULL THEN null ELSE t.id END AS via_fact_id
            LIMIT $limit
        """, case_id=case_id, approved=_APPROVED, kws=kws, seed_ids=seed_ids, limit=limit)

    # ------------------------------------------------------------------ 분석
    def find_evidence_gaps(self, case_id: str) -> List[Dict[str, Any]]:
        """승인된 근거가 연결되지 않은 쟁점/사실(증거 공백)을 찾는다.

        - LegalIssue: 연결된 Fact 중 어느 것도 승인 Claim의 SUPPORTS 를 받지 못한 경우
        - Fact: 사용자 진술(USER_CLAIM) 등으로 생성되어 증거 SUPPORTS 가 없는 경우
        """
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
        """CONTRADICTS 관계와, 같은 대상에 대한 SUPPORTS 근거를 함께 반환한다."""
        return self._run("""
            MATCH (src)-[:CONTRADICTS]->(t {case_id: $case_id})
            OPTIONAL MATCH (sup:EvidenceClaim)-[:SUPPORTS]->(t)
            WHERE sup.review_status IN $approved
            RETURN labels(t)[0] AS target_type, t.id AS target_id,
                   coalesce(t.statement, t.title) AS target_content,
                   src.id AS contradicting_id, labels(src)[0] AS contradicting_type,
                   collect(DISTINCT sup.id) AS supporting_claim_ids
            LIMIT 30
        """, case_id=case_id, approved=_APPROVED)

    # ------------------------------------------------------------------ 전략 3
    @trace
    def search_vector(self, case_id: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """ChromaDB를 이용해 증거/사실에 대한 벡터 검색을 수행한다.
        
        Args:
            case_id: 사건 ID.
            query: 사용자 질문.
            limit: 최대 결과 수.
            
        Returns:
            [{node_type, node_id, content, score}]
        """
        try:
            from ai_legal_helper.rag.evidence_vector import retrieve_evidence_vector
            docs = retrieve_evidence_vector(case_id, query, k=limit)
            results = []
            for i, doc in enumerate(docs):
                results.append({
                    "node_type": doc.metadata.get("node_type", "Unknown"),
                    "node_id": doc.metadata.get("node_id"),
                    "content": doc.page_content,
                    "score": limit - i  # 우선순위 역순 부여
                })
            return results
        except Exception as e:
            logger.error(f"[GRAPH_RAG] Vector search failed: {e}")
            return []

    @trace
    def search_hybrid(self, case_id: str, query: str) -> Dict[str, Any]:
        """Vector 검색 결과를 시드로 Traversal 확장 + 공백/상충 분석을 결합한다.

        Graph DB 사용이 불가능할 경우(Fallback), Vector 검색 결과만 반환한다.
        """
        # 1. Vector 검색으로 시드 후보 추출
        vector_results = self.search_vector(case_id, query)
        seeds = [v["node_id"] for v in vector_results if v.get("node_id")] or None
        
        # 2. Graph DB Fallback 검사
        if self.driver is None:
            try: update_span(get_current_span_id(), {"fallback": True, "vector_matches_count": len(vector_results)})
            except: pass
            return {
                "strategy": "hybrid_fallback",
                "available": False,
                "keywords": extract_keywords(query),
                "baseline_matches": [],
                "vector_matches": vector_results,
                "traversal_paths": [],
                "evidence_gaps": [],
                "contradictions": []
            }
            
        # 3. 그래프 탐색
        traversal = self.search_traversal(case_id, query=query, seed_ids=seeds)
        
        try: update_span(get_current_span_id(), {"fallback": False, "vector_matches_count": len(vector_results), "traversal_paths_count": len(traversal)})
        except: pass
        return {
            "strategy": "hybrid",
            "available": True,
            "keywords": extract_keywords(query),
            "baseline_matches": [],
            "vector_matches": vector_results,
            "traversal_paths": traversal,
            "evidence_gaps": self.find_evidence_gaps(case_id),
            "contradictions": self.find_contradictions(case_id),
        }

    # ------------------------------------------------------------------ UI
    def get_case_graph(self, case_id: str, include_pending: bool = False) -> Dict[str, Any]:
        """React Evidence Graph 탭용 노드/엣지 목록을 반환한다.

        Args:
            case_id: 사건 ID.
            include_pending: True 면 미승인 Claim 도 포함(UI에서 '검토 대기'로 표시).
        """
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
    """그래프 경로를 PostgreSQL(Source of Truth)과 대조하여 코드 레벨로 검증한다.

    Neo4j 는 파생 저장소이므로 동기화 지연으로 이미 삭제·반려된 근거가 남아 있을 수 있다.
    LLM 에 전달하거나 사용자에게 보여주기 전에 다음을 확인한다.

    검증 항목:
      1. claim_id 가 존재하고 동일 case_id 에 속하는가
      2. claim 이 APPROVED/EDITED 상태인가
      3. evidence_id 가 존재하고 claim 의 문서와 일치하는가
      4. span_id 가 있다면 해당 evidence 문서에 속하는가
      5. target(Fact/Event/LegalIssue)이 동일 사건에 존재하는가

    Args:
        db: SQLAlchemy 세션.
        case_id: 사건 ID.
        paths: search_traversal() 결과.

    Returns:
        {"valid": [...], "invalid": [{"path":..., "reasons":[...]}], "checked": n}
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

        if p.get("span_id"):
            span = db.get(EvidenceSpan, p["span_id"])
            if span is None or span.evidence_id != p.get("evidence_id"):
                reasons.append("SPAN_NOT_FOUND")

        model = target_models.get(p.get("target_type"))
        target = db.get(model, p.get("target_id")) if model and p.get("target_id") else None
        if target is None or target.case_id != case_id:
            reasons.append("TARGET_NOT_FOUND")

        (invalid if reasons else valid).append(p if not reasons else {"path": p, "reasons": reasons})

    return {"valid": valid, "invalid": invalid, "checked": len(paths)}


def format_graph_context(result: Dict[str, Any], valid_paths: List[Dict[str, Any]]) -> str:
    """검증된 GraphRAG 결과를 Supervisor 프롬프트용 텍스트로 변환한다.

    각 항목에 [GRAPH:span_id 또는 claim_id] 형태의 출처 ID 를 붙여
    Verification Agent 가 근거를 추적할 수 있게 한다.
    """
    if not result.get("available") and not result.get("vector_matches"):
        return ""
        
    lines: List[str] = []
    
    # Fallback 처리: 그래프가 가용하지 않지만 벡터 매치는 있는 경우
    if not result.get("available") and result.get("vector_matches"):
        lines.append("[증거 관련 문서 (Graph DB 장애로 인한 의미 기반 검색 Fallback)]")
        for v in result.get("vector_matches", [])[:10]:
            lines.append(f"- {v.get('node_type')}: {v.get('content')}")
        return "\n".join(lines)
        
    if valid_paths:
        lines.append("[증거 그래프 경로 (Evidence GraphRAG) — 연결 관계이며 법률적 증명이 아님]")
        for p in valid_paths[:10]:
            sid = p.get("span_id") or p.get("claim_id")
            excerpt = (p.get("evidence_text") or p.get("claim_statement") or "")[:80]
            lines.append(
                f"- [GRAPH:{sid}] 증거({p.get('filename') or p.get('evidence_id')}) '{excerpt}' "
                f"-{p.get('relation')}-> {p.get('target_type')}: {p.get('target_content')}"
            )
    gaps = result.get("evidence_gaps") or []
    if gaps:
        lines.append("\n[증거 공백 — 승인된 증거가 연결되지 않은 항목]")
        lines += [f"- {g['node_type']}: {g['content']}" for g in gaps[:10]]
    contra = result.get("contradictions") or []
    if contra:
        lines.append("\n[상충 증거 — 반박 관계가 존재하는 항목]")
        lines += [f"- {c['target_type']}: {c['target_content']}" for c in contra[:10]]
    return "\n".join(lines)


def graph_paths_to_sources(valid_paths: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """검증된 그래프 경로를 Verification Agent 의 출처 형식으로 변환한다."""
    return [{
        "source_id": f"GRAPH:{p.get('span_id') or p.get('claim_id')}",
        "category": "EVIDENCE_GRAPH",
        "content": f"{p.get('claim_statement')} -{p.get('relation')}-> {p.get('target_content')}",
        "evidence_id": p.get("evidence_id"),
        "span_id": p.get("span_id"),
        "claim_id": p.get("claim_id"),
    } for p in valid_paths]
