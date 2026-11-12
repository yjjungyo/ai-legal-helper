# AI Legal Helper — 상담 정확도·성능·토큰 비용 통합 개선 검토 보고서

- 작성일: 2026-11-12
- 저장소: `yjjungyo/ai-legal-helper`
- 검토 기준: `main` 커밋 `f1f03128f1e44a86fe085a911c6f7e689bdac00a`
- 검토 방법: 최신 개선·감사 보고서와 주요 상담 실행 소스 정적 대조
- 변경 범위: **분석 및 권고 문서만 추가. 실행 소스 미변경**
- 검증 한계: E2E 및 Langfuse 재실행 없음. 보고서의 수치는 기존 평가 기록이며 개선 후 실측치가 아님.

## 1. 결론

최적화 목표는 **법률 정확도를 유지·향상하면서 중복 LLM 호출, 중복 컨텍스트, 중복 검색 및 재검증을 줄이는 것**이다. 법령의 시점 적용, 부칙, 반대 증거, 승인 상태를 확인하기 위한 필수 검증을 무조건 제거해서는 안 된다. 우선 정확도 위험(P0)을 해결하고 동일 시나리오 회귀검증을 통과한 뒤 성능 최적화(P1)를 단계별 적용한다.

**주요 결함 후보:** (1) 시행일이 다른 법령 조문의 과도한 중복 제거, (2) 질문 첫 날짜를 계약 체결일로 간주하는 초기화, (3) 초안에 인용되지 않은 증거의 150자 축약, (4) 최신 법령의 과거 계약 적용을 암묵적으로 가정하는 프롬프트, (5) 첫 번째 금액을 보증금으로 취급하는 QA, (6) 승인 상태와 원문 대체 정보의 불명확한 경계.

## 2. 기존 E2E V2 측정치

| 시나리오 | 응답 시간(초) | 총 토큰 | LLM 호출 |
|---|---:|---:|---:|
| SC001-1 | 241.01 | 75,002 | 5 |
| SC001-2 | 115.31 | 87,486 | 5 |
| SC001-3 | 95.76 | 19,984 | 5 |
| SC002-1 | 71.11 | 38,689 | 3 |
| SC003-1 | 95.58 | 1,194 | 1 |
| **단순 평균** | **123.75** | **44,471** | **3.8** |

출처: 기존 E2E V2 평가 보고서. 5턴 평가 통과는 전체 법률 상담 정확도 100%의 근거가 아니다. SC003의 적은 토큰 대비 긴 응답시간은 토큰 외 API·승인·대기시간 분해가 필요함을 보여준다. 시나리오별 입력·증거가 다르므로 턴 간 토큰 차이를 최적화 효과로 직접 해석해서는 안 된다.

## 3. P0 — 정확도 위험: 실제 소스 대조

### P0-01 법령 버전이 다른데 동일 조문으로 중복 제거

- 위치: `backend/src/ai_legal_helper/rag/grounding_context.py`, `normalize_statute_key()`, `prune_sources_for_verification()`.
- 확인: 법령명과 조문 번호를 중복 키로 사용하고 동일 키 출처를 축약·선택한다.
- 위험: 시행 전후 조문이나 부칙이 다른데도 동일 조문으로 간주되어 Verifier가 필요한 버전을 못 볼 수 있다.
- 개선: **law_id + article + effective_date + promulgation/amendment metadata + source_hash** 기반 버전 식별. 적용례/경과조치는 별도 연결. 내용·버전까지 동일한 출처만 중복 제거. 서로 다른 시행본은 시간성 판정 완료 전까지 보존.
- 회귀: 동일 제36조의 시행 전후 버전 및 부칙을 동시에 제공하고 사건일별 올바른 법령을 고르는지 검증.

### P0-02 날짜 역할을 확인하지 않고 CONTRACT_SIGNED로 지정

- 위치: `backend/src/ai_legal_helper/workflows/legal_workflow.py`, 초기 질문 날짜 추출 및 `event_type` 할당; `workflows/temporal_search_plan.py` 173~190행.
- 확인: 질문에서 추출한 날짜가 있으면 `event_type="CONTRACT_SIGNED"`로 설정되는 경로가 있다. `build_temporal_search_plan()`은 날짜·유형 쌍이 모두 있으면 `explicit_pair`로 처리하여 LLM 사건일 추출을 생략할 수 있다.
- 위험: 법령 시행일, 통지일, 갱신일을 계약 체결일로 오인.
- 개선: 날짜 문자열 정규화와 **사건 행위 유형의 의미 판단**을 분리. 확정되지 않은 `event_type`을 생성하지 않는다. `LAW_EFFECTIVE_DATE`와 계약 관련 이벤트를 구분하고, 근거 문장과 출처를 함께 보존한다. 날짜 계산 자체는 결정론적으로 수행.
- 회귀: 개정일·시행일·계약일·통지일이 혼재한 질문, 생략된 행위, 여러 계약이 있는 질문.

### P0-03 검증 출처를 초안 인용 여부에 따라 과도하게 축약

- 위치: `rag/grounding_context.py`의 `prune_sources_for_verification()`, `agents/verification.py`의 호출부.
- 확인: 초안에서 인용하지 않은 증거의 본문을 기본 150자 내외로 축약하는 경로가 있다.
- 위험: 초안이 반대 증거를 누락하면 Verifier도 반대 증거의 결정적 구간을 못 볼 수 있다. 출처 manifest의 전체 문서와 LLM에 전달한 축약 문서를 구별해야 한다.
- 개선: 질문 쟁점, 동일 사실에 대한 상충/보완 관계, 시점 변경, 중요도에 따라 검증 출처 선정. 인용 여부는 보조 신호만 사용. 결정적 원문 span은 완전 보존. 원문 전체 manifest와 실제 검증 입력 manifest를 별도 기록.
- 회귀: 핵심 반대 사실이 긴 문서의 마지막 부분에 있고 초안에서 인용되지 않은 경우.

### P0-04 시간성 법령 적용을 가정하는 프롬프트

- 위치: `backend/src/ai_legal_helper/agents/document_answer.py` `DOCUMENT_ANSWER_SYSTEM` 54~56행.
- 확인: 최근 시행본의 기본 법리와 요건이 과거 계약에도 원칙적으로 동일 취지로 적용된다는 안내가 있다.
- 위험: 개정 조문의 소급 적용 또는 적용례 누락을 유도할 수 있다.
- 개선: 기본 법리 유사성과 **해당 버전의 법적 적용 가능성**을 분리. 과거 시행본, 개정 내용, 부칙을 확인한 경우에만 확정적 적용 판단. 단순히 최신본이라는 이유만으로 상담 전체를 중단하지는 않는다.
- 회귀: 실제 개정 조문과 부칙 적용례가 사건 시점에 따라 결론을 바꾸는 사례.

### P0-05 보증금 금액 첫 번째 매칭 오탐

- 위치: `backend/src/ai_legal_helper/agents/qa_checker.py` 220~242행.
- 확인: `deposit_matches[0]`을 기준 금액으로 사용하여 답변의 보증금 표현과 비교한다.
- 위험: 계약 보증금, 계약금, 일부 반환액, 미반환 잔액을 혼동하여 올바른 답변에 REPAIR를 요구할 수 있다.
- 개선: `amount_type`, `as_of_date`, `party`, `source`를 가진 구조화된 금액을 대조. 원금·기지급액·잔액 관계는 산술 검증하되, 금액 의미 분류는 단순 문자열 정규식으로 확정하지 않는다.
- 회귀: 계약금/잔금, 일부 반환, 상계 주장, 지급 예정과 실제 지급을 구분.

### P0-06 증거 승인 및 대체 원문 경계

- 위치: `case_intelligence/case_briefing.py`의 EvidenceSpan 복원, `workflows/legal_workflow.py`의 문서 모드 판정.
- 확인: 승인 Claim이 없을 때 전체 Claim 문장을 대체 텍스트로 사용할 수 있는 경로가 있고, 초기 모드 판정에서 `source_registry` 존재를 활용한다.
- 위험: 원문 EvidenceSpan과 파생 Claim의 출처가 혼동되거나, 단순 등록 문서 존재와 승인된 상담 근거 존재가 혼동될 수 있다.
- 개선: `REGISTERED / CLAIM_APPROVED / PARTIAL / REJECTED` 및 원문 span 확보 여부를 별도 상태로 관리. 반려된 Claim을 승인 원문 대체물로 승격 금지. 등록만 된 증거도 조건부 참고 가능하되 확정 사실과 구별.
- 회귀: EvidenceSpan 공란, 일부 승인, 전체 반려, 등록만 된 문서, 수정 후 승인 상태 변경.

## 4. P1 — 중복 입력 및 비용 최적화

### P1-01 이전 상담 이력 다중 주입

- 위치: `legal_workflow.py`, `conversation_context.py`, `document_consultation.py`.
- 관찰: 최근 3턴 메시지, 사건 요약/최근 턴, 별도 `user_history`가 중첩될 수 있다.
- 개선: 기본 상담에는 현재 질문 + 최신 승인 사실 + 관련 증거만 전달. "그 방법", "앞서 말한 날짜" 같은 지시어가 필요한 경우에만 특정 이전 발언을 선택 복원. 이전 AI 답변은 사실의 SSOT가 아니다.
- 검증: 대명사·생략어 후속 질문의 정확도 및 입력 토큰 수 비교.

### P1-02 법령 검색 및 LLM 반복

- 위치: `legal_workflow.py`의 검색·재분석·검증 분기, `document_consultation.py`.
- 개선: 법령 존재 여부가 아니라 **쟁점에 필요한 조문·버전·부칙이 충분한지** 판단하여 추가 검색 여부 결정. 동일 요청·법령 버전의 검색은 캐시하되 시행일과 검색 시점 키를 보존. 정확한 초안은 부분 수정만 수행. 동일 오류의 무변경 재검증은 반복하지 않는다.
- 주의: HITL 승인/재개 및 공식 API 오류 처리 정책을 임의로 우회하지 않는다.

### P1-03 상담 경로 책임 분리

- 권장 기본 경로: `Context Preparation → Legal Retrieval → Synthesizer → Verification → Finalize`.
- 조건부 경로: 추가 공식 법령 검색 승인, 관련 증거 보강, 국소 수정, 재검증, 유보.
- 주의: LangGraph 노드 개수 감소 자체가 성능 개선은 아니다. 실제 LLM 호출·입출력 토큰·검색·직렬화 시간을 기준으로 판단한다. 사건 변경, 증거 승인, 문서 생성은 사용자 요청에 따라 별도 처리한다.

### P1-04 State 경량화

- `LegalState`에는 사건/증거/법령의 참조 ID, 버전·해시, 현재 질문, 검증 결과, 승인·수정 상태를 유지.
- 긴 원문·검색 후보·이전 대화는 저장소/일시적 컨텍스트에서 필요한 구간만 로드.
- HITL 재개 시 원문·버전 일관성 및 체크포인트 복구 검증 필수.

## 5. 기존 보고서 권고에 대한 정정

| 기존 권고/진단 | 소스 대조 결과 | 조치 |
|---|---|---|
| HITL `GraphInterrupt`가 계속 ERROR 처리됨 | 최신 `observability/decorators.py`에서 정상 제어 흐름 처리 분기 확인 | 재개발 전 실제 로그 회귀 확인 |
| `get_checkpointer()`가 MemorySaver 반환 → 운영 전체 메모리 | 해당 함수는 메모리를 반환하지만 `run_legal_consultation()`은 설정에 따라 `AsyncPostgresSaver`를 직접 주입 | 실행 진입점별·재시작 복구 테스트 |
| `pre_synthesis_coverage.py` 미사용이므로 삭제 | 테스트가 직접 import함 | 사용처·테스트 목적 확인 후 정리 |
| 미인용 증거 150자 축약으로 비용 절감 | 상충 증거 누락 위험 | 관련성 기반 검증 입력으로 교체 |
| QA 통과 시 의미 검증 전면 생략 | 법률 해석·부칙 적용은 단순 문자열 검사로 확인 불가 | 저위험 항목만 결정론적 검사, 핵심 법률 판단은 의미 검증 |
| 전체 재작성 fallback | 국소 수정 실패 때 비용 급증·정확도 퇴행 가능 | 실패 원인 분류, 한정적 재작성 및 회귀 |
| 프론트 단계/마크다운 불일치 | UX 문제로 중요하나 법률 정확도·토큰 절감과는 별도 | 기능 회귀로 분리 |

참고: 과거 감사 보고서의 그래프 노드 수는 해당 시점의 등록 노드 기준이다. 최신 그래프와 과거 보고서의 노드 수를 혼용하지 않는다.

## 6. 목표 KPI 및 검증 방법

| 지표 | 기준 | 제안 목표 | 측정 |
|---|---:|---:|---|
| 평균 총 토큰 | 44,471 | 30% 이상 절감 | Langfuse 턴별 input/output |
| 평균 LLM 호출 | 3.8 | 2~3회 수준 | trace의 generation 수 |
| 평균 응답시간 | 123.75초 | 60초 이하 | 요청~최종 답변, 승인 대기 별도 |
| 실제 토큰 비용 | 별도 산출 | 30% 이상 절감 | 모델별 단가×실측 토큰 |
| 답변 정확도 | 기존 E2E 기준선 | **회귀 0건** | 동일 Gold Set, 근거별 판정 |
| 시행일·부칙 오적용 | 별도 집계 | **기존 대비 악화 0건** | 시간성 전용 테스트 |
| 상충 증거 검출 | 별도 집계 | 기존 대비 악화 0건 | 누락 반대 증거 사례 |

위 수치는 **개선 목표**이며 달성 실측값이 아니다. SC001~SC007 동일 질문·증거·법령 스냅샷에서 baseline과 개선 버전을 비교한다. 각 결과 행에 Langfuse trace ID, 입력/출력 토큰, 모델, 실제 비용, 노드별 소요시간, 검색/HITL 대기, 검증 PASS/REVISE/INSUFFICIENT 및 정확도 채점 근거를 기록한다.

## 7. 단계별 실행 계획 및 중단 조건

1. **기준선 동결:** 현재 커밋·E2E 결과·Gold Set·법령 스냅샷 고정. 오류가 있던 기준선 결과는 숨기지 않고 별도 기록.
2. **P0 정확도 수정:** 법령 버전, 사건일 의미, 검증 증거, 프롬프트, 금액 유형, 승인·EvidenceSpan. 항목별 단위 테스트 후 E2E 회귀.
3. **P1 입력 최적화:** 대화 중복 제거, 증거·법령 출처 중복 제거(법적 동일성 보장), State 경량화. 각 단계 Langfuse 비교.
4. **P1 호출 최적화:** 충분성 판정, 검색 캐시, 불필요한 재분석·재검증 제거. 수정 전후 정확도 비교.
5. **선택적 모델/프롬프트 최적화:** 더 작은 모델·짧은 검증 출력은 동등성 검증 후에만 채택.
6. **최종 E2E:** 기존 상담·최신법 시행일·부칙·상충 증거·미승인 증거·HITL 재개·문서 변경을 포함.

**배포 중단 조건:** 법령 적용 시점 오판, 반대 증거 누락으로 인한 허위 PASS, 미승인/반려 사실의 확정 채택, 기존 Gold Set의 핵심 법률 결론 회귀, HITL 재개 시 출처 버전 불일치.

## 8. 소스 및 보고서 참조

- `docs/analysis/CODEBASE_IMPROVEMENT_AND_PERFORMANCE_AUDIT_REPORT_2026-11-12.md`
- `docs/analysis/COMPREHENSIVE_CODE_LOGIC_PROMPT_AUDIT_REPORT.md`
- `docs/analysis/AI_LEGAL_HELPER_FULL_WORKFLOW_SOURCE_REVIEW_2026-11-11.md`
- `backend/src/ai_legal_helper/workflows/legal_workflow.py`
- `backend/src/ai_legal_helper/workflows/temporal_search_plan.py`
- `backend/src/ai_legal_helper/workflows/document_consultation.py`
- `backend/src/ai_legal_helper/rag/grounding_context.py`
- `backend/src/ai_legal_helper/agents/verification.py`
- `backend/src/ai_legal_helper/agents/document_answer.py`
- `backend/src/ai_legal_helper/agents/qa_checker.py`
- `backend/src/ai_legal_helper/case_intelligence/case_briefing.py`
- `backend/src/ai_legal_helper/observability/decorators.py`

> **최종 권고:** 정확도를 지키는 필수 법률 판단은 유지하고, 중복 입력·중복 생성·중복 검증만 제거한다. 모든 최적화는 동일 데이터 기반 정확도 회귀와 Langfuse 비용·시간 실측으로 승인한다.
