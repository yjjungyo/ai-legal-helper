# AI Legal Helper — AOP / Observability 요구사항 v1.0

상태: 설계 기준안(P0), 구현 전. 기존 코드 확인 전이므로 통합 방식은 검증 필요.

## 목적
사용자가 요청부터 Supervisor, LangGraph Node, Agent, RAG, LLM, DB, Verification까지 한 Trace로 추적하고, 오류의 실제 소스 파일/함수/라인을 확인하며 LLM 토큰 소비를 호출·Agent·사건 단위로 분석한다.

## 필수 요구사항
- OBS-001: 모든 요청에 request_id, trace_id, case_id(있는 경우), run_id, node_name, agent_name을 연계한다. 비동기/재시도에도 contextvars 및 명시적 context propagation으로 보존한다.
- OBS-002: 구조화 JSON 로그에 timestamp, level, event, source_file, source_function, source_line, trace_id, span_id, request_id, run_id를 기록한다.
- OBS-003: 예외는 traceback 전체와 error_file/error_function/error_line을 기록한다. AOP wrapper 위치와 실제 실패 위치를 구분한다.
- OBS-004: Python logging + Decorator/AOP + LangGraph callback + OpenTelemetry를 공통 계층으로 적용한다. 로컬 파일 로그는 로테이션/보존 정책을 둔다.
- OBS-005: LLM 호출마다 model_id, provider_adapter, agent_name, node_name, attempt, input_tokens, output_tokens, total_tokens, token_source(api_reported/estimated/unavailable), latency_ms, status, cache_hit, retry_reason을 기록한다.
- OBS-006: API usage를 우선 사용하고 없을 경우 해당 모델과 호환되는 tokenizer로 추정한다. 추정값을 실제값처럼 표시하지 않는다. tokenizer도 없으면 unavailable로 표시한다. 입력+출력 합산이 provider total과 다를 경우 원본 usage 필드와 별도 기록한다.
- OBS-007: 호출별, trace별, run별, case별, agent별, model별, 일별 집계와 재시도 낭비 토큰, 상위 소비 Node를 조회할 수 있다.
- OBS-008: 토큰 예산은 요청/사건/Agent 별 경고 임계값을 구성 가능하게 한다. hard stop은 진행 중 안전한 상태 저장 및 사용자 안내를 보장할 때만 사용한다.
- OBS-009: Prompt, 답변, 계약서/녹음/주민번호/연락처 등 원문은 일반 로그 및 trace attributes에 기본 저장 금지. ID, 해시, 길이, 안전한 메타데이터만 기록한다. 접근통제와 보존/삭제 정책을 적용한다.
- OBS-010: 관측 시스템 장애가 핵심 법률 업무를 중단시키지 않도록 graceful degradation을 적용하되, 추적 손실을 경고한다.
- OBS-011: Docker, 유료 SaaS, 외부 텔레메트리 전송을 사용하지 않는다. Python venv + 로컬 OSS; 회사 제공 LLM만 연결한다.

## 예시 JSON 이벤트 (가상)
```json
{
  "timestamp":"2026-10-08T14:00:00+09:00",
  "level":"INFO",
  "event":"llm_call_completed",
  "trace_id":"trace-123", "span_id":"span-4", "case_id":"case-1",
  "run_id":"run-9", "agent_name":"LegalAgent", "node_name":"legal_research",
  "source_file":"agents/legal_agent.py", "source_function":"analyze", "source_line":142,
  "model_id":"company-model", "attempt":1,
  "input_tokens":2100, "output_tokens":420, "total_tokens":2520,
  "token_source":"api_reported", "latency_ms":1890, "status":"success"
}
```

## 아키텍처
Streamlit -> Trace Context -> Main LangGraph -> Supervisor/Agents -> LLM Gateway / Chroma / DB
공통 횡단 계층: Decorator/AOP + LangGraph callbacks + Python Logging + OpenTelemetry SDK
로컬 저장: Rotating JSON logs + SQLite/PostgreSQL usage ledger; 시각화는 추후 로컬 Jaeger 연동을 선택적으로 검증한다.

## 구현 순서
1. 기존 소스 분석과 회사 LLM usage 응답 스키마 확인(수정 없음).
2. 공통 TraceContext, JSON formatter, source location/traceback, 마스킹 구현.
3. 동기/비동기 decorator 및 LangGraph/LLM/RAG callback 연동.
4. 호출별 usage ledger, 집계, budget alert 구현.
5. Streamlit Trace/Token 대시보드 구현.
6. 단위·통합·실패 주입 테스트, 평가 전후 측정.

## 인수 기준(DoD)
- 정상 요청 하나를 trace_id로 검색해 모든 주요 Node, LLM/RAG 호출, 실행시간을 연결할 수 있다.
- 고의 예외 주입 시 실제 error_file/error_line과 traceback이 정확히 기록된다.
- sync/async, retry, concurrent runs에서 trace/case 정보가 섞이지 않는다.
- LLM usage 제공 시 합계가 API 값과 일치하고, 미제공 시 estimated/unavailable로 표시된다.
- 재시도와 캐시로 절감/추가된 토큰이 별도로 계산된다.
- 프롬프트/증거 원문/개인정보가 일반 로그에 남지 않는다.
- 동일한 테스트셋·모델·환경에서 개선 전후 token/call/latency/quality를 비교한다.

## 평가 증빙
- 토큰 사용 상위 Agent 및 Trace 대시보드 캡처
- 실패 주입 로그(실제 파일/라인) 및 문제 해결 기록
- 변경 전후 input/output/total tokens, 재시도 횟수, latency, 정확도 비교
- 개선 효과가 없거나 품질이 하락한 경우도 그대로 기록
