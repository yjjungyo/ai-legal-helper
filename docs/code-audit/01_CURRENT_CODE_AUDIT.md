# AI Legal Helper — 01. 현재 코드 구조 감사 및 P0 결함 재현 보고서

## 1. 개요

본 문서는 `AI Legal Helper 소스코드 결함 수정 및 품질 고도화 개발지시서`에 따라, 현재 저장소의 실제 소스코드를 조사하고 P0 등급의 핵심 결함 4건에 대한 재현(Reproduction) 결과를 기록한 감사 보고서이다.

- **감사 일시**: 2026-10-18
- **감사 대상 저장소**: `C:\myprjs\ai-legal-helper`
- **핵심 점검 모듈**:
  - `backend/src/ai_legal_helper/agents/verification.py`
  - `backend/src/ai_legal_helper/workflows/legal_workflow.py`
  - `backend/src/ai_legal_helper/tools/official_statute_search.py`
  - `backend/src/ai_legal_helper/workflows/state.py`

---

## 2. P0 결함별 코드 감사 및 재현 결과

### P0-01. Verification Agent Fail-open 취약점
- **위치**: `backend/src/ai_legal_helper/agents/verification.py` (라인 643~666)
- **현재 코드 현황**:
  ```python
  except Exception as e:
      logger.error(f"Verification Agent 오류: {str(e)}")
      has_citation_defect = bool(unverified_citations or unsupported_citations)
      fallback_status = "REVISE" if has_citation_defect else "PASS"
      return {
          "status": fallback_status,
          "reason_code": "NONE",
          "recommended_action": "FINALIZE",
          ...
      }
  ```
- **실제 원인**: LLM 호출 타임아웃, 네트워크 단절, 잘못된 JSON 응답, Pydantic 검증 실패 등 검증기 내부 예외가 발생할 때, 초안에 명시적 출처 결함(`unverified_citations`)이 발견되지 않으면 기본 상태값을 `PASS`로 설정하여 Fail-open됨.
- **재현 테스트**: `test_p0_defects_reproduction.py::test_p0_01_reproduce_verification_fail_open`
- **재현 결과**: **FAIL (결함 확인)** — 타임아웃 발생 시 `res['status'] == 'PASS'`를 반환하여 검증되지 않은 초안이 통과됨.

---

### P0-02. HILT 이후 검증 우회 및 비법령 사유 오분기
- **위치**: `backend/src/ai_legal_helper/workflows/legal_workflow.py` (`verification_condition`)
- **현재 코드 현황**:
  ```python
  # 2. HILT 진입 조건
  if not hilt_executed and candidate_laws and (
      reason_code in ("LEGAL_SOURCE_MISSING", "LEGAL_SOURCE_INSUFFICIENT")
      or (status in ("INSUFFICIENT", "REVISE") and reason_code != "NONE")
  ):
      return "statute_search_approval"

  # 4. HILT 이후 분기
  if hilt_executed:
      return "finalize"
  ```
- **실제 원인**:
  1. `hilt_executed == True`이면 2차 Verifier 검증 결과(status)가 `INSUFFICIENT`나 `ERROR`라 하더라도 무조건 `finalize`로 반환하여 검증 실패 답변을 확정함.
  2. `CASE_EVIDENCE_MISSING`(사건 사실/증거 부족)이나 `EVIDENCE_CONFLICT`(증거 간 모순)인 경우에도 `reason_code != "NONE"` 조건을 만족하여 법령 검색 HILT 노드로 오분기됨.
- **재현 테스트**:
  - `test_p0_defects_reproduction.py::test_p0_02_reproduce_hilt_bypass_verification_failure`
  - `test_p0_defects_reproduction.py::test_p0_02_reproduce_non_statute_issue_does_not_trigger_hilt`
- **재현 결과**: **FAIL (2건 모두 결함 확인)** — 2차 검증 실패 시 `finalize` 반환, 사건 증거 부족 시 `statute_search_approval` 반환.

---

### P0-03. LangGraph Checkpointer 휘발성(MemorySaver) 결함
- **위치**: `backend/src/ai_legal_helper/workflows/legal_workflow.py` (`get_checkpointer`)
- **현재 코드 현황**:
  ```python
  _checkpointer_instance = None
  def get_checkpointer():
      global _checkpointer_instance
      if _checkpointer_instance is None:
          _checkpointer_instance = MemorySaver()
      return _checkpointer_instance
  ```
- **실제 원인**: 인메모리 `MemorySaver`를 사용하므로 FastAPI 프로세스 또는 서버 재시작 시 메모리가 소멸되어 HILT 인터럽트 대기 상태(`__interrupt__`)가 증발함.
- **기술 조사 결과**:
  - 이미 `psycopg` 및 `langgraph.checkpoint.postgres.aio`(`AsyncPostgresSaver`) 라이브러리가 환경에 설치되어 있음.
  - PostgreSQL 내에 `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` 테이블 생성 및 프로세스 간 재개(Cross-Process Resume) 동작 가능 확인.

---

### P0-04. 공식 법령 검색 통신 보안 및 임의 법령 채택 결함
- **위치**: `backend/src/ai_legal_helper/tools/official_statute_search.py`
- **현재 코드 현황**:
  ```python
  search_url = f"http://www.law.go.kr/DRF/lawSearch.do?OC={api_key}&target=law&type=XML&query={encoded_name}"
  ...
  if matched_elem is None:
      matched_elem = search_root.find(".//law")  # 검색 결과의 첫 번째 법령 임의 선택
  ```
- **실제 원인**:
  1. `http://` 프로토콜을 사용하여 평문 통신 보안 취약점 존재 (테스트 결과 `https://`가 정상 지원됨).
  2. 법령명 완전 일치 및 정제 일치가 모두 실패했을 때 `search_root.find(".//law")`로 첫 번째 법령을 임의 채택하여 엉뚱한 법령 조문이 인용될 위험 존재.
  3. API 키가 URL에 노출되어 로깅이나 에러 추적 시 노출될 위험 존재.

---

## 3. 재현 테스트 요약표

| 테스트 ID | 결함 구분 | 재현 조건 | 현재 실행 결과 | 판정 |
|---|---|---|---|:---:|
| `test_p0_01` | P0-01 | Verifier LLM 타임아웃 예외 발생 | `status: PASS` 반환 | **재현 완료 (결함)** |
| `test_p0_02_1` | P0-02 | HILT 완료 후 2차 검증 INSUFFICIENT | `finalize`로 강제 전이 | **재현 완료 (결함)** |
| `test_p0_02_2` | P0-02 | `CASE_EVIDENCE_MISSING` (증거 부족) | `statute_search_approval` 오분기 | **재현 완료 (결함)** |
| `test_p0_03` | P0-03 | 프로세스 종료 후 체크포인트 상태 복원 | MemorySaver 휘발로 상태 소실 | **재현 완료 (결함)** |
| `test_p0_04` | P0-04 | 비보안 HTTP 호출 및 임의 법령 Fallback | http:// 호출 및 첫번째 법령 매칭 | **재현 완료 (결함)** |

