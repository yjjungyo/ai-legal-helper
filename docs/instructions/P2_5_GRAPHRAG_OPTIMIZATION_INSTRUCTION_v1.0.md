# AI Legal Helper — P2.5 GraphRAG Optimization & Benchmark 개발 지시서

본 문서는 사용자의 "P2.5 GraphRAG 고도화 및 성능 검증 개발지시서 v1.0"에 따라 수행될 상세 개발 지침입니다.

## 1. 하이브리드 검색 구현 (Vector + Graph)
- **Vector Search (ChromaDB)**
  - `case_evidence` 컬렉션을 생성합니다.
  - `graph_sync.py`에서 Neo4j 스냅샷 데이터를 쓸 때, ChromaDB에도 동일한 데이터를 Upsert 합니다 (메타데이터: `case_id`, `node_id`, `node_type`).
- **GraphRAGRetriever 업데이트**
  - 기존의 키워드 기반 `search_baseline`을 `search_vector`로 대체하거나 결합합니다.
  - `search_vector` 결과를 `seed_ids`로 사용하여 `search_traversal`을 수행합니다.
  - Neo4j 장애 시, `search_vector` 결과만으로 Fallback 컨텍스트를 구성하여 반환하도록 예외 처리를 강화합니다.

## 2. 동기화 안정성 (Graph Sync Reliability)
- **Alembic 마이그레이션**
  - `graph_sync_task` 테이블을 추가합니다 (`id`, `case_id`, `status`, `retry_count`, `error_message`, `created_at`, `updated_at`).
- **Outbox 패턴 적용**
  - 사건 데이터가 변경되는 라우터(`cases.py`, `evidence.py`)에서 백그라운드 태스크 대신 DB 트랜잭션 내에 Task를 기록합니다.
  - 백그라운드 워커를 도입하여 Task 테이블을 폴링하고 동기화를 수행합니다. 실패 시 재시도 로직을 포함합니다.

## 3. 벤치마크 및 평가
- 주택 임대차 분쟁 관련 테스트 데이터셋 (`docs/evaluation/P2_5_BENCHMARK_DATASET.md`)을 구축합니다.
- Baseline RAG (Vector Only), Graph Traversal (Neo4j Only), Hybrid GraphRAG 세 가지 방식을 정량적으로 평가하고 보고서(`P2_5_BASELINE_VS_GRAPHRAG.md`, `P2_5_TEST_REPORT.md`)를 작성합니다.

## 4. 최종 보고서 작성
- `P2_5_COMPLETION_REPORT.md` 및 기술 인터뷰 대비를 위한 `P2_5_MASTER_QA.md`를 작성합니다.
- 기존 주석 표준(한글 주석)을 준수하며, 파괴적 변경을 피합니다.

