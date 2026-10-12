# AI 법률도우미 Red-Team Architecture & Tech Stack Review v1.0
Document ID: ALH-ARCH-REVIEW-002
Status: REVIEW COMPLETE

## 결론
Baseline v1.1은 방향이 타당하지만 구현 전에 추가 Control을 명시해야 한다.

## Critical/High Findings

### R1 Authentication / Authorization
Case와 Evidence는 사용자별 접근경계를 가져야 한다. `user_id/owner_id`를 무작정 Domain 의미와 혼합하지 말고 Application/Auth context에서 authorization을 강제한다. 모든 case/evidence/document endpoint에 object-level authorization test가 필요하다.

### R2 Long-running Job Model
OCR/STT/embedding/indexing/대규모 분석은 HTTP request 안에서 완료시키지 않는다.
`Job` contract: job_id, case_id, job_type, status, progress, input_refs, output_refs, retry_count, error, timestamps, trace_id.
상태: QUEUED/RUNNING/SUCCEEDED/PARTIAL/FAILED/CANCELLED.

### R3 Human-in-the-loop
Verification FAIL, conflicting critical facts, unverifiable legal source, 고위험 문서 생성은 `REVIEW_REQUIRED`/사용자 확인 경로가 필요하다. 자동으로 그럴듯한 결론을 만들지 않는다.

### R4 Case Revision / Invalidation
새 Evidence가 들어오면 모든 결과를 무조건 다시 계산하지 않는다. AnalysisArtifact dependency를 추적하여 영향받은 Fact/Issue/Retrieval/Playbook/Synthesis를 invalidate한다. 이전 분석은 audit 목적으로 보존한다.

### R5 Idempotency / Concurrency
중복 업로드, 재시도, 동시 Case update에서 중복 Fact/Action/Job을 만들지 않도록 idempotency key와 optimistic revision check를 둔다.

### R6 Audit Trail
법률 AI에서는 일반 application log와 별도로 audit event가 필요하다.
누가/무엇이/언제 어떤 Case artifact를 생성·변경·검증했는지 기록하되 Evidence 원문을 audit log에 복제하지 않는다.

### R7 Citation Snapshot
외부 법률 source가 변경될 수 있으므로 분석 당시 사용한 source identifier/version/retrieved_at/content hash 또는 허용된 snapshot reference를 기록한다.

### R8 Prompt/Model Registry
Agent별 prompt_version/model/provider/schema_version을 AgentRun에 기록한다. 재현성과 평가 비교에 필요하다.

### R9 Router Failure Boundary
Supervisor/Router가 잘못 routing해도 Orchestrator의 allowlist/state/precondition 검증이 차단해야 한다. Router는 control authority가 아니라 planning authority다.

### R10 Legal Answer Output Contract
최종 답변을 단순 string으로 끝내지 않는다.
최소: summary, confirmed_facts, disputed_or_unknown, issues, legal_bases, precedent_comparisons, recommended_actions, evidence_gaps, cautions, verification_status, trace refs.

### R11 Retrieval Security
사용자 Evidence와 외부 RAG corpus를 동일 trust level로 취급하지 않는다. Evidence 속 prompt injection/명령은 retrieval content로만 처리한다.

### R12 Data Lifecycle
원본 Evidence/추출물/embedding/cache/log/audit 각각 retention/deletion policy extension point를 둔다.

### R13 Disaster/Recovery
PoC라도 DB migration/backup 및 object-store recovery 방법을 문서화한다.

### R14 Evaluation Independence
개발/validation/challenge dataset을 분리하고 challenge 결과로 prompt를 반복 튜닝하지 않는다.

### R15 Cost/Latency Budget
Agent 호출 횟수를 무제한 허용하지 않는다. workflow별 max agent calls, max retries, timeout, token/cost telemetry를 둔다.

## Architecture 최종 판단
Supervisor/Router + deterministic Orchestrator + bounded Specialist Agents + independent Verification 구조를 유지한다.
추가로 Job Manager, Auth Boundary, Audit/Observability, Human Review, Artifact Versioning을 Cross-Cutting Control로 지정한다.

## 구현 금지
초기 MVP에서 Kafka, Kubernetes, Neo4j, Elasticsearch/OpenSearch, 별도 Vector DB, 10개 microservice를 기본 도입하지 않는다. 실제 요구가 측정되어 ADR 승인될 때 추가한다.
