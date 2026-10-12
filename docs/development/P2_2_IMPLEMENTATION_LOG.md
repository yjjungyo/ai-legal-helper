# P2.2 구현 로그 (Implementation Log)

## 구현된 주요 컴포넌트

### 1. Database & Models (`database/`)
- `session.py`: PostgreSQL 17 연동 (`psycopg 3`), `.env` 기반 설정 완료.
- `models.py`: `Case`, `Party`, `Fact`, `Event`, `LegalIssue`, `CaseRevision` 엔터티 정의. 동시성 충돌 방지를 위해 `version` 컬럼 및 `__mapper_args__` 추가 (Optimistic Locking).
- 마이그레이션 도구로 `Alembic` 도입 완료 및 초기화.

### 2. Case Intelligence Service (`case_intelligence/`)
- `extractor.py`: Azure OpenAI의 `with_structured_output` 미지원 문제를 해결하기 위해 표준 JSON 포맷을 요청하는 프롬프트를 구성하여 당사자, 사실, 추가 질문 추출.
- `timeline.py`: 추출된 Fact 중 `occurred_at`이 존재하는 데이터를 바탕으로 `Event` 엔터티 생성 (모호한 날짜 처리 포함).
- `manager.py`: `process_new_statement` 함수에서 위 모듈들을 조율하며, 트랜잭션을 사용하여 원자성 보장. 변경 발생 시 `CaseRevision` 기록.

### 3. API Routes & Schemas (`api/`)
- `schemas/case.py`: Case 엔터티들의 직렬화 및 검증을 위한 Pydantic 모델.
- `routes/cases.py`: CRUD 엔드포인트 구현 (사건 생성, 진술 추가, 상세 조회 등).
- `main.py`: `cases.router` 등록.

### 4. Supervisor 연동 (`workflows/`)
- `state.py`: `LegalState`에 `case_context` 필드 추가.
- `legal_workflow.py`: `supervisor_initialize_node`에서 `case_id` 존재 시 DB를 조회하여 사건의 기본 정보, 사실, 타임라인을 문자열로 조립해 `case_context`에 할당. 이를 `run_agents_node`에서 전문 에이전트에게 `chat_brief`와 함께 전달.

### 5. Frontend React UI (`frontend/`)
- `types/case.ts`: TypeScript 인터페이스 선언.
- `api/caseClient.ts`: FastAPI 연동.
- `hooks/useConsultation.ts`: `caseId` 파라미터 연동.
- `App.tsx`: 단순 상태 기반 라우팅을 이용해 `CaseList`, `CaseDetail`, `Consultation(Chat)` 뷰 구현.
- `App.css`: 카드/그리드 형태의 스타일링 추가.

## 주요 고려사항 및 제약
- **개인정보 보호**: 현재 버전에서는 DB에 원문이 그대로 저장되나, 추후 비식별화 파이프라인 추가 필요.
- **동시성 충돌 방지**: PostgreSQL 환경에서 SQLAlchemy의 Optimistic Locking(`version_id_col`)을 도입하여 클라이언트 간 동시 수정 충돌 해결.
- **주석 준수**: 모든 새 코드에 한국어 모듈, 함수 Docstring 및 `AGENTS.md` 규범 준수.
