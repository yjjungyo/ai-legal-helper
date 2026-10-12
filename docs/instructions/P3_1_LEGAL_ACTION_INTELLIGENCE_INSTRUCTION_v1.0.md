# AI Legal Helper — P3.1 Legal Action Intelligence 개발지시서 v1.0

**프로젝트:** `C:\myprjs\ai-legal-helper`  
**개발 단계:** P3.1 — Legal Action Intelligence  
**대상 분야:** 대한민국 주택 임대차 분쟁  
**핵심 목표:** 사건 분석 결과를 근거 기반의 실행 가능한 법률 대응 계획으로 변환한다.

## 1. 개발 배경

현재 P2.5까지 구현된 기능은 다음과 같다.

- LangGraph 기반 Multi-Agent 분석
- 사건 사실 및 타임라인 관리
- 증거 업로드, 추출, 사용자 검토
- PostgreSQL 사건 데이터 관리
- ChromaDB 법률·증거 검색
- Neo4j Evidence GraphRAG
- Supervisor 및 Verification Agent
- React 사건 관리 UI

이제 법률 분석 결과를 실제 사용자의 대응 행동으로 연결해야 한다.

핵심 질문:

1. 현재 사건에서 사용자가 취할 수 있는 행동은 무엇인가?
2. 각 행동에 필요한 법률 요건은 무엇인가?
3. 어떤 증거가 확보되었고 무엇이 부족한가?
4. 행동의 선행조건과 순서는 무엇인가?
5. 법률상 기한과 실무상 권고 시점을 어떻게 구분할 것인가?
6. 사건 정보가 변경되면 대응 계획을 어떻게 갱신할 것인가?

## 2. 개발 원칙

1. 기존 P0~P2.5 기능을 보존한다.
2. `ai-legal-agent` 원본 프로젝트는 수정하지 않는다.
3. PostgreSQL을 사건 및 Action 상태의 Source of Truth로 사용한다.
4. Neo4j는 행동의 근거 및 의존 관계 탐색에 활용한다.
5. LLM은 행동 후보를 제안할 수 있지만 법적 적합성을 단독 확정하지 않는다.
6. 법률 요건·기한·절차에 관한 주장은 확인 가능한 출처를 연결한다.
7. 법률상 의무, 선택 가능한 절차, 일반적 실무 권고를 명확히 구분한다.
8. 사건에 필요한 정보가 부족하면 확정적 행동 대신 확인 질문을 제시한다.
9. 사용자 승인 없이 법률문서 발송, 법원 제출, 외부 서비스 신청을 수행하지 않는다.
10. 실제 변호사의 개별 사건 판단을 대체한다고 표현하지 않는다.

## 3. Action Domain Model

PostgreSQL에 다음 모델을 설계한다.

### LegalAction

- `id`
- `case_id`
- `action_type`
- `title`
- `description`
- `priority`
- `status`
- `rationale`
- `risk_level`
- `confidence`
- `created_at`
- `updated_at`

### ActionRequirement

- `id`
- `action_id`
- `requirement_type`
- `description`
- `satisfaction_status`
- `supporting_evidence_ids`
- `legal_source_ids`

### ActionDependency

- `id`
- `action_id`
- `depends_on_action_id`
- `dependency_type`

### ActionDeadline

- `id`
- `action_id`
- `deadline_type`
- `deadline_date`
- `calculation_basis`
- `legal_source_ids`
- `verification_status`

### ActionRevision

- `id`
- `case_id`
- `case_revision_id`
- `action_plan_version`
- `change_summary`
- `created_at`

기존 모델과 중복되는 필드나 엔터티가 있다면 재사용하고 설계 근거를 기록한다.

모든 데이터 변경에 Alembic 마이그레이션을 적용한다.

## 4. Legal Action Planner

LangGraph에 `LegalActionPlanner`를 구현한다.

입력:

- 사건의 승인된 사실
- 사건 타임라인
- 승인된 증거 및 EvidenceSpan
- LegalIssue
- GraphRAG 관계 경로
- 법령·판례 검색 결과
- 기존 Action 상태
- CaseRevision

출력:

- 추천 행동 목록
- 추천 이유
- 관련 법률 쟁점
- 선행조건
- 필요한 증거
- 확인되지 않은 사실
- 예상 위험
- 법률상 기한 또는 확인 필요 상태
- 근거 출처
- 행동 우선순위

LLM의 자유 형식 응답을 직접 저장하지 말고 Pydantic 구조화 출력으로 검증한다.

## 5. 주택 임대차 Action Catalog

우선 다음 행동 유형을 검토 대상으로 구현한다.

- 계약 종료 의사표시 및 도달 사실 확인
- 보증금 반환 요구
- 내용증명 작성 준비
- 계약서 및 통지 기록 확보
- 임대차 관련 법률 요건 확인
- 임차권등기명령 신청 가능성 검토
- 지급명령 또는 보증금 반환 청구 소송 검토
- 강제집행 등 후속 절차 검토
- 보증보험 가입·보증이행 관련 사항 확인
- 전문 법률 상담 권고

**주의:** 이 목록은 자동 추천 확정 목록이 아니라 법률 요건 검토를 위한 후보 Catalog이다.

각 행동에 적용되는 법률 요건, 절차, 관할, 선행조건 및 기한은 실제 근거를 검증한 뒤 제시한다.

모든 사건에 모든 행동을 추천하지 않는다.

## 6. Action Reasoning 및 우선순위

행동 우선순위는 다음 요소를 반영한다.

- 법률상 기한의 긴급성
- 권리 보전 필요성
- 증거 확보의 시급성
- 선행조건 충족 여부
- 사용자의 목표
- 절차상 위험
- 예상 비용 및 복잡성

초기에는 설명 가능한 규칙 기반 우선순위를 우선 적용한다.

LLM의 판단은 보조 신호로 사용한다.

우선순위 점수 및 추천 이유를 사용자가 이해할 수 있도록 기록한다.

## 7. Deadline Engine

법률상 기한을 단순히 LLM에 계산시키지 않는다.

- 기준일
- 적용 법률
- 법률 요건
- 계산 규칙
- 확인되지 않은 조건
- 결과 검증 상태

위 항목을 구조화하여 처리한다.

명확한 근거가 없거나 필수 날짜가 누락된 경우 임의의 기한을 생성하지 않는다.

`LEGAL_DEADLINE`, `RECOMMENDED_DATE`, `UNKNOWN`을 구분한다.

기한 계산 로직은 독립적인 단위 테스트로 검증한다.

## 8. Action Verification

기존 Verification Agent를 확장한다.

다음 사항을 검증한다.

1. 행동이 현재 사건과 관련 있는가?
2. 필요한 사실이 확인되었는가?
3. 근거 증거가 현재 사건에 속하는가?
4. 증거의 승인 상태가 유효한가?
5. 법령·판례 근거가 실제 존재하는가?
6. 법률상 요건을 충족하지 않았는데 행동을 확정적으로 권고하지 않는가?
7. 기한 계산에 충분한 정보가 있는가?
8. 행동 간 선후 관계에 모순이 없는가?
9. 반대 증거 또는 불확실성을 누락하지 않았는가?
10. 법률적 결론과 일반적 정보 제공을 구분하는가?

검증 실패 시 행동을 수정하거나 보류 상태로 전환한다.

## 9. Action Plan Revision

사건 정보가 변경되면 기존 행동 계획을 재평가한다.

예:

- 임대인의 보증금 반환 약속 변경
- 계약 해지 통보일 정정
- 신규 증거 승인
- 기존 증거 반려
- 새로운 법률 쟁점 발견

변경 전후 Action Plan을 비교하여 다음을 표시한다.

- 새로 추가된 행동
- 변경된 행동
- 더 이상 필요하지 않은 행동
- 우선순위 변경
- 기한 변경
- 변경 이유

사용자가 직접 완료 표시한 행동 상태를 AI 재분석 과정에서 임의로 초기화하지 않는다.

## 10. Neo4j Action Graph 연동

기존 Knowledge Graph를 확장한다.

예상 관계:

- `ACTION_ADDRESSES_ISSUE`
- `ACTION_REQUIRES_FACT`
- `ACTION_REQUIRES_EVIDENCE`
- `ACTION_GROUNDED_IN_AUTHORITY`
- `ACTION_DEPENDS_ON_ACTION`

기존 관계 스키마와 충돌하거나 중복되지 않도록 검토한다.

모든 Action 관계는 PostgreSQL의 유효한 원본 ID와 연결한다.

AI가 생성한 미검증 관계를 확정 사실처럼 저장하지 않는다.

## 11. FastAPI

기존 API 구조를 따르되 다음 기능을 제공한다.

- 사건별 Action Plan 생성
- Action Plan 조회
- 행동 상세 조회
- 행동 상태 변경
- 계획 재평가
- 계획 버전 비교
- 관련 증거 및 법률 근거 조회

API에는 사건 ID 검증, 입력 스키마 검증, 오류 처리, 트랜잭션 관리 및 테스트를 적용한다.

## 12. React UI

기존 Case Workspace에 `Action Plan` 탭을 추가한다.

필수 화면:

- 우선순위별 추천 행동 목록
- 각 행동의 추천 이유
- 법률상 기한과 권고 시점 구분
- 행동별 필요 증거 체크리스트
- 선행조건 및 미확인 사항
- 행동 완료 상태 관리
- Action Plan 변경 이력
- 관련 Evidence Graph 연결
- 근거 출처 상세 보기

추천 행동과 사용자가 실제 수행한 행동을 명확하게 구분한다.

UI는 기존 React 디자인 시스템과 통일한다.

## 13. 테스트 시나리오

대표 사건은 **전세보증금 미반환**으로 한다.

필수 검증:

1. 계약 종료 통지일이 있는 사건
2. 종료 통지일이 없는 사건
3. 보증금 반환 약속 증거가 있는 사건
4. 상충 증거가 존재하는 사건
5. 보증금 일부만 반환된 사건
6. 계약 종료 여부가 불명확한 사건
7. 사건 정보 수정 후 Action Plan 갱신
8. 승인 취소된 증거가 있는 사건
9. 법률 근거 검색 실패
10. 기한 계산 필수 정보 누락
11. 다른 사건 데이터 혼입 시도
12. Neo4j 장애 시 대응

기존 회귀 테스트도 수행한다.

## 14. AI Master 평가 준비

이번 단계에서는 다음 질문에 답할 수 있어야 한다.

- 왜 단순 법률 상담을 넘어 Action Planner를 개발했는가?
- 왜 LLM에게 모든 행동 결정을 맡기지 않았는가?
- 행동 추천의 법률적 신뢰성을 어떻게 확보했는가?
- 법률상 기한을 어떻게 계산하고 검증하는가?
- 사건 변경 시 대응 계획을 어떻게 유지하는가?
- GraphRAG는 행동 추천에 어떤 실질적 기여를 하는가?
- 이 기능이 사용자에게 제공하는 비즈니스 가치는 무엇인가?

각 질문에 대해 설계 이유, 구현 위치, 테스트 결과, 한계를 기록한다.

## 15. 필수 산출물

- `docs/instructions/P3_1_LEGAL_ACTION_INTELLIGENCE_INSTRUCTION_v1.0.md`
- `docs/architecture/P3_1_ACTION_INTELLIGENCE_ARCHITECTURE.md`
- `docs/architecture/P3_1_ACTION_DOMAIN_MODEL.md`
- `docs/adr/P3_1_ACTION_PLANNER_DECISIONS.md`
- `docs/development/P3_1_IMPLEMENTATION_LOG.md`
- `docs/development/P3_1_ISSUE_RESOLUTION.md`
- `docs/evaluation/P3_1_TEST_REPORT.md`
- `docs/evaluation/P3_1_MASTER_QA.md`
- `docs/evaluation/P3_1_COMPLETION_REPORT.md`

