# P0 결함 수정 및 구현 변경 이력 (Changelog)

**프로젝트:** AI Legal Helper  
**수행 일자:** 2026-10-18  
**구현 단계:** P0 — 필수 결함 수정  
**원칙 준수:** 하드코딩 금지, CODING_COMMENT_STANDARD 준수, 기존 기능 및 회귀 무결성 보존  

---

## 1. 개요

본 문서는 AI Legal Helper 소스코드 결함 수정 및 품질 고도화 개발지시서에 따른 **P0 단계 필수 결함 4건(P0-01 ~ P0-04)**의 실제 소스코드 변경 내역 및 설계 결정 사항을 기록한다.

---

## 2. 결함별 상세 변경 내역

### [P0-01] Verification Agent Fail-open 취약점 제거 및 Safe Fallback 도입

- **수정 파일:** [`backend/src/ai_legal_helper/agents/verification.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/agents/verification.py)
- **주요 변경 사항:**
  1. `VerificationOutput` 스키마 확장:
     - `reason_code`에 `VERIFICATION_ERROR` 추가.
     - `recommended_action`에 `SAFE_FALLBACK` 추가.
  2. 일시적 네트워크/타임아웃 장애에 대한 1회 제한적 재시도 루프 도입:
     - `(TimeoutError, ConnectionError)` 발생 시 지수 백오프로 최대 1회 재시도.
  3. 예외 핸들러 Fail-open 완전 제거:
     - 검증 처리 중 예외 발생 시 인용 오류 여부와 상관없이 무조건 `status: "INSUFFICIENT"`, `reason_code: "VERIFICATION_ERROR"`, `recommended_action: "SAFE_FALLBACK"` 반환.
     - 사용자에게 검증 시스템 장애 사실 및 전문가 상담 권고 경고 메시지 전달.
  4. LangChain / Mock 호환성 개선:
     - `prompt | llm` 체인 대신 `llm.invoke(formatted_prompt)` 직접 호출 구조로 표준화하여 `Runnable` 및 단위 테스트 모의 객체(`mock_llm.invoke`) 간의 시그니처 불일치 방지.

### [P0-02] HILT 이후 검증 우회 취약점 제거 및 안전한 전이 보장

- **수정 파일:** [`backend/src/ai_legal_helper/workflows/legal_workflow.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/workflows/legal_workflow.py)
- **주요 변경 사항:**
  1. HILT 조건 분기 엄격화:
     - HILT 승인 요청(`statute_search_approval`)은 오직 `reason_code in ("LEGAL_SOURCE_MISSING", "LEGAL_SOURCE_INSUFFICIENT")`이고 `candidate_laws`가 존재할 때만 진입.
     - 사실관계 부족(`CASE_EVIDENCE_MISSING`)이나 단순 초안 수정 필요 시에는 HILT로 잘못 분기하지 않고 정상 분기하도록 차단.
  2. HILT 수행 후 검증 우회 차단:
     - `if hilt_executed: return "finalize"` 코드를 완전 제거.
     - 오직 `status == "PASS"`인 경우에만 `finalize`로 전이 허용.
     - HILT 이후 재분석 결과가 여전히 `INSUFFICIENT` 또는 `ERROR`인 경우 안전하게 `insufficient` 노드로 라우팅되어 불완전한 초안의 사용자 노출을 원천 방지.

### [P0-03] LangGraph Checkpointer의 PostgreSQL 영속 저장소 전환

- **수정 파일:**
  - [`backend/src/ai_legal_helper/workflows/legal_workflow.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/workflows/legal_workflow.py)
  - [`backend/src/ai_legal_helper/api/main.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/main.py)
  - [`backend/tests/conftest.py`](file:///c:/myprjs/ai-legal-helper/backend/tests/conftest.py) (신규 생성)
- **주요 변경 사항:**
  1. `AsyncPostgresSaver` 기반 영속 저장소 구축:
     - `get_postgres_conn_string()`을 통해 SQLAlchemy PostgreSQL URL을 psycopg 호환 연결 문자열로 변환.
     - 기본 `CHECKPOINTER_TYPE="postgres"` 환경에서 `AsyncPostgresSaver.from_conn_string()` 컨텍스트 매니저를 통해 체크포인트 자동 보존 및 복원.
     - 격리 테스트 환경을 위해 `CHECKPOINTER_TYPE="memory"` 옵션 및 `get_memory_checkpointer()` 하위 호환성 제공.
  2. 앱 라이프사이클(`lifespan`) 자동 테이블 초기화:
     - `init_checkpointer()` 함수를 구현하여 서버 기동 시 `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations` 테이블을 자동 idempotent setup.
  3. 존재하지 않는 thread 방어 예외 처리:
     - `run_legal_consultation`에서 `resume_data` 호출 시 지정된 `thread_id`의 체크포인트가 없으면 `ValueError("해당 thread_id(...)에 대기 중이거나 저장된 워크플로우 상태가 존재하지 않습니다.")`를 즉시 발생.
  4. Windows Selector EventLoop 정책 보장:
     - Windows 환경에서 psycopg async 드라이버의 ProactorEventLoop 호환성 문제를 해결하기 위해 `WindowsSelectorEventLoopPolicy`를 `main.py`, `legal_workflow.py`, `tests/conftest.py`에 적용.

### [P0-04] 공식 법령 검색 HTTPS 강제, 인증키 마스킹, 임의 fallback 제거

- **수정 파일:** [`backend/src/ai_legal_helper/tools/official_statute_search.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/tools/official_statute_search.py)
- **주요 변경 사항:**
  1. HTTPS 프로토콜 강제:
     - `lawSearch.do` 및 `lawService.do` API 엔드포인트를 `https://www.law.go.kr/...`로 강제 전환.
  2. API 키 마스킹 기능(`mask_api_key`) 도입:
     - 요청 URL, 로깅, 예외 메시지에서 `LAW_OPENAPI_KEY` 및 `OC=[MASKED]` 마스킹 처리하여 정보 유출 차단.
  3. 임의 법령 채택 Fallback 제거:
     - 후보 법령 검색 결과 불일치 시 첫 번째 법령을 임의 선택하던 `search_root.find(".//law")` fallback 로직을 완전 삭제. 일치하지 않으면 즉시 경고 기록 후 건너뜀.
  4. 네트워크 오류에 대한 1회 지수 백오프 재시도:
     - `_fetch_xml_with_retry()` 헬퍼 함수를 통해 타임아웃 또는 네트워크 단절 시 1회 대기 후 재시도 수행.

---

## 3. 수정 파일 요약

| 파일 경로 | 수정 유형 | 관련 결함 |
|---|---|---|
| `backend/src/ai_legal_helper/agents/verification.py` | 수정 | P0-01 |
| `backend/src/ai_legal_helper/workflows/legal_workflow.py` | 수정 | P0-02, P0-03 |
| `backend/src/ai_legal_helper/tools/official_statute_search.py` | 수정 | P0-04 |
| `backend/src/ai_legal_helper/api/main.py` | 수정 | P0-03 |
| `backend/tests/conftest.py` | 신규 | P0-03 |
| `backend/tests/unit/test_p0_defects_reproduction.py` | 신규 | P0-01 ~ P0-04 |

