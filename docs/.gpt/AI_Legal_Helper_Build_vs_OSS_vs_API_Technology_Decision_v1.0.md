# AI 법률도우미 Build vs OSS vs External API 기술선정 v1.0
Document ID: ALH-TECH-002
Status: APPROVED TECHNOLOGY DIRECTION
Date: 2026-10-07

## 1. 원칙

범용 AI 인프라를 다시 만들지 않는다.
직접 개발은 AI 법률도우미의 차별화 영역에 집중한다.

```text
OSS/Framework = 범용 실행 능력
External API  = 고비용/고난도 모델 능력
BUILD         = Legal Domain Intelligence
```

## 2. 최종 선정표

| 영역 | 결정 | 기본 기술 | 우리가 개발할 것 |
|---|---|---|---|
| Multi-Agent orchestration | OSS | LangGraph | 법률 Workflow graph/node/state/routing policy |
| LLM abstraction/tools | OSS | LangChain | Agent persona/tool permission/domain adapter |
| Supervisor routing | OSS+BUILD | LangGraph routing + structured LLM | Intent taxonomy, RoutingPlan, legal safety rules |
| Workflow persistence/HITL | OSS | LangGraph checkpointer/interrupt | Case ↔ thread/run mapping, review policy |
| Structured contracts | OSS | Pydantic v2 | Case/Evidence/Fact/Issue/etc schemas |
| API | OSS | FastAPI | legal application endpoints/auth boundary |
| ORM/migration | OSS | SQLAlchemy + Alembic | domain repositories/migrations |
| relational DB | OSS | PostgreSQL | legal domain schema |
| vector search | OSS | pgvector | legal metadata/hybrid retrieval/reranking policy |
| document parsing | OSS | Docling | Evidence adapter, provenance, Korean legal document tests |
| OCR | OSS/API adapter | Docling OCR engines; API fallback | quality routing/confidence/provenance |
| STT | External API/adapter | provider selected by Korean benchmark | audio evidence adapter/timestamp provenance |
| object storage | OSS/cloud interface | S3-compatible | Evidence object policy/checksum/access |
| async jobs | OSS | Celery + Redis initially | legal job types/idempotency/reanalysis rules |
| RAG | OSS+BUILD | LangChain retrievers + pgvector | statute/precedent normalization, metadata filters, hybrid retrieval |
| reranking | OSS/API adapter | pluggable reranker | legal relevance features and comparison |
| RAG evaluation | OSS | Ragas | Korean legal gold set/custom metrics |
| Agent evaluation | OSS | DeepEval + deterministic tests | routing/trajectory/legal grounding rubrics |
| tracing | OSS/SaaS option | OpenTelemetry; LangSmith optional | legal trace metadata/redaction |
| prompt/model registry | BUILD thin layer | DB/config + LangChain metadata | approved prompt/version governance |
| legal playbook | BUILD | YAML/JSON + Pydantic validation | 핵심 경쟁자산 |
| Evidence→Fact reasoning | BUILD | LangGraph nodes + LLM | 핵심 경쟁자산 |
| Case intelligence/traceability | BUILD | relational edge model first | 핵심 경쟁자산 |
| Verification | BUILD+OSS | deterministic validators + LLM judge where suitable | 핵심 신뢰자산 |
| legal document generation | BUILD | LangChain/LLM | verified-fact drafting rules/templates |
| frontend | OSS | React + TypeScript | 사건 중심 UX |
| deployment | OSS | Docker Compose first | environment/release configuration |

## 3. LangChain / LangGraph 역할

### LangChain
- model/provider integration
- tool definitions
- structured output integration
- retriever interface
- embeddings
- document/RAG integration

### LangGraph
- Supervisor/Router
- StateGraph
- conditional edges
- specialist agent execution graph
- checkpoint/persistence
- interrupt/human review
- retry/resume flow
- reanalysis flow

### 우리 코드
LangGraph State가 Domain Model 그 자체가 되게 하지 않는다.
Domain entity와 graph execution state를 분리한다.

```text
Domain CaseState != LangGraph runtime state
```

LangGraph는 실행 상태를 관리하고 PostgreSQL은 제품의 영속 Domain State/System of Record를 관리한다.

## 4. 제안 Graph

```text
START
  ↓
load_case_context
  ↓
supervisor_router
  ↓
validate_routing_plan
  ├─ clarification → INTERRUPT → user response
  ├─ evidence_update → evidence_subgraph
  ├─ case_analysis → analysis_subgraph
  ├─ legal_research → research_subgraph
  ├─ document → document_subgraph
  └─ status_query
            ↓
        synthesis
            ↓
       verification
       ├─ PASS → persist_result → END
       ├─ WARNING → review/action
       └─ FAIL → targeted_reanalysis / human_review
```

## 5. Document AI

Docling을 기본 parser 후보로 채택한다.

사용:
- native PDF extraction
- OCR
- layout/table structure
- DOCX/image conversion

직접 개발:
- EvidenceNormalizer
- source location mapping
- extraction confidence
- Korean legal document benchmark
- original artifact checksum
- extracted content provenance

Docling 결과를 법적 Fact로 자동 간주하지 않는다.

## 6. RAG

`LangChain + PostgreSQL/pgvector`를 기본 조합으로 한다.

우리가 직접 개발해야 하는 부분:
- statute/precedent schema
- legal metadata filter
- case issue query generation
- hybrid retrieval policy
- reranking policy
- current case vs precedent comparison
- citation verification
- source freshness

pgvector는 저장/검색 엔진일 뿐 Legal RAG 자체가 아니다.

## 7. Evaluation

### Ragas
주 용도:
- context precision/recall
- faithfulness
- response relevance
- RAG retrieval quality
- 일부 agent/tool metric

### DeepEval
주 용도:
- end-to-end agent tests
- component tests
- trajectory/tool behavior
- custom legal rubric
- CI regression

### 직접 deterministic 평가
법률 AI에서 반드시 직접 검사:
- 존재하지 않는 판례번호
- 존재하지 않는 법조문
- source ID mismatch
- CONFIRMED Fact without Evidence
- broken traceability
- forbidden router transition
- Verification bypass

LLM-as-judge 점수만으로 Release Gate를 통과시키지 않는다.

## 8. Observability

OpenTelemetry를 vendor-neutral 기본 instrumentation으로 둔다.
LangSmith는 LangChain/LangGraph 개발·trace/evaluation 편의성이 실제로 유리하면 사용한다.

민감 Evidence 원문을 외부 tracing 서비스로 자동 전송하지 않는다.
전송 field allowlist/redaction이 먼저다.

## 9. 직접 만들지 않을 것

- 자체 agent framework
- 자체 graph execution engine
- 자체 checkpoint engine
- 자체 vector database
- 자체 PDF layout engine
- 자체 OCR engine
- 자체 generic evaluation framework
- 자체 distributed message broker
- 자체 observability protocol

## 10. 반드시 직접 만들 것

1. Legal Domain Model
2. Legal Taxonomy
3. Legal Playbook
4. Case Supervisor의 법률 routing policy
5. Evidence/Fact/Issue 관계 모델
6. Evidence Gap logic
7. Case↔Precedent comparison
8. Legal source verification
9. Verification policy
10. Next Action logic
11. Explainability/Traceability
12. Legal document safety rules
13. 주택임대차 Gold/Challenge dataset

이 13개가 제품의 핵심 지적자산이다.

## 11. 보류/Benchmark 후 결정

### OCR
Docling 내 OCR을 우선 시험하되 한국어 계약서/문자 캡처/스캔 내용증명에서 품질이 부족하면 Cloud Vision 계열 API adapter를 추가한다.

### STT
한국어 전화녹음 benchmark 후 provider 결정. Speaker diarization, timestamp, 숫자/금액/날짜 정확도를 평가한다.

### Reranker
초기 vector+metadata baseline 측정 후 필요하면 cross-encoder/API reranker 추가.

### Graph DB
P7 query complexity를 측정한 뒤 결정. 기본은 PostgreSQL edge model.

### LangSmith
개인정보/비용/운영 정책 검토 후 선택. OpenTelemetry는 기본 유지.

## 12. 금지되는 기술결정 방식

- Gemini가 편하다는 이유만으로 framework 추가 금지
- library가 존재한다는 이유만으로 무조건 도입 금지
- 동일 기능 library 중복 사용 금지
- Domain Model을 framework-specific class에 종속 금지
- 법률 검증을 generic evaluator에 위임 금지
- 실제 benchmark 없이 OCR/STT 품질 가정 금지

## 13. 구현 전 Repository Assessment

Gemini는 먼저 기존 프로젝트에서 다음을 조사한다.

- Python/version/package manager
- LangChain 사용 여부/version
- existing agent implementation
- statute RAG implementation
- vector DB/embedding
- Synthesizer
- database
- API
- frontend
- tests
- deployment
- existing prompts
- external service dependencies

결과를 `REPOSITORY ASSESSMENT REPORT`로 제출한다.

기존 검증 자산은 재작성하지 않고 adapter를 우선한다.

## 14. 기술 Baseline

```text
Python
FastAPI
Pydantic
LangChain
LangGraph
PostgreSQL
pgvector
SQLAlchemy
Alembic
Docling
Celery
Redis
Ragas
DeepEval
OpenTelemetry
React
TypeScript
Docker Compose
```

단, 정확한 package version은 Repository Assessment 시 호환성 검증 후 lock한다.
