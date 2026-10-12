# P2.5 Hybrid Retrieval Architecture Design

## 1. 개요
P2.5 단계의 핵심은 기존 키워드 기반의 단순 매칭(Baseline)을 넘어, **Vector Search(ChromaDB)**와 **Graph Traversal(Neo4j)**을 결합한 하이브리드 검색을 구현하는 것입니다.

## 2. 아키텍처 결정 사항
- **Vector Store:** `ChromaDB`의 `case_evidence` 컬렉션을 사용합니다. (기존 법령 컬렉션과 논리적 분리)
- **대상 노드:** `Fact`, `Event`, `LegalIssue`, `EvidenceClaim`(APPROVED/EDITED), `EvidenceSpan`의 텍스트 프로퍼티.
- **색인 시점:** `graph_sync.py`에서 Neo4j에 그래프를 동기화할 때, 동일한 스냅샷 데이터를 바탕으로 ChromaDB에도 동기화합니다. 기존 데이터는 `where={"case_id": case_id}`로 삭제 후 일괄 삽입(Idempotent)합니다.
- **검색 흐름:**
  1. 사용자 질문을 임베딩 모델을 통해 벡터화합니다.
  2. ChromaDB에서 `case_id` 메타데이터 필터링을 적용하여 Top K 노드 ID를 추출합니다. (Vector Search)
  3. 추출된 노드 ID들을 `seed_ids`로 삼아 Neo4j의 `search_traversal`에 주입합니다. (Graph Traversal)
  4. (Neo4j 장애 시) Graph Traversal 단계를 건너뛰고 ChromaDB에서 찾은 노드 정보만으로 Fallback 컨텍스트를 구성하여 반환합니다.

## 3. 왜 Neo4j Vector Index가 아닌 ChromaDB인가?
- **Fallback 원칙:** Neo4j가 다운되더라도 기존의 RAG(벡터 기반 유사도 검색)를 통해 사건 증거를 최소한이라도 검색할 수 있어야 합니다.
- **일관성:** 이미 `law_docs`를 위해 임베딩 모델과 ChromaDB 파이프라인이 구축되어 있으므로 재사용성이 높습니다.
- **성능:** 사건 크기가 작으므로 ChromaDB 메타데이터 필터링(`case_id`)이 매우 빠르며, Neo4j는 관계(Edge) 탐색에 전념하게 함으로써 역할을 분리합니다.

## 4. 컴포넌트 간 상호작용
1. **Sync Pipeline (`graph_sync.py`):**
   - PostgreSQL에서 데이터를 읽어 Neo4j 트랜잭션 수행
   - 완료 후 `Chroma(collection="case_evidence")._collection.delete(where={"case_id": cid})`
   - `Chroma.add_texts(texts=..., metadatas=[{"case_id": cid, "node_type": ..., "node_id": ...}, ...])`
2. **Retriever (`graph_rag.py`):**
   - `search_vector`: ChromaDB 쿼리 -> `[node_id_1, node_id_2, ...]` 반환
   - `search_hybrid`: `search_vector` 결과를 `seed_ids`로 `search_traversal` 호출
   - 반환 결과 포맷팅 (`validate_graph_paths` 거침)

