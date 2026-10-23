# -*- coding: utf-8 -*-
"""
모듈명: graph_sync.py

[모듈 개요]
PostgreSQL(Source of Truth)에 저장된 사건·증거 데이터를 Neo4j Knowledge Graph로
투영(projection)하는 동기화 파이프라인을 구현한다.

[주요 기능]
1. 사건 단위(case_id) 스냅샷 수집 (PostgreSQL → 순수 dict)
2. 사건 서브그래프 재구축 (단일 쓰기 트랜잭션: 기존 삭제 → 재생성)
3. 사건 서브그래프 삭제
4. 백그라운드 작업용 안전 동기화 래퍼(예외 비전파)

[처리 흐름]
증거 승인/반려/업로드, 사실 추가 등 변경 발생
  → safe_sync_case(case_id)
  → collect_case_snapshot()   : PostgreSQL 조회
  → write_case_snapshot()     : Neo4j 트랜잭션
       ├ MATCH (n {case_id}) DETACH DELETE n
       └ UNWIND 배치로 노드·관계 MERGE

[설계 의도]
- '사건 단위 전체 재구축' 방식을 택했다. 증분 MERGE만으로는 PostgreSQL에서 삭제되거나
  REJECTED로 바뀐 관계가 그래프에 남는 문제(stale edge)가 생기기 때문이다.
  하나의 트랜잭션에서 삭제와 생성을 수행하므로 동일 입력에 대해 항상 같은 그래프가
  만들어진다(멱등성). 사건당 노드 수가 수백 개 수준이므로 비용은 무시할 만하다.
- 모든 노드에 case_id 속성을 기록하여 검색 시 사건 격리를 Cypher 레벨에서 강제한다.

[주요 의존성]
- SQLAlchemy ORM 모델 (ai_legal_helper.database.models)
- neo4j Driver (ai_legal_helper.database.neo4j)

[주의사항]
- 개인정보 최소 복제: 증거 원문 Span은 최대 _MAX_EXCERPT 글자까지만 복제하고,
  파일 저장 경로(safe_storage_key)·해시·사건 설명 원문은 복제하지 않는다.
- AI 추론 관계(Span→Claim)에는 is_ai_inferred=true, Claim에는 review_status를 기록하여
  승인되지 않은 추출 결과를 확정 사실과 구분한다.
- 로그에는 ID와 건수만 남기고 진술 원문은 남기지 않는다.
"""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ai_legal_helper.database.models import (
    Case, Party, Fact, Event, LegalIssue,
    EvidenceDocument, EvidenceSpan, EvidenceClaim, EvidenceLink, EvidenceSpanClaimLink,
    LegalAction, ActionRequirement, ActionDependency
)

logger = logging.getLogger(__name__)

# 그래프에 복제하는 증거 발췌문 최대 길이 (개인정보 최소 복제 원칙)
_MAX_EXCERPT = 300

# EvidenceLink.target_type → Neo4j 레이블 매핑. 화이트리스트로 Cypher 인젝션을 차단한다.
_TARGET_LABELS = {"FACT": "Fact", "EVENT": "Event", "LEGAL_ISSUE": "LegalIssue"}

# EvidenceLink.link_type → 관계 타입 매핑. 정의되지 않은 값은 CONTEXT 로 취급한다.
_LINK_RELS = {"SUPPORTS": "SUPPORTS", "CONTRADICTS": "CONTRADICTS"}

# 사실의 근거로 인정하는 Claim 검토 상태. PENDING/REJECTED 는 근거로 쓰지 않는다.
APPROVED_REVIEW_STATUSES = ("APPROVED", "EDITED")

# safe_sync_case 가 사용할 세션 팩토리. None 이면 기본 SessionLocal(개발 DB)을 사용한다.
# 통합 테스트에서 테스트 DB 세션 팩토리로 교체하기 위한 주입 지점이다.
session_factory = None


def _truncate(text: Optional[str], limit: int = _MAX_EXCERPT) -> Optional[str]:
    """그래프 복제용으로 텍스트를 잘라낸다. None은 그대로 반환한다."""
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + "…"


def collect_case_snapshot(db: Session, case_id: str) -> Optional[Dict[str, Any]]:
    """PostgreSQL에서 사건 하나의 그래프 투영용 스냅샷을 수집한다.

    ORM 객체를 Neo4j 파라미터로 바로 넘기지 않고 순수 dict로 변환하여,
    DB 세션 수명과 Neo4j 트랜잭션을 분리하고 단위 테스트를 쉽게 한다.

    Args:
        db: SQLAlchemy 세션.
        case_id: 대상 사건 ID.

    Returns:
        노드/관계 목록을 담은 dict. 사건이 없으면 None.
        키: case, parties, facts, events, issues, documents, spans, claims,
            span_claim_links, evidence_links, issue_fact_links, event_fact_links, event_order
    """
    case = db.query(Case).filter(Case.id == case_id).first()
    if case is None:
        return None

    parties = db.query(Party).filter(Party.case_id == case_id).all()
    facts = db.query(Fact).filter(Fact.case_id == case_id).all()
    events = db.query(Event).filter(Event.case_id == case_id).all()
    issues = db.query(LegalIssue).filter(LegalIssue.case_id == case_id).all()
    docs = db.query(EvidenceDocument).filter(EvidenceDocument.case_id == case_id).all()
    doc_ids = [d.id for d in docs]

    spans: List[EvidenceSpan] = []
    links: List[EvidenceLink] = []
    if doc_ids:
        spans = db.query(EvidenceSpan).filter(EvidenceSpan.evidence_id.in_(doc_ids)).all()
        links = db.query(EvidenceLink).filter(EvidenceLink.evidence_id.in_(doc_ids)).all()
    claims = db.query(EvidenceClaim).filter(EvidenceClaim.case_id == case_id).all()

    span_ids = {s.id for s in spans}
    claim_ids = {c.id for c in claims}
    scl: List[EvidenceSpanClaimLink] = []
    if span_ids and claim_ids:
        scl = db.query(EvidenceSpanClaimLink).filter(
            EvidenceSpanClaimLink.claim_id.in_(claim_ids)
        ).all()
        # 다른 사건의 Span을 가리키는 비정상 링크는 사건 격리를 위해 제외한다.
        scl = [l for l in scl if l.span_id in span_ids]

    fact_ids = {f.id for f in facts}
    claim_status = {c.id: c.review_status for c in claims}

    # LegalIssue.related_fact_ids(JSON) → Fact-[:RELATED_TO]->LegalIssue
    issue_fact_links = [
        {"fact_id": fid, "issue_id": i.id}
        for i in issues for fid in (i.related_fact_ids or []) if fid in fact_ids
    ]
    # Event.related_fact_ids(JSON) → Event-[:RELATED_TO]->Fact
    event_fact_links = [
        {"fact_id": fid, "event_id": e.id}
        for e in events for fid in (e.related_fact_ids or []) if fid in fact_ids
    ]
    # 날짜가 있는 이벤트만 정렬하여 인접 쌍에 OCCURRED_BEFORE 를 만든다.
    # 날짜 미상 이벤트는 순서를 단정할 수 없으므로 시간 관계를 만들지 않는다.
    dated = sorted([e for e in events if e.event_date], key=lambda e: e.event_date)
    event_order = [
        {"before": a.id, "after": b.id} for a, b in zip(dated, dated[1:])
        if a.event_date < b.event_date
    ]

    # EvidenceLink 를 관계 타입·대상 레이블별로 정규화한다.
    evidence_links = []
    for l in links:
        label = _TARGET_LABELS.get(l.target_type)
        if label is None:
            continue
        # 확정된 관계(SUPPORTS, CONTRADICTS)만 Neo4j 엣지로 투영한다 (POTENTIAL_CONFLICT는 PostgreSQL에서 관리).
        if l.link_type not in _LINK_RELS:
            continue
        # Claim 기반 링크인데 Claim이 승인되지 않았다면 근거 관계로 투영하지 않는다(원칙 6).
        if l.claim_id and claim_status.get(l.claim_id) not in APPROVED_REVIEW_STATUSES:
            continue
        evidence_links.append({
            "link_id": l.id,
            "source_kind": "EvidenceClaim" if l.claim_id else "EvidenceSpan",
            "source_id": l.claim_id or l.span_id,
            "target_label": label,
            "target_id": l.target_id,
            "rel": _LINK_RELS[l.link_type],
            "evidence_id": l.evidence_id,
            "span_id": l.span_id,
        })

    actions = db.query(LegalAction).filter(LegalAction.case_id == case_id).all()
    action_ids = {a.id for a in actions}
    action_reqs = []
    action_deps = []
    if action_ids:
        action_reqs = db.query(ActionRequirement).filter(ActionRequirement.action_id.in_(action_ids)).all()
        action_deps = db.query(ActionDependency).filter(ActionDependency.action_id.in_(action_ids)).all()

    return {
        "case": {"id": case.id, "title": case.title, "case_type": case.case_type,
                 "status": case.status, "version": case.version},
        "parties": [{"id": p.id, "name": p.name, "role": p.role} for p in parties],
        "facts": [{"id": f.id, "statement": f.statement, "fact_type": f.fact_type,
                   "occurred_at": f.occurred_at, "source_type": f.source_type,
                   "verification_status": f.verification_status,
                   "source_evidence_id": f.source_ref if f.source_type == "DOCUMENT_SUPPORTED" else None}
                  for f in facts],
        "events": [{"id": e.id, "title": e.title, "event_date": e.event_date,
                    "date_precision": e.date_precision, "event_type": e.event_type} for e in events],
        "issues": [{"id": i.id, "title": i.title, "description": _truncate(i.description),
                    "status": i.status} for i in issues],
        "documents": [{"id": d.id, "filename": d.original_filename, "media_type": d.media_type,
                       "status": d.status, "source_kind": d.source_kind} for d in docs],
        "spans": [{"id": s.id, "evidence_id": s.evidence_id, "text_excerpt": _truncate(s.text_excerpt),
                   "page_number": s.page_number, "paragraph_index": s.paragraph_index,
                   "location_quality": s.location_quality} for s in spans],
        "claims": [{"id": c.id, "evidence_id": c.evidence_id, "statement": c.statement,
                    "claim_type": c.claim_type, "subject_key": c.subject_key,
                    "predicate_key": c.predicate_key, "scope": c.scope,
                    "temporal_context": c.temporal_context, "assertion_status": c.assertion_status,
                    "review_status": c.review_status, "confidence": c.confidence} for c in claims],
        "span_claim_links": [{"span_id": l.span_id, "claim_id": l.claim_id} for l in scl],
        "evidence_links": evidence_links,
        "issue_fact_links": issue_fact_links,
        "event_fact_links": event_fact_links,
        "event_order": event_order,
        "actions": [{"id": a.id, "title": a.title, "action_type": a.action_type, "status": a.status, "priority": a.priority} for a in actions],
        "action_reqs": [{"id": ar.id, "action_id": ar.action_id, "requirement_type": ar.requirement_type, "satisfaction_status": ar.satisfaction_status, "supporting_evidence_ids": ar.supporting_evidence_ids or []} for ar in action_reqs],
        "action_deps": [{"id": ad.id, "action_id": ad.action_id, "depends_on_action_id": ad.depends_on_action_id, "dependency_type": ad.dependency_type} for ad in action_deps],
    }


def _write_snapshot_tx(tx, snap: Dict[str, Any]) -> Dict[str, int]:
    """단일 트랜잭션 안에서 사건 서브그래프를 삭제 후 재생성한다.

    Args:
        tx: Neo4j ManagedTransaction.
        snap: collect_case_snapshot() 결과.

    Returns:
        생성된 노드 수 등 간단한 통계.
    """
    cid = snap["case"]["id"]
    # 1) 기존 사건 서브그래프 제거 — case_id 범위로만 삭제하므로 다른 사건에 영향 없음
    tx.run("MATCH (n {case_id: $cid}) DETACH DELETE n", cid=cid)

    # 2) Case 루트 노드
    tx.run("""
        MERGE (c:Case {id: $c.id})
        SET c += $c, c.case_id = $c.id, c.synced_at = datetime()
    """, c=snap["case"])

    # 3) 사건 소속 노드들 — (레이블, 데이터키, Case 관계) 순으로 동일 패턴 적용
    for label, key, rel in (
        ("Party", "parties", "INVOLVES_PARTY"),
        ("Fact", "facts", "HAS_FACT"),
        ("Event", "events", "HAS_EVENT"),
        ("LegalIssue", "issues", "HAS_ISSUE"),
        ("EvidenceDocument", "documents", "HAS_EVIDENCE"),
        ("LegalAction", "actions", "RECOMMENDS_ACTION"),
    ):
        # label/rel 은 위 상수 튜플에서만 오므로 f-string 삽입이 안전하다.
        tx.run(f"""
            MATCH (c:Case {{id: $cid}})
            UNWIND $rows AS row
            MERGE (n:{label} {{id: row.id}})
            SET n += row, n.case_id = $cid
            MERGE (c)-[:{rel}]->(n)
        """, cid=cid, rows=snap[key])

    # 4) 증거 문서 하위 노드
    tx.run("""
        UNWIND $rows AS row
        MATCH (d:EvidenceDocument {id: row.evidence_id})
        MERGE (s:EvidenceSpan {id: row.id})
        SET s += row, s.case_id = $cid
        MERGE (d)-[:CONTAINS_SPAN]->(s)
    """, cid=cid, rows=snap["spans"])
    tx.run("""
        UNWIND $rows AS row
        MATCH (d:EvidenceDocument {id: row.evidence_id})
        MERGE (cl:EvidenceClaim {id: row.id})
        SET cl += row, cl.case_id = $cid
        MERGE (d)-[r:HAS_CLAIM]->(cl)
        SET r.review_status = row.review_status
    """, cid=cid, rows=snap["claims"])

    # 5) Span → Claim : AI 추출기가 제안한 근거 관계이므로 is_ai_inferred 표시
    tx.run("""
        UNWIND $rows AS row
        MATCH (s:EvidenceSpan {id: row.span_id}), (cl:EvidenceClaim {id: row.claim_id})
        MERGE (s)-[r:SUPPORTS]->(cl)
        SET r.is_ai_inferred = true, r.review_status = cl.review_status
    """, rows=snap["span_claim_links"])

    # 6) Claim/Span → Fact/Event/LegalIssue : 사용자 승인으로 확정된 근거 관계
    for link in snap["evidence_links"]:
        tx.run(f"""
            MATCH (src:{link['source_kind']} {{id: $sid, case_id: $cid}})
            MATCH (t:{link['target_label']} {{id: $tid, case_id: $cid}})
            MERGE (src)-[r:{link['rel']}]->(t)
            SET r.link_id = $lid, r.evidence_id = $eid, r.is_ai_inferred = false
        """, sid=link["source_id"], tid=link["target_id"], cid=cid,
             lid=link["link_id"], eid=link["evidence_id"])

    # 7) 사실-쟁점, 이벤트-사실, 이벤트 시간 순서
    tx.run("""
        UNWIND $rows AS row
        MATCH (f:Fact {id: row.fact_id}), (i:LegalIssue {id: row.issue_id})
        MERGE (f)-[:RELATED_TO]->(i)
    """, rows=snap["issue_fact_links"])
    tx.run("""
        UNWIND $rows AS row
        MATCH (e:Event {id: row.event_id}), (f:Fact {id: row.fact_id})
        MERGE (e)-[:RELATED_TO]->(f)
    """, rows=snap["event_fact_links"])
    tx.run("""
        UNWIND $rows AS row
        MATCH (a:Event {id: row.before}), (b:Event {id: row.after})
        MERGE (a)-[:OCCURRED_BEFORE]->(b)
    """, rows=snap["event_order"])

    # 8) Action 관련 관계
    tx.run("""
        UNWIND $rows AS row
        MATCH (a:LegalAction {id: row.action_id})
        MERGE (ar:ActionRequirement {id: row.id})
        SET ar += row, ar.case_id = $cid
        MERGE (a)-[:HAS_REQUIREMENT]->(ar)
    """, cid=cid, rows=snap["action_reqs"])

    tx.run("""
        UNWIND $rows AS row
        MATCH (a:LegalAction {id: row.action_id}), (dep:LegalAction {id: row.depends_on_action_id})
        MERGE (a)-[:DEPENDS_ON_ACTION {type: row.dependency_type}]->(dep)
    """, rows=snap["action_deps"])
    
    tx.run("""
        UNWIND $rows AS row
        MATCH (ar:ActionRequirement {id: row.id})
        UNWIND row.supporting_evidence_ids AS ev_id
        MATCH (c:EvidenceClaim {id: ev_id})
        MERGE (ar)-[:REQUIRES_EVIDENCE]->(c)
    """, rows=snap["action_reqs"])

    return {
        "nodes": 1 + sum(len(snap[k]) for k in
                         ("parties", "facts", "events", "issues", "documents", "spans", "claims", "actions", "action_reqs")),
        "evidence_links": len(snap["evidence_links"]),
    }


def sync_case_to_graph(db: Session, driver, case_id: str) -> Dict[str, Any]:
    """사건 하나를 PostgreSQL에서 Neo4j로 동기화한다(멱등).

    Args:
        db: SQLAlchemy 세션.
        driver: Neo4j Driver.
        case_id: 동기화 대상 사건 ID.

    Returns:
        {"status": "SYNCED", "nodes": n, ...} 또는 사건이 없을 때 {"status": "CASE_NOT_FOUND"}.
        PostgreSQL에서 사건이 삭제된 경우 그래프의 잔여 서브그래프도 함께 제거한다.

    Raises:
        neo4j.exceptions.* : 연결/쿼리 오류. 호출자가 Fallback 정책을 결정한다.
    """
    snap = collect_case_snapshot(db, case_id)
    if snap is None:
        delete_case_graph(driver, case_id)
        return {"status": "CASE_NOT_FOUND", "case_id": case_id}

    with driver.session() as session:
        stats = session.execute_write(_write_snapshot_tx, snap)

    logger.info(f"[GRAPH_SYNC] case={case_id} nodes={stats['nodes']} links={stats['evidence_links']}")
    return {"status": "SYNCED", "case_id": case_id, **stats}


def delete_case_graph(driver, case_id: str) -> None:
    """사건 서브그래프(Case 노드 포함)를 삭제한다."""
    with driver.session() as session:
        session.execute_write(
            lambda tx: tx.run("MATCH (n {case_id: $cid}) DETACH DELETE n", cid=case_id).consume()
        )


def safe_sync_case(case_id: str) -> Dict[str, Any]:
    """백그라운드 작업용 동기화 래퍼. 어떤 예외도 호출자에게 전파하지 않는다.

    증거 승인 등 PostgreSQL 트랜잭션은 이미 커밋된 상태에서 호출되므로,
    Graph 동기화 실패가 사용자 요청을 실패시키면 안 된다. 실패 시 상태만 반환하고,
    이후 수동 재동기화(POST /cases/{id}/graph/sync)로 복구한다.

    Returns:
        {"status": "SYNCED" | "CASE_NOT_FOUND" | "GRAPH_UNAVAILABLE" | "FAILED", ...}
    """
    from ai_legal_helper.database.neo4j import get_neo4j_driver

    driver = get_neo4j_driver()
    if driver is None:
        return {"status": "GRAPH_UNAVAILABLE", "case_id": case_id}
    if session_factory is not None:
        db = session_factory()
    else:
        from ai_legal_helper.database.session import SessionLocal
        db = SessionLocal()
    try:
        return sync_case_to_graph(db, driver, case_id)
    except Exception as e:
        logger.warning(f"[GRAPH_SYNC] case={case_id} 실패: {type(e).__name__}")
        return {"status": "FAILED", "case_id": case_id, "error": type(e).__name__}
    finally:
        db.close()
