---
document_id: ALH-DIRECTIVE-P1
title: Gemini Antigravity Execution Directive - P1 Core Domain Model
version: 1.0
status: Prepared - Execute Later
---

# Gemini Antigravity 실행지시 — P1 전체

## 1. 역할

You are the implementation team for AI Legal Helper.

Implement the approved design. Do not redefine product scope or architecture.

## 2. Source of Truth 우선순위

1. ALH-DEV-001 Master Development Plan
2. ALH-DOMAIN-001 P1 Core Domain Model
3. Task-specific approved documents such as ALH-DOMAIN-P1.1
4. Existing repository conventions

충돌 시 임의 결정하지 말고 `DESIGN CONFLICT`로 보고한다.

## 3. 실행 전 Repository Audit

먼저 다음을 조사한다.

- languages/frameworks
- repository structure
- domain model conventions
- database/persistence
- validation/schema tools
- datetime/ID conventions
- existing Case/Evidence/Agent models
- test framework
- existing Legal RAG/Agents/Synthesizer
- backwards compatibility constraints

결과를 `P1 Repository Assessment`로 보고한다.

## 4. 구현 순서

반드시 순차 수행한다.

```text
P1.1 Case
P1.2 Party
P1.3 Fact
P1.4 Evidence
P1.5 Event/Timeline
P1.6 LegalIssue
P1.7 LegalSource
P1.8 Precedent
P1.9 Action
P1.10 CaseState
P1.11 AgentMessage
P1.12 Integrated Schema
```

각 Task마다:

```text
Inspect
→ Gap Analysis
→ Implement
→ Unit Test
→ Regression Test
→ Task Report
```

향후 실제 실행 시 Supervisor 승인 없이 다음 Task로 넘어갈지 여부는 별도 실행 명령을 따른다.

## 5. Gap Classification

```text
EXISTS
PARTIAL
MISSING
CONFLICT
```

Material CONFLICT 발생 시 중지한다.

## 6. 공통 구현 요구

- typed models
- explicit enums
- runtime validation
- timezone-aware datetime
- immutable/stable IDs
- traceable references
- deterministic serialization
- test fixtures
- minimal new dependencies

## 7. 금지사항

- lease-specific fields in generic Case Root
- legal rules hard-coded into Domain Model
- win probability
- invented liability fields
- Evidence 원본을 AI summary로 대체
- statute/precedent body를 Case에 중복 저장
- free-text workflow state
- untracked Agent communication
- unrelated refactoring
- architecture redesign without approval

## 8. Cross-Entity Validation

P1.12에서 반드시 검증한다.

- same-case references
- duplicate refs
- required fields
- enum validity
- invalid cross-case references
- traceability chain
- serialization/deserialization

## 9. 테스트 Fixture

최소:

- valid lease case graph
- unsupported claim
- conflicting facts
- invalid cross-case reference
- agent request/response trace

## 10. 설계변경

필요하면 다음 형식으로만 제안한다.

```text
PROPOSED DESIGN CHANGE
Task:
Current Specification:
Repository Constraint:
Proposed Change:
Reason:
Affected Components:
Migration Impact:
Backward Compatibility:
```

승인 전 임의 반영하지 않는다.

## 11. Task 완료보고

```text
TASK COMPLETION REPORT
Task ID:
Status: COMPLETE | PARTIAL | BLOCKED

Implemented:
Changed Files:
Tests Added:
Test Commands:
Test Results:
Regression:
Requirement Coverage:
Design Deviations:
Known Issues:
Dependencies Added:
Next Recommended Task:
```

## 12. P1 최종보고

P1.12 종료 후:

```text
P1 FINAL REPORT

Repository Assessment:
Domain Components Implemented:
Schemas:
Integrity Rules:
Test Summary:
Regression Summary:
Scenario Fixture Results:
Design Deviations:
Open Issues:
Readiness:
- P2 Legal Knowledge: READY/NOT READY
- P3 Evidence Intelligence: READY/NOT READY
- P4 Legal Playbook: READY/NOT READY
```
