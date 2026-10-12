---
document_id: ALH-DOMAIN-P1.1
title: AI 법률도우미 P1.1 Case Model 상세설계
version: 1.0
status: Implementation Ready
parent: ALH-DEV-001
phase: P1 Core Domain Model
task: P1.1 Case Model
---

# P1.1 Case Model 상세설계

## 1. 목적

`Case`는 AI 법률도우미에서 하나의 법률 사건을 대표하는 최상위 Aggregate Root이다.

Case는 사건의 식별, 유형, 처리 상태, 생성/수정 정보와 하위 객체의 참조를 관리한다.  
법률적 사실, 증거, 판례, 법령의 상세 내용을 Case 객체 내부에 중복 저장하지 않는다.

## 2. 설계 원칙

1. Case는 사건의 최상위 식별 단위이다.
2. 모든 Fact, Evidence, Event, Issue, Action은 반드시 하나의 `case_id`에 귀속된다.
3. Case State는 자유 텍스트가 아닌 Enum으로 관리한다.
4. 법률 판단 결과를 Case 기본 필드에 직접 저장하지 않는다.
5. 상세 Entity는 ID Reference로 연결한다.
6. 생성·수정 시각과 버전을 유지한다.
7. 삭제는 MVP에서 물리 삭제보다 상태 기반 관리가 우선이다.
8. 사용자 입력값과 AI 생성값을 혼동하지 않는다.
9. 향후 임대차 외 법률분야를 수용할 수 있어야 한다.

---

## 3. Case Aggregate

```text
Case
 ├─ identity
 ├─ classification
 ├─ lifecycle state
 ├─ user description
 ├─ references
 ├─ metadata
 └─ audit/version
```

### 3.1 필드 정의

| Field | Type | Required | Description |
|---|---|---:|---|
| case_id | string | Y | 사건 고유 ID |
| title | string | Y | 사용자에게 표시할 사건명 |
| description | string | Y | 사용자가 입력한 최초 사건 설명 |
| legal_domain | enum | Y | 사건의 상위 법률 분야 |
| case_type | string/null | N | 세부 사건유형. 초기에는 UNKNOWN 가능 |
| status | CaseStatus | Y | 시스템 처리 상태 |
| resolution_status | ResolutionStatus | Y | 실제 사건 해결 상태 |
| primary_user_role | string/null | N | 임차인 등 현재 사용자의 사건상 역할 |
| party_ids | string[] | Y | Party 참조 |
| evidence_ids | string[] | Y | Evidence 참조 |
| fact_ids | string[] | Y | Fact 참조 |
| event_ids | string[] | Y | Event 참조 |
| issue_ids | string[] | Y | Legal Issue 참조 |
| action_ids | string[] | Y | Action 참조 |
| active_playbook_ids | string[] | Y | 적용 중인 Playbook 참조 |
| created_at | datetime | Y | 생성시각 |
| updated_at | datetime | Y | 최종 수정시각 |
| schema_version | string | Y | Domain Schema 버전 |
| revision | integer | Y | Case 변경 revision |
| metadata | object | Y | 확장 Metadata |

배열 필드는 값이 없으면 `[]`를 사용한다.  
확인되지 않은 단일 값은 임의 추정하지 않고 `null` 또는 정의된 `UNKNOWN` 값을 사용한다.

---

# 4. Legal Domain

MVP에서는 다음 값을 최소 지원한다.

```text
LEASE
UNKNOWN
```

향후 확장을 고려하여 Domain Model이 임대차 전용 구조에 종속되지 않도록 한다.

예상 확장:

```text
DEBT
CONTRACT
DAMAGES
LABOR
CONSUMER
```

확장값은 후속 Taxonomy 설계에서 확정한다.

---

# 5. CaseStatus — 시스템 처리 상태

`CaseStatus`는 AI 법률도우미 내부 Workflow 상태를 나타낸다.

```text
NEW_CASE
INTAKE
EVIDENCE_PROCESSING
FACT_ANALYSIS
ISSUE_ANALYSIS
LEGAL_RESEARCH
PLAYBOOK_EVALUATION
SYNTHESIS
VERIFICATION
ACTION_READY
WAITING_USER
REANALYSIS
RESOLVED
CLOSED
ERROR
```

중요:

`CaseStatus`와 실제 법률분쟁 해결상태를 혼동하지 않는다.

예를 들어:

```text
CaseStatus = WAITING_USER
ResolutionStatus = ACTIVE
```

가 가능하다.

---

# 6. ResolutionStatus — 실제 사건 상태

```text
UNKNOWN
PRE_DISPUTE
ACTIVE
PARTIALLY_RESOLVED
RESOLVED
CLOSED
```

이 값은 법률적 승패를 의미하지 않는다.

---

# 7. Case ID 규칙

권장 형식:

```text
CASE-{UUID}
```

예:

```text
CASE-550e8400-e29b-41d4-a716-446655440000
```

ID는 의미를 Encoding하지 않는다.

다음과 같은 ID는 사용하지 않는다.

```text
LEASE-DEPOSIT-USER-001
```

이유:

- 사건분류가 변경될 수 있음
- 개인정보 노출 위험
- ID와 Business Meaning 결합 방지

---

# 8. Case 생성 규칙

새 사건 생성 시 최소 입력:

```text
title
description
```

초기 기본값:

```text
legal_domain = UNKNOWN
case_type = null
status = NEW_CASE
resolution_status = UNKNOWN
party_ids = []
evidence_ids = []
fact_ids = []
event_ids = []
issue_ids = []
action_ids = []
active_playbook_ids = []
revision = 1
```

Case Agent/분류 단계 이후 `legal_domain`, `case_type` 등이 업데이트된다.

---

# 9. Case Update 규칙

Case 수정 시:

1. 기존 `case_id` 유지
2. `updated_at` 갱신
3. `revision += 1`
4. 변경 History를 추적 가능하게 함
5. 다른 Entity의 실제 내용을 Case에 복제하지 않음

향후 `CaseHistory` 또는 Event Log는 Orchestration 설계에서 구체화한다.

---

# 10. JSON 표현 예시

```json
{
  "case_id": "CASE-550e8400-e29b-41d4-a716-446655440000",
  "title": "전세보증금 반환 문제",
  "description": "계약 종료를 앞두고 있는데 임대인이 보증금 반환이 어렵다고 합니다.",
  "legal_domain": "LEASE",
  "case_type": "DEPOSIT_RETURN",
  "status": "EVIDENCE_PROCESSING",
  "resolution_status": "ACTIVE",
  "primary_user_role": "TENANT",
  "party_ids": [
    "PARTY-001",
    "PARTY-002"
  ],
  "evidence_ids": [
    "EV-001"
  ],
  "fact_ids": [],
  "event_ids": [],
  "issue_ids": [],
  "action_ids": [],
  "active_playbook_ids": [],
  "created_at": "2026-10-07T10:00:00+09:00",
  "updated_at": "2026-10-07T10:05:00+09:00",
  "schema_version": "1.0",
  "revision": 2,
  "metadata": {}
}
```

예시는 Schema 설명을 위한 Fixture이며 실제 사건 사실을 의미하지 않는다.

---

# 11. JSON Schema 요구사항

Gemini 구현 시 JSON Schema 또는 프로젝트 언어에 맞는 동등한 Runtime Validation을 제공해야 한다.

최소 Validation:

- `case_id`: 빈 문자열 금지
- `title`: 빈 문자열 금지
- `description`: 빈 문자열 금지
- Enum 외 `status` 거부
- Enum 외 `resolution_status` 거부
- `revision >= 1`
- 참조 배열은 중복 ID를 허용하지 않는 방향 권장
- Timestamp는 timezone 정보를 포함하는 ISO-8601 사용
- 알 수 없는 핵심 필드의 임의 삽입 방지 여부는 기존 프로젝트 정책을 조사 후 결정

---

# 12. API/Service 수준 동작 요구사항

P1.1에서는 특정 Web Framework API 구현을 강제하지 않는다.

Domain 또는 Service Layer에서 최소 다음 동작이 가능해야 한다.

```text
create_case()
get_case()
update_case()
transition_case_status()
```

### create_case()

Input:

```text
title
description
optional metadata
```

Output:

```text
Case
```

### update_case()

Case의 허용된 Metadata/Classification 값을 변경한다.

### transition_case_status()

Workflow 상태를 변경한다.

P1.1에서는 모든 Transition Rule을 Hard Coding하지 않는다.  
상세 State Machine은 P6 Orchestration에서 정의한다.

단, 존재하지 않는 상태로 변경하는 것은 거부한다.

---

# 13. 금지 설계

Gemini는 다음을 구현하지 않는다.

- Case 내부에 계약서 원문 저장
- Case 내부에 판례 전문 저장
- Case 내부에 법령 전문 저장
- LLM 요약을 원본 Evidence처럼 저장
- 임대차 전용 필드를 Case Root에 직접 추가
- 승소확률 필드 추가
- 법적 책임 확정 필드 추가
- P1.2 이후 Entity를 임의 상세설계
- Workflow 전체를 P1.1에서 구현

---

# 14. 테스트 요구사항

최소 테스트:

1. 정상 Case 생성
2. 필수값 누락 실패
3. 잘못된 CaseStatus 실패
4. 잘못된 ResolutionStatus 실패
5. revision 초기값 검증
6. Case update 시 revision 증가
7. status 변경
8. invalid status transition input 거부
9. 참조 배열 기본값 검증
10. Serialization/Deserialization round trip

기존 Repository에 Test Framework가 있으면 반드시 재사용한다.

---

# 15. 추적성

관련 요구사항:

```text
P1.1 Case Model
SC-LEASE-001
SC-LEASE-002
SC-LEASE-003
P6 Workflow & Orchestration
```

후속 모델은 `case_id`를 Foreign Reference로 사용한다.

---

# 16. Definition of Done

P1.1은 다음 조건을 모두 만족해야 완료이다.

- Case Model 구현
- CaseStatus 구현
- ResolutionStatus 구현
- Runtime/Schema Validation 구현
- 생성/조회/수정/상태변경 기본 동작 구현
- 자동 Unit Test 구현
- 모든 관련 Test PASS
- 기존 기능 Regression 없음
- 변경파일 목록 제출
- 설계 변경사항 보고
- 다음 Task를 임의 진행하지 않음

---

# 17. 후속 Task

P1.1 승인 후에만:

> **P1.2 Party Model**

로 진행한다.
