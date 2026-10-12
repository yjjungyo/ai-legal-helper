# P2.2 테스트 결과 보고서 (Test Report)

## 1. 개요
P2.2 Case Intelligence 기능 검증을 위해, 요구사항에 명시된 "실제 시나리오 검증 (주택임대차 분쟁)"을 바탕으로 테스트(`tests/test_case_intelligence.py` 및 `tests/integration/test_db_postgres.py`)를 작성하고 실행하였다.

## 2. 테스트 환경
- **로컬 환경**: `pytest`, `PostgreSQL 17`, `Alembic`, `psycopg 3`
- **LLM**: Azure OpenAI `gpt-4o` (Fact Extraction, Timeline Generation, Missing Info Detection, Supervisor)
- **테스트 케이스 시나리오**:
  1. 데이터베이스 트랜잭션 정상 동작, Optimistic Locking 예외, 마이그레이션 적용 확인
  2. 임대차 계약 체결
  3. 계약의 묵시적 갱신
  4. 해지 통지
  5. 보증금 반환 거절
  6. 추가 증거 (문자 내역)

## 3. 검증 항목 및 결과

| 검증 항목 | 설명 | 상태 | 비고 |
|---|---|:---:|---|
| PostgreSQL 연결 및 마이그레이션 | DB 연동, Alembic 마이그레이션, 트랜잭션 정상 동작 | PASS | `.env` 로드 및 `test_db_postgres.py` 정상 확인 |
| 사건 생성 및 영속 저장 | `Case` 테이블에 데이터가 생성되고 UUID가 반환됨 | PASS | PostgreSQL 기반 CRUD 정상 동작 |
| 당사자·사실관계 구조화 | `ExtractedFact`, `ExtractedParty` JSON 파싱 및 DB 적재 | PASS | "임대인", "계약 갱신" 등 사실 도출 확인 |
| 사건 타임라인 생성 | 날짜가 포함된 사실들을 시계열로 정렬하여 `Event` 생성 | PASS | 2022-03 -> 2024-03 -> 2024-05 순 정렬 확인 |
| 정보 부족 탐지 | `missing_info_questions`에 추가 쟁점 포함 여부 | PASS | "보증금 반환 기일은 언제인가?" 등 |
| 신규 진술 추가 및 변경 이력 | 동일 사건에 대해 진술이 추가될 때 `CaseRevision` 레코드 증가 | PASS | 진술 5회 추가에 따라 버전 5까지 증가 |
| 동시성 충돌 방지 및 안전성 | 다중 클라이언트 환경에서 `version_id_col` 충돌 검증 및 Rollback 검증 | PASS | `StaleDataError` 정상적으로 예외 처리됨 |
| 사건 기반 Supervisor | `case_id`로 사건 컨텍스트 조회 후 LangGraph 주입 | PASS | 기존 `LegalState`의 `case_context`를 통해 답변 도출 확인 |

## 4. 이슈 사항
- `AzureChatOpenAI`가 `with_structured_output`을 지원하지 않아서 예외가 발생할 가능성이 있으나, JSON 프롬프트 + Pydantic 예외처리 방식으로 fallback 로직을 구현하여 통과함.
- 동시성 충돌 방지는 PostgreSQL 환경에서 SQLAlchemy의 Optimistic Locking(`version_id_col`)을 도입하여 해결 완료.
