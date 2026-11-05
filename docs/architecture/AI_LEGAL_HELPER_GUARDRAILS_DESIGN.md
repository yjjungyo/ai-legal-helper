# AI Legal Helper — Guardrails 설계 및 코드 리뷰 정리

- 작성 기준: 2026-11-05
- 범위: SC-001 1차 사건 상담, DOCUMENT_MODE 중심
- 검토 방법: GitHub `main` 정적 코드 리뷰. 실제 실행·테스트·DB 변경은 수행하지 않음.
- 목적: 법률 상담 답변의 사실·법령·출처 오류가 최종 사용자에게 전달되지 않도록 통제하는 장치를 명확히 설명하고 개선 과제를 정리한다.

## 1. 개념 정의

**Verification(검증)**은 답변에 포함된 주장(Claim)이 증거 원문과 법령 근거로 뒷받침되는지 판단하는 절차다.

**Guardrails(가드레일)**는 입력부터 최종 출력까지 위험한 추론, 부정확한 인용, 미확인 법령 적용 및 미검증 답변의 전달을 방지하는 통제 장치의 총체다. 따라서 Verification은 Guardrails의 한 구성요소다.

**Self-Correction(자가교정)**은 Verification에서 발견한 결함을 재작성 또는 보강 검색으로 수정하고 다시 검증하는 복구 루프다. Self-Evolution은 장기적 개선 프로세스이며 본 상담 1회 실행의 Guardrails와 구분한다.

## 2. Guardrails 분류

| 구분 | 목적 | 구현·검토 근거 | 실패 시 기대 동작 |
|---|---|---|---|
| 입력 가드레일 | 질문에 필요 없는 사건 원문 유입 방지 | `intent_analysis_node`, `consultation_mode`, `evidence_unavailable_node` | 사건 근거가 필요하지만 승인 원문이 없으면 판단 유보 |
| 증거 가드레일 | 반려·삭제·변경된 문서 사용 방지 | `document_sources`, `validate_document_snapshot` | 검증 실패 및 확정 차단 |
| 출처 가드레일 | 작성·검증에 사용한 출처 일치 | `answer_source_manifest`, `content_sha256` 비교 | 출처 불일치 시 검증 실패 |
| 주장 가드레일 | 사실·법률 주장과 근거 대조 | `verify_answer` → `run_verification` | PASS / REVISE / INSUFFICIENT 판정 |
| 시간 가드레일 | 시행일·적용시점 오판 방지 | `evaluate_temporal_answer_gate`, `apply_temporal_gate_to_verification` | BLOCK 시 공식 검색 또는 안전 종료 |
| 복구 가드레일 | 오류 수정 및 재검증 | `next_verification_step`, `revise_node`, `generate_answer(repair=True)` | 재작성 최대 3회, 재검증 |
| 출력 가드레일 | 미검증 초안 전달 방지 | `finish_answer`의 초안·출처 해시 재확인, 제한 답변 재검증 | 검증되지 않으면 WITHHELD |

> 이 표는 코드에서 확인한 통제 경로를 정리한 것이다. 각 LLM 검증 판정의 실제 정확도나 E2E 실행 성공을 증명하는 표는 아니다.

## 3. SC-001 1차 상담 정상 경로

전제: 이번 상담에 등록된 승인 증거만 사용하고, RAG가 정확한 법령을 검색했으며 Agent가 정확한 초안을 작성했다고 가정한다. 특정 증거 번호·금액·질문 원문은 실제 Gold Set 확인 전까지 확정하지 않는다.

1. `intent_analysis_node`: 사건 증거가 필요한 질문인지 결정하고 사건 브리핑을 로딩한다.
2. `run_agents_node` 등: 법령 검색 및 분석을 수행한다.
3. `synthesize_node` → `generate_answer`: 사건 원문과 법령 출처를 사용해 초안을 작성하고 출처 명세를 생성한다.
4. `verification_node` → `verify_answer`: 승인 문서 상태, 출처 해시, 주장별 근거 및 질문 충족을 검증한다.
5. `evaluate_temporal_answer_gate`: 시행일·적용시점 관련 위험을 검증 결과에 반영한다.
6. `supervisor_verification_decision`: PASS이고 시간 가드레일이 차단하지 않으면 `finalize`로 보낸다.
7. `finalize_node` → `finish_answer`: 초안 해시, 출처 명세, 문서 상태를 재확인하고 최종 답변을 반환한다.
8. `END`: 상담 종료.

## 4. 분기별 시나리오

### G-01: 검증 통과
- 조건: `verification_result.status == PASS`, 시간 가드레일 미차단, 문서·출처 스냅샷 유효.
- 경로: Verification → Finalize → END.
- 기대: 검증된 초안을 그대로 반환하고 출처를 연결한다.

### G-02: 일부 주장 오류
- 조건: Verification이 `REVISE` 또는 수정 가능한 `INSUFFICIENT`를 반환하며, 우선할 법령 검색 요청이 없음.
- 경로: Verification → Revise → Verification → (PASS 시 Finalize, 아니면 추가 분기).
- 현재 구현: DOCUMENT_MODE의 `revise_node`는 `generate_answer(state, repair=True)`를 호출한다. 기존 초안, 검증 지적사항, `preserved_points`를 재작성 입력으로 제공한다.
- 유의: 문서 상담은 코드 기반 문장별 교체가 아니라 LLM 기반 재작성이다. 정상 주장 보존은 입력 지침과 재검증에 의존한다.

### G-03: 법령 근거 부족
- 조건: 검증 결과에 추가 법령 검색 요청이 존재함.
- 경로: Verification → `statute_search_approval` 또는 승인된 `execute_statute_search` → 재분석·재검증.
- 유의: 승인 상태와 검색 횟수 제한이 적용된다. 실제 법령 검색의 정확성은 별도 검증 대상이다.

### G-04: 적용시점 위험
- 조건: `temporal_gate.status == BLOCK`.
- 경로: 후보 법령이 있고 공식 검색이 미실행이면 승인 요청, 그렇지 않으면 `insufficient`.
- 기대: 시행일 미확인 상태에서 확정적 법률 판단을 전달하지 않는다.

### G-05: 재작성 한도 초과
- 조건: `revision_count >= 3`, PASS 미달.
- 현재 경로: 초안과 Claim이 있으면 `finalize`로 이동할 수 있다. 그러나 `finish_answer`는 PASS 여부와 해시를 재확인하고, 제한 답변을 새로 작성·재검증하거나 `WITHHELD`를 반환한다.
- 개선 검토: `finalize` 진입의 의미를 ‘최종 출력 정책 실행’으로 명확히 하고, 제한 답변 가능성과 즉시 유보를 라우팅 수준에서 구분하면 이해하기 쉽다.

### G-06: 증거 변경·반려
- 조건: 작성 후 증거의 승인 상태, 해시, 추출 버전 등이 달라짐.
- 경로: `validate_document_snapshot` 실패 → 검증 실패 또는 최종 출력 유보.
- 기대: 과거에 승인됐다는 이유로 현재 무효인 문서를 인용하지 않는다.

### G-07: 생성·검증 기술 오류
- 조건: 초안 생성 실패, 출처 명세 불일치, 검증 예외 등.
- 경로: `INSUFFICIENT` 또는 `VERIFICATION_ERROR` → 안전 종료.
- 기대: 시스템 오류를 검증 성공으로 둔갑시키지 않는다.

## 5. 현재 코드 리뷰 결과

| 항목 | 판정 | 근거·주의 |
|---|---|---|
| 정상 PASS 흐름 | 구조상 정상 | Verification → Finalize → END 연결 확인 |
| 승인 증거 통제 | 구현 확인 | 승인 원문 필터와 문서 스냅샷 재검증 |
| 출처 무결성 | 구현 확인 | 생성·검증·최종화 사이 해시 비교 |
| 시행일 차단 | 구현 확인 | Temporal Gate BLOCK 우선 처리 |
| Self-Correction 반복 | 구현 확인 | DOCUMENT_MODE 재작성 최대 3회 |
| 정상 주장 보존 | 보완 검토 | 문서 상담 전체 재작성 방식으로 보존이 절대 보장되지는 않음 |
| 재작성 한도 이후 라우팅 | 보완 검토 | `finalize`가 PASS와 제한 출력 정책을 함께 의미함 |
| 법령 검색 일관성 | 보완 검토 | 문서 상담 직접 Vector 검색과 공통 Law Retrieval Service의 기능 정합성 확인 필요 |
| 최종 인용 출처 | 보완 검토 | Claim `source_ids` 누락 시 문자열 기반 폴백 가능 |

## 6. 과제 범위 내 권고사항

**우선순위 1 — 논리적 정합성**
1. Verification 실패 후 `finalize` 진입은 ‘검증 성공’이 아니라 ‘제한 출력 또는 유보 판단’임을 명확히 한다.
2. 수정 전후 Claim 비교로 정상 주장이 소실되거나 바뀌지 않았는지 확인한다. 불필요한 전체 재작성 기능 확장은 지양한다.
3. 최종 출처 목록이 검증된 Claim의 출처와 일치하는지 확인하고, 출처 누락을 정상 인용으로 오인하지 않도록 한다.

**우선순위 2 — 검색 경로 정합성**
4. 문서 상담에서 사용한 법령 출처가 공통 법령 검색 서비스의 조문·MST·시행일 검증 정책과 일치하는지 점검한다.

**범위 제외**
- 운영용 heartbeat, 고가용성, 분산 재시도 등 과제 범위를 벗어나는 운영 고도화.
- 정적 리뷰만으로 확인할 수 없는 실제 성능·정확도 수치 주장.

## 7. 평가 발표용 핵심 설명

> AI Legal Helper의 Guardrails는 답변 생성 이후 단순한 LLM 재질문에 그치지 않습니다. 승인된 사건 증거만 사용하도록 입력을 통제하고, 생성된 답변의 주장과 실제 원문·법령을 대조합니다. 법령 시행일과 적용시점도 별도 검증합니다. 오류가 발견되면 재작성과 재검증을 수행하며, 검증되지 않은 결론은 제한하거나 판단을 유보합니다. 또한 작성 시점과 최종 반환 시점의 문서·출처 무결성을 다시 확인합니다.

## 8. 관련 소스

- `backend/src/ai_legal_helper/workflows/legal_workflow.py`
  - `intent_analysis_node`, `verification_node`, `supervisor_verification_decision`, `revise_node`, `finalize_node`, `build_legal_graph`
- `backend/src/ai_legal_helper/workflows/document_consultation.py`
  - `document_sources`, `generate_answer`, `validate_document_snapshot`, `verify_answer`, `next_verification_step`, `finish_answer`
- `backend/src/ai_legal_helper/agents/verification.py`
  - `run_verification` (실제 판정 정확도는 추가 검증 필요)
- `backend/src/ai_legal_helper/legal_knowledge/temporal_verification.py`
  - 시행일·적용시점 가드레일

**주의:** 본 문서는 확인된 코드 흐름을 설명하는 설계·리뷰 문서다. 코드 변경이나 실행 테스트는 수행하지 않았다.

## 9. 후속 전체 분기 리뷰 및 수정 기록 (2026-11-05)

### 공식 법령 검색 분기

- `statute_search_approval_node`는 `interrupt`로 사용자 승인 여부를 수신한다.
- `statute_search_approval_condition`은 `APPROVED`만 공식 검색으로 보낸다.
- `execute_statute_search_node`는 승인 상태를 다시 검사하며, DOCUMENT_MODE 후속 검색은 `execute_document_search`로 위임한다.
- `execute_document_search`는 `pending_searches`로 중복 요청을 제외하고, 승인된 법령 범위와 검색 횟수(최대 2회)를 검사한다.
- `statute_search_result_condition`은 API 오류 시 판단 유보, 사전 검색 시 분석 진행, 사후 검색 시 재분석을 선택한다.
- `re_analyze_node`의 DOCUMENT_MODE는 `generate_answer(repair=True, increment_revision=False)`로 재작성 후 Verification으로 복귀한다.
- 검색 결과가 `NOT_FOUND` 또는 `PARTIAL_SUCCESS`인 경우에도 재작성은 가능하지만, 최종 출력의 검색 미확인 안내 및 검증 조건을 지켜야 한다.

### 확인된 오류 및 실제 수정

**오류: 재작성 성공 후 과거 `answer_generation_error` 상태 잔류**

- 위치: `backend/src/ai_legal_helper/workflows/document_consultation.py`의 `generate_answer`.
- 원인: 성공한 재작성의 반환값이 `answer_generation_error`를 명시적으로 초기화하지 않아, LangGraph 상태 병합 시 과거 생성 실패가 남을 수 있었다.
- 영향: `verify_answer`의 생성 오류 검사와 `next_verification_step`의 오류 분기가 정상 재작성을 잘못 차단할 수 있었다.
- 수정: 작성 시도 시작 시 `answer_generation_error: None`을 반환 상태에 포함하고, 실제 예외가 발생한 경우에만 오류명을 기록하도록 했다.
- 회귀 테스트 추가: `backend/tests/unit/test_document_consultation.py::test_successful_document_repair_clears_previous_generation_error`.
- 코드 커밋: `9250186fb77dbfe6662c5bd1783616fad72f087c`.
- 테스트 커밋: `30872b5256d75e5035a4265be945a0e38c78fb60`.
- **실행 상태:** 정적 검토 및 GitHub 반영 완료. 테스트 실행 및 E2E 검증은 미수행.

### 추가 개선 후보 (미수정)

1. 문서 상담의 `revise_node`는 전체 재작성 방식이므로 정상 Claim 보존을 별도 회귀 시나리오로 검증한다.
2. `next_verification_step`에서 한도 초과 후 `finalize`로 가는 경우는 PASS 확정이 아니라 제한 출력·판단 유보 정책 실행임을 명확히 한다. `finish_answer`가 별도 검증을 수행하므로 즉각적인 미검증 답변 노출로 단정하지 않는다.
3. `finish_answer`의 출처 목록 선별에서 Claim 출처 ID 누락 시 문자열 포함 여부에 의존하는 폴백의 정합성을 검토한다.
4. DOCUMENT_MODE의 Vector 검색과 공통 Law Retrieval Service 사이 법령 버전·조문·시행일 정책 일관성을 별도로 점검한다.

**평가 범위 주의:** 본 기록은 GitHub `main` 코드의 분기 정적 리뷰에 근거한다. 실제 API 호출·DB·LLM·LangGraph 런타임을 실행하지 않았으므로 E2E 성공 여부는 주장하지 않는다.
