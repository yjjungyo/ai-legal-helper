# P2.4 Graph Architecture & Evidence GraphRAG

## 1. 아키텍처 개요 (Architecture Overview)

이 문서는 기존 AI Legal Helper (P0~P2.3) 시스템 위에 Neo4j 기반 Knowledge Graph를 통합하는 아키텍처를 정의한다.

```text
React Frontend (Case Workspace)
        │
FastAPI (API Gateway)
        │
    [ LangGraph ]
  Supervisor ─┬─ Specialist Agents
              └─ Verification Agent
        │
        ▼
   [ Data Layer ]
   ┌────────────────────────────────┐
   │ 1. PostgreSQL (Source of Truth)│
   │    - Case, Party, Facts        │
   │    - Evidence, Span, Claim     │
   └──────────────┬─────────────────┘
                  │ (Sync / Ingestion)
   ┌──────────────▼─────────────────┐
   │ 2. Neo4j (Knowledge Graph)     │
   │    - Entities as Nodes         │
   │    - Semantic Relationships    │
   └──────────────┬─────────────────┘
                  │ (Graph Traversal & Cypher)
   ┌──────────────▼─────────────────┐
   │ 3. GraphRAG Engine             │
   │    - Baseline Chroma RAG       │
   │    - Hybrid RAG (Vector+Graph) │
   └────────────────────────────────┘
```

## 2. 주요 설계 원칙
1. **이원화된 데이터 저장소**: 
   - PostgreSQL은 모든 사건 진행 데이터의 Source of Truth이다. 증거의 메타데이터와 리뷰 상태 변경은 반드시 RDB 트랜잭션으로 처리된다.
   - Neo4j는 관계 탐색 및 GraphRAG 쿼리를 위한 읽기 위주의(파생된) 저장소로 사용된다.
2. **이벤트 기반 그래프 동기화**:
   - 데이터베이스 변경 시 (사건 생성, 증거 업로드, 검토 승인/수정/거절 시) 백그라운드 태스크나 별도 워커를 통해 Neo4j 그래프를 UPSERT 한다.
   - 멱등성(Idempotency)을 보장하여 동기화 오류 시에도 전체 사건 그래프 재구축(Rebuild)이 가능하도록 설계한다.
3. **Fallback 정책**:
   - Neo4j 컨테이너에 장애가 발생하더라도, PostgreSQL에 기반한 기본 사건 조회와 ChromaDB 기반의 법령 RAG는 정상 동작하도록 예외 처리를 둔다.

## 3. Evidence GraphRAG 전략

### 3.1. Baseline RAG
기존 ChromaDB의 임베딩 기반 검색. 법령, 조문, 판례 등 고정된 지식 검색에 강점이 있다.

### 3.2. Graph Traversal (Cypher)
Neo4j에 구축된 `EvidenceSpan` ↔ `EvidenceClaim` ↔ `Fact` ↔ `LegalIssue` 간의 명시적 관계를 탐색한다.
- 쟁점 누락 탐지: `MATCH (i:LegalIssue) WHERE NOT (i)<-[:SUPPORTS]-(:EvidenceClaim) RETURN i`
- 상충 증거 탐지: `MATCH (c1:EvidenceClaim)-[:SUPPORTS]->(f:Fact)<-[:CONTRADICTS]-(c2:EvidenceClaim) RETURN c1, c2`

### 3.3. Hybrid GraphRAG
사용자의 복잡한 쿼리에 대해, 먼저 벡터 기반 검색으로 유망한 노드(엔터티)를 찾고, 해당 노드를 시작점으로 Graph Traversal을 수행하여 컨텍스트를 수집한다.
수집된 경로는 구조화된 텍스트로 변환되어 LangGraph Supervisor 및 Specialist Agent에 제공된다.

## 4. Verification Agent 확장
기존 Verification Agent는 생성된 답변에 대한 근거 유무만을 판별했다. P2.4에서는 다음과 같이 GraphRAG 데이터를 추가로 검증한다.
1. 답변에 인용된 증거(Claim ID)가 Neo4j 및 PostgreSQL에 실제로 존재하고 **승인(APPROVED)** 상태인지 확인.
2. 쟁점과 연결된 증거가 그래프 상에서 논리적 흐름(SUPPORTS/CONTRADICTS)에 맞게 인용되었는지 확인.

