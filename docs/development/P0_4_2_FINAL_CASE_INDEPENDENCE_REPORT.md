# AI Legal Helper — P0-4.2 최종 사건 독립성 및 법률 판단 무결성 완료보고서

- **문서 버전:** v1.0
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
1. **`DynamicCaseContext` 전면 미사용 및 삭제 확인:**
   - 추가적인 Context 계층을 신설하지 않고, `CaseEvidenceBriefing`을 상담 워크플로우의 유일한 사건 정보 전달 모델(Single Source of Truth)로 확고히 유지했습니다.
2. **단일 원천 공통 계산 모듈(`settlement_calculator.py`) 신설:**
   - `issue_verifier.py`와 `final_disposition.py` 간의 상호 순환 참조(Circular Import)를 원천 방지하고, 계약 원금·누적 반환액·미반환 잔액·통지 상태·권리순위를 일관되게 추출·계산하는 공통 유틸리티를 `case_intelligence` 계층에 구현했습니다.
3. **P0-3.1 및 P0-4.2 유효 개선의 온전한 보존:**
   - Fact Adjudication(`EVIDENCE_SUPPORTED`, `CORROBORATED`), EvidenceClaim 기반 출처 연결, 9대 핵심 법률 쟁점 구조, 법령 검색 부스트(+50.0) 및 상황별 맞춤 행동 가이드를 모두 유지했습니다.
4. **제로 의존성(Zero-Dependency) 원칙 준수:**
   - 외부 라이브러리 추가 없이 파이썬 표준 라이브러리(`calendar`, `datetime`)만을 활용하여 역(曆)에 의한 월말 3개월 만료일을 안전하게 산출했습니다 (`AGENTS.md` 규칙 준수).

---

## 2. 주요 개선 및 무결성 조치

### 2.1 사건 고유값의 동적 추출 체계 구축
`settlement_calculator.py`를 통해 모든 사건 데이터가 브리핑의 검증된 Fact와 Evidence로부터 동적으로 결정되도록 구현했습니다:
- **보증금 원금 및 잔액:** `extract_case_contract_deposit()`, `extract_case_prior_verified_repayments()`를 통해 검증된 사실로부터 동적 추출하며, `format_krw_to_korean()`으로 자연스러운 한국어 표기(예: 3억 원, 2억 2천만 원, 1억 7천만 원) 제공.
- **목적물 및 부동산 유형:** `find_case_property_info()`를 통해 목적물 주소와 주택 유형(오피스텔, 아파트, 다세대주택 등)을 동적으로 추출.
- **증거 라벨 매핑:** `find_evidence_labels_by_type()`을 통해 특정 증거번호(E01, E03 등)의 역할을 고정하지 않고 실제 `document_type` 및 메타데이터를 기준으로 매칭.

### 2.2 발송일과 도달일 분리 및 묵시적 갱신 법률 효력 (지시서 작업 D)
- `evaluate_notice_status()`를 통해 통지 발송 사실(`has_sent`, `sent_date`)과 상대방 도달 확인 사실(`has_reached`, `reach_date`)을 엄격히 분리했습니다.
- 임대인의 도달 또는 수신 확인 증빙이 없는 경우, 법정 해지 효력일(`statutory_effect_date`)을 `None`으로 유지하고 쟁점 상태를 `CONDITIONAL` (`TERMINATION_NOTICE_REACH_UNCONFIRMED`, `NOTICE_REACH_UNCONFIRMED`)로 처리하여 법률적 단정을 방지했습니다.
- 묵시적 갱신 중 해지(주택임대차보호법 제6조의2)의 경우, 표준 라이브러리 `calendar.monthrange`를 사용하여 1/31 도달 시 4/30 만료, 3/31 도달 시 6/30 만료 등 역(曆)에 의한 정확한 달력 계산을 적용했습니다.

### 2.3 권리순위 선후관계 검증 (지시서 작업 E)
- `evaluate_attachment_ranking()`을 통해 임차인의 대항요건 취득일(주택인도+전입) 및 확정일자와 가압류·저당권의 등기접수일자를 정밀 비교했습니다.
- 등기일자가 결여되었거나 선후관계가 불명확한 경우, `priority_status`를 `UNCERTAIN`으로 설정하고 `PRIORITY_UNCERTAIN_NEEDS_REGISTRY` 코드를 부여하여 '선순위 우선변제권 인정'을 확정 문장으로 단정하지 않고 최신 등기부 대조를 전제로 하는 조건부 권고를 제공합니다.

### 2.4 반환금 집계 엔진 단일화 및 Case Delta 동기화
- `DynamicCaseContext`와 Final Disposition 간의 이원화 문제를 해소하고, `final_disposition.py`의 `detect_case_delta()`와 `assemble_grounded_answer()`가 `settlement_calculator`의 단일 계산 로직을 공유하도록 통합했습니다.
- 고유 거래번호(TX-ID), 차수, 시간 등 식별자가 다른 거래는 각각 분할 정산하고, 중복 업로드 사본은 차단하며, Case Delta와 최종 응답의 미반환 잔액이 100% 일치하도록 보장했습니다.

---

## 3. 수정 대상 파일 및 변경 내역

| 파일 경로 | 변경 구분 | 주요 변경 내용 |
|---|---|---|
| `backend/src/ai_legal_helper/case_intelligence/settlement_calculator.py` | 신규 생성 | 단일 원천 정산·계산·통지·권리순위·목적물 공통 유틸리티 (Google Docstring 표준 준수) |
| `backend/src/ai_legal_helper/agents/issue_verifier.py` | 전면 리팩토링 | 14대 쟁점 분기에서 하드코딩된 금액·일자·증거번호 전면 제거, 도달일 분리 및 권리순위 조건부 처리 |
| `backend/src/ai_legal_helper/workflows/issue_planner.py` | 수정 | 쟁점 계획 시 특정 채권자명(동진은행, HUG) 및 고정 수치·증거번호 역할 가정 제거, 동적 목적물 유형 반영 |
| `backend/src/ai_legal_helper/workflows/final_disposition.py` | 수정 | 계산 로직을 `settlement_calculator`로 일원화(재수출 지원), 맞춤 행동 가이드의 하드코딩 텍스트 전면 동적화 |
| `backend/tests/unit/test_case_independence_counterexamples.py` | 신규 생성 | 필수 12대 반례 테스트 및 교차 검증 테스트 (13개 테스트 전건 PASS) |

---

## 4. 필수 12대 반례 및 교차 검증 테스트 결과

`backend/tests/unit/test_case_independence_counterexamples.py` 실행 결과: **13개 전건 PASS**

```text
collected 13 items
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
============================== 13 passed in 0.53s ==============================
```

---

## 5. 전체 회귀 테스트 및 E2E 통합 테스트 결과

1. **전체 단위 테스트 스위트 (Unit Tests):**
   - 명령: `pytest backend/tests/unit/`
   - 결과: **339 passed, 0 failed** (100% 통과)
2. **동적 사건 무결성 E2E 통합 테스트 (Integration Tests):**
   - 명령: `pytest backend/tests/integration/test_dynamic_case_integrity_e2e_p0_3_1.py`
   - 결과: **22 passed, 0 failed** (100% 통과)
3. **종합 회귀 테스트 결과:**
   - 기존 P0, P1, P2 결함 재현 및 수정 검증, 쟁점 분리 검증, RAG 검색 및 라우터 테스트 일체 무결함 확인.

---

## 6. 개발 주석 표준 준수 점검

- **표준 준수:** `docs/development/CODING_COMMENT_STANDARD.md` 및 `AGENTS.md` 필수 원칙 100% 준수.
- **모듈 Docstring:** 신규 모듈(`settlement_calculator.py`) 및 수정 모듈 전부에 모듈 개요, 설계 원칙, 주요 기능 한국어 Docstring 기술.
- **함수 Docstring:** Google 스타일 한국어 Docstring (Args, Returns, 요건사실 포섭 배경 명시).
- **인라인 주석:** 코드 변경 이유와 법률적 포섭 논리(무엇을/왜)를 명확히 기록하고 민감정보나 무의미한 기계적 주석 배제.

---

## 7. 결론

P0-4.2 최종 개발지시서 v3.0의 모든 요구사항이 성공적으로 완료되었습니다:
- `DynamicCaseContext`를 생성하지 않고 기존 `CaseEvidenceBriefing`을 보존했습니다.
- 특정 사건(SC-001)에 종속되었던 모든 하드코딩(3억 원, 가람오피스텔, 동진은행, 2026.04.01, E01~E17 등)을 완전 제거했습니다.
- 임의의 사건(E2E-LEASE-02 등)에서도 보증금, 목적물, 권리순위, 해지 효력 및 다음 행동 가이드가 사건 독립적으로 정확하게 동작함을 13대 반례·교차 검증 테스트로 입증했습니다.
- 기존 단위·통합 테스트(361건) 전건 통과를 달성했습니다.
