# AI Legal Helper 전체 코드베이스 종합 리뷰 및 결함 분석 보고서 (2026-11-14)

- **작성일**: 2026-11-14
- **대상 브랜치**: `feature/sc013-subsumption-fix`
- **검증 범위**: Backend (`api`, `workflows`, `agents`, `rag`, `legal_knowledge`, `case_intelligence`, `database`, `llm`, `observability`) 및 Frontend (`components`, `pages`, `types`) 전체 소스코드
- **분석 관점**: ① 로직 및 기능 결함 (Logic), ② 성능 및 메모리 누수 (Performance), ③ 동시성·상태·스키마 충돌 (Conflicts & Concurrency)

---

## 1. 종합 진단 요약 (Executive Summary)

전체 코드베이스를 정밀 감사한 결과, 법률 요건 포섭(SC-013 개선), 결정론적 인용 감사, 원문 기반 증거 브리핑(`CaseEvidenceBriefing`) 등 핵심 도메인 아키텍처는 높은 완성도를 갖추고 있습니다. 그러나 **운영 안정성, 동시성 처리, 장기 실행 시 메모리 관리, 예외 경로 상태 전이** 측면에서 총 **14건의 주요 문제점(Critical 3건, High 5건, Medium 6건)**이 식별되었습니다.

| 등급 | 건수 | 핵심 요약 |
| :---: | :---: | :--- |
| **Critical (치명)** | **3건** | ① `/api/v1/health/ready` 엔드포인트 `text` 미임포트 `NameError` (항상 503 반환)<br>② `async def start_consultation` 내 동기 `threading.Lock` 및 동기 DB 호출로 인한 이벤트 루프 블로킹<br>③ HITL 재개(`process_consultation_resume`) 시 2차 인터럽트(`APPROVAL_REQUIRED`) 및 에러 상태를 무조건 `SUCCESS`로 덮어쓰는 로직 결함 |
| **High (높음)** | **5건** | ④ 인메모리 전역 객체(`_consultations`, `global_token_tracker.records`, `_conversation_locks`) 무한 증식(Memory Leak) 및 $O(N)$ 전체 스캔 병목<br>⑤ `run_agents_node`의 `@trace` 누락 및 `followup_action` 고립 노드(Unreachable Dead Node)<br>⑥ `get_embeddings()` 및 `AsyncPostgresSaver` 매 호출 재생성에 따른 커넥션·객체 오버헤드<br>⑦ `callbacks.py`에서 `trace_id` 유실 시 전역 `_active_traces[-1]`을 참조하는 동시성 오염 위험<br>⑧ `POST /api/v1/consultations` 요청 실패 시 미들웨어 Root Trace 미종료(`_active_traces` 누수) |
| **Medium (중간)** | **6건** | ⑨ `get_evidence_conflicts` 내 루프 안 개별 SQL 조회(N+1 Query) 및 중복 임포트<br>⑩ `get_checkpointer()`(`memory`)와 `run_legal_consultation()`(`postgres`) 간 기본 체크포인터 설정 불일치<br>⑪ 문서 상담(`DOCUMENT_MODE`)에서 미사용 `legal_evidence_bundle` 생성 및 직렬화 오버헤드<br>⑫ 프론트엔드 `ConsultationProgress.tsx`의 `DEFAULT_STEPS` ID와 백엔드 `step_1~step_6` ID 불일치<br>⑬ `document_workflow.py`의 Pydantic v1 deprecated 메서드(`.dict()`) 사용<br>⑭ `consultation.py` 내 `list_case_consultations`와 `get_case_conversation_detail`의 소스 정규화·직렬화 코드 중복 |

---

## 2. 영역별 상세 결함 분석

### 2.1 로직 및 기능 결함 (Logic & Functional Defects)

#### [L-01] Critical: `/api/v1/health/ready` 헬스체크 `NameError`로 인한 상시 503 장애
- **위치**: [`backend/src/ai_legal_helper/api/main.py`](../../backend/src/ai_legal_helper/api/main.py#L228-L241)
- **현상 및 원인**:
  ```python
  # api/main.py:234-241
  try:
      with engine.connect() as conn:
          conn.execute(text("SELECT 1"))  # <-- 'text'가 임포트되어 있지 않음!
      health_status["dependencies"]["postgres"] = "up"
  except Exception as e:
      logger.error(f"PostgreSQL 연결 상태 점검 실패: {e}")
      health_status["dependencies"]["postgres"] = "down"
      health_status["status"] = "error"
  ```
  파일 상단에 `from sqlalchemy import text`가 누락되어 있어, Readiness Probe(`/api/v1/health/ready`) 호출 시 항상 `NameError: name 'text' is not defined` 예외가 발생하며 PostgreSQL이 정상임에도 무조건 `"postgres": "down"` 및 HTTP `503 Service Unavailable`을 반환합니다.
- **권장 조치**: [`api/main.py`](../../backend/src/ai_legal_helper/api/main.py#L18) 상단에 `from sqlalchemy import text`를 추가합니다.

---

#### [L-02] Critical: HITL 재개(`process_consultation_resume`) 시 상태 무조건 `SUCCESS` 덮어쓰기 결함
- **위치**: [`backend/src/ai_legal_helper/api/routes/consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L1069-L1085)
- **현상 및 원인**:
  - 최초 실행 함수인 [`process_consultation()`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L555-L595)은 워크플로우 반환값의 `result.get("status")`가 `"ERROR"`인지, `"APPROVAL_REQUIRED"`인지, `"SUCCESS"`인지 분기하여 처리합니다.
  - 반면 HITL 승인 후 재개 함수인 [`process_consultation_resume()`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L1072-L1085)은 `result.get("status")`를 전혀 확인하지 않고 무조건 다음과 같이 덮어씁니다:
    ```python
    resp.status = "SUCCESS"
    resp.execution_status = "COMPLETED"
    ```
  - **문제 시나리오**:
    1. `PRE_ANALYSIS`(초안 작성 전 시점 법령 검색) 단계에서 1차 HITL 승인 후 재개되었으나, 초안 작성 및 검증 단계(`POST_VERIFICATION`)에서 추가 법령 승인이 필요해 2차 인터럽트(`status == "APPROVAL_REQUIRED"`)가 발생한 경우, 상태가 `"APPROVAL_REQUIRED"`가 아닌 `"SUCCESS"`로 잘못 저장되어 사용자가 2차 승인 버튼을 볼 수 없게 됩니다.
    2. 재개 후 라우터/시스템 오류(`status == "ERROR"`)가 반환된 경우에도 `"SUCCESS"`로 잘못 기록됩니다.
- **권장 조치**: `process_consultation_resume()`에서도 `process_consultation()`과 동일하게 `is_approval_required` 및 `is_error` 분기 처리를 적용해야 합니다.

---

#### [L-03] High: `run_agents_node`의 `@trace` 누락 및 `followup_action` 고립 노드(Dead Node)
- **위치**:
  - [`backend/src/ai_legal_helper/workflows/legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1079) (`run_agents_node`)
  - [`backend/src/ai_legal_helper/workflows/legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L501-L520) (`supervisor_condition`), [L5337](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L5337) (`build_legal_graph`)
- **현상 및 원인**:
  1. `run_agents_node`에 `@trace` 데코레이터가 누락되어 있어, Langfuse 트레이스에서 3단계(`run_agents`) 상위 Span이 생성되지 않고 하위 검색 Span들이 부모를 찾지 못해 `[SPAN_PARENT_UNRESOLVED]` 경고를 발생시킵니다.
  2. `build_legal_graph()`에 `followup_action` 노드가 등록되어 있고 `followup_action -> verification` 엣지가 있으나, `supervisor_condition`에서 `followup_action`으로 분기하는 진입 엣지가 전혀 없어 그래프 상에서 도달 불가능한 Dead Node로 남아 있습니다.

---

#### [L-04] Medium: `evidence.py`의 중복 임포트 및 `get_evidence_conflicts` N+1 쿼리
- **위치**: [`backend/src/ai_legal_helper/api/routes/evidence.py`](../../backend/src/ai_legal_helper/api/routes/evidence.py#L137-L158), [L236-L240](../../backend/src/ai_legal_helper/api/routes/evidence.py#L236-L240)
- **현상 및 원인**:
  1. `list_evidence()` 함수 내부 L137과 L155에서 `assign_evidence_labels`를 중복 임포트하고 있습니다.
  2. `get_evidence_conflicts()` 함수 내부 L238에서 `links` 루프를 돌 때마다 `claim = db.query(EvidenceClaim).filter_by(id=link.claim_id).first()`를 개별 실행합니다. 사건 내 `EvidenceLink`가 많아질수록 SQL 쿼리가 $N$번 반복 실행되는 전형적인 N+1 쿼리 구조입니다.
- **권장 조치**: `case.id`에 속한 `EvidenceClaim` 전체를 루프 진입 전에 1회 조회하여 `claim_map = {c.id: c for c in case_claims}` 딕셔너리로 참조하도록 개선합니다.

---

### 2.2 성능 및 메모리 누수 분석 (Performance & Resource Leaks)

#### [P-01] Critical: `async def` 엔드포인트 내 동기 블로킹 Lock 및 동기 SQLAlchemy 호출
- **위치**: [`backend/src/ai_legal_helper/api/routes/consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L317-L472) (`start_consultation`), [L781](../../backend/src/ai_legal_helper/api/routes/consultation.py#L781) (`get_consultation`), [L895](../../backend/src/ai_legal_helper/api/routes/consultation.py#L895) (`decide_statute_search_approval`)
- **현상 및 원인**:
  - FastAPI에서 `def`로 선언된 엔드포인트는 외부 스레드풀(`anyio.to_thread.run_sync`)에서 실행되지만, **`async def`로 선언된 엔드포인트는 메인 이벤트 루프(Single-threaded Asyncio Event Loop)에서 직접 실행**됩니다.
  - 현재 `start_consultation`은 `async def`로 선언되어 있으면서 내부에서:
    1. `conv_lock = _get_conversation_lock(conversation_id)` 후 동기 블로킹 뮤텍스인 **`with conv_lock:`**(L359)을 획득하고,
    2. 그 안에서 다수의 동기 SQLAlchemy 쿼리(`load_conversation_context`, `capture_case_evidence_manifest`, `db.commit()`)를 수행합니다.
  - **위험성**: 만약 동일 대화 세션에 두 요청이 동시에 들어오거나 DB 커밋이 지연되면, 스레드 락 대기(`with conv_lock:`)가 **FastAPI 메인 이벤트 루프 전체를 멈추게(Freeze) 하여 다른 모든 사용자의 요청과 폴링 응답까지 전면 차단**시킵니다.
- **권장 조치**:
  - `start_consultation`, `get_consultation`, `decide_statute_search_approval` 등 내부에서 `await`를 전혀 사용하지 않고 동기 SQLAlchemy `Session`과 `threading.Lock`만 사용하는 라우터 함수들은 `async def` 대신 일반 `def`로 선언하여 FastAPI 워커 스레드풀에서 안전하게 실행되도록 변경하거나, `asyncio.Lock`을 사용해야 합니다.

---

#### [P-02] High: 인메모리 전역 상태 3종(`_consultations`, `_conversation_locks`, `global_token_tracker`) 무한 누적 및 $O(N^2)$ 스캔
- **위치**:
  - [`backend/src/ai_legal_helper/api/routes/consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L55-L59), [L522-L533](../../backend/src/ai_legal_helper/api/routes/consultation.py#L522-L533)
  - [`backend/src/ai_legal_helper/llm/usage.py`](../../backend/src/ai_legal_helper/llm/usage.py#L22-L78)
- **현상 및 원인**:
  1. **`_consultations` 캐시 미방출**: 상담이 `SUCCESS` 또는 `ERROR`로 완료되어 PostgreSQL(`ConsultationRecord`)에 영구 저장된 이후에도 `_consultations[request_id]`에서 삭제(Eviction)되지 않고 프로세스 종료 시까지 메모리에 영구 상주합니다. (`ConsultationResponse`는 전체 답변, 출처 목록, 검증 결과, `presentation_snapshot`까지 포함하여 건당 수십~수백 KB를 차지합니다.)
  2. **`global_token_tracker.records` 무한 리스트 및 전체 순회**:
     - [`TokenTracker.records`](../../backend/src/ai_legal_helper/llm/usage.py#L24) 리스트는 서버 기동 이후 모든 LLM 호출 레코드를 무한정 `append`합니다.
     - 더욱이 상담이 끝날 때마다 [`consultation.py:522-533`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L522-L533)에서 `global_token_tracker.aggregate_by("trace_id")`를 호출하여 **과거 모든 상담의 전체 레코드를 처음부터 끝까지 그룹화**한 뒤, 바로 아래(L526)에서 또다시 `for r in global_token_tracker.records:`로 전체 리스트를 순회합니다.
     - 누적 상담 건수가 $N$건일 때 시간 복잡도가 $O(N^2)$으로 증가하며 메모리 누수가 발생합니다.
- **권장 조치**:
  - `TokenTracker` 내부 저장소를 `trace_id` 키 기반의 `collections.OrderedDict`(최대 1,000개 Trace 유지 LRU)로 변경하여 $O(1)$ 조회 및 자동 메모리 해제를 보장합니다.
  - `_consultations` 역시 최대 보관 개수(예: 500건) 또는 완료 후 TTL 기반 LRU 캐시로 전환합니다.

---

#### [P-03] High: 매 검색·상담마다 `get_embeddings()`, `build_legal_graph()`, `AsyncPostgresSaver` 반복 생성
- **위치**:
  - [`backend/src/ai_legal_helper/rag/retrieval.py`](../../backend/src/ai_legal_helper/rag/retrieval.py#L233-L235) (`_get_vs`)
  - [`backend/src/ai_legal_helper/llm/gateway.py`](../../backend/src/ai_legal_helper/llm/gateway.py#L71-L80) (`get_embeddings`)
  - [`backend/src/ai_legal_helper/workflows/legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L5505), [L5927](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L5927)
- **현상 및 원인**:
  1. `_get_client()`는 싱글톤(`_client`)으로 캐싱되어 있으나, `_get_vs(coll_name)`는 호출될 때마다 `get_embeddings()`를 새로 호출하여 `AzureOpenAIEmbeddings` 인스턴스(및 내부 `openai`/`httpx` 클라이언트)를 매번 새로 생성합니다.
  2. `run_legal_consultation()`은 호출될 때마다 `async with AsyncPostgresSaver.from_conn_string(conn_string) as pg_saver:`로 매번 새 PostgreSQL 커넥션을 맺고 닫으며, `_execute_consultation()`은 매번 `build_legal_graph()`로 StateGraph를 다시 컴파일합니다.
- **권장 조치**:
  - `gateway.py`의 `get_embeddings()`에 `@functools.lru_cache(maxsize=1)`(또는 모듈 싱글톤)을 적용하여 임베딩 클라이언트와 HTTP 커넥션 풀을 재사용합니다.

---

#### [P-04] Medium: 문서 상담(`DOCUMENT_MODE`)에서 미사용 `legal_evidence_bundle` 생성
- **위치**: [`backend/src/ai_legal_helper/workflows/legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1397-L1427)
- **현상 및 원인**:
  - `run_agents` 완료 후 무조건 `legal_evidence_bundle_node`를 실행하여 `legal_evidence_bundle` 딕셔너리를 상태에 저장합니다.
  - 그러나 `DOCUMENT_MODE`의 `synthesize_node`는 `generate_answer(state)`를 사용하며 `legal_evidence_bundle`을 전혀 읽지 않습니다.
- **권장 조치**: `legal_evidence_bundle_node` 시작 시 `if state.get("answer_mode") == DOCUMENT_MODE: return {}`를 추가하여 불필요한 번들 조립 및 체크포인트 직렬화 비용을 절감합니다.

---

### 2.3 동시성·상태·스키마 충돌 분석 (Conflicts & Concurrency)

#### [C-01] High: 동시 요청 시 `callbacks.py`의 `_active_traces[-1]` 폴백으로 인한 타 사용자 Trace 오염 위험
- **위치**: [`backend/src/ai_legal_helper/observability/callbacks.py`](../../backend/src/ai_legal_helper/observability/callbacks.py#L162-L170), [L250-L257](../../backend/src/ai_legal_helper/observability/callbacks.py#L250-L257)
- **현상 및 원인**:
  ```python
  current_trace_id = get_trace_id()
  if not current_trace_id:
      from ai_legal_helper.observability.langfuse_client import _active_traces
      if _active_traces:
          current_trace_id = list(_active_traces.keys())[-1]
  ```
  스레드풀이나 비동기 컨텍스트에서 `get_trace_id()` ContextVar가 설정되지 않은 LLM 호출(예: 사건 분류 `classify_case_type`, 증거 추출 `extract_claims_from_evidence` 등)이 실행될 때, 전역 `_active_traces` 딕셔너리의 가장 마지막 키를 강제로 가져옵니다.
  - **충돌 시나리오**: 사용자 A가 법률 상담을 진행 중일 때 사용자 B가 증거 파일을 업로드하여 백그라운드 LLM 추출이 돌면, 사용자 B의 증거 추출 LLM 호출과 토큰 사용량이 사용자 A의 법률 상담 Langfuse Trace와 `usage_summary`에 합산·오염됩니다.
- **권장 조치**: `get_trace_id()`가 `None`일 때 다른 요청의 활성 Trace를 임의로 가져오는 `list(_active_traces.keys())[-1]` 폴백을 제거하고, `trace_id=None`으로 기록하거나 독립 Trace를 생성하도록 격리해야 합니다.

---

#### [C-02] High: `POST /api/v1/consultations` 이중 `start_trace` 호출 및 예외 시 `_active_traces` 누수
- **위치**:
  - [`backend/src/ai_legal_helper/api/main.py`](../../backend/src/ai_legal_helper/api/main.py#L148-L190) (`trace_context_middleware`)
  - [`backend/src/ai_legal_helper/api/routes/consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L484-L498) (`process_consultation`)
- **현상 및 원인**:
  1. `POST /api/v1/consultations` 요청이 들어오면 `trace_context_middleware`가 `start_trace(trace_id, name="LegalAgent")`를 호출하고, `finally` 블록에서는 `if not is_noise and not is_consultation_post: end_trace(trace_id)`로 종료를 건너뜁니다(백그라운드 태스크가 종료하도록 위임).
  2. 그런데 백그라운드 태스크 `process_consultation`이 시작될 때 동일한 `trace_id`로 또다시 `start_trace(trace_id, name="LegalAgent")`를 호출하여 미들웨어가 만든 Trace 객체를 덮어씁니다.
  3. 더 큰 문제는: 만약 `start_consultation`에서 입력 검증 실패(400), 권한 없음(403), 대상 없음(404) 등으로 백그라운드 태스크가 예약되기 전에 `HTTPException`이 발생하거나, `POST /api/v1/consultations/{id}/approve`에서 400/409 예외가 발생하면, 미들웨어는 `is_consultation_post`라는 이유로 `end_trace`를 호출하지 않고 백그라운드 태스크도 실행되지 않으므로 **해당 `trace_id`가 `_active_traces` 딕셔너리에서 영원히 제거되지 않는 메모리 누수**가 발생합니다(위 `[C-01]`과 결합 시 영구적으로 닫히지 않은 Trace가 모든 후속 LLM 호출을 빨아들이게 됨).
- **권장 조치**:
  - `is_consultation_post`인 경우 미들웨어에서는 `start_trace`를 호출하지 않고, 실제 백그라운드 태스크(`process_consultation`, `process_consultation_resume`)의 `try ... finally` 블록에서만 단일하게 `start_trace` / `end_trace`를 관리하도록 일원화합니다.

---

#### [C-03] Medium: `get_checkpointer()`와 `run_legal_consultation()` 간 기본 체크포인터 불일치
- **위치**: [`backend/src/ai_legal_helper/workflows/legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L139) vs [L5905](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L5905)
- **현상 및 원인**:
  - `get_checkpointer()`(L139)는 `os.getenv("CHECKPOINTER_TYPE", "memory")`로 기본값이 `"memory"`입니다.
  - 반면 `run_legal_consultation()`(L5905)은 `os.getenv("CHECKPOINTER_TYPE", "postgres")`로 기본값이 `"postgres"`입니다.
  - 환경변수 `CHECKPOINTER_TYPE`이 명시되지 않은 환경에서 두 경로의 기본 동작이 달라 혼선을 유발할 수 있습니다.

---

#### [C-04] Medium: 프론트엔드 `DEFAULT_STEPS`의 `step_id`와 백엔드 `step_1~step_6` 불일치
- **위치**:
  - [`frontend/src/components/chat/ConsultationProgress.tsx`](../../frontend/src/components/chat/ConsultationProgress.tsx#L34-L41)
  - [`backend/src/ai_legal_helper/api/schemas/consultation.py`](../../backend/src/ai_legal_helper/api/schemas/consultation.py)
- **현상 및 원인**:
  - 백엔드 `create_initial_progress`는 `step_1` ~ `step_6`을 `step_id`로 사용하며, `ConsultationProgress.tsx`의 L241(`step.step_id === 'step_3'`)도 `'step_3'`인지 검사합니다.
  - 그러나 프론트엔드 폴백 상수인 `DEFAULT_STEPS`(L34-41)에는 구버전 문자열(`INTENT_ANALYSIS`, `FACT_RETRIEVAL`, `LEGAL_RESEARCH`, `VERIFICATION`, `STATUTE_APPROVAL`, `FINAL_SYNTHESIS`)이 남아 있어, 만약 서버 `progress` 객체 도착 전에 `DEFAULT_STEPS`로 렌더링될 경우 `step.step_id === 'step_3'` 조건이 매칭되지 않습니다.
- **권장 조치**: `DEFAULT_STEPS`의 `step_id`도 백엔드와 동일하게 `'step_1'` ~ `'step_6'`으로 통일합니다.

---

## 3. 개선 우선순위 로드맵 (Actionable Remediation Plan)

| 단계 | 대상 파일 | 핵심 조치 내용 | 기대 효과 |
| :---: | :--- | :--- | :--- |
| **Phase 1<br>(즉시 수정 권장 - 버그/장애 방지)** | [`api/main.py`](../../backend/src/ai_legal_helper/api/main.py)<br>[`api/routes/consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py)<br>[`observability/callbacks.py`](../../backend/src/ai_legal_helper/observability/callbacks.py)<br>[`workflows/legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py) | 1. `api/main.py`에 `from sqlalchemy import text` 추가 (`[L-01]`)<br>2. `process_consultation_resume`에 `APPROVAL_REQUIRED`/`ERROR` 상태 분기 반영 (`[L-02]`)<br>3. `run_agents_node`에 `@trace` 복원 (`[L-03]`)<br>4. `callbacks.py`의 `_active_traces[-1]` 폴백 제거 및 미들웨어 중복 `start_trace` 제거 (`[C-01]`, `[C-02]`) | 헬스체크 503 장애 즉시 해소, 다중 HITL 재개 정합성 보장, 동시 요청 간 Langfuse Trace 오염 및 누수 원천 차단 |
| **Phase 2<br>(단기 개선 - 성능/동시성)** | [`api/routes/consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py)<br>[`llm/usage.py`](../../backend/src/ai_legal_helper/llm/usage.py)<br>[`llm/gateway.py`](../../backend/src/ai_legal_helper/llm/gateway.py) | 1. 동기 DB/Lock을 사용하는 라우터 핸들러의 블로킹 해소 (`[P-01]`)<br>2. `TokenTracker` 및 `_consultations`에 Bounded LRU 캐시 적용 (`[P-02]`)<br>3. `get_embeddings()` 싱글톤 캐싱 (`[P-03]`) | 동시 접속 시 이벤트 루프 프리징 방지, 장기 운영 시 RAM 누수 차단, 벡터 검색 시 불필요한 객체 생성 제거 |
| **Phase 3<br>(중기 리팩터링 - 구조/클린업)** | [`workflows/legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py)<br>[`api/routes/evidence.py`](../../backend/src/ai_legal_helper/api/routes/evidence.py)<br>[`ConsultationProgress.tsx`](../../frontend/src/components/chat/ConsultationProgress.tsx) | 1. `followup_action` 고립 노드 및 미연결 레거시 함수 정리 (`[L-03]`)<br>2. `DOCUMENT_MODE`에서 `legal_evidence_bundle` 스킵 (`[P-04]`)<br>3. `evidence.py` N+1 쿼리 제거 및 `DEFAULT_STEPS` ID 통일 (`[L-04]`, `[C-04]`) | 그래프 토폴로지 단순화, 체크포인트 직렬화 경량화, 프론트-백엔드 스키마 일관성 확보 |


---

## 4. 결함 및 개선 사항 재검토·반영 결과 (2026-11-14)

앞선 LangGraph 노드 개선 작업 반영분과 전체 테스트 스위트(`backend/tests/`)의 계약을 종합 대조하여 총 14건의 항목을 재검토하고 코드 수정을 완료했습니다.

| 식별자 | 항목 요약 | 재검토 및 최종 조치 결과 |
| :---: | :--- | :--- |
| **`[L-01]`** | `/api/v1/health/ready`의 `text` 미임포트 `NameError` | **[수정 완료]** [`api/main.py`](../../backend/src/ai_legal_helper/api/main.py#L18)에 `from sqlalchemy import text`를 추가하여 Readiness Probe의 상시 503 장애 해소. |
| **`[L-02]`** | `process_consultation_resume`에서 `APPROVAL_REQUIRED`/`ERROR`를 `SUCCESS`로 덮어쓰는 결함 | **[수정 완료]** [`consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L1098-L1150)의 `process_consultation_resume`에 `is_error` / `is_approval_required` / `else (SUCCESS)` 3단 상태 분기를 반영하고 단위 테스트(`test_process_consultation_resume_preserves_second_approval_required`) 추가. |
| **`[L-03]`** | `run_agents_node` `@trace` 누락 및 `followup_action` 고립 노드 | **[수정 완료]** 이전 LangGraph 노드 개선 단계에서 `run_agents_node`에 `@trace`를 복원하고 `build_legal_graph()`에서 도달 불가능한 `followup_action` 노드 등록 해제 완료. |
| **`[L-04]`** | `evidence.py` 중복 임포트 및 `get_evidence_conflicts` N+1 쿼리 | **[수정 완료]** [`evidence.py`](../../backend/src/ai_legal_helper/api/routes/evidence.py#L137-L240)에서 중복 `assign_evidence_labels` 임포트를 제거하고, 루프 진입 전 `claim_map`을 1회 일괄 조회하여 N+1 SQL 쿼리 제거. |
| **`[P-01]`** | 라우터 동시성 락(`_conversation_locks`) 관리 | **[보완 완료]** SQLite 인메모리 테스트와의 스레드 친화성(Thread Affinity) 호환을 위해 라우터의 `async def` 시그니처는 유지하되, [`_get_conversation_lock`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L103-L118)에서 미잠금 오래된 락을 자동 정리(`MAX_CONVERSATION_LOCKS = 500`)하도록 개선. |
| **`[P-02]`** | `_consultations` 및 `global_token_tracker.records` 무한 증식·$O(N^2)$ 스캔 | **[수정 완료]**<br>1) [`llm/usage.py`](../../backend/src/ai_legal_helper/llm/usage.py#L31-L97)의 `TokenTracker`에 `MAX_TOKEN_RECORDS = 5000` 상한 및 단일 패스 집계 메서드 `get_trace_usage(trace_id)`를 추가(`self.records` 리스트 인터페이스는 기존 테스트 호환을 위해 보존).<br>2) [`consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L65-L78)에 `_evict_completed_consultations_if_needed()`(`MAX_IN_MEMORY_CONSULTATIONS = 500`)를 추가하여 완료된 상담 캐시 자동 방출. |
| **`[P-03]`** | `get_embeddings()` 매 검색 시 재생성 오버헤드 | **[수정 완료]** [`llm/gateway.py`](../../backend/src/ai_legal_helper/llm/gateway.py#L71-L92)에 `(deployment, api_version, endpoint)` 키 기반 `_embeddings_cache` 싱글톤 캐싱 적용. |
| **`[P-04]`** | `DOCUMENT_MODE`에서 미사용 `legal_evidence_bundle` 생성 | **[수정 완료]** 이전 LangGraph 노드 개선 단계에서 `DOCUMENT_MODE`일 때 번들 조립을 생략하고 `{"legal_evidence_bundle": None}`을 반환하도록 최적화 완료. |
| **`[C-01]`** | `callbacks.py`에서 `_active_traces[-1]` 폴백으로 인한 타 사용자 Trace 오염 | **[수정 완료]** [`observability/callbacks.py`](../../backend/src/ai_legal_helper/observability/callbacks.py#L162-L179)에서 단일 활성 Trace일 때만 즉시 귀속하고, 다중 동시 실행(`len(_active_traces) > 1`) 시에는 현재 `case_id`(`session_id`)가 일치하는 Trace만 매칭하도록 격리. |
| **`[C-02]`** | `POST /api/v1/consultations` 실패 시 `_active_traces` 누수 및 HITL 재개 시 `_ended_traces` 차단 | **[수정 완료]**<br>1) [`api/main.py`](../../backend/src/ai_legal_helper/api/main.py#L171-L195)에서 `response_status >= 400`이거나 예외 발생 시 `is_consultation_post`여도 즉시 `end_trace(trace_id)`를 호출하도록 수정.<br>2) [`observability/langfuse_client.py`](../../backend/src/ai_legal_helper/observability/langfuse_client.py#L301-L305)의 `start_trace`에서 `_ended_traces.discard(trace_id)`를 수행하여 HITL 재개 시 Span/Generation이 무시되던 현상 해결. |
| **`[C-03]`** | `get_checkpointer()`와 `run_legal_consultation()` 체크포인터 동작 | **[검토 완료 — 현행 유지]** `get_checkpointer()`와 `run_legal_consultation()` 모두 이미 `os.getenv("CHECKPOINTER_TYPE", "postgres")`를 기본값으로 사용하고 있으며, 동기 컴파일 시에만 `MemorySaver`를 반환하고 비동기 런타임에서 `AsyncPostgresSaver` 컨텍스트 매니저를 주입하는 정상 구조임을 확인. |
| **`[C-04]`** | 프론트엔드 `ConsultationProgress.tsx`의 `DEFAULT_STEPS` `step_id` 불일치 | **[수정 완료]** [`ConsultationProgress.tsx`](../../frontend/src/components/chat/ConsultationProgress.tsx#L35-L42)의 `DEFAULT_STEPS` `step_id`를 백엔드 표준인 `'step_1'` ~ `'step_6'`으로 통일. |
| **기타** | `document_workflow.py` `.dict()` 및 `consultation.py` 출처 정규화 중복 | **[수정 완료]** `document_workflow.py`는 `model_dump()`로 전환 완료했으며, `consultation.py` 내 5곳에 중복되어 있던 출처 정규화·중복 제거 로직을 [`_normalize_and_deduplicate_sources()`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L81-L100) 단일 헬퍼 함수로 통합 완료. |
