# AI 법률도우미 Technology Stack Baseline v1.0
Document ID: ALH-TECH-001
Status: RECOMMENDED BASELINE
Rule: Existing repository audit can override with Supervisor approval.

## 1. Architecture Style
**Modular Monolith first.**
하나의 배포 가능한 Backend 안에서 domain/application/agents/rag/evidence/playbook/orchestration 모듈을 명확히 분리한다.
Worker process는 long-running job 처리를 위해 별도 실행 가능하다.
Microservice 분리는 MVP 이후 측정 근거가 있을 때 한다.

## 2. Backend
- Python 3.12 권장
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- Alembic
- pytest

선택 이유: AI/RAG/document 처리 생태계, typed schema, API/OpenAPI, async I/O, 테스트 용이성.

## 3. Primary Database
- PostgreSQL 17 또는 18
- pgvector
- JSONB는 flexible metadata에 제한적으로 사용
- 핵심 relation/ID/state는 정규화된 table/constraint 사용

MVP에서는 사건 관계데이터 + metadata filtering + vector retrieval을 PostgreSQL 계열에서 시작한다.

## 4. Object Storage
S3-compatible Object Storage abstraction.
개발환경은 local filesystem 또는 S3-compatible local storage를 사용할 수 있으나 application은 `ObjectStore` interface에 의존한다.
원본 Evidence와 대용량 extracted artifact를 DB blob으로 무분별하게 저장하지 않는다.

## 5. Async Jobs
OCR/STT/embedding/indexing/대규모 analysis는 background job.
초기 권장: Celery + Redis.
단, 기존 repository에 이미 검증된 queue가 있으면 재사용.
Redis를 system-of-record로 사용하지 않는다.

## 6. LLM Layer
`LLMProvider` abstraction을 둔다.
- structured output
- function/tool calling
- timeout/retry
- model/prompt version
- usage telemetry
- schema validation

Gemini를 사용할 수 있지만 business/domain code가 Gemini SDK에 직접 결합되지 않게 한다.
Structured output은 application-side Pydantic validation을 다시 수행한다.

## 7. Embedding
`EmbeddingProvider` abstraction.
초기에는 Gemini embedding 또는 기존 시스템 embedding을 재사용 가능.
Embedding model/dimension/version을 index metadata에 저장한다.
모델 변경 시 re-index 전략 필수.

## 8. Agent/Workflow
**초기 기본: custom lightweight orchestration + explicit state machine.**
P6의 deterministic workflow를 application code로 명시한다.

LangGraph 등 agent framework는 Repository audit 후 다음 조건에서만 도입:
- durable graph execution이 실제 구현량을 크게 줄임
- state persistence/replay 요구 충족
- framework lock-in보다 이득이 큼
- P1/P6 contracts를 framework object로 오염시키지 않음

즉, LangGraph는 선택사항이지 Baseline dependency가 아니다.

## 9. Document Processing
Adapter interfaces:
`TextExtractor`, `PdfExtractor`, `VisionOcrProvider`, `SpeechToTextProvider`.
구체 라이브러리/Cloud API는 품질 테스트 후 결정.
원본→추출물→Fact provenance를 보존한다.

## 10. Frontend
Web PoC:
- React + TypeScript
- Vite 계열 build setup 권장
- API client/schema generation 가능

기존 frontend가 있으면 우선 재사용.
PWA/Android native는 MVP 핵심 검증 후 결정한다.

## 11. Observability
- structured JSON logs
- OpenTelemetry traces/metrics
- trace_id/case_id/job_id/agent_run_id
- 민감 Evidence 본문 logging 금지
- token/cost telemetry 가능 시 수집

## 12. Security
- secrets via environment/secret store
- authentication provider는 배포환경에 맞게 adapter
- object-level authorization
- file type/size validation
- malware scanning extension point
- encryption in transit
- storage encryption capability
- log redaction
- prompt injection boundary
- dependency scanning

## 13. Dev/Deploy
- Docker Compose for local integration environment
- dependency lock file
- `.env.example` without secrets
- CI: lint/type/test/migration/schema/evaluation smoke
- production deployment target은 MVP 환경 확인 후 결정
- Kubernetes는 기본 요구사항 아님

## 14. Repository Shape (new repo일 때만)
```text
backend/
  app/
    domain/
    application/
    api/
    agents/
    orchestration/
    evidence/
    legal_knowledge/
    playbooks/
    verification/
    infrastructure/
  tests/
frontend/
playbooks/
evaluation/
docs/
docker/
```
기존 repo가 있으면 새 구조를 강제로 만들지 않는다.

## 15. Not Baseline
- Neo4j
- Kafka
- Kubernetes
- Elasticsearch/OpenSearch
- Pinecone/Weaviate/Qdrant 별도 vector DB
- 10개 Agent microservices
- event sourcing 전체 적용

필요성이 측정되면 ADR로 도입한다.

## 16. 기술 선택 Gate
Gemini는 실제 구현 전 repository assessment에서 다음을 보고한다:
현재 language/framework/database/vector store/LLM SDK/test/deploy 구조, 재사용 가능 항목, 충돌, migration cost.
그 결과가 본 권장 stack보다 우선할 이유가 있으면 `PROPOSED DESIGN CHANGE`를 제출한다.
