---
document_id: ALH-ACCEPT-P1.1
title: P1.1 Case Model 검수기준
version: 1.0
status: Active
task: P1.1
---

# P1.1 Case Model 검수기준

## 1. 목적

본 문서는 Gemini Antigravity가 구현한 P1.1 결과를 Supervisor가 승인 또는 반려하기 위한 기준이다.

Gemini의 `COMPLETE` 보고 자체는 승인 조건이 아니다.

---

# 2. 승인 Gate

## Gate A — 설계 준수

| 검사항목 | 승인조건 |
|---|---|
| Case Aggregate | 최상위 사건 객체로 구현 |
| Domain 독립성 | 임대차 전용 Root 필드 없음 |
| CaseStatus | 명시된 Enum 지원 |
| ResolutionStatus | Workflow 상태와 분리 |
| Reference 구조 | 하위 Entity를 ID로 참조 |
| revision | 생성=1, 수정 시 증가 |
| Timestamp | timezone-aware |
| UNKNOWN 처리 | 추정값으로 자동 치환하지 않음 |

하나라도 핵심 위반 시 **REJECT**.

---

## Gate B — 범위 통제

다음을 임의 구현했으면 검토 후 원칙적으로 반려한다.

- Party 상세 모델
- Evidence 상세 모델
- Fact 상세 모델
- 전체 State Machine
- 임대차 법률 판단 로직
- 승소확률
- 법적 책임 확정
- 판례/법령 전문 Case 저장

P1.1의 목적은 Foundation이지 기능 확장이 아니다.

---

## Gate C — 테스트

필수:

- 정상 생성 PASS
- Required Validation PASS
- Enum Validation PASS
- revision PASS
- update PASS
- status update PASS
- serialization PASS
- 관련 기존 Test Regression PASS

테스트 실패 상태에서는 승인하지 않는다.

---

## Gate D — 기존 시스템 통합

확인:

1. 기존 프로젝트 구조를 재사용했는가
2. 불필요한 Parallel Model을 만들지 않았는가
3. 기존 법령 RAG/Agent 코드를 불필요하게 변경하지 않았는가
4. 신규 Dependency가 있다면 정당한가
5. 기존 API/Module과 충돌하지 않는가

---

## Gate E — 코드 품질

확인:

- 타입 명확성
- Enum 사용
- Validation 위치 적절성
- 중복 최소화
- 불필요한 abstraction 없음
- Error가 명시적임
- Test가 구현 세부사항이 아닌 Contract를 검증함

---

# 3. 검수 결과

Supervisor는 다음 중 하나로 판정한다.

### APPROVED

모든 필수 Gate 통과.

다음 Task:

```text
P1.2 Party Model
```

### APPROVED WITH MINOR FIX

Architecture 변경 없이 작은 수정만 필요.

Gemini에게 수정 Task를 부여하고 재검증한다.

### REJECTED

다음 중 하나:

- 설계 위반
- Scope Creep
- 핵심 Test 실패
- 기존 구조 훼손
- 임의 Architecture 변경
- 데이터 Traceability를 저해하는 구현

수정지시 후 P1.1을 재실행한다.

### BLOCKED

외부 Dependency, Repository 문제 또는 선행 결정이 필요함.

---

# 4. Gemini 결과를 사용자에게 전달할 때 필요한 자료

Supervisor 검수를 위해 다음을 전달한다.

1. Gemini의 `TASK COMPLETION REPORT`
2. 실패한 Test가 있다면 전체 오류
3. `Design Deviations` 또는 `PROPOSED DESIGN CHANGE`
4. 필요 시 주요 변경 코드/Diff

모든 코드 전체를 복사할 필요는 없다.  
검수가 필요한 경우 Supervisor가 추가 자료를 요청한다.

---

# 5. P1.1 최종 완료조건

다음 문장이 모두 참이어야 P1.1을 종료한다.

```text
[ ] Case가 정의된 Schema를 만족한다.
[ ] CaseStatus와 ResolutionStatus가 분리되어 있다.
[ ] 하위 Entity는 ID Reference 방식이다.
[ ] revision과 timestamp가 정상 동작한다.
[ ] 자동 Validation이 존재한다.
[ ] 필수 Unit Test가 모두 PASS한다.
[ ] 기존 기능 Regression이 없다.
[ ] 승인되지 않은 설계 변경이 없다.
[ ] Gemini 결과를 Supervisor가 검수했다.
```
