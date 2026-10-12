# P2.2 Data Model 명세 (Case Intelligence)

## 1. 개요
AI Legal Helper의 P2.2 단계에서 단발성 질의를 넘어, 사건의 영속성과 맥락(Context)을 확보하기 위해 새로운 데이터 모델을 정의한다.
데이터베이스는 PostgreSQL 17을 기반으로 운영되며, SQLAlchemy 2.x ORM과 Alembic 마이그레이션 툴을 사용한다.

## 2. 엔터티(Entity) 명세

### 2.1 Case (사건)
최상위 단위로 하나의 상담 사건을 대표한다.
- `id` (PK, String, UUID)
- `title` (String): AI가 임시로 부여하는 사건 제목
- `case_type` (String): 법률 분야 (예: "주택임대차")
- `description` (Text): 개요 설명
- `status` (String): OPEN, IN_PROGRESS, CLOSED
- `version` (Integer): 동시성 충돌 방지(Optimistic Locking)용 버전 번호 (`version_id_col`)
- `created_at` (DateTime)
- `updated_at` (DateTime)

### 2.2 Party (당사자)
사건에 연루된 인물이나 단체를 지칭한다.
- `id` (PK, String, UUID)
- `case_id` (FK -> Case.id)
- `name` (String): 이름 또는 호칭
- `role` (String): 임차인, 임대인, 대리인 등
- `relationship` (String): 당사자 간 관계
- `notes` (Text): 추가 메모

### 2.3 Fact (사실관계)
사건에 포함된 개별 사실이나 주장. AI가 문장에서 분리해 낸다.
- `id` (PK, String, UUID)
- `case_id` (FK -> Case.id)
- `statement` (Text): 사실 진술문
- `fact_type` (String): 금액, 날짜, 행위, 조건 등
- `confidence` (Float): AI 추출 신뢰도
- `source_type` (String): USER_CLAIM, DOCUMENT_SUPPORTED, AI_INFERENCE 등
- `source_ref` (Text): 출처 참조
- `occurred_at` (String): 발생 시점 (문자열 형태)
- `verification_status` (String): UNVERIFIED, VERIFIED, DISPUTED
- `created_at` (DateTime)

### 2.4 Event (타임라인 이벤트)
시간 흐름에 따라 전개된 사건의 단위.
- `id` (PK, String, UUID)
- `case_id` (FK -> Case.id)
- `title` (String): 짧은 제목
- `description` (Text): 이벤트 설명
- `event_date` (String): YYYY-MM-DD 포맷 또는 대략적인 시기
- `date_precision` (String): EXACT, APPROXIMATE, UNKNOWN
- `event_type` (String): 계약, 통지, 지급, 위반 발생 등
- `related_fact_ids` (JSON): 해당 이벤트를 뒷받침하는 사실관계 ID 목록
- `created_at` (DateTime)

### 2.5 LegalIssue (법률 쟁점)
확정된 사실관계를 기반으로 검토가 필요한 법적 쟁점.
- `id` (PK, String, UUID)
- `case_id` (FK -> Case.id)
- `title` (String): 쟁점 (예: 보증금 반환 의무 발생 여부)
- `description` (Text): 쟁점 상세 설명
- `related_fact_ids` (JSON): 쟁점과 관련된 사실관계 ID
- `status` (String): OPEN, RESOLVED
- `created_at` (DateTime)

### 2.6 CaseRevision (사건 변경 이력)
새로운 진술이 추가될 때마다 사실관계와 타임라인이 갱신된 이력을 남긴다.
- `id` (PK, String, UUID)
- `case_id` (FK -> Case.id)
- `version` (Integer): 해당 이력이 저장될 때의 Case 버전
- `change_type` (String): FACTS_ADDED, ISSUE_RESOLVED 등
- `change_summary` (Text): "새로운 진술 2건 추가" 등 요약
- `changed_entity_ids` (JSON): 갱신되거나 추가된 엔터티 ID 목록
- `created_at` (DateTime)

## 3. 개인정보 보호 원칙
- 데이터베이스에 저장되는 원문(`source_ref`) 및 `statement` 등은 AI를 통한 최소한의 구조화/비식별화 조치를 취한 채 저장하는 것을 지향하며, 추후 파이프라인 단에서 정식 마스킹 AOP(P0) 모듈과 연동해야 한다.
