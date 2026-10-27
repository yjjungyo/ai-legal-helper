# AI Legal Helper — P0-4.2 최종 법률 판단 무결성 보완 완료보고서 v3.1

## 법률 요건사실 검증 및 시간·권리순위 판단 정확성 강화 완료

**작성일시:** 2026-10-28  
**대상 브랜치:** `feature/p0-4.2-final-legal-integrity-v3.1`  
**기준 소스 커밋:** `a2546bd7d2b347e58b34173afa8ee9e182022052` (origin/main)  
**주요 문서 준수:** `AGENTS.md`, `CODING_COMMENT_STANDARD.md`  

---

## 1. 개요 및 목적

본 작업은 지시서 `P0-4.2 최종 법률 판단 무결성 보완 지시서 v3.1`에 따라, 실제 사건의 미검증 사실, 날짜 불일치 및 미확인 권리관계가 단정적 법률 효력으로 오판되던 5대 핵심 결함을 근원적으로 해결하고 사건 독립적 법률 판단 무결성을 강화한 작업이다.

기존 아키텍처 원칙을 준수하여 `DynamicCaseContext`를 일체 재도입하지 않았으며, `CaseEvidenceBriefing`, `FactAdjudication`, `TimelineItemBrief` 구조 내에서 엄격한 요건사실 검증 체계를 구현하였다.

---

## 2. 5개 결함별 수정 내용 요약

| 결함 번호 | 결함 항목 | 수정 전 문제점 | 수정 내용 및 법률적 효과 |
|---|---|---|---|
| **P0-01** | 주택 인도 및 전입신고 요건 검증 | 전입신고일만 확인되어도 대항요건 구비일 산정 (`elif transfer_dates`) | 전입신고와 주택 인도가 **모두** 확인된 경우에만 대항요건 구비일 및 익일 0시 대항력 산정. 하나라도 결여 시 대항요건 미확정(`opposing_satisfied_date = None`), `priority_status != "TENANT_SENIOR"` 원천 차단 |
| **P0-02** | Timeline 검증 상태 및 날짜 연결 수정 | `TimelineItemBrief`에 없는 `verification_status` 조회로 미검증 이벤트 누락 불가 | `occurrence_status == "ACTUAL"` (SCHEDULED/REQUESTED 배제) 및 `related_fact_ids`의 엄격 검증(`is_fact_strictly_verified`) 여부를 대조하여 검증된 실발생 이벤트만 권리순위에 반영 |
| **P0-03** | 해지 효력 발생일과 상담 기준일 비교 | 3개월 경과 효력 발생일이 미래인 경우에도 이미 도과하여 종료되었다고 단정 | 상담 기준일(`ref_date`, `briefing.as_of_date` 또는 `datetime.date.today()`)과 3개월 경과 효력일(`statutory_effect_date`)을 비교하여 미래인 경우 `CONDITIONAL` (`TERMINATION_EFFECT_DATE_FUTURE` / `NOTICE_EFFECT_PENDING_FUTURE`)로 처리하고 이행기 미도래 명시 |
| **P0-04** | 발송일과 도달일의 분리 | 단일 Fact에 복수 날짜 존재 시 첫 번째 날짜를 발송·도달에 단순 대입 | 날짜별 인접 결합 동사 및 문맥 윈도우를 의미론적으로 분석(`parse_notice_dates_semantically`)하여 발송일, 도달일, 임대인 회신일, 퇴거일을 정밀 분리. 최초 도달일을 회신일로 덮어쓰지 않음 |
| **P0-05** | 상충 Fact 및 가압류 부존재 검증 | 다툼 사실(`GENUINELY_DISPUTED`) 누락 및 등기부 미등록 시 부존재 단정 | `is_fact_strictly_verified`에 `GENUINELY_DISPUTED` 및 `opposing_statement` 대조를 추가하여 상충 사실 신뢰 차단. 등기부 미등록 시 가압류 부존재 단정을 금지하고 `UNCERTAIN` 유지, 오래된 등기부(1개월 이상) 최신 확인 권고 |

---

## 3. 핵심 모듈별 상세 구현 내용

### 3.1 `CaseEvidenceBriefing` (`case_briefing.py`)
- 상담 기준일자 필드 `as_of_date: Optional[str] = Field(None, description="상담 기준일자 (YYYY.MM.DD 또는 YYYY-MM-DD)")` 추가.
- 워크플로우 전반에서 상담 시점과 미래 법률 효과를 대조하는 기준 일자로 기능.

### 3.2 단일 원천 계산 유틸리티 (`settlement_calculator.py`)
1. **`is_fact_strictly_verified(f, briefing)`**:
   - `adjudication_status` 및 `trust_level`에서 `GENUINELY_DISPUTED` 명시 차단.
   - `briefing.genuinely_disputed` 대조 시 `fact_id`, `statement` 뿐만 아니라 `opposing_statement` 및 `related_fact_ids`를 종합 대조.
   - 다툼이 존재하는 Fact는 긍정적 검증 상태(`EVIDENCE_SUPPORTED`)가 있더라도 `False` 반환.
2. **`parse_notice_dates_semantically(stmt)`**:
   - 정규식 탐색된 각 날짜의 전후 문맥을 추출하여 결합 동사를 판별.
   - 부정 문맥(`수신 확인이 되지 않았다`, `도달하지 않음`, `회신 없음`)을 감지하여 미도달·미수신 상태를 도달일로 오인하지 않도록 차단.
   - 발송일(`sent_dates`), 도달일(`reach_dates`), 임대인 회신일(`ack_dates`), 퇴거일(`move_out_dates`)을 의미론적으로 분리.
3. **`evaluate_notice_status(briefing, reference_date=None)`**:
   - `ref_d` 산출: `reference_date` $\rightarrow$ `briefing.as_of_date` $\rightarrow$ `today`.
   - `is_implicit_renewal`, `has_sent`, `has_reached`, `statutory_effect_date` 도출.
   - `statutory_effect_date > ref_d`인 경우 `is_effect_date_future = True`, `is_effect_date_reached = False` 지정.
4. **`evaluate_attachment_ranking(briefing, reference_date=None)`**:
   - 전입신고(`has_transfer`)와 주택인도(`has_move_in`)를 독립 검증하여 둘 다 충족된 경우에만 대항요건 구비일 및 익일 0시 대항력 산정.
   - Timeline 이벤트 검증: `occurrence_status == "ACTUAL"` 및 `related_fact_ids` 검증 사실 연결 확인.
   - 등기사항증명서 미등록 시 `priority_status = "UNCERTAIN"` 및 최신 등기부 확인 필수 안내.
   - 등기부 확인일자가 `ref_d` 대비 1개월(30일) 이상 경과한 경우 `UNCERTAIN` 유지 및 최신 확인 권고.
   - 대항요건 미충족 시 `tenant_priority_date = None`으로 유지하여 `TENANT_SENIOR` 반환 원천 차단.

### 3.3 쟁점 검증 에이전트 (`issue_verifier.py`)
1. **`ISSUE_LEASE_TERMINATION`**:
   - 묵시적 갱신: `is_effect_date_future`일 경우 `status = "CONDITIONAL"`, `reason_codes = ["TERMINATION_EFFECT_DATE_FUTURE"]` 부여 및 "해지 효력이 발생할 예정이며 현재 시점에서는 아직 효력이 발생하지 않았음"을 명시.
   - 비묵시적 갱신: 계약 만기일이 `ref_date`보다 미래인 경우 `status = "CONDITIONAL"`, `reason_codes = ["TERMINATION_EXPIRY_DATE_FUTURE"]` 부여.
2. **`ISSUE_NOTICE_REACH`**:
   - `is_effect_date_future`일 경우 `status = "CONDITIONAL"`, `reason_codes = ["NOTICE_EFFECT_PENDING_FUTURE"]` 부여 및 도달 사실 확인과 3개월 효력 발생 예정 시점을 명확히 구분.
3. **`ISSUE_ATTACHMENT_RANKING`**:
   - 전입만 확인 시 `MOVE_IN_EVIDENCE_NEEDED`, 인도만 확인 시 `TRANSFER_REGISTRATION_EVIDENCE_NEEDED` 부여.
   - 등기부 미제출 시 `REGISTRY_EVIDENCE_NEEDED` 부여.
4. **`ISSUE_AUCTION_DIVIDEND_RISK` / `ISSUE_AUCTION_STRATEGY`**:
   - `priority_status != "TENANT_SENIOR"`인 경우 낙찰자에 대한 선순위 대항력 행사를 차단하고 배당 절차를 통한 회수 안내.

### 3.4 최종 종합 답변 (`final_disposition.py`)
- 표준 5대 행동 권고 중 경매 행동 지침(Action Item 5)을 `priority_status`에 따라 동적으로 분기:
  - `TENANT_SENIOR`: 선순위 대항력 인수 vs 우선배당 선택 안내.
  - `ATTACHMENT_SENIOR`: 후순위 권리자로서 배당신고 필수 안내.
  - `UNCERTAIN`: 권리 선후관계 확인을 위한 등기부·전입일자 대조 및 배당신고 안내.
  - `NO_ATTACHMENT`: 권리 변동 주기적 확인 및 임차권등기명령 권리보전 안내.
- Verifier 결과가 `CONDITIONAL`인 경우 `[3. 조건부 판단 및 미확인 사항]` 섹션에 전제 조건과 미확인 사항을 체계적으로 노출.

---

## 4. 반례 테스트 검증 결과 (TC-20 ~ TC-37)

`backend/tests/unit/test_case_independence_counterexamples.py`에 지시서의 신규 반례 18건(TC-20 ~ TC-37)을 추가하여 기존 19건(TC-01 ~ TC-19)과 함께 총 37건의 반례를 전수 검증하였다.

| 테스트 번호 | 함수명 | 검증 요건 | 결과 |
|---|---|---|:---:|
| **TC-20** | `test_counterexample_20_transfer_only_unconfirmed_opposing` | 전입만 확인 시 대항요건 미확정, MOVE_IN_EVIDENCE_NEEDED, 선순위 배제 | **PASS** |
| **TC-21** | `test_counterexample_21_move_in_only_unconfirmed_opposing` | 인도만 확인 시 대항요건 미확정, TRANSFER_REGISTRATION_EVIDENCE_NEEDED | **PASS** |
| **TC-22** | `test_counterexample_22_both_transfer_and_move_in_computes_next_day` | 전입(03.01)+인도(03.05) 모두 확인 시 늦은 날 익일 0시(03.06) 산정 | **PASS** |
| **TC-23** | `test_counterexample_23_timeline_scheduled_ignored` | Timeline SCHEDULED(예정) 권리순위 미반영 | **PASS** |
| **TC-24** | `test_counterexample_24_timeline_requested_ignored` | Timeline REQUESTED(요청) 권리순위 미반영 | **PASS** |
| **TC-25** | `test_counterexample_25_timeline_actual_with_unverified_fact_ignored` | Timeline ACTUAL이나 연결 Fact 미검증 시 권리순위 미반영 | **PASS** |
| **TC-26** | `test_counterexample_26_notice_future_effect_date_conditional` | 통지 도달 확인 후 효력일 미래 시 CONDITIONAL (TERMINATION_EFFECT_DATE_FUTURE) | **PASS** |
| **TC-27** | `test_counterexample_27_notice_past_effect_date_verified` | 통지 도달 후 효력일 과거 경과 시 VERIFIED | **PASS** |
| **TC-28** | `test_counterexample_28_single_fact_multiple_dates_separated` | 단일 Fact 내 발송일(04.01)·도달일(04.03) 의미론적 정확 분리 | **PASS** |
| **TC-29** | `test_counterexample_29_reach_date_not_overwritten_by_ack_date` | 최초 도달일(04.03)을 임대인 회신일(04.05)로 덮어쓰지 않음 | **PASS** |
| **TC-30** | `test_counterexample_30_multiple_notices_dates_isolated` | 복수 통지 간 날짜 혼합 방지 및 부정 문맥(수신 확인 안 됨) 분리 | **PASS** |
| **TC-31** | `test_counterexample_31_genuinely_disputed_fact_blocked` | GENUINELY_DISPUTED 사실 엄격 검증 차단 (False) | **PASS** |
| **TC-32** | `test_counterexample_32_disputed_statement_overrides_positive_trust` | 상충 사실 등재 시 긍정 trust_level 무력화 및 검증 차단 (False) | **PASS** |
| **TC-33** | `test_counterexample_33_unregistered_registry_avoids_no_attachment` | 등기부 미등록 시 NO_ATTACHMENT 단정 금지 (UNCERTAIN) | **PASS** |
| **TC-34** | `test_counterexample_34_outdated_registry_marked_uncertain` | 오래된 등기부(1개월 이상) 현재 권리관계 UNCERTAIN 유지 | **PASS** |
| **TC-35** | `test_counterexample_35_verified_recent_registry_no_attachment` | 최근 등기부 확인 시 NO_ATTACHMENT 인정 및 열람일 기준 명시 | **PASS** |
| **TC-36** | `test_counterexample_36_uncertain_opposing_auction_avoids_senior_claim` | 대항요건 미확정 경매 질문 시 선순위 대항력 단정 차단 및 배당 중심 안내 | **PASS** |
| **TC-37** | `test_counterexample_37_conditional_verifier_leads_to_conditional_disposition` | Verifier CONDITIONAL 판정 시 Final Disposition 조건부 결론 유지 | **PASS** |

---

## 5. 전체 회귀 테스트 결과

| 테스트 스위트 | 실행 명령어 | 대상 파일/테스트 수 | 결과 | 소요 시간 |
|---|---|---|:---:|:---:|
| **사건 독립성 반례 전체** | `pytest backend/tests/unit/test_case_independence_counterexamples.py` | 37개 테스트 | **37 / 37 PASS** | 0.51s |
| **백엔드 전체 단위 테스트** | `pytest backend/tests/unit/` | 379개 테스트 | **379 / 379 PASS** | 108.80s |
| **동적 사건 무결성 E2E 통합 테스트** | `pytest backend/tests/integration/test_dynamic_case_integrity_e2e_p0_3_1.py` | 22개 테스트 | **22 / 22 PASS** | 269.91s |

회귀 결함 없이 전체 438개(379+22+37포함) 테스트가 100% 정상 통과함을 확인하였다.

---

## 6. 주석 표준 및 개발 원칙 준수 점검

1. **`CODING_COMMENT_STANDARD.md` 준수**:
   - 신규/수정된 Python 함수(`parse_notice_dates_semantically`, `evaluate_notice_status`, `evaluate_attachment_ranking`, `is_fact_strictly_verified` 등)에 한국어 Google 스타일 Docstring 작성.
   - 각 조건 분기 및 정규식 윈도우 분리 이유(무엇을/왜)를 명확히 주석으로 기록.
2. **`AGENTS.md` 지시사항 준수**:
   - 신규 외부 라이브러리 추가 없음 (표준 라이브러리 `calendar`, `datetime`, `re` 활용).
   - `DynamicCaseContext` 미도입 원칙 엄격 준수.
   - Gold 데이터 및 Evaluation Harness 임의 수정 일체 없음.
   - P0-4.3 기능 선행 개발 없이 P0-4.2 무결성 보완에만 집중.

---

## 7. 형상 관리 및 커밋 정보

- **작업 브랜치:** `feature/p0-4.2-final-legal-integrity-v3.1`
- **커밋 메시지:** `fix(p0-4.2): enforce legal fact integrity and temporal priority verification v3.1`
- **수정 파일 목록:**
  - `backend/src/ai_legal_helper/case_intelligence/case_briefing.py`
  - `backend/src/ai_legal_helper/case_intelligence/settlement_calculator.py`
  - `backend/src/ai_legal_helper/agents/issue_verifier.py`
  - `backend/src/ai_legal_helper/workflows/final_disposition.py`
  - `backend/tests/unit/test_case_independence_counterexamples.py`
  - `docs/development/P0_4_2_FINAL_LEGAL_INTEGRITY_PATCH_REPORT.md`
