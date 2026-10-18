# P1 결함 사전 코드 감사 보고서 (Current Code Audit)

**프로젝트:** AI Legal Helper  
**수행 일자:** 2026-10-18  
**감사 대상:** P1 — 신뢰성 및 논리 개선 (P1-01 ~ P1-06)  
**브랜치:** `main`  

---

## 1. P1 결함별 코드 감사 및 문제점 분석

### [P1-01] 검색 결과와 검색 장애 미구분
- **위치:** [`backend/src/ai_legal_helper/rag/retrieval.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/rag/retrieval.py)
- **현상:**
  - ChromaDB 연결 실패, 원격 HttpClient 타임아웃, 특정 법률 컬렉션 누락, 쿼리 불일치가 모두 `[]` (빈 리스트)로 반환됨.
  - `_get_client()`에서 오류 발생 시 조용히 `EphemeralClient()`로 폴백하여 아무 문서도 없는 빈 인덱스를 정상 연결로 오인.
  - 상위 `retrieval_factory.py` 및 `legal_workflow.py`는 지식 기반에 법률이 없는 것인지, 검색 시스템 장애인지 구분 불가.
- **수정 방향:** `RetrievalStatus` 열거형 및 `RetrievalResult` 구조체 도입, `retrieve_with_status()` 제공, 사용된 인덱스 정보(`used_index_info`) 기록.

---

### [P1-02] 법령 시행일 및 버전 관리 부재
- **위치:** [`backend/src/ai_legal_helper/rag/source_schema.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/rag/source_schema.py), [`backend/src/ai_legal_helper/tools/official_statute_search.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/tools/official_statute_search.py)
- **현상:**
  - `StandardSource`에 `law_id`, `version_id`(MST), `promulgation_date`(공포일자) 필드가 누락되어 법령 개정 이력 추적 불가.
  - 사건 발생 시점(예: 임대차계약 체결일 2020년, 갱신일 2022년, 해지통지일 2026년)과 법령 시행일 간의 비교 유틸리티 부재.
- **수정 방향:** `StandardSource` 스키마 확장, 법제처 XML 파싱 시 식별자 메타데이터 완전 수집, 사건 기준일 대조 함수 `is_statute_applicable_to_date()` 구현.

---

### [P1-03] Source Registry 및 Citation Validator의 법령 인용 한계
- **위치:** [`backend/src/ai_legal_helper/agents/verification.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/agents/verification.py)
- **현상:**
  - 인용 정규식 `CITATION_PATTERN`이 `(파일명.pdf, p.페이지)` 형태만 인식하여, 실무적인 `(주택임대차보호법 제6조의2)` 또는 `(민법 제623조)` 같은 실제 법령 인용을 인식하지 못하고 누락시킴.
  - 인용이 아예 없는 경우 `total_gen == 0`일 때 `citation_existence_rate`와 `citation_support_rate`를 `1.0(100%)`으로 잘못 계산.
  - 조문 번호는 맞지만 본문과 반대되는 효과(예: 3개월 후 효력 발생인데 당일 즉시 효력 발생 주장)를 단어 중첩만으로 통과시킬 위험 존재.
- **수정 방향:** 법령명+조문 인용 패턴 추가 지원, 의미적 반대/왜곡 효과 검증 로직 보강, 제로 분모 시 `N/A` 산출, `citation_coverage_rate` 평가 지표 추가.

---

### [P1-04] Adaptive Retrieval 의사결정 미흡
- **위치:** [`backend/src/ai_legal_helper/workflows/legal_workflow.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/workflows/legal_workflow.py)
- **현상:**
  - `verification_condition()`에서 부족 원인(법령 부재 vs 인프라 오류 vs 사실관계 증거 부족 vs 단순 초안 수정)을 세분화하지 않고 획일적으로 HILT 또는 revise를 시도할 수 있음.
  - 검색 인프라가 다운된 상황에서 반복 재검색을 시도하는 비효율 발생.
- **수정 방향:** `reason_code`에 따른 5단계 정밀 분기 정책 적용 (인프라 장애 시 복구 시도/안전 안내, 사실관계 부족 시 사용자 증거 요청, 단순 문구 수정 시 1회 revise).

---

### [P1-05] 상담 상태 모델 단일성
- **위치:** [`backend/src/ai_legal_helper/database/models.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/database/models.py), [`backend/src/ai_legal_helper/api/schemas/consultation.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/schemas/consultation.py)
- **현상:**
  - 상담 상태가 단일 `status`(`SUCCESS`, `IN_PROGRESS`, `APPROVAL_REQUIRED`, `ERROR`)로만 관리되어, HTTP 응답의 `SUCCESS`가 답변 검증 통과를 의미하는지 불분명함.
- **수정 방향:**
  - `execution_status`: `IN_PROGRESS`, `APPROVAL_REQUIRED`, `COMPLETED`, `FAILED`
  - `verification_status`: `PASS`, `REVISE`, `INSUFFICIENT`, `ERROR`, `UNVERIFIED`
  - `answer_status`: `VERIFIED`, `PARTIAL`, `WITHHELD`, `PENDING`
  - 3계층 상태 분리 및 DB 컬럼 매핑, 기존 `status` 하위 호환 유지.

---

### [P1-06] API 동시성 및 DB 일관성 취약
- **위치:** [`backend/src/ai_legal_helper/api/routes/consultation.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/routes/consultation.py)
- **현상:**
  - `_consultations` 딕셔너리를 메모리에 유지하여 서버 재시작 시 상태 유실 가능성 존재.
  - `decide_statute_search_approval()`에서 동시 요청 시 중복 resume을 방지하는 원자적 DB 행 잠금/조건부 UPDATE 미적용.
- **수정 방향:**
  - PostgreSQL `ConsultationRecord`를 SSOT(Single Source of Truth)로 확립하고 메모리 딕셔너리는 캐시로만 동작.
  - `WHERE request_id = :id AND status = 'APPROVAL_REQUIRED'` 조건부 원자적 업데이트를 통해 중복 승인 차단 (0행 업데이트 시 409 Conflict/400 Bad Request 반환).
  - DB Commit 실패 시 명시적 예외 처리 및 트랜잭션 롤백.

