import os
import sys
import logging
import asyncio
from datetime import date

# 환경변수 설정 (테스트 DB 및 설정)
os.environ["ENV"] = "test"

from ai_legal_helper.database.session import SessionLocal, Base, engine
from ai_legal_helper.database.models import (
    Case, Party, Fact, Event, EvidenceDocument, EvidenceSpan, EvidenceClaim, EvidenceLink
)
from ai_legal_helper.database.neo4j import get_neo4j_driver
from ai_legal_helper.database.graph_sync import sync_case_to_graph
from ai_legal_helper.rag.graph_rag import GraphRAGRetriever

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_benchmark_data(db):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # 1. 사건 생성
    case_id = "synth-case-lease-001"
    db.add(Case(id=case_id, title="주택 임대차 전세보증금 미반환", case_type="CIVIL", status="IN_PROGRESS"))
    
    # 격리용 타 사건
    case_id_2 = "synth-case-lease-002"
    db.add(Case(id=case_id_2, title="타 사건", case_type="CIVIL", status="IN_PROGRESS"))
    db.commit()

    # 2. 당사자
    db.add_all([
        Party(id="party-1", case_id=case_id, name="김임차", role="PLAINTIFF"),
        Party(id="party-2", case_id=case_id, name="박임대", role="DEFENDANT"),
    ])
    
    # 3. 사실 (Facts)
    f1 = Fact(id="f-1", case_id=case_id, statement="2021년 5월 1일 전세 계약 체결", fact_type="UNDISPUTED")
    f2 = Fact(id="f-2", case_id=case_id, statement="2023년 5월 1일 묵시적 갱신", fact_type="UNDISPUTED")
    f3 = Fact(id="f-3", case_id=case_id, statement="2024년 1월 15일 해지 통보", fact_type="PLAINTIFF_CLAIM")
    f4 = Fact(id="f-4", case_id=case_id, statement="2024년 4월 15일 해지 효력 발생", fact_type="LEGAL_CONCLUSION")
    f5 = Fact(id="f-5", case_id=case_id, statement="임대인이 5월 말 보증금 반환 약속", fact_type="PLAINTIFF_CLAIM")
    f6 = Fact(id="f-6", case_id=case_id, statement="임차인 미퇴거로 반환 불가 주장", fact_type="DEFENDANT_CLAIM")
    f7 = Fact(id="f-7", case_id=case_id, statement="퇴거 시 집을 깨끗이 사용함", fact_type="PLAINTIFF_CLAIM")
    f8 = Fact(id="f-8", case_id=case_id, statement="관리비 임의 인상 징수", fact_type="PLAINTIFF_CLAIM")
    db.add_all([f1, f2, f3, f4, f5, f6, f7, f8])
    
    # 4. 이벤트 (Events) - 시간 흐름
    e1 = Event(id="e-1", case_id=case_id, title="해지 통보 문자 발송", event_date=date(2024, 1, 15))
    e2 = Event(id="e-2", case_id=case_id, title="내용증명 발송", event_date=date(2024, 4, 20))
    db.add_all([e1, e2])
    
    # 5. 증거 문서 및 발췌 (Documents, Spans, Claims)
    # Doc 1: 문자 캡처 (상충 진술 관련)
    d1 = EvidenceDocument(id="doc-1", case_id=case_id, original_filename="통화녹취록.pdf", safe_storage_key="test-1", media_type="application/pdf", size_bytes=1000, sha256="dummy1")
    c1 = EvidenceClaim(id="c-1", case_id=case_id, evidence_id="doc-1", statement="5월 말까지 꼭 빼드릴게요", review_status="APPROVED")
    
    d2 = EvidenceDocument(id="doc-2", case_id=case_id, original_filename="카톡.png", safe_storage_key="test-2", media_type="image/png", size_bytes=1000, sha256="dummy2")
    c2 = EvidenceClaim(id="c-2", case_id=case_id, evidence_id="doc-2", statement="비밀번호 안 주면 돈 못 줘", review_status="APPROVED")
    
    # Doc 3: 퇴거 사진 (반려됨)
    d3 = EvidenceDocument(id="doc-3", case_id=case_id, original_filename="퇴거사진.jpg", safe_storage_key="test-3", media_type="image/jpeg", size_bytes=1000, sha256="dummy3")
    c3 = EvidenceClaim(id="c-3", case_id=case_id, evidence_id="doc-3", statement="방이 깨끗함", review_status="REJECTED")
    
    # Doc 4: 타 사건 증거
    d4 = EvidenceDocument(id="doc-4", case_id=case_id_2, original_filename="누수.jpg", safe_storage_key="test-4", media_type="image/jpeg", size_bytes=1000, sha256="dummy4")
    c4 = EvidenceClaim(id="c-4", case_id=case_id_2, evidence_id="doc-4", statement="천장에서 물이 샙니다", review_status="APPROVED")
    
    db.add_all([d1, c1, d2, c2, d3, c3, d4, c4])
    db.flush()
    
    # 6. Links
    # c1 SUPPORTS f5
    # c2 CONTRADICTS f5 (or SUPPORTS f6)
    db.add(EvidenceLink(id="l-1", evidence_id="doc-1", claim_id="c-1", target_type="FACT", target_id="f-5", link_type="SUPPORTS"))
    db.add(EvidenceLink(id="l-2", evidence_id="doc-2", claim_id="c-2", target_type="FACT", target_id="f-5", link_type="CONTRADICTS"))
    # c3 SUPPORTS f7 (하지만 c3가 REJECTED 이므로 연결 무효화 기대)
    db.add(EvidenceLink(id="l-3", evidence_id="doc-3", claim_id="c-3", target_type="FACT", target_id="f-7", link_type="SUPPORTS"))
    
    db.commit()
    logger.info("Benchmark data setup complete.")
    return case_id

def run_benchmark():
    db = SessionLocal()
    case_id = setup_benchmark_data(db)
    
    driver = get_neo4j_driver()
    # 그래프 동기화 실행
    sync_res = sync_case_to_graph(db, driver, case_id)
    logger.info(f"Sync result: {sync_res}")
    
    retriever = GraphRAGRetriever(driver)
    
    queries = [
        "보증금을 5월 말에 반환하겠다는 약속 증거가 있나요?",
        "관리비 인상과 관련된 증거",
        "퇴거 시 집 상태 사진",
        "누수 문제 증거",
    ]
    
    print("\n" + "="*50)
    print("GraphRAG Benchmark Results")
    print("="*50)
    
    for q in queries:
        print(f"\n[Q] {q}")
        
        # 1. Baseline
        base = retriever.search_baseline(case_id, q, limit=5)
        print("  - Baseline (Keyword Matches):")
        for b in base:
            print(f"      [{b['node_type']}] {b['content'][:50]}")
            
        # 2. Vector
        vector = retriever.search_vector(case_id, q, limit=5)
        print("  - Vector Matches:")
        for v in vector:
            print(f"      [{v['node_type']}] {v['content'][:50]}")
            
        # 3. Hybrid
        hybrid = retriever.search_hybrid(case_id, q)
        print("  - Traversal Paths:")
        for p in hybrid.get("traversal_paths", []):
            print(f"      {p['claim_statement'][:20]} -[{p['relation']}]-> {p['target_content'][:20]}")
            
    # Gaps & Contradictions
    print("\n[Analysis]")
    hybrid_empty = retriever.search_hybrid(case_id, "test")
    gaps = hybrid_empty.get("evidence_gaps", [])
    print(f"  - Evidence Gaps: {len(gaps)} items")
    for g in gaps:
         print(f"      {g['node_type']}: {g['content']}")
         
    contra = hybrid_empty.get("contradictions", [])
    print(f"  - Contradictions: {len(contra)} items")
    for c in contra:
         print(f"      {c['target_type']}: {c['target_content']} (반박 증거 존재)")

    db.close()

if __name__ == "__main__":
    run_benchmark()
