# -*- coding: utf-8 -*-
"""
모듈명: graph.py (API Route)

[모듈 개요]
P2.4 / Evidence Structured GraphRAG v2.0 조회·동기화·검색 REST 엔드포인트를 제공한다.

[주요 기능]
1. GET  /graph/health                     : Neo4j 가용성 확인
2. POST /cases/{case_id}/graph/sync       : 사건 그래프 수동 재동기화(복구용)
3. GET  /cases/{case_id}/graph            : React Evidence Graph 탭용 노드/엣지
4. GET  /cases/{case_id}/graph/search     : baseline / traversal / hybrid / text / structured 검색
5. GET  /cases/{case_id}/graph/analysis   : 증거 공백 및 상충 분석 (Neo4j 또는 PostgreSQL 폴백)

[주의사항]
- Neo4j 장애 시 503 대신 available=false 를 담은 200 응답을 반환한다.
  UI 가 '그래프 비활성' 상태를 표시하고 나머지 사건 화면은 정상 동작하게 하기 위함이다.
  단, 명시적 동기화 요청(sync)은 실패를 알 수 있도록 503 을 반환한다.
- 모든 사건 경로는 PostgreSQL 에 사건이 존재하는지 먼저 확인한다(존재하지 않는 case_id 탐색 방지).
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import Case, User, AuditLog
from ai_legal_helper.database.neo4j import get_neo4j_driver
from ai_legal_helper.database.graph_sync import sync_case_to_graph
from ai_legal_helper.rag.graph_rag import GraphRAGRetriever, validate_graph_paths
from ai_legal_helper.api.dependencies import get_current_user, get_case_for_user

router = APIRouter(tags=["graph"])


@router.get("/graph/health")
def graph_health():
    """Neo4j 연결 가능 여부를 반환한다."""
    return {"available": get_neo4j_driver() is not None}


@router.post("/cases/{case_id}/graph/sync")
def sync_graph(
    request: Request,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """사건 그래프를 PostgreSQL 기준으로 재구축한다(멱등)."""
    driver = get_neo4j_driver()
    if driver is None:
        raise HTTPException(status_code=503, detail="Graph DB unavailable")
    try:
        result = sync_case_to_graph(db, driver, case.id)

        audit = AuditLog(
            actor_user_id=current_user.id,
            event_type="SYNC_GRAPH",
            resource_type="Case",
            resource_id=case.id,
            result="SUCCESS",
        )
        db.add(audit)
        db.commit()

        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Graph sync failed: {type(e).__name__}")


@router.get("/cases/{case_id}/graph")
def get_graph(
    include_pending: bool = False,
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """UI 시각화용 사건 그래프(노드/엣지)를 반환한다."""
    driver = get_neo4j_driver()
    if driver is None:
        return {"available": False, "case_id": case.id, "nodes": [], "edges": []}
    return {"available": True, **GraphRAGRetriever(driver).get_case_graph(case.id, include_pending)}


@router.get("/cases/{case_id}/graph/search")
def search_graph(
    q: str = Query(..., min_length=1, max_length=500),
    strategy: Literal["baseline", "traversal", "hybrid", "text", "structured"] = "hybrid",
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """사건 그래프 및 구조화 증거 검색.

    traversal/hybrid 경로는 PostgreSQL 대조 검증 결과를 함께 반환하며,
    hybrid 전략은 Neo4j 미연결 시에도 PostgreSQL 기반 사건 증거 폴백 검색을 수행한다.
    """
    driver = get_neo4j_driver()
    if strategy in ("text", "structured"):
        from ai_legal_helper.rag.evidence_search import search_evidence_in_postgres
        pg_res = search_evidence_in_postgres(db, case.id, q, strategy=strategy)
        hits_dump = [h.model_dump() for h in pg_res.hits]
        return {
            "available": driver is not None,
            "strategy": strategy,
            "search_mode": "POSTGRESQL_ONLY",
            "results": hits_dump,
            "structured_matches": hits_dump,
            "invalid": [],
        }

    if driver is None and strategy not in ("hybrid", "text", "structured"):
        return {"available": False, "strategy": strategy, "results": []}

    r = GraphRAGRetriever(driver)
    if strategy == "baseline":
        return {"available": True, "strategy": strategy, "results": r.search_baseline(case.id, q)}
    if strategy == "traversal":
        paths = r.search_traversal(case.id, query=q)
        checked = validate_graph_paths(db, case.id, paths)
        return {
            "available": True,
            "strategy": strategy,
            "results": checked["valid"],
            "invalid": checked["invalid"],
        }
    result = r.search_hybrid(case.id, q, db=db)
    checked = (
        validate_graph_paths(db, case.id, result.get("traversal_paths", []))
        if result.get("traversal_paths")
        else {"valid": [], "invalid": []}
    )
    result["traversal_paths"] = checked["valid"]
    result["invalid"] = checked["invalid"]
    return result


@router.get("/cases/{case_id}/graph/analysis")
def analyze_graph(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    """증거 공백(승인 증거 미연결 사실/쟁점)과 상충 증거를 반환한다."""
    driver = get_neo4j_driver()
    r = GraphRAGRetriever(driver)
    if driver is None:
        pg_gaps, pg_contra = r._find_pg_gaps_and_contradictions(db, case.id)
        return {"available": False, "evidence_gaps": pg_gaps, "contradictions": pg_contra}
    return {
        "available": True,
        "evidence_gaps": r.find_evidence_gaps(case.id),
        "contradictions": r.find_contradictions(case.id),
    }
