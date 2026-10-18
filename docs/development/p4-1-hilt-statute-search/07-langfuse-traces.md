# P4.1 Verifier-Guided HILT 법령 검색 — 07. Langfuse Trace 검증 보고서

## 1. 개요
본 문서는 `AI Legal Helper`의 P4.1 Verifier-Guided HILT 법령 검색 구현 전후에 수집되는 **Langfuse Trace, Observation, Span, Scores** 구조를 검증하고, 시나리오별 관측성(Observability) 데이터 흐름을 보고한다.

---

## 2. Langfuse 아키텍처 및 메트릭 구조

### 2.1 Trace 계층 구조
```
Trace: LegalConsultation (session_id=case_id, metadata={"question": ..., "request_id": ...})
  ├── Span: supervisor_initialize
  ├── Span: route
  ├── Span: plan
  ├── Span: run_agents
  │     ├── Generation: civil_law_specialist
  │     └── Generation: tenancy_specialist
  ├── Generation: synthesize
  ├── Span: verification (법률검증 Agent)
  │     └── Generation: verification_agent_eval
  ├── Span: statute_search_approval (HILT 인터럽트 대기)
  ├── Span: execute_statute_search (법제처 open.law.go.kr API 호출)
  ├── Generation: re_analyze (공식 법령 기반 초안 재작성)
  ├── Span: verification (2차 재검증)
  └── Span: finalize
```

### 2.2 핵심 메타데이터 및 정량 평가 지표 (Scores)
Verifier 및 최종 응답 완료 시 Langfuse에 기록되는 정량 지표는 다음과 같다:

1. **`verification_status`**:
   - `PASS`: 1.0 점
   - `REVISE`: 0.5 점
   - `INSUFFICIENT`: 0.0 점
2. **`citation_existence_rate`**:
   - 답변에 인용된 출처 중 실제 Source Registry에 존재하는 비율 (0.0 ~ 1.0)
3. **`citation_support_rate`**:
   - 출처 문서의 본문 내용이 해당 주장을 실제로 뒷받침하는 비율 (0.0 ~ 1.0)
4. **HILT 추적 메타데이터**:
   - `reason_code`: `LEGAL_SOURCE_MISSING`, `LEGAL_SOURCE_INSUFFICIENT` 등
   - `candidate_laws`: `["주택임대차보호법"]`
   - `approval_status`: `APPROVED` / `REJECTED`
   - `retrieval_methods`: `["CHROMA_VECTOR", "OFFICIAL_STATUTE_API"]`

---

## 3. 시나리오별 Trace 실행 경로 비교

### 3.1 Trace T-01: 내부 RAG 충분 사건
- **Trace ID**: `trace-t-ar-01-xxxx`
- **실행 노드**: `initialize` → `route` → `plan` → `run_agents` → `synthesize` → `verification` → `finalize`
- **검증 평가**: `verification_status`: 1.0, `reason_code`: `"NONE"`
- **HILT 진입 여부**: 미진입 (정상 직행)

### 3.2 Trace T-02 & T-03: 특별법 누락 및 승인 재분석
- **Trace ID**: `trace-t-ar-hilt-pass-xxxx`
- **1차 실행 노드**: `initialize` → `route` → `plan` → `run_agents` → `synthesize` → `verification` → `statute_search_approval(INTERRUPT)`
- **1차 검증 평가**: `verification_status`: 0.0, `reason_code`: `"LEGAL_SOURCE_MISSING"`, `candidate_laws`: `["주택임대차보호법"]`
- **Resume 재개 노드**: `statute_search_approval(RESUMED)` → `execute_statute_search` → `re_analyze` → `verification` → `finalize`
- **2차 검증 평가**:
  - `verification_status`: 1.0 (PASS)
  - `retrieval_source_ids`: `["STATUTE:주택임대차보호법:제6조의2:276291", ...]`
  - `retrieval_methods`: `["OFFICIAL_STATUTE_API"]`
  - `citation_existence_rate`: 1.0
  - `citation_support_rate`: 1.0

### 3.3 Trace T-04: 사용자 거절 시나리오
- **Trace ID**: `trace-t-ar-hilt-reject-xxxx`
- **실행 노드**: `...` → `statute_search_approval(INTERRUPT)` → `statute_search_approval(RESUMED)` → `insufficient` → `END`
- **결과**: 외부 검색 도구 Span이 일체 생성되지 않음 확인.

---

## 4. 데이터 프라이버시 및 보안 검증
1. **API Key 마스킹**:
   - `execute_statute_search` Span의 `source_url` 메타데이터에서 `OC=[LAW_OPENAPI_KEY]` 등 실제 인증키 파라미터가 `OC=[MASKED]` 또는 숨김 처리되어 트레이스 로그에 노출되지 않음을 확인.
2. **개인정보 비식별화**:
   - 의뢰인의 사건 번호, 당사자 실명, 민감 사실관계가 외부 검색 도구 및 Langfuse 공개 메타데이터에 노출되지 않도록 법률 키워드만 정제되어 전송됨을 확인.

