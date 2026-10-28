# LAWYER — Langfuse Observability 고도화 v2.0 P0 최종 완료 보고서

**대상 브랜치:** `feature/langfuse-observability-v2.0`  
**현재 Git SHA:** `0aad456cc5decb66373487bfb8cf766e7b74841a`  
**시스템 식별자:** `LegalAgent`  
**완료 일자:** 2026-10-28  

---

## 1. 개요 및 추진 목표

"LAWYER Observability v2.0 — P0 잔여 결함 보완 지시"에 따라 다음 4개 항목을 완벽히 해결하고, 로컬 Langfuse v2.95.11 서버 및 실제 사내 Azure OpenAI LLM과 연동하여 실측 검증을 완료하였습니다:

1. **Span 교차 연결 원천 차단:** `langfuse_client.py`의 `start_span()` 및 `log_generation()`에서 전역 이름 기반 부모 탐색을 완전히 제거하고, `_span_to_trace[parent_span_id] == trace_id` 검증 및 `_resolve_parent_span()` 격리 구조 확립.
2. **비동기 종료 후 지연 콜백 차단:** `_ended_traces` 집합을 도입하여 `end_trace()` 이후 도착한 지연 콜백이 임의의 신규 Trace(`Workflow:...` 또는 `LLM_Trace`)를 생성하거나 오염시키는 현상 차단 (`[DELAYED_CALLBACK_IGNORED]`).
3. **개인정보 수집 기본값 강화:** `LANGFUSE_CAPTURE_CONTENT` 미설정 시 기본값을 `"false"`로 변경하여 법률 상담 질문 및 증거 원문이 기본적으로 마스킹(`[MASKED FOR PRIVACY]`)되도록 보장.
4. **모델·비용 실측 검증:** 단위 테스트 외에 실제 SC-001 상담 파이프라인을 구동하여 Langfuse에 모델명(`gpt-5.4-2026-03-05`), 토큰 사용량, 계산된 비용(`calculatedTotalCost`), 1 LLM 호출당 1 Generation 생성 및 부모-자식 트리 구조 무결성을 실측 검증.

---

## 2. 세부 구현 내용

### 1) Span 교차 연결 원천 차단 및 부모 해결 표준화 (`langfuse_client.py`)
- `_resolve_parent_span(trace_id, parent_span_id, name, span_id)` 함수 신설:
  - 1단계: 현재 `trace_id`의 격리 인덱스(`_trace_spans[trace_id]`)에서 UUID 직접 매칭.
  - 2단계: 현재 `trace_id`의 격리 이름 스택(`_trace_spans_by_name[trace_id]`)에서 최신 스팬(`[-1]`) 매칭.
  - 3단계: 전역 UUID 인덱스에 존재하더라도 `_span_to_trace[parent_span_id] == trace_id`인 경우에만 허용. 타 Trace 소속인 경우 `[SPAN_CROSS_TRACE_REJECTED]` 경고 로그와 함께 즉시 거부(`return None`).
  - 4단계: 전역 이름 매칭(`_active_spans_by_name`) 완전 배제. 부모 미해결 시 `[SPAN_PARENT_UNRESOLVED]` 진단 로그를 남기고 Root Trace로 연결.

### 2) 종료된 Trace에 대한 지연 콜백 방어
- `_ended_traces: set[str]` 추적기 도입.
- `end_trace(trace_id)` 시점에 `_ended_traces.add(trace_id)` 등록.
- `start_span()` 및 `log_generation()` 진입 즉시 `trace_id in _ended_traces` 여부를 점검하여, 비동기 워크플로우 종료 후 지연 도착한 콜백이 새로운 루트 트레이스를 생성하지 않고 안전하게 무시되도록 방어.

### 3) 개인정보 보호 기본값 마스킹 전환
- `start_span()`, `end_span()`, `log_generation()`의 콘텐츠 수집 판별 로직을 `os.getenv("LANGFUSE_CAPTURE_CONTENT", "false").lower() == "true"`로 통일.
- 환경변수를 명시적으로 `"true"`로 부여한 승인된 개발/테스트 환경을 제외하고는 기본적으로 입출력 텍스트가 `[MASKED FOR PRIVACY]`로 전송됨.

---

## 3. 검증 결과

### 1) 신규 P0 단위 테스트 11종 전체 통과 ([`test_langfuse_observability_p0.py`](file:///c:/myprjs/ai-legal-helper/backend/tests/unit/test_langfuse_observability_p0.py))

| 테스트 번호 | 대상 요구사항 | 검증 내용 | 결과 |
|---|---|---|---|
| TC-01 | P0-1, P0-3 | Trace 이름 `LegalConsultation`, LLM 1회 호출 시 1회 Generation 기록 및 태그/토큰 검증 | **PASS** |
| TC-02 | P0-2 | 동시 실행 상담 간 동일 노드명(`supervisor_initialize`) Span 상호 오염 차단 검증 | **PASS** |
| TC-03 | P0-2 | 중첩·반복 에이전트 실행 시 Span 스택 관리 및 `end_span()` 시 부모 복원 검증 | **PASS** |
| TC-04 | P0-3 | Git Commit SHA 및 `LegalAgent` 메타데이터 자동 주입 검증 | **PASS** |
| TC-05 | P0-2 | `end_trace()` 호출 시 `_trace_spans`, `_trace_spans_by_name` 메모리 정리 검증 | **PASS** |
| TC-06 | P0-1 | Azure OpenAI 응답 모델명(`gpt-5.4-2026-03-05`) 정밀 추출 및 Langfuse Cost 계산 연계 검증 | **PASS** |
| **TC-P0-07** | P0-2 교차 차단 | Trace A에만 존재하는 부모 이름을 Trace B에서 요청했을 때 교차 연결 원천 차단 검증 | **PASS** |
| **TC-P0-08** | P0-2 동시 중첩 | 서로 다른 Trace에서 동일 이름의 Agent가 동시에 중첩 실행될 때 스택 독립성 검증 | **PASS** |
| **TC-P0-09** | P0-2 UUID 격리 | 다른 Trace 소속 UUID를 부모로 전달했을 때 교차 연결 거부(`[SPAN_CROSS_TRACE_REJECTED]`) 검증 | **PASS** |
| **TC-P0-10** | P0 지연 방어 | 상담 종료 이후 지연된 Callback이 도착했을 때 새 Trace가 임의 생성되지 않고 무시됨 검증 | **PASS** |
| **TC-11** | P0 개인정보 | `LANGFUSE_CAPTURE_CONTENT` 미설정 시 기본 마스킹(`[MASKED FOR PRIVACY]`) 적용 검증 | **PASS** |

### 2) 전체 단위·회귀 테스트 현황
- **Observability 단위 테스트 26종:** **전체 PASS** (`test_langfuse.py` 6종, `test_observability_enhanced.py` 9종, `test_langfuse_observability_p0.py` 11종)
- **사건 독립성 및 법률 판단 회귀 테스트 37종:** **전체 PASS** (`test_case_independence_counterexamples.py`)
- **총 63개 테스트 100% 통과**
- **프론트엔드 빌드:** TypeScript 컴파일 및 Vite 번들링 무결성 확인 (0 Errors, 2.16s 완료)

---

## 4. 로컬 Langfuse v2.95.11 실제 SC-001 상담 실측 검증

실제 사내 Azure OpenAI LLM 및 로컬 Langfuse 인스턴스(`http://localhost:3001`)를 대상으로 SC-001 상담 질의를 전송하고 Langfuse REST API로 조회한 실측 결과입니다:

- **실측 Trace ID:** `sc001-live-1707d981`
- **Trace Name:** `LegalConsultation`
- **Session ID:** `SC-001`
- **Tags:** `['LegalAgent']`
- **총 관측치 (Observations):** 34개 (Spans: 28개, Generations: 6개)
- **상담 총 계산 비용 (Total Trace Cost):** **`$0.164602`**

### 세부 Generation 실측 내역

| No. | 식별자 (ID) | 이름 (Name) | 모델 (Model) | 토큰 사용량 (Usage) | 계산 비용 (Cost) | 부모 구간 (Parent Span) |
|---|---|---|---|---|---|---|
| 1 | `adc0616a-acc5` | `LegalAgent` | `gpt-5.4-2026-03-05` | 1,123 → 189 (∑ 1,312) | **$0.005642** | `0c845389` (supervisor_init) |
| 2 | `87e44e41-08d3` | `LegalAgent` | `gpt-5.4-2026-03-05` | 988 → 87 (∑ 1,075) | **$0.003775** | `1b422132` (route) |
| 3 | `da3b1178-4d6e` | `LegalAgent` | `gpt-5.4-2026-03-05` | 342 → 39 (∑ 381) | **$0.001440** | `26c3bd7a` (plan) |
| 4 | `41c38362-4b0f` | `LegalAgent` | `gpt-5.4-2026-03-05` | 967 → 868 (∑ 1,835) | **$0.015437** | `6f1a7552` (specialist) |
| 5 | `847dd9d9-fc6b` | `LegalAgent` | `gpt-5.4-2026-03-05` | 2,714 → 4,335 (∑ 7,049) | **$0.071810** | `b9b024d0` (synthesize) |
| 6 | `82df9bb8-e7e3` | `LegalAgent` | `gpt-5.4-2026-03-05` | 6,691 → 3,318 (∑ 10,009) | **$0.066498** | `f4dbb711` (verification) |

### 실측 검증 항목 충족 여부
1. **LLM 실제 호출 횟수와 Generation 수 일치:** 6회 호출에 정확히 6개 Generation 생성 (중복 없음)
2. **모델명 정상:** `unknown` 없이 모든 항목이 `gpt-5.4-2026-03-05`로 정확히 기록
3. **입출력 토큰 일치:** OpenAI API 반환 토큰과 Langfuse `usage` 일치
4. **비용 정상 기록:** Langfuse 모델 단가에 따라 각 호출별 및 트레이스 총 비용($0.164602)이 정상 산출
5. **Parent/Child 구조 정상:** 모든 Generation이 해당 노드 Span 하위에 정확히 연결
6. **상담 간 Span 혼합 없음:** `SC-001` 트레이스 내에 타 상담의 Span이 단 1건도 섞이지 않음

---

## 5. 지침 준수 및 보고

> [!NOTE]
> `AGENTS.md` 지침에 따라 P0 잔여 결함 보완 및 단위·실측 검증을 모두 마쳤으며, 사용자 지시 없이 P1 단계로 자동 진행하지 않고 대기합니다.
