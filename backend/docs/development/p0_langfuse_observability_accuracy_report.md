# LAWYER — Langfuse Observability 고도화 v2.0 1차(정확성 확보) 완료 보고서

**대상 브랜치:** `feature/langfuse-observability-v2.0`  
**기준 Git SHA:** `a2546bd7d2b347e58b34173afa8ee9e182022052`  
**시스템 식별자:** `LegalAgent`  
**완료 일자:** 2026-10-28  

---

## 1. 개요 및 추진 목표

"LAWYER — Langfuse Observability 고도화 개발지시서 v2.0"의 **1차 (정확성 확보)** 단계에 따라 다음 3개 핵심 과제를 완료하였습니다:

1. **P0-1 — 중복 Generation 계측 조사 및 단일화:** LLM 실제 호출 1회당 Langfuse Generation이 정확히 1회 기록되도록 단일 계측 경로(`TokenTrackingCallbackHandler`) 확립, Generation 이름 및 태그를 `LegalAgent`로 통일.
2. **P0-2 — Span 부모·자식 관계 개선 및 사건별 격리:** 전역 이름 기반 `_active_spans_by_name` 구조로 인한 동시 상담 간 부모 오염 원천 차단, `trace_id` 스코프의 격리 인덱스 및 활성 스팬 스택 도입, `end_trace` 시 메모리 완전 해제.
3. **P0-3 — 상담 실행 Trace 표준화:** 상담 실행 Trace의 공식 이름을 `LegalConsultation`으로 표준화, HTTP 미들웨어-백그라운드 태스크 간 지연 덮어쓰기 문제 해결, `case_id`, `request_id`, `session_id`, `run_id`, `git_commit` 표준 메타데이터 자동 주입.

---

## 2. 주요 개선 내용

### P0-1: 단일 Generation 계측 경로 확립
- **원인 분석:** `gateway.py`에서 `AzureChatOpenAI` 초기화 시 Langfuse `CallbackHandler`를 중복 주입할 경우 LangChain 자동 콜백과 `TokenTrackingCallbackHandler`의 수동 계측이 이중으로 Generation을 생성할 위험이 있었습니다.
- **개선 조치:**
  - `TokenTrackingCallbackHandler`를 유일한 Generation 기록 책임자로 명확히 확립 (`callbacks.py`).
  - LLM 모델 인스턴스에 `name="LegalAgent"`, `tags=["LegalAgent"]` 주입하여 SDK 내부에서도 `AzureChatOpenAI` 대신 `LegalAgent` 식별자 일관 유지.
  - 실패한 LLM 호출(`on_llm_error`)은 `status_message` 및 에러 상세를 Generation에 별도 기록하여 재시도 및 실패를 명확히 구분.

### P0-2: trace_id 단위 Span 격리 및 스택 관리
- **원인 분석:** 기존 `_active_spans_by_name: Dict[str, str]`은 전역 딕셔너리로 관리되어, 복수의 사용자가 동시에 상담을 진행하거나 노드가 반복 호출될 때 한 상담의 하위 작업이 다른 상담의 부모 Span에 오염 연결되는 위험이 존재했습니다.
- **개선 조치 (`langfuse_client.py`):**
  - `_trace_spans: Dict[str, Dict[str, Any]]`: `trace_id`별 격리 Span 캐시.
  - `_trace_spans_by_name: Dict[str, Dict[str, List[str]]]`: `trace_id`별 노드명 활성 스팬 ID 스택(Stack).
  - `_span_to_trace: Dict[str, str]`: Span ID에서 역방향으로 `trace_id`를 추적하는 인덱스.
  - Span 탐색 우선순위 확립: (1) `ContextVar` UUID -> (2) `trace_id` 내부 이름 스택의 최신 스팬(`[-1]`) -> (3) Root Trace 연결 (오염 방지).
  - `end_trace(trace_id)` 호출 시 해당 Trace에 귀속된 모든 인덱스 및 스팬 인스턴스를 완전 회수하여 메모리 누수 방지.

### P0-3: 상담 Trace 명명 및 메타데이터 표준화
- **원인 분석:** `api/main.py`의 HTTP 미들웨어가 `HTTP:POST_/api/v1/consultations`라는 임시 이름으로 Trace를 먼저 시작하고 응답 반환 직후 `end_trace`를 호출하여, 백그라운드 태스크 `process_consultation` 실행 도중 활성 Trace가 유실되거나 Langfuse 대시보드에서 `HTTP:...` 이름으로 조회되는 결함이 있었습니다.
- **개선 조치:**
  - `api/main.py`: 상담 요청(`POST /api/v1/consultations`)은 시작 즉시 공식 Trace 이름인 `LegalConsultation`으로 명명하고, HTTP 완료 시점의 조기 `end_trace`를 건너뜀.
  - `api/routes/consultation.py`: `process_consultation` 및 `process_consultation_resume` 진입 시 `start_trace(..., name="LegalConsultation", metadata=...)`를 호출하여 Trace 메타데이터를 정식 확장.
  - `langfuse_client.py`: 이미 생성된 Trace ID로 `start_trace`가 재호출될 경우 기존 활성 Trace의 `name`, `session_id`, `metadata`, `tags`를 안전하게 `.update()`하도록 보강.
  - 메타데이터에 `case_id`, `request_id`, `session_id`, `run_id`, `git_commit`(`get_git_commit()`), `system_name`(`LegalAgent`)을 자동 주입.
  - 백그라운드 태스크 종료(`finally:`) 시점에 `end_trace(trace_id)`를 호출하여 정상 정리 완료.

---

## 3. 검증 결과

### 단위 테스트 5종 신규 개발 (`test_langfuse_observability_p0.py`)

| 테스트 케이스 | 대상 요구사항 | 내용 | 결과 |
|---|---|---|---|
| `test_tc01_single_trace_and_generation_instrumentation` | P0-1, P0-3 | Trace 이름 `LegalConsultation`, LLM 1회 호출 시 1회 Generation 기록 및 태그/토큰 검증 | **PASS** |
| `test_tc02_concurrent_traces_span_isolation` | P0-2 | 동시 실행 상담 간 동일 노드명(`supervisor_initialize`) Span 상호 오염 차단 검증 | **PASS** |
| `test_tc03_nested_span_stack_and_cleanup` | P0-2 | 중첩·반복 에이전트 실행 시 Span 스택 관리 및 `end_span()` 시 부모 복원 검증 | **PASS** |
| `test_tc04_git_commit_and_system_metadata_injection` | P0-3 | Git Commit SHA 및 `LegalAgent` 메타데이터 자동 주입 검증 | **PASS** |
| `test_tc05_end_trace_memory_cleanup` | P0-2 | `end_trace()` 호출 시 `_trace_spans`, `_trace_spans_by_name` 메모리 정리 검증 | **PASS** |

### 회귀 및 전체 테스트 결과

1. **Observability 단위 테스트 20종:** **전체 PASS** (`test_langfuse.py`, `test_observability_enhanced.py`, `test_langfuse_observability_p0.py`)
2. **사건 독립성 및 법률 판단 회귀 테스트 37종:** **전체 PASS** (`test_case_independence_counterexamples.py`)
3. **프론트엔드 빌드 검증:** TypeScript 컴파일 및 Vite 번들링 무결성 확인 (0 Errors, 221ms 완료)

---

## 4. 변경 파일 목록

- `backend/src/ai_legal_helper/observability/langfuse_client.py`
  - `get_git_commit()` 추가
  - `_trace_spans`, `_trace_spans_by_name`, `_span_to_trace` 격리 인덱스 추가
  - `start_trace()` 내 기존 Trace 업데이트 로직(P0-3) 및 Git SHA 주입
  - `end_trace()` 내 격리 인덱스 정리 로직(P0-2)
  - `start_span()`, `end_span()`, `update_span()`, `log_generation()` 리팩토링
- `backend/src/ai_legal_helper/api/main.py`
  - 상담 파이프라인(POST) `LegalConsultation` 명명 및 조기 `end_trace` 지연 처리
- `backend/src/ai_legal_helper/api/routes/consultation.py`
  - `process_consultation` 및 `process_consultation_resume`에 표준 메타데이터 주입 및 워크플로우 완료 시 `end_trace()` 호출
- `backend/tests/unit/test_langfuse_observability_p0.py`
  - P0-1, P0-2, P0-3 종합 단위 테스트 5종 추가

---

## 5. 지침 준수 및 다음 단계 안내

> [!NOTE]
> `AGENTS.md` 지침에 따라 1차 (정확성 확보: P0-1, P0-2, P0-3) 단계 작업을 모두 완료하고 검증하였으며, 사용자의 명시적 지시 없이 2차 (집계 기능: P1-1 ~ P1-3)로 자동 진행하지 않고 대기합니다.

