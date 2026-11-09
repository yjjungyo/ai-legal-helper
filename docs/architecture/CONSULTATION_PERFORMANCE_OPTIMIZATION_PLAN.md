# 법률 상담 워크플로우 성능 개선 및 응답 지연 단축 방안 (RFC)

- **문서 버전:** v1.0
- **작성 일자:** 2026-11-10
- **상태:** 제안 (Proposed / Implementation-Ready)
- **대상 모듈:** `ai_legal_helper` 상담 워크플로우 전반 (`legal_workflow.py`, `verification.py`, `synthesizer.py`, `semantic_judgment.py`)

---

## 1. 개요 및 배경 (Executive Summary)

### 1.1 배경 및 현재 상황
본 시스템(`ai-legal-helper`)은 다중 법률 에이전트(Multi-Agent), RAG, 엄격한 법률 사실관계 및 시행일 검증(Temporal Legal Verification)을 결합하여 환각(Hallucination) 없는 고신뢰 법률 상담을 제공하고 있다.

그러나 최근 실측 관측(Langfuse Trace) 분석 결과, 단일 법률 상담 질의를 처리하는 데 **평균 113.2초 (약 1분 53초)**가 소요되어, 실제 사용자가 체감하기에 심각한 응답 지연이 발생하고 있다.

### 1.2 선행 최적화 이력 및 성과
- **1차 최적화 (정산 계산기/상담 의미론 Fast-Path):**
  - 사실 목록 순회 시 무조건 LLM을 호출하던 문제를 비금액/비종료 문장 Fast-Path 및 인스턴스 캐시로 개선.
  - LLM 호출 수: 181회 ➡️ 57회 단축 (총 소요 시간 206초).
- **2차 최적화 (프롬프트 중복 제거 & 부칙 해석 병목 해소):**
  - `synthesizer.py`의 중복 증거 원문 블록(2,272자) 제거 및 사건 브리핑 단일 소스 정돈.
  - 40개 법령 조문에 대한 순차 부칙 해석 루프(109초 소요)에 사건 키워드/조문 불일치 Fast-Path 적용.
  - 총 소요 시간: **206초 ➡️ 113.2초 (45% 단축, -93초 절감)**, LLM 호출 수: **57회 ➡️ 18회**.

### 1.3 당면 과제
113초 중 **사후 검증 노드(`verification_node`)와 사후 분류(`finalize_node`)에서만 77.3초(전체의 68.3%)**를 소모하고 있다. 상담 품질과 법적 안정성을 절대 훼손하지 않으면서, 최종 응답 시간을 **113초 ➡️ 20~30초대(최대 70~80% 추가 단축)**로 압축하기 위한 종합 성능 개선 방안을 정의한다.

---

## 2. 프로덕션 트레이스 심층 분석 (Trace: `ad99de72-3f16-42c4-8435-44073cee7f9f`)

### 2.1 트레이스 프로파일
- **질의:** *"임대차 계약 후 다른 계약서 작성 없이 현재 2026년까지 계속 거주하고 있습니다. 이건 묵시적 계약연장에 해당하나요 ?"*
- **사건:** 전세보증금 반환 사건 (`87901cfe-4b0f-49fb-af07-a6015ab4ee91`)
- **총 레이턴시:** **113.17s**
- **LLM 총 호출 수:** **18회** (누적 순수 LLM 생성 시간: 111.41s)

### 2.2 노드별 지연 시간 및 비중 분석

```
[113.2s 전체 워크플로우 구성]
├── 1. 사전 분석 파이프라인 (8.5s | 7.5%)
│   ├── intent_analysis_node (4.3s)
│   ├── route_node (2.4s)
│   └── statute_search_plan_node (1.8s)
├── 2. 전문 에이전트 실행 (19.1s | 16.9%)
│   ├── query_rewriting (2.0s)
│   └── specialist_agent_react (16.6s)
├── 3. 종합 답변 초안 작성 (7.5s | 6.6%)
│   └── synthesizer_node (7.5s)
└── 4. 사후 검증 및 확정 파이프라인 (77.4s | 68.3%) 🚨 최대 병목
    ├── verification_node (62.9s)
    │   ├── run_verification LLM 1회 (55.2s, 6.5KB JSON 생성) 🚨
    │   └── semantic_judgment 직렬 4회 (7.7s)
    └── finalize_node (14.4s)
        └── semantic_judgment 직렬 7회 (14.4s)
```

| 구간 | 실행 노드 / 구성 | 소요 시간 | 비중 | 주요 병목 원인 |
| :--- | :--- | :--- | :--- | :--- |
| **사전 분석** | `intent_analysis`, `route`, `statute_plan` | **8.5초** | 7.5% | 단순 분류 작업임에도 3번의 LLM 직렬 네트워크 통신 발생 |
| **에이전트 실행** | `run_agents_node` | **19.1초** | 16.9% | ReAct 쿼리 재작성(2.0s) 및 법률 추론 본체(16.6s) |
| **답변 종합** | `synthesize_node` | **7.5초** | 6.6% | 정상 작동 (사건 브리핑 및 인용 단일 소스 처리) |
| **사후 검증** 🚨 | `verification_node` (`run_verification`) | **62.9초** | **55.6%** | **최대 병목:** 초안 답변의 모든 문장을 분해하여 거대 JSON(6,582자)을 출력하느라 1회 호출에 **55.2초** 소요 |
| **사후 의미판정** 🚨 | `finalize_node` 및 내부 `semantic_judgment` | **22.1초** | **19.5%** | 정산/처분/케이스 델타 판정을 위해 단문 단위로 **11회의 LLM을 순차 직렬 호출** (각 1.5~2.6초 소요) |
| **전체 합계** | - | **113.2초** | 100.0% | - |

---

## 3. 목표 성능 지표 (Target SLO)

| 지표 | 현재 (As-Is) | 1단계 목표 (단기) | 2단계 목표 (중장기) |
| :--- | :--- | :--- | :--- |
| **전체 응답 시간 (E2E Latency)** | **113.2초** | **35초 이하** (-69%) | **18~25초** (-80%) |
| **LLM 호출 횟수 (API Calls)** | **18회** | **5~6회** (-70%) | **3~4회** |
| **최초 토큰 도달 시간 (TTFT)** | 113초 (배치 반환) | 35초 | **10초 이내 (스트리밍)** |
| **법률 검증 무결성 (Accuracy)** | 100% 유지 | 100% 유지 | 100% 유지 |

---

## 4. 구체적 성능 개선 방안 (Actionable Solutions)

### 방안 1: `verification_node` 거대 JSON 병목 해소 (55.2s ➡️ 10~15s, -45초 절감)

#### 문제점
현재 `VERIFICATION_PROMPT`는 초안 답변 전체를 문장(Claim) 단위로 분해하고, 모든 문장에 대해 10개 이상의 메타데이터 필드(`claim_type`, `source_ids`, `fact_status`, `model_reason`, `inference_basis`, `inference_limit`, `grounding_status`, `user_statement_basis`, `model_grounding_status`, `user_statement_equivalent`)를 포함하는 거대한 JSON(6.5KB 이상)을 생성하도록 강제하고 있다. 이로 인해 모델의 출력 토큰 생성 시간이 55초 이상 소요된다.

#### 개선 설계
1. **린 검증 스키마 (Lean Verification Schema) 도입:**
   - 정상적으로 입증된 진술(PASS 항목)은 장황한 근거 문장 없이 문장 식별자와 인용 ID 매핑만 최소화하여 출력.
   - 위험 요소(위반, 미검증, 시간 충돌, 허위 사실)가 있는 문장만 상세 `reason`을 생성하도록 조건부 출력 설계.
   - 출력 JSON 크기를 6.5KB ➡️ 1.5KB 이내로 축소하여 생성 토큰 수를 75% 절감.
2. **이원화 모델 아키텍처 (Flash Verification):**
   - 심층 법률 추론이 완료된 초안을 단순 출처 대조·인용 검증하는 작업은 초고속 경량 모델(`gemini-1.5-flash` / `gpt-4o-mini`)로 위임.
   - 추론 속도 4~5배 향상으로 검증 시간 55초 ➡️ 8~12초로 단축.
3. **결정론적 패스트패스(Deterministic Bypass) 조건 합리화:**
   - 현재 `substantive_legal_sources`가 존재하면 결정론적 QA가 ALL PASS여도 무조건 Full LLM 검증으로 진입함 (`verification.py:962`).
   - 초안에 인용된 모든 법령 조문이 검색된 출처와 100% 일치하고, 브리핑 확정 사실과 충돌이 없는 경우 Full LLM 검증을 안전하게 건너뛰는 바이패스 로직 적용.

---

### 방안 2: 사후 Semantic Judgment 11회 직렬 호출 제거 (22.1s ➡️ 2~3s, -19초 절감)

#### 문제점
`verification_node`와 `finalize_node`(`final_disposition.py`, `detect_case_delta` 등)에서 다음 질문/진술들을 판정하기 위해 개별 LLM 호출을 **11회 연속 직렬 실행**하고 있다:
- `CONTRACT_DEPOSIT_PRINCIPAL_CLASSIFICATION` (계약금, 잔금 등 2회)
- `REPAID_AMOUNT` 판정 (2회)
- `MOVE_OUT_QUESTION`, `NEW_ATTACHMENT_ASSERTION`, `NOTICE_DATE_CORRECTION` 등 질문/답변 문장별 개별 판정 (7회)

#### 개선 설계
1. **배치 의미 분류(Batch Semantic Classification):**
   - 11번의 개별 프롬프트 호출 대신, 분류 대상 문장 전체를 하나의 리스트로 묶어 **단 1회의 배치 LLM 호출**로 구조화된 딕셔너리를 일괄 반환.
   - 11회 호출(22.1초) ➡️ 1회 호출(2.5초)로 압축 (**약 19.5초 즉시 절감**).
2. **비동기 병렬화 (`asyncio.gather` / `ThreadPoolExecutor`):**
   - 독립적인 쟁점 판정 항목들을 직렬 순회가 아닌 병렬로 동시 실행하여 지연 시간을 가장 긴 단일 호출(2초 내외) 수준으로 수렴.
3. **사전 필터링 Fast-Path 확대:**
   - "묵시적 계약연장에 해당하나요?", "원하시면 다음 단계로..."와 같은 순수 법률 질의나 시스템 안내 문장은 정산/퇴거/가압류 등과 명백히 무관하므로 키워드 기반으로 LLM 호출 전 즉시 제외.

---

### 방안 3: 사전 노드 파이프라인 통합 (8.5s ➡️ 3.0s, -5초 절감)

#### 문제점
상담 시작 단계에서 세 단계의 단순 분류 노드가 직렬로 실행된다:
1. `intent_analysis_node`: 4.26초
2. `route_node`: 2.39초
3. `statute_search_plan_node`: 1.84초

#### 개선 설계
- **통합 디스패처 (Unified Dispatcher Prompt):**
  - 사용자의 질문을 1회 분석할 때 [상담 의도(Intent) + 법률 분야(Route) + 시행일 검색 필요성(Statute Plan)]을 단일 프롬프트에서 한 번에 추론.
  - LLM 호출 3회(8.5초) ➡️ 1회(2.5~3.0초)로 통폐합 (**약 5.5초 절감**).

---

### 방안 4: 전문 에이전트 ReAct 최적화 (19.1s ➡️ 12s, -7초 절감)

#### 문제점
- 질문이 이미 명확한 단일 법률 질문임에도 불필요하게 `rewrite_query`(2.0초)를 별도로 실행함.
- 전문 에이전트가 ReAct 프레임워크 내에서 불필요하게 긴 생각(Thought)과 중간 단계를 생성함.

#### 개선 설계
- 질문에 핵심 법률 키워드가 포함되어 있고 길이가 충분한 경우 쿼리 재작성 스킵 (Fast-Path).
- ReAct 루프의 반복 횟수(max_iterations)를 1~2회로 엄격 제한하고, 고정 검색 도구(Fixed Retrieval Tool)를 Direct-Inject 방식으로 전환.

---

### 방안 5: 스트리밍 및 체감 응답시간 혁신 (UX Latency Optimization)

#### 문제점
현재 아키텍처는 검증과 정리가 모두 끝난 113초 시점에 최종 답변 텍스트를 한꺼번에 반환하므로 사용자가 2분 가까이 빈 화면/로딩 인디케이터만 보며 대기해야 한다.

#### 개선 설계
```
[2단계 점진적 응답 파이프라인]
1. Synthesizer 초안 생성 완료 (T = 15~20초 시점)
   └── 클라이언트로 초안 답변 즉시 스트리밍 전송 (사용자는 15초부터 텍스트 열람)
2. 백그라운드 Verification & Citation 정비 (T = 20~30초 시점)
   └── 검증 완료 배지, 인용 출처 카드, 확정 상태를 SSE(Server-Sent Events) 이벤트로 실시간 푸시
```
- 사용자의 체감 대기시간(TTFT)을 **113초 ➡️ 15초 이내로 86% 이상 획기적 단축**.

---

## 5. 예상 성능 개선 종합 매트릭스 (Before vs After)

```mermaid
gantt
    title 상담 처리 구간별 소요 시간 비교 (단위: 초)
    dateFormat X
    axisFormat %s초

    section As-Is (현재: 113.2초)
    사전분석(Intent/Route/Plan 3회)    :a1, 0, 8.5
    전문 에이전트(민법/주임법)         :a2, 8.5, 27.6
    Synthesizer 초안작성              :a3, 27.6, 35.1
    Verification LLM 전수분해         :crit, a4, 35.1, 90.3
    Semantic Judgments 직렬 11회      :crit, a5, 90.3, 113.2

    section To-Be (개선 후: 26.5초)
    통합 디스패처 (Intent/Route 1회)   :b1, 0, 3.0
    전문 에이전트 최적화               :b2, 3.0, 15.0
    Synthesizer 초안작성              :b3, 15.0, 22.0
    경량화 Verification (린 스키마)   :b4, 22.0, 24.5
    배치 Semantic Judgment (1회)      :b5, 24.5, 26.5
```

### 세부 수치 비교표

| 파이프라인 단계 | 현재 소요시간 (As-Is) | 개선 후 소요시간 (To-Be) | 절감 시간 | 핵심 개선 기법 |
| :--- | :--- | :--- | :--- | :--- |
| **1. 사전 분석 (Intent/Route/Plan)** | 8.5초 (3회) | **3.0초 (1회)** | **-5.5초** | 통합 디스패처 단일 프롬프트화 |
| **2. 전문 에이전트 (RAG & ReAct)** | 19.1초 (2회) | **12.0초 (1회)** | **-7.1초** | 쿼리 리라이팅 바이패스 및 검색 캐시 |
| **3. 종합 답변 초안 (Synthesizer)** | 7.5초 (1회) | **7.0초 (1회)** | **-0.5초** | 브리핑 단일 소스 유지 (현상 유지) |
| **4. 사후 검증 (Verification LLM)** | 55.2초 (1회, 6.5KB) | **2.5초 (경량화/Flash)** | **-52.7초** | 린 스키마 + 고속 검증 모델 분리 |
| **5. 사후 의미판정 (Judgments)** | 22.1초 (11회 직렬) | **2.0초 (1회 배치)** | **-20.1초** | 11회 직렬 호출 ➡️ 단일 배치 묶음 |
| **총합 (E2E Latency)** | **113.2초 (18회)** | **26.5초 (5회)** | **-86.7초 (76.6% 단축)** | |

---

## 6. 구현 우선순위 및 로드맵 (Action Plan)

### Phase 1: 즉시 적용 가능한 퀵윈 (Quick Wins, 113s ➡️ 55s 달성)
- [ ] **Semantic Judgment 배치화 및 필터링:** `finalize_node`와 `verification_node`의 11회 직렬 호출을 단일 배치 또는 `asyncio.gather` 병렬 호출로 변경 (-20초).
- [ ] **통합 디스패처 구현:** `intent_analysis_node`와 `route_node`를 단일 LLM 호출로 통합 (-5.5초).
- [ ] **쿼리 리라이팅 불필요 시 Fast-Path 바이패스** (-2.0초).

### Phase 2: 검증 아키텍처 개편 (55s ➡️ 26s 달성)
- [ ] **Verification 출력 JSON 스키마 슬림화:** 성공 문장의 불필요한 메타데이터 필드를 제거하고 이상 징후/미검증 문장만 상세 출력 (-35초).
- [ ] **Verification 전용 고속/경량 모델 분리 적용:** 검증 노드에 `gemini-1.5-flash` 등 고속 모델 옵션 도입 (-15초).
- [ ] **결정론적 1차 통과(Deterministic Bypass) 조건 완화.**

### Phase 3: 체감 UX 혁신 (체감 대기시간 15초 이내)
- [ ] **초안 스트리밍(Token Streaming) & 후속 검증 배지(Verification Badge) 2단계 렌더링 파이프라인 구현.**
- [ ] 세션 레벨 캐시(동일 질의/후속 질의 간 검색 결과 재사용) 활성화.

---

## 7. 검증 및 안전성 보장 기준

1. **법률 안전성 불변 원칙:** 검증 시간을 단축하더라도 법령 조문 인용의 일치 여부, 시행일/경과조치 판정, 확정 사실관계 대조의 엄격성은 기존과 100% 동일하게 유지되어야 한다.
2. **회귀 테스트 세트 (Regression Suite):**
   - 기존 검증 테스트(`test_verification_agent.py`, `test_sc001_temporal_plan_consistency.py`, `test_synthesizer_evidence_grounding.py` 등) 전수 PASS 필수.
3. **관측성 추적 (Observability):**
   - 각 개선 단계 적용 후 Langfuse Trace를 통해 실제 노드별 Latency 및 토큰 소모량을 정량 비교하여 배포를 검증한다.
