# AI Legal Helper — P0-4.2 최종 사건 독립성 및 법률 판단 무결성 완료보고서

- **문서 버전:** v2.0 (미검증 Fact 차단, 금액 정확성, 잔여 하드코딩 완전 제거 및 19대 반례 보강)
- **작성일자:** 2026-10-27
- **대상 단계:** P0-4.2 최종 보완 v3.0 (사건 독립적 법률 판단 구현 및 아키텍처 복원)
- **작업 브랜치:** `feature/p0-4.2-final-case-independence`
- **기준 커밋:** `060bca02e2df3256d7d19c68462894a8b0e1a3f1` (롤백 복원 SHA: `92604bd9bab178de92a93bbd27c011e667c7b379`)
- **수행 원칙:** `DynamicCaseContext` 미사용, 기존 `CaseEvidenceBriefing` 단일 원천 유지, 하드코딩 전면 제거, 법률 무결성 확보

---

## 1. 개발 배경 및 최종 아키텍처 결정

### 1.1 배경
P0-4.2 초기 구현에서 SC-001 평가 시나리오의 품질을 개선하는 과정에서, `issue_verifier.py`와 `final_disposition.py` 등에 특정 사건의 보증금(3억 원), 계약기간(2022.03.01~2024.02.29), 통지일(2026.04.01), 가압류 채권자(동진은행, HUG) 및 목적물 명칭(가람오피스텔 503호)이 고정되는 결함이 발생했습니다.
이를 해결하기 위해 도입 시도되었던 `DynamicCaseContext`는 기존 `CaseEvidenceBriefing` 및 P0-3.1 계산 엔진과 중복 계층을 형성하는 한계가 있었습니다.

### 1.2 아키텍처 결정 사항 (지시서 v3.0 준수)
1. **`DynamicCaseContext` 전면 미사용 및 삭제:**
   - 추가적인 Context 계층을 신설하지 않고, `CaseEvidenceBriefing`을 상담 워크플로우의 유일한 사건 정보 전달 모델(Single Source of Truth)로 확고히 유지했습니다.
2. **단일 원천 공통 계산 모듈(`settlement_calculator.py`) 신설:**
   - `issue_verifier.py`와 `final_disposition.py` 간의 상호 순환 참조(Circular Import)를 원천 방지하고, 계약 원금·누적 반환액·미반환 잔액·통지 상태·권리순위를 일관되게 추출·계산하는 공통 유틸리티를 `case_intelligence` 계층에 구현했습니다.
3. **P0-3.1 및 P0-4.2 유효 개선의 온전한 보존:**
   - Fact Adjudication(`EVIDENCE_SUPPORTED`, `CORROBORATED`), EvidenceClaim 기반 출처 연결, 9대 핵심 법률 쟁점 구조, 법령 검색 부스트(+50.0) 및 상황별 맞춤 행동 가이드를 모두 유지했습니다.
4. **제로 의존성(Zero-Dependency) 원칙 준수:**
   - 외부 라이브러리 추가 없이 파이썬 표준 라이브러리(`calendar`, `datetime`)만을 활용하여 역(曆)에 의한 월말 3개월 만료일을 안전하게 산출했습니다 (`AGENTS.md` 규칙 준수).

---

## 2. 핵심 보강 사항 (사용자 최종 지시사항 100% 반영)

### 2.1 미검증 Fact 차단 (Strict Fact Verification)
- **엄격 검증 필터(`is_fact_strictly_verified`):**
  - 사실관계가 `EVIDENCE_SUPPORTED`, `CORROBORATED` 등 공적 증거로 엄격히 입증된 사실만 확정 판단에 진입할 수 있도록 차단 필터를 전면 적용했습니다.
  - 당사자 일방 진술(`PARTY_ALLEGED`), 증거 불충분(`EVIDENCE_INCOMPLETE`), 미검증(`UNVERIFIED`), 또는 사건 다툼 사실(`genuinely_disputed`, `DISPUTED`)은 해지 효력 및 권리순위 확정에 반영되지 않고 `CONDITIONAL` 상태를 유지하도록 통제했습니다.
- **대항요건과 확정일자의 분리 및 익일 0시 효력 계산:**
  - 주택임대차보호법 제3조 제1항에 따라 주택 인도와 주민등록 전입(대항요건) 구비 익일(다음 날) 0시(`tenant_opposing_effective_date = opposing_satisfied_date + 1 day`)에 대항력이 발생하는 법리를 정확히 반영했습니다.
  - 확정일자 부여일과 대항력 발생 시점을 비교하여 우선변제권 효력 기준일(`tenant_priority_date = max(tenant_opposing_effective_date, tenant_fixed_date)`)을 산출했습니다.
  - 전입 당일에 가압류가 설정된 경우, 당일 일과시간에 설정된 가압류가 익일 0시에 효력이 발생하는 임차권보다 선순위(`ATTACHMENT_SENIOR`)임을 판정하고, 임차인이 낙찰자에게 대항할 수 없음을 명확히 안내하도록 개선했습니다.

### 2.2 금액 정확성 (Amount Accuracy & No Double Claim)
- **보증금 후보 충돌 시 `max()` 자동 선택 제거:**
  - `extract_case_contract_deposit()`에서 서로 다른 보증금 액수가 상충될 경우, 임의로 최대 금액을 자동 선택하던 fallback을 제거하고 불확실성을 표시하기 위해 `0원`을 반환하여 추가 확인(CONDITIONAL)으로 안전하게 유도하도록 수정했습니다.
- **기변제 원금 재청구 방지:**
  - 총 계약 보증금 중 일부(예: 5천만 원)가 이미 변제된 사건에서, 권고안이 계약 보증금 전액(예: 2억 2천만 원)의 일시 반환을 청구하여 이미 받은 돈을 다시 청구하는 법률적 오류를 원천 차단했습니다.
  - 기변제액이 있는 경우 권고안, 내용증명 안내, 지급명령/소송 청구취지, Final Disposition 행동 가이드 전체가 오직 `미반환 잔액`(예: 1억 7천만 원)만을 청구하도록 일괄 동기화했습니다.

### 2.3 잔여 하드코딩 완전 제거 (Zero Remaining Hardcoding)
- **특정 임대인 명칭 및 증거번호 제거:**
  - `최성호`, `E04`, `E05`, `["E01", "E03", "E16"]` 등 특정 사건에 의존한 조건 분기를 제품 코드에서 완전히 제거했습니다.
  - 임의의 임대인 성명(예: 박영수)이 지정되더라도 `briefing.parties` 및 동적 역할을 통해 반환 거래를 정상 식별하도록 일반화했습니다.
  - `action_item_configs` 등 최종 응답 조립 시에도 `find_evidence_labels_by_type()`을 통해 동적 증거 라벨(`dyn_lease_labels`, `dyn_notice_labels`, `dyn_attachment_labels` 등)을 매핑하도록 수정했습니다.
- **가공 증거의 논리적 한계 정밀화:**
  - 질문에서 언급된 가공 증거(제99호증 등)가 Source Registry에 부재함을 확인하되, "가공 증거의 부재 자체가 다른 모든 변제 사실의 부존재까지 증명하는 것은 아니나, 현재 공식 등록·검증된 금융 증빙상으로는 미반환 잔액이 남아있다"는 법률적으로 온전한 논리를 서술하도록 보완했습니다.

---

## 3. 수정 파일 내역

| 파일 경로 | 주요 변경 내용 |
|---|---|
| `backend/src/ai_legal_helper/case_intelligence/settlement_calculator.py` | `is_fact_strictly_verified` 추가, `max()` 자동 선택 제거, 동적 임대인 파티 반영, 익일 0시 대항력 산출(`tenant_opposing_effective_date`), 날짜 정규식 보정 |
| `backend/src/ai_legal_helper/agents/issue_verifier.py` | 엄격 검증 필터 적용, E04/E05 하드코딩 제거, 기변제액 공제 후 미반환 잔액만 청구하도록 권고문 일괄 수정, 가압류 선순위(`ATTACHMENT_SENIOR`) 분기 및 가공증거 설명 정밀화 |
| `backend/src/ai_legal_helper/workflows/final_disposition.py` | 행동 가이드 5대 조치사항의 하드코딩 증거 라벨(`E01`, `E05` 등)을 동적 라벨(`find_evidence_labels_by_type`)로 대체, 분할반환 거절 시 미반환 잔액만 청구하도록 수정 |
| `backend/tests/unit/test_case_independence_counterexamples.py` | 14~19번 반례 테스트 6건 추가 (총 19건 전수 통과) |
| `docs/development/P0_4_2_FINAL_CASE_INDEPENDENCE_REPORT.md` | 완료보고서 갱신 |

---

## 4. 19대 반례 및 사건 독립성 검증 결과

`backend/tests/unit/test_case_independence_counterexamples.py` 실행 결과: **19개 전건 PASS**

```text
collected 19 items
test_case_independence_counterexamples.py::test_counterexample_01_non_sc001_deposit_isolation PASSED
test_case_independence_counterexamples.py::test_counterexample_02_lease_period_isolation PASSED
test_case_independence_counterexamples.py::test_counterexample_03_sent_only_notice_unconfirmed PASSED
test_case_independence_counterexamples.py::test_counterexample_04_distinguish_expiry_from_implicit_renewal PASSED
test_case_independence_counterexamples.py::test_counterexample_05_uncertain_priority_avoids_senior_claim PASSED
test_case_independence_counterexamples.py::test_counterexample_06_e03_bank_statement_by_doc_type PASSED
test_case_independence_counterexamples.py::test_counterexample_07_fake_citation_denied_without_hallucination PASSED
test_case_independence_counterexamples.py::test_counterexample_08_evidence_order_independence PASSED
test_case_independence_counterexamples.py::test_counterexample_09_two_distinct_returns_same_date_amount PASSED
test_case_independence_counterexamples.py::test_counterexample_10_duplicate_repayment_not_double_counted PASSED
test_case_independence_counterexamples.py::test_counterexample_11_case_delta_and_disposition_balance_match PASSED
test_case_independence_counterexamples.py::test_counterexample_12_unverified_facts_conditional PASSED
test_case_independence_counterexamples.py::test_counterexample_13_cross_case_sc001_vs_e2e_lease_02 PASSED
test_case_independence_counterexamples.py::test_counterexample_14_unverified_notice_reach_blocked PASSED
test_case_independence_counterexamples.py::test_counterexample_15_opposing_power_effective_next_day_zero_hour_ranking PASSED
test_case_independence_counterexamples.py::test_counterexample_16_conflicting_deposit_candidates_refuse_max PASSED
test_case_independence_counterexamples.py::test_counterexample_17_advice_demands_only_unrepaid_balance_no_double_claim PASSED
test_case_independence_counterexamples.py::test_counterexample_18_arbitrary_landlord_name_no_choi_seong_ho PASSED
test_case_independence_counterexamples.py::test_counterexample_19_fake_citation_does_not_assert_universal_non_repayment PASSED
============================== 19 passed in 0.46s ==============================
```

---

## 5. 전체 회귀 테스트 및 통합 테스트 결과

1. **전체 단위 테스트 스위트 (Unit Tests):**
   - 명령: `pytest backend/tests/unit/`
   - 결과: **358 passed, 0 failed** (100% 통과)
2. **동적 사건 무결성 E2E 통합 테스트 (Integration Tests):**
   - 명령: `pytest backend/tests/integration/test_dynamic_case_integrity_e2e_p0_3_1.py`
   - 결과: **22 passed, 0 failed** (100% 통과)
3. **결과 분석:**
   - 쟁점 검증 엔진, Fact 심리, RAG 검색, 라우터, AOP 감사 등 백엔드 전 영역에서 일체의 회귀 결함 없이 100% 통과를 확인했습니다.

---

## 6. 개발 주석 표준 준수 점검

- **표준 준수:** `docs/development/CODING_COMMENT_STANDARD.md` 및 `AGENTS.md` 필수 원칙 100% 준수.
- **Docstring:** 신규/수정 함수 전체에 한국어 Google 스타일 Docstring 적용 (법률적 배경 및 요건사실 포섭 명시).
- **의존성 준수:** 외부 신규 라이브러리 추가 없음 (표준 라이브러리 사용으로 `requirements.txt`와 완벽 동기화 상태 유지).
