---
document_id: ALH-ACCEPT-P1
title: P1 Core Domain Model 통합 검수기준
version: 1.0
status: Active
---

# P1 Core Domain Model 통합 검수기준

## 1. 검수 목적

Gemini 구현 결과가 이후 모든 Phase의 안정적인 공통 Contract로 사용 가능한지 판단한다.

## 2. Gate A — Entity Coverage

다음이 모두 존재해야 한다.

| Entity | 필수 |
|---|---:|
| Case | Y |
| Party | Y |
| Fact | Y |
| Evidence | Y |
| Event | Y |
| LegalIssue | Y |
| LegalSource | Y |
| Precedent | Y |
| CasePrecedentComparison | Y |
| Action | Y |
| CaseState | Y |
| AgentMessage | Y |

누락 시 P1 승인 불가.

## 3. Gate B — Evidence Integrity

필수 조건:

- Original Evidence와 Extracted Content 분리
- Fact와 Evidence 분리
- AI Interpretation과 Fact 분리
- Fact → Evidence 역추적 가능
- Evidence 없는 주장을 CONFIRMED로 자동 처리하지 않음
- CONFLICTED 표현 가능

위반 시 REJECT.

## 4. Gate C — Domain Independence

Generic Domain에 다음이 Hard Coding되어 있으면 반려 대상이다.

- 임대차 전용 법률조건
- 특정 법 조문
- 특정 판례
- 승소확률
- 법적 책임 확정
- 특정 Playbook decision

Domain은 구조를 제공하고 법률지식은 P2/P4가 제공한다.

## 5. Gate D — State Separation

다음이 구분되어야 한다.

```text
Workflow State
Resolution State
Issue State
Action State
Evidence Extraction State
Agent Message State
```

하나의 범용 `status` 문자열로 처리하면 승인하지 않는다.

## 6. Gate E — Traceability

최소 다음 Chain이 실제 Test Fixture에서 성립해야 한다.

```text
Evidence
→ Fact
→ Event
→ Issue
→ LegalSource / Precedent
→ Action
```

ID만 존재하고 관계 검증이 없으면 미완료로 본다.

## 7. Gate F — Cross Case Safety

Case A Entity가 Case B의 Evidence/Fact/Issue를 잘못 참조하는 Fixture가 Validation에서 실패해야 한다.

## 8. Gate G — Agent Contract

AgentMessage에 최소:

- case_id
- trace_id
- sender
- receiver
- type
- payload
- status
- error representation

이 있어야 한다.

Agent 간 핵심 데이터 교환이 자유형 Prompt 문자열에만 의존하면 승인하지 않는다.

## 9. Gate H — Tests

최소:

- entity creation
- required field validation
- enum validation
- serialization round trip
- invalid reference
- cross-case reference
- traceability fixture
- conflicting fact
- agent message
- existing regression tests

모든 Critical Test PASS 필요.

## 10. Gate I — Scenario Representability

SC-LEASE-001을 Domain Model만으로 표현할 수 있어야 한다.

검증 항목:

```text
Case
Tenant/Landlord
Lease contract Evidence
Communication Evidence
Deposit-related Facts
Timeline Events
Legal Issues
Legal Sources
Precedents
Recommended Actions
Current Case State
```

법률 결론의 정확성을 P1에서 평가하는 것은 아니다. 구조적 표현 가능성을 평가한다.

## 11. Gate J — Future Phase Readiness

P1 종료 시:

```text
P2 Legal Knowledge → LegalSource/Precedent/Issue 사용 가능
P3 Evidence → Evidence/Fact/Event 사용 가능
P4 Playbook → Issue/Action/State 사용 가능
P5 Agents → AgentMessage 사용 가능
P6 Orchestration → State/Message/Action 사용 가능
```

하위 Phase가 P1을 대규모 재설계해야만 시작할 수 있다면 P1을 승인하지 않는다.

## 12. 판정

### APPROVED
모든 Critical Gate 통과.

### APPROVED WITH MINOR FIX
Schema 의미 변경 없는 작은 수정.

### REJECTED
Evidence integrity, traceability, domain independence, cross-case safety 또는 핵심 테스트 실패.

### BLOCKED
Repository/Dependency/Architecture 선결문제 존재.

## 13. P1 최종 체크리스트

```text
[ ] 전체 Entity 구현
[ ] 공통 Enum 구현
[ ] Schema Validation
[ ] Cross-Entity Validation
[ ] Evidence Traceability
[ ] UNKNOWN/CONFLICTED 지원
[ ] Agent Message Contract
[ ] SC-LEASE-001 Fixture
[ ] Unit Tests PASS
[ ] Regression PASS
[ ] 승인되지 않은 Architecture 변경 없음
[ ] P2/P3/P4 Ready
```
