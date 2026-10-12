---
document_id: ALH-ARCH-REVIEW-001
title: AI 법률도우미 Architecture Review & Baseline Freeze
version: 1.0
status: APPROVED WITH REQUIRED CONTROLS
review_scope: P0-P10
---

# Architecture Review & Baseline Freeze

## 1. 결론

P0~P10 설계는 구현 착수 가능한 구조이다.

핵심 Architecture:

```text
Evidence
→ Fact / Timeline
→ Legal Issue
→ Statute + Precedent
→ Legal Playbook
→ Multi-Agent Reasoning
→ Synthesis
→ Verification
→ Next Action / Document
→ Case Update
```

은 제품 목표와 일치한다.

다만 구현 전에 아래 Cross-Cutting Control을 전체 Phase에 적용해야 한다.

---

# 2. Review Findings

## F-01 — Fact와 AI Conclusion 경계 강화

위험:
Fact, Issue analysis, Synthesizer conclusion이 구현 과정에서 혼합될 수 있다.

조치:
새 공통 개념을 논리적으로 구분한다.

```text
Source Evidence
Extracted Content
Fact
Legal Issue
Analysis/Inference
Verified Conclusion
Action
```

`Fact.statement`에는 법률 결론을 저장하지 않는다.

예:
- 허용 Fact: "임대인이 2026-08-10 보증금 반환이 어렵다고 말했다."
- 금지 Fact: "임대인은 보증금 반환 의무를 위반했다."

후자는 Legal Analysis 영역이다.

판정: REQUIRED

---

## F-02 — Verification 결과의 독립 Contract 필요

기존 P5 Verification Agent만으로는 구현자가 단순 boolean으로 축소할 위험이 있다.

공통 VerificationResult:

```yaml
verification_id:
case_id:
trace_id:
target_type:
target_id:
overall_status: PASS|WARNING|FAIL
checks:
  - check_type:
    status:
    claim:
    source_refs:
    reason:
    severity:
created_at:
verifier_version:
```

Check Type 최소:
`FACT_GROUNDING, STATUTE_EXISTENCE, STATUTE_FRESHNESS, PRECEDENT_EXISTENCE, PRECEDENT_RELEVANCE, PLAYBOOK_CONSISTENCY, UNSUPPORTED_CLAIM, TRACEABILITY`

판정: REQUIRED

---

## F-03 — Analysis Artifact의 Version/Provenance

새 Evidence 입력 후 이전 분석과 최신 분석을 구분해야 한다.

모든 주요 AI 결과에는 가능한 경우:
`analysis_id, case_revision, input_refs, model_id, prompt_version, created_at, supersedes_id`

를 유지한다.

판정: REQUIRED

---

## F-04 — P2 Legal Source Freshness

법률서비스에서는 검색 성공만으로 부족하다.

법령/판례 결과에:
`retrieved_at, source provider, verification status, effective/decision date`

를 유지하고 사용자 근거로 사용하기 전 Verification한다.

공식/권위 Source 우선. Source unavailable이면 LLM memory로 보충하지 않는다.

판정: REQUIRED

---

## F-05 — Legal Playbook 법률규칙과 제품절차 분리

Playbook에는 두 종류의 Rule이 섞일 수 있다.

```text
LEGAL_RULE
PROCESS_RULE
```

LEGAL_RULE은 법적 근거 Source를 필수로 가진다.
PROCESS_RULE은 제품 Workflow/UX 규칙일 수 있다.

이 구분이 없으면 제품 편의 규칙이 법률규칙처럼 보일 위험이 있다.

판정: REQUIRED

---

## F-06 — Evidence Gap과 User Question 연결

Evidence Gap만 생성하고 끝내면 UX 가치가 낮다.

Gap은 필요 시 사용자 질문으로 변환 가능해야 한다.

```text
Gap
→ Clarification Question
→ User Answer / New Evidence
→ Fact Update
→ Reanalysis
```

질문에는 `question_id, gap_id, answer_type, required/optional, status`가 필요하다.

P3/P6/P8 구현 시 반영한다.

판정: REQUIRED

---

## F-07 — Case Graph 기술 선택을 늦춘 것은 적절함

P7에서 Graph DB를 강제하지 않은 것은 적절하다.

MVP는 관계형 DB + edge/provenance table로도 충분할 수 있다.
Graph DB 도입은 실제 query/scale 필요성을 측정한 후 결정한다.

판정: KEEP

---

## F-08 — Multi-Agent 과분리 방지

9개 Agent는 논리적 역할이다.

9개의 독립 LLM process/service를 반드시 만들 필요는 없다.
비용/latency/복잡도를 측정해 물리 실행 단위를 통합할 수 있다.

단, Prompt/Schema/Responsibility boundary는 유지한다.

판정: KEEP

---

## F-09 — P8 UI보다 Application Service Contract가 선행되어야 함

UI가 Agent를 직접 호출하면 결합도가 급증한다.

P8 전에 P6에서 Application/Orchestration facade를 고정하고 UI는 해당 API만 사용한다.

판정: REQUIRED

---

## F-10 — Document Generation 안전성

법률문서 생성 시:
- verified facts만 확정형 문장에 사용
- CLAIMED/UNKNOWN은 적절한 표현/placeholder
- 금액/날짜/당사자 자동 창작 금지
- 사용된 Fact IDs 기록
- 생성본 revision/audit 유지

판정: REQUIRED

---

## F-11 — Evaluation Data Leakage 방지

Gold/Challenge case를 Prompt나 Playbook 개발 과정에서 과도하게 맞추면 평가가 무의미해진다.

Dataset을:
`development / validation / challenge`
로 구분한다.

Challenge set은 최종 통합 전까지 직접 튜닝 대상으로 사용하지 않는 것을 원칙으로 한다.

판정: REQUIRED

---

## F-12 — KPI 의미 명확화

"정확도 90%" 같은 단일 값은 모호하다.

P9에서 각 KPI의:
`unit of evaluation, denominator, scoring rubric, human review rule`
을 먼저 고정한 뒤 측정한다.

목표치는 목표이며 실제 측정값과 혼합하지 않는다.

판정: REQUIRED

---

## F-13 — Privacy/Retention을 P10까지 미루면 늦음

보안 최종 Review는 P10이지만 최소 보안 설계는 P1/P3/P6/P8부터 적용한다.

최소:
- secret separation
- access boundary
- raw evidence protection
- log redaction
- upload validation
- retention/deletion extension point

판정: REQUIRED

---

## F-14 — Model/Provider Lock-in 방지

Gemini Antigravity는 개발 환경/구현팀 역할이며 서비스 Runtime LLM provider를 자동 의미하지 않는다.

LLM invocation은 Adapter/Provider interface 뒤에 둔다.
특정 모델 기능에 의존할 경우 명시적으로 기록한다.

판정: REQUIRED

---

## F-15 — Observability

PoC라도 다음을 추적한다.

```text
trace_id
case_id
workflow run
agent/tool
latency
status/error
model/prompt version
token/cost metrics if available
```

민감한 Evidence 원문 전체를 일반 로그에 남기지 않는다.

판정: REQUIRED

---

# 3. Architecture Decision Principles

## ADR-01
Domain Contract first.

## ADR-02
Original Evidence is immutable/reference-preserved.

## ADR-03
Legal knowledge must be retrievable and verifiable.

## ADR-04
Legal process knowledge lives in versioned Playbooks.

## ADR-05
Agent boundaries are logical; physical deployment is optimized later.

## ADR-06
Workflow state is controlled by deterministic orchestration.

## ADR-07
Verification is a separate stage and produces structured results.

## ADR-08
Traceability is a product feature, not only a debug feature.

## ADR-09
Graph database is optional until justified.

## ADR-10
UI accesses an Application/Orchestration boundary, not Agents directly.

## ADR-11
LLM provider is abstracted.

## ADR-12
Evaluation uses versioned, leakage-controlled datasets.

---

# 4. Baseline Freeze Decision

다음 설계를 **Development Baseline v1.0**으로 승인한다.

```text
P0 Problem/Scenario
P1 Core Domain
P2 Legal Knowledge
P3 Evidence Intelligence
P4 Legal Playbook
P5 Agent System
P6 Workflow/Orchestration
P7 Case Intelligence
P8 Application
P9 Evaluation
P10 Stabilization/Release
```

본 Review의 F-01~F-15는 각 Phase 구현 시 상위 Cross-Cutting Requirement로 적용한다.

---

# 5. 변경 허용

Baseline Freeze는 변경 금지가 아니다.

변경은 다음 절차로 한다.

```text
Issue 발견
→ Proposed Design Change
→ 영향분석
→ Supervisor 승인
→ 관련 문서 Version Update
→ 구현
→ Regression
```

Gemini가 코드에서 먼저 Architecture를 변경하고 사후 문서화하는 방식은 금지한다.

---

# 6. 개발 착수 판정

```text
Architecture: READY
Domain Direction: READY
Legal Knowledge Direction: READY
Evidence Direction: READY
Playbook Direction: READY
Agent Direction: READY
Orchestration Direction: READY
Evaluation Direction: READY

Implementation Status: NOT STARTED
Next Gate: Repository Assessment
```

첫 실제 개발 작업:

```text
P1 Repository Assessment
→ P1.1 Case Model
```
