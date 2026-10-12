# AI Legal Helper — P2.4 Evidence GraphRAG 개발지시서 v1.0

**프로젝트:** `C:\myprjs\ai-legal-helper`  
**단계:** P2.4 — Knowledge Graph & Evidence GraphRAG  
**핵심 기술:** Neo4j, Cypher, GraphRAG, LangGraph, PostgreSQL, ChromaDB, Azure OpenAI

## 1. 개발 목표
P2.3에서 구현한 증거 분석 기능을 확장하여 사건의 사실, 증거, 당사자, 사건 발생 시점, 법률 쟁점 간 관계를 Knowledge Graph로 구축한다. 단순 유사도 검색이 아닌 그래프 관계 탐색을 통해 증거와 쟁점 간의 구조적 관계를 파악하고 최종적으로 GraphRAG 결과를 기존 Supervisor 및 Verification Agent에 통합한다.

## 2. 개발 원칙
1. 기존 P0~P2.3 기능을 유지한다.
2. `ai-legal-agent` 원본 프로젝트는 수정하지 않는다.
3. PostgreSQL은 Source of Truth, Neo4j는 관계 탐색 파생 데이터 저장소로 사용.
4. ChromaDB 법령 RAG는 유지한다.
5. 승인되지 않은 AI 추출 결과는 확정된 사실로 취급하지 않으며, 그래프 관계 자체가 법률적 증명이 아님을 명시.
6. 원본 Evidence ID와 Span ID의 추적 가능성 확보.
7. Graph DB 장애 시 Fallback 제공.
8. 새로운 유료 서비스 미도입.

## 3. Neo4j 개발 환경
기존 Docker Compose 구성에 Neo4j Community Edition 추가.
- 포트: Bolt(7687), Browser(7474) (로컬 환경 127.0.0.1 바인딩)
- Named Volume 데이터 영속화, `.env` 기반 인증정보.
- PostgreSQL 컨테이너와 독립적인 장애 관리.
- Python `neo4j` 드라이버 사용.

## 4. Knowledge Graph 스키마
노드: Case, Party, Fact, Event, EvidenceDocument, EvidenceSpan, EvidenceClaim, LegalIssue, LegalAuthority, Action.
관계: INVOLVES_PARTY, HAS_FACT, HAS_EVENT, HAS_EVIDENCE, HAS_ISSUE, HAS_CLAIM, CONTAINS_SPAN, SUPPORTS, CONTRADICTS, RELATED_TO, OCCURRED_BEFORE, REQUIRES_EVIDENCE, GROUNDED_IN, SUGGESTS_ACTION.
모든 노드에 ID(PostgreSQL 연동)를 기록.

## 5. 그래프 생성 파이프라인
1. P2.2/P2.3 PostgreSQL 데이터 기반 초기 그래프 구축.
2. 증거 갱신 시(승인/반려/삭제 등) Neo4j 그래프 동기화.
3. LLM 기반 AI 관계 추출 (AI 제안/승인/상충 여부 구분).

## 6. Evidence GraphRAG
검색 전략: Baseline RAG, Graph Traversal (Cypher), Hybrid GraphRAG.
검색 결과를 정규화하여 출력 (경로 유지).

## 7. Supervisor 및 Verification 연동
LangGraph Supervisor에서 GraphRAG 검색 요청 후 Verification Agent에서 ID/상태의 실존 여부 및 논리적 일치성을 코드 레벨에서 검증.

## 8. React 그래프 탐색 UI
사건 상세 화면에 `Evidence Graph` 탭 추가.
- 노드/관계 시각화 및 필터링, 클릭 시 원본 문서 이동.
- SUPPORTS/CONTRADICTS 구분, 분석 근거 경로 표시.

## 9. 개인정보 및 보안
`case_id` 범위 제한, 불필요한 개인정보 원문 복제 금지, 프롬프트 인젝션 방지.

## 10. 테스트 및 성능 평가
P0~P2.3 회귀 테스트 유지 + GraphRAG, 멱등성, 실패 복구 등 신규 테스트.

## 11. 완료 후 산출물
`P2_4_GRAPH_ARCHITECTURE.md`, `P2_4_GRAPH_SCHEMA.md`, `ADR-007-NEO4J-GRAPHRAG.md` 작성 및 최종 평가 보고서 제출.

