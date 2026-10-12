# P0 Verification & Supplementation Report

본 문서는 P0 검증 및 보완 지시에 따라 수행된 보완 작업과 그 결과를 정리한 보고서입니다.

## 1. 검증 결과 요약 (항목별 PASS / FAIL)

| 검증 항목 | 상태 | 비고 |
|---|---|---|
| LLM 토큰 집계 검증 (호출/Agent/Trace 등 집계) | **PASS** | `TokenTracker.aggregate_by()` 구현 완료 |
| actual / estimated / unavailable 구분 검증 | **PASS** | 미응답 시 0토큰/unavailable 로직 검증 완료 |
| 동일 호출 이중 집계 방지 (Gateway & Callback) | **PASS** | `run_id` 단위 개별 레코드 저장으로 집계 분리 |
| 재시도 및 실패 계측 | **PASS** | 실패 시 에러 타입 저장 및 `unavailable` 처리 검증 (`test_llm_tracking_error_and_retry`) |
| AOP 병렬 실행 검증 (ThreadPoolExecutor) | **PASS** | `copy_context().run()`을 통한 ContextVar 전파 테스트 통과 (`test_threadpool_executor_context`) |
| 중첩 함수 오류 발생 위치 검증 | **PASS** | `__traceback__` 파싱을 통해 원래 예외 파일/라인 유지 재검증 |
| 예외 메시지 보안 필터링 | **PASS** | AOP `@trace` 내부에 API Key(`sk-...`) 마스킹 로직 추가 및 테스트 통과 (`test_exception_scrubbing`) |
| LangSmith 의존성 및 원격 전송 차단 | **PASS** | LangChain 패키지 의존성 확인 및 `.env` 파일에 `LANGCHAIN_TRACING_V2=false` 설정 완료 |
| 유료 클라우드 / Docker 사용 배제 | **PASS** | 순수 Python venv 및 로컬 환경에서 구현 확인 |

## 2. 실제 수정 파일 및 함수

1. **`src/ai_legal_helper/llm/usage.py`**
   - `TokenTracker.aggregate_by(field)` 메서드 추가: Agent, Node, Trace 등 원하는 필드 기준으로 총 호출 수, 에러 수, 사용량 출처(actual/estimated/unavailable), 토큰 합계를 그룹핑하여 반환.

2. **`src/ai_legal_helper/observability/decorators.py`**
   - `@trace` 데코레이터 내 예외 로깅 시 보안 필터 로직 추가: `re.sub`를 통해 `stack_trace` 내에 평문으로 포함될 수 있는 API Key(`api_key=...`, `sk-...` 등)를 `***`로 마스킹 처리.

3. **`tests/unit/test_llm_tracking.py`**
   - `test_llm_token_tracking_actual()`: `aggregate_by("agent_name")` 기능 검증 추가.
   - `test_llm_token_tracking_error_and_retry()`: **신규 추가**. 실패한 모델을 시뮬레이션하여 에러 타입 기록과 `unavailable` 처리를 검증.

4. **`tests/unit/test_aop.py`**
   - `test_threadpool_executor_context()`: **신규 추가**. `concurrent.futures.ThreadPoolExecutor` 사용 시 `contextvars.copy_context().run`을 통해 Trace ID가 정상 전파되는지 검증.
   - `test_sync_aop_error()`: 예외 메시지 내 API Key 마스킹 동작 검증 로직 추가.

5. **`.env.example`**
   - `LANGCHAIN_TRACING_V2=false` 추가 (LangSmith 자동 전송 방지).

## 3. 전체 Pytest 재실행 결과

```text
============================= test session starts =============================
platform win32 -- Python 3.11.6, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\myprjs\ai-legal-helper
configfile: pyproject.toml
plugins: anyio-4.10.0, langsmith-0.4.27, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 10 items

tests\unit\test_aop.py .......                                           [ 70%]
tests\unit\test_llm_tracking.py ...                                      [100%]

======================== 10 passed, 1 warning in 0.35s ========================
```
- 총 10개의 테스트가 수행되었으며 100% 통과(PASS)했습니다.

## 4. 실제 집계 로그 형태 (Mock 결과)

* `aggregate_by("agent_name")` 실행 결과 예시
```json
{
  "TestAgent": {
    "total_calls": 3,
    "actual_calls": 2,
    "estimated_calls": 0,
    "unavailable_calls": 1,
    "input_tokens": 1500,
    "output_tokens": 300,
    "total_tokens": 1800,
    "errors": 1
  }
}
```

* `test_sync_aop_error` 내 API Key 마스킹 로그 예시
```json
{
  "status": "ERROR",
  "exception_type": "ValueError",
  "message": "Error in sample_sync_error: Test Error with API_KEY=secret_12345 and sk-abcde1234567890123456789",
  "stack_trace": "Traceback (most recent call last):\n  ... ValueError: Test Error with API_KEY=*** and sk-***\n"
}
```

## 5. 보안 및 의존성 조사 (LangSmith)

- **LangSmith 설치 원인**: `langchain` 및 `langgraph` 패키지를 `pip install` 할 때, 내부 의존성으로 `langsmith` 패키지가 자동으로 설치됩니다.
- **해결 및 차단 방안**: 의존성 자체를 삭제하면 LangChain이 동작하지 않으므로 패키지는 유지하되, `LANGCHAIN_TRACING_V2=false` 환경변수를 설정하여 외부 서버로의 원격 추적 데이터 전송을 완벽히 차단했습니다. P1 운영 시에도 이 변수가 `false`로 주입되도록 구성해야 합니다.

## 6. 잔여 위험 및 P1 진입 가능 여부

- **P1 진입 가능 여부**: **가능 (Ready)**
- **잔여 위험 (P1에서 해결 요망)**: 
  - `ThreadPoolExecutor`를 직접 사용할 경우 개발자가 반드시 `copy_context().run()`을 호출해야 컨텍스트가 유지됩니다. LangGraph는 내부적으로 컨텍스트를 잘 전파하지만, 커스텀 스레드를 띄우는 레거시 코드가 있다면 컨텍스트 누락 위험이 있습니다. 레거시 통합 시 스레드 풀 사용 구간에 대한 래퍼(Wrapper) 적용을 권장합니다.
  - 마스킹 정규식(`sk-...`)이 완벽하지 않아 예상치 못한 형태의 민감정보가 로그에 남을 가능성이 있습니다. 상용망 적용 전 민감정보 패턴 딕셔너리를 고도화할 필요가 있습니다.

