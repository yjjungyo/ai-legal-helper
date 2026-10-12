# ADR 007: Neo4j 및 GraphRAG 도입

## Status
Accepted

## Context
기존 P1.2 ~ P2.3 단계에서 구축된 시스템은 ChromaDB를 활용한 법령 검색(Baseline RAG)과 PostgreSQL을 통한 사건/증거 관리를 수행해 왔다. 그러나 법률 상담 과정은 단순히 단어 유사도 기반의 텍스트 검색을 넘어, 특정 주장(Fact)이 어떤 증거(Evidence)에 의해 뒷받침되는지, 쟁점(LegalIssue)을 해결하기 위한 요건 사실이 모두 증명되었는지를 파악해야 한다.

PostgreSQL의 RDB 조인이나 재귀 쿼리(Recursive CTE)로 다단계 관계 탐색을 처리할 수 있으나, 향후 시맨틱 관계가 복잡해짐에 따라 쿼리 성능이 저하되고 유지보수성이 나빠진다. 따라서 엔터티 간의 관계를 1급 시민(First-class citizen)으로 취급하는 Knowledge Graph와 GraphRAG 기법의 도입이 필요해졌다.

## Decision
1. **Neo4j Community Edition 도입**:
   - 복잡한 다단계 관계(Fact ↔ Claim ↔ Span ↔ Issue)를 직관적인 Cypher 쿼리로 탐색하기 위해 Neo4j를 도입한다.
   - 오픈소스 및 자체 호스팅이 가능한 Community Edition을 사용하며, 라이선스 제약(Docker 실행)을 준수한다.
2. **PostgreSQL과 Neo4j의 분리 (CQRS 패턴 차용)**:
   - 데이터 무결성이 중요한 원본 사건 관리, 사용자 검토 이력 보존은 PostgreSQL에서만 수행한다.
   - Neo4j는 PostgreSQL 데이터를 기반으로 재구성(Rebuild) 가능한 읽기 전용/관계 탐색 특화 저장소로 운용한다. 분산 트랜잭션을 강제하지 않고 Eventual Consistency(최종적 일관성)를 허용한다.
3. **GraphRAG 검색 전략 채택**:
   - Vector Search(ChromaDB)와 Graph Traversal(Neo4j)를 결합한 Hybrid GraphRAG를 구축하여, LangGraph Agent가 입체적인 법률 논리 구조를 추론하도록 돕는다.

## Consequences
**Positive:**
- 법률 논리와 증거 관계(지지/상충/연관)를 그래프 형태로 시각화 및 직관적 탐색 가능.
- 사실 기반의 Hallucination(환각) 억제 효과 증대. 증거 없는 주장을 그래프 단절(Disconnected Node)로 쉽게 파악 가능.
- LangGraph 내 Supervisor 및 Verification Agent의 검증 로직이 견고해짐.

**Negative:**
- 시스템 아키텍처 복잡도 증가 (Neo4j 컨테이너 추가 관리, 동기화 스크립트 작성 유지보수 등).
- 데이터 이중 저장으로 인한 스토리지 사용량 증가 및 동기화 지연(Latency) 이슈 대응 로직 추가 필요.

