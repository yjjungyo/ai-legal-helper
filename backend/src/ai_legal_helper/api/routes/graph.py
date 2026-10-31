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


def _validated_graph_contradictions(case: Case, db: Session) -> list[dict]:
    """PostgreSQL 원본과 현재 상충 판정기를 대조한 실제 Fact 상충만 그래프 UI에 전달한다.

    오래된 Neo4j CONTRADICTS 엣지나 과거 오탐 EvidenceLink를 그대로 신뢰하지 않는다.
    검증된 쌍만 반환하므로 패널과 연결선이 같은 판정 결과를 공유한다.
    """
    from ai_legal_helper.api.routes.evidence import get_evidence_conflicts
    from ai_legal_helper.observability.logging_config import get_logger

    logger = get_logger(__name__)
    verified = get_evidence_conflicts(case=case, db=db).get("contradictions", [])
    items = []
    for conflict in verified:
        # EVENT/LEGAL_ISSUE 등은 현재 Fact 비교 엔진으로 검증되지 않으므로
        # 기존 링크 타입만으로 확정 상충으로 표시하지 않는다.
        if str(conflict.get("target_type", "")).upper() != "FACT":
            continue
        claim_id = conflict.get("claim_id")
        fact_id = conflict.get("target_id")
        if not claim_id or not fact_id:
            continue
        items.append({
            "target_type": "Fact",
            "target_id": fact_id,
            "target_content": conflict.get("target_description") or "",
            "contradicting_id": claim_id,
            "contradicting_type": "EvidenceClaim",
            "contradicting_statement": conflict.get("claim_statement") or "",
            "supporting_claim_ids": [],
            "reason_code": conflict.get("reason_code"),
            "explanation": conflict.get("explanation"),
        })
    logger.info(
        "[GRAPH_CONFLICT_AUDIT] 사건 상충 그래프 재검증: 조회=%d건, 실제 Fact 모순=%d건, 제외=%d건",
        len(verified), len(items), len(verified) - len(items),
    )
    return items


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
    graph = GraphRAGRetriever(driver).get_case_graph(case.id, include_pending)
    confirmed = _validated_graph_contradictions(case, db)
    confirmed_pairs = {(item["contradicting_id"], item["target_id"]) for item in confirmed}
    # 시각화용 엣지 역시 현재 원본 사실과 재대조해야 한다.
    graph["edges"] = [
        edge for edge in graph.get("edges", [])
        if edge.get("type") != "CONTRADICTS"
        or (edge.get("source"), edge.get("target")) in confirmed_pairs
    ]
    return {"available": True, **graph}


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
    confirmed = _validated_graph_contradictions(case, db)
    if driver is None:
        pg_gaps, _ = r._find_pg_gaps_and_contradictions(db, case.id)
        return {"available": False, "evidence_gaps": pg_gaps, "contradictions": confirmed}
    return {
        "available": True,
        "evidence_gaps": r.find_evidence_gaps(case.id),
        "contradictions": confirmed,
    }
