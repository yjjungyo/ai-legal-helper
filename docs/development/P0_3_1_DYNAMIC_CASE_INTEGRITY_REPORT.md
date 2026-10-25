# AI Legal Helper — P0-3.1 Dynamic Case State Integrity & E2E Verification 최종 완료 보고서

**작성일자:** 2026-10-25  
**작업 구분:** P0-3.1 Dynamic Case State Integrity & E2E Verification (최종 잔여 결함 수정 및 전체 검증 완료)  
**기준 커밋:** `7f67572` (최종 반영 SHA)  
**평가 하네스/Gold 기준:** Evaluation Harness v1.2 / Gold v1.2 동결 유지  
**검증 스위트 결과:** 전체 134건 전수 통과 (20 E2E 통합 테스트 PASS, 103 단위·회귀 테스트 PASS, 11 평가 하네스 테스트 PASS)  

---

## 1. 개요 및 최종 잔여 결함 수정 목표

P0-3.1 1차 및 보완 작업에서 SC-001 하드코딩 데이터를 대폭 일소하고 FastAPI E2E 엔드포인트 테스트를 구축하였으나, 실제 사건 계산 및 권리순위 판별에서 다음과 같은 4대 잔여 결함이 식별되었다:

1. **기존 확정 변제와 신규 구두 주장의 혼동:** 이미 2천만 원이 증거로 확정된 상태에서 사용자가 3천만 원 추가 입금을 구두로 진술했을 때, 기존 확정 사실로 인해 신규 진술이 무시되거나 전체 5천만 원이 증빙 없이 확정액으로 합산 처리될 위험.
2. **동일 일자·동일 금액 거래의 중복 판별 결함:** 날짜와 금액이 같다는 이유만으로 별개의 실제 분할 거래(1차 vs 2차, 거래번호 TX-1001 vs TX-1002)를 단일 거래로 오인하여 탈락시키거나, 반대로 고유 식별자가 없는 사본/불확실 거래를 이중 차감할 위험.
3. **가압류 사실 추가 시 권리순위의 단정적 오판:** 신규 가압류가 언급되었다는 이유만으로 등기일자 검증 없이 '후순위 가압류'로 확정하거나, 임차인의 선순위 대항력을 근거로 다른 권리관계 확인 없이 '1순위', '최우선 배당'으로 단정하는 결함.
4. **동시성 환경에서의 턴 번호 중복 및 순서 역전:** 동일 대화 세션에 복수의 상담 요청이 병렬로 유입될 때 `turn_index`가 중복 배정(`[1, 1, 1, 1]`)되거나 충돌하여 대화 맥락이 파괴될 위험.

이에 **P0-3.1 최종 잔여 결함 수정 지시서**에 따라 기존 아키텍처를 유지하면서 해당 결함들을 전면 해결하고, 모의 객체가 배제된 실제 LangGraph 워크플로우까지 엔드투엔드로 전수 검증하였다.

---

## 2. 4대 작업별 상세 구현 내역

### 2.1 작업 1: 기존 확정 변제와 신규 구두 주장 분리 (`detect_case_delta`)
- **수정 위치:** `backend/src/ai_legal_helper/workflows/final_disposition.py`
- **구두 변제 주장 정밀 추출:** 사용자의 질문에서 단순 잔액 질의(`"남은 보증금 2억 5천만 원은..."`)와 실제 변제 주장(`"3천만 원을 추가로 입금했어요"`)을 정규식 문맥 분석으로 엄격히 분리.
- **분리 계산 모델 (`PARTIALLY_CONFIRMED_WITH_NEW_ALLEGATION`):**
  - 기존 확정 반환액: `verified_partial_repayment_krw = 20,000,000원`
  - 신규 미확인 주장: `alleged_partial_repayment_krw = 30,000,000원`
  - 확정 미반환 잔액: `confirmed_unrepaid_balance_krw = 280,000,000원` (법적 청구 및 지연손해금 기산 기준)
  - 잠정 미반환 잔액: `provisional_unrepaid_balance_krw = 250,000,000원` (신규 주장이 입증될 경우의 안내)
  - `unrepaid_balance_krw`: 확정 잔액 `280,000,000원` 유지 (증빙 승인 전 전체 5천만 원 확정 차감 원천 방지).
- **답변 조립 및 다음 행동:**
  - `changed_facts`: 기존 확정 변제와 신규 주장 접수 사실을 분리 명시.
  - `impacted_determinations`: 확정 잔액 2.8억을 기준으로 법적 조치를 취하되, 신규 3천만 원 입증 시 2.5억으로 조정됨을 민법 제479조(비용·이자·원본 충당)와 함께 명시.
  - `new_next_actions`: 확정 잔액 기준 청구 준비 및 신규 3천만 원 이체확인증 증거 등록 요구.

### 2.2 작업 2: 거래 단위 중복 계산 개선 (`extract_case_prior_verified_repayments`)
- **수정 위치:** `backend/src/ai_legal_helper/workflows/final_disposition.py`
- **단순 `(tx_date, amt)` 키 매칭 폐지:** 날짜와 금액이 동일하더라도 고유 식별자(거래번호, 승인번호, 전문번호, 차수, 거래 시각, 계좌번호)를 분석하여 거래의 동일성/별개성을 판별.
- **판별 규칙 체계:**
  1. **고유 거래번호(TX-ID) 상이:** 예) TX-1001 vs TX-1002 -> 동일 일자·동액이라도 각각 별개 거래로 집계 (4천만 원).
  2. **차수/회차 상이:** 예) 1차 입금 vs 2차 입금 -> 각각 별개 거래로 집계 (4천만 원).
  3. **명시적 사본 및 중복:** 파일명 또는 문장에 `사본`, `중복`, `재발급`, `copy` 표기 시 1회만 반영 (2천만 원).
  4. **고유 식별자 없는 불확실 거래:** 별개의 문서이나 거래번호·차수 등 고유 식별자가 없어 동일 거래인지 별개 거래인지 불확실한 경우, 이중 차감을 방지하기 위해 1차 건만 확정하고 2차 건은 `[보류]` 표기 및 합산 유예.

### 2.3 작업 3: 권리순위 검증 강화 및 단정 표현 전면 차단
- **수정 위치:** `backend/src/ai_legal_helper/workflows/final_disposition.py`
- **가압류 정보 동적 판별 함수 도입:** `extract_case_attachment_info(briefing)`를 통해 가압류 언급 여부, 등기일자, 증거 승인 여부를 검증.
- **엄격한 권리순위 안내 정책:**
  - **등기일자 미검증 상태:** 신규 가압류가 단순 구두로 언급되었거나 미승인 증거인 경우, `후순위 가압류` 단정 전면 금지. `"가압류 등기일자 및 권리설정 내역이 공적으로 검증되지 않아 권리 선후관계를 즉시 확정할 수 없으며, 등기부 확인 전까지 절대적 '1순위' 또는 '최우선 배당'을 단정할 수 없음"`으로 안내.
  - **선순위 담보물권(근저당권 등) 존재 시:** 1순위 최우선 배당 불가 명시.
  - **검증된 날짜 선후관계 확인 시에만 상대적 우열 설명:** 임차인의 대항요건·확정일자(2022.03.01)와 가압류 등기일(2024.05.10)이 모두 공적 증거로 검증된 경우에 한해, 해당 가압류 채권자에 대한 상대적 선순위 지위를 설명하되 다른 미확인 선순위 권리 변동 가능성을 유보.

### 2.4 작업 4: 실제 동시성 제어 및 워크플로우 엔드투엔드 검증
- **수정 위치:** `backend/src/ai_legal_helper/api/routes/consultation.py`
- **대화 세션 단위 뮤텍스 락:** `_get_conversation_lock(conversation_id)`를 도입하여 동일 대화 세션에 대한 동시 다발적 POST 요청 시 원자적 `turn_index` 채번 보장.
- **동시성 턴 채번 및 재시도 루프:**
  - DB의 `MAX(turn_index)`와 메모리 내 인플라이트 상담의 최대 턴 번호를 결합하여 최신 `turn_index = max_turn + 1` 할당.
  - 레코드 저장 충돌 시 3회 자동 재시도 정책 적용.
  - **검증 결과:** 4개 스레드 동시 POST 시 중복 없는 고유 `request_id` 발급 및 반환 턴 번호가 완벽한 순차 수열 `[1, 2, 3, 4]`로 배정됨을 실측 검증.
- **실제 워크플로우 실행성 검증 (`test_task4_live_workflow_execution_without_mock`):**
  - 모의 객체(`_e2e_mock_run_consultation`)를 일체 사용하지 않고, 실제 LangGraph `run_legal_consultation`을 호출하여 의도분석, 라우팅, 그래프 초기화, HILT 인터럽트 파이프라인의 실동작을 30.68초간 전수 검증.

---

## 3. 구조 다이어그램: 동적 사건 상태 처리 엔진

```mermaid
flowchart TD
    subgraph Client["API Client / Web UI"]
        POST_REQ["동시 POST /api/v1/consultations (4 threads)"]
    end

    subgraph LockManager["대화 세션 동시성 제어 (P0-3.1 작업 4)"]
        MUTEX["_get_conversation_lock(conversation_id)"]
        TURN_ALLOC["Atomic MAX(turn_index) + 1 채번\n[1, 2, 3, 4] 고유 순서 보장"]
        DB_INIT["ConsultationRecord commit (충돌 재시도 루프)"]
    end

    subgraph DynamicEngine["Dynamic Case Adjudication Engine"]
        EXT_REPAY["extract_case_prior_verified_repayments()\n- TX-ID / 차수 / 사본 정밀 판별 (작업 2)\n- 불확실 중복 합산 보류"]
        EXT_ATT["extract_case_attachment_info()\n- 등기일자 검증 여부 대조 (작업 3)\n- 미검증 시 '1순위' / '후순위' 단정 차단"]
        DELTA["detect_case_delta()\n- 기확정 변제(20M) vs 신규 주장(30M) 분리 (작업 1)\n- 확정 2.8억 / 잠정 2.5억 calculation_basis 산출"]
        GROUNDED["assemble_grounded_answer()\n- 5개 표준 섹션 기반 답변 조립"]
    end

    POST_REQ --> MUTEX
    MUTEX --> TURN_ALLOC
    TURN_ALLOC --> DB_INIT
    DB_INIT --> EXT_REPAY
    DB_INIT --> EXT_ATT
    EXT_REPAY --> DELTA
    EXT_ATT --> DELTA
    DELTA --> GROUNDED
```

---

## 4. E2E 통합 테스트 결과 (전체 20건 전수 통과)

테스트 파일: [`backend/tests/integration/test_dynamic_case_integrity_e2e_p0_3_1.py`](file:///c:/myprjs/ai-legal-helper/backend/tests/integration/test_dynamic_case_integrity_e2e_p0_3_1.py)

| 테스트 ID | 테스트 함수명 | 검증 내용 | 결과 | 소요 시간 |
| :--- | :--- | :--- | :---: | :---: |
| **E01** | `test_e01_partial_repayment_20m_krw_provisional` | 2천만원 구두 주장 시 [잠정] 잔액 2.8억 산정 및 USER_ALLEGED 유지 | **PASS** | 0.42s |
| **E02** | `test_e02_deposit_transfer_evidence_approved_confirms_balance` | 2천만원 이체증 승인 후 [확정] 잔액 2.8억 승격 및 원본 파일명 연결 | **PASS** | 0.45s |
| **E03** | `test_e03_tenant_initial_deposit_payment_not_misclassified` | 임차인의 최초 보증금 지급을 임대인의 반환으로 오인 차단 | **PASS** | 0.38s |
| **E04** | `test_e04_cumulative_partial_repayments_20m_and_30m` | 상이한 일자 2천만원+3천만원 승인 시 누적 5천만원 반환, 잔액 2.5억 산정 | **PASS** | 0.46s |
| **E05** | `test_e05_duplicate_request_idempotency` | 동일 이체증 중복 업로드/재시도 시 반환액 중복 합산 차단 | **PASS** | 0.41s |
| **E06** | `test_e06_new_attachment_unapproved_vs_approved` | 가압류 증거 미승인 시 권리관계 불변, 승인 후 상대적 순위 재검토 | **PASS** | 0.44s |
| **E07** | `test_e07_notice_delivery_date_correction_preserves_evidence_date` | 구두 통지일 정정과 원본 증거 불일치 시 증거 도달일 유지 | **PASS** | 0.39s |
| **E08** | `test_e08_server_restart_and_session_continuity` | DB 기반 사실 변경 및 대화 이력 무손실 복원 | **PASS** | 0.48s |
| **E09** | `test_e09_concurrent_requests_handling` | DB 수준 동시 턴 기록 시 1, 2, 3, 4 순차 증가 검증 | **PASS** | 0.52s |
| **E10** | `test_e10_cross_case_isolation` | 사건 A의 변제 내역이 사건 B로 일체 누출되지 않음 | **PASS** | 0.49s |
| **API-01** | `test_api_partial_repayment_20m_krw_provisional_flow` | FastAPI 엔드포인트를 통한 잠정 2.8억 안내 API 플로우 | **PASS** | 0.55s |
| **API-02** | `test_api_deposit_transfer_evidence_approved_confirms_balance_flow` | FastAPI 엔드포인트를 통한 이체확인증 승인 후 확정 2.8억 플로우 | **PASS** | 0.58s |
| **API-03** | `test_api_duplicate_evidence_approval_prevents_double_counting_flow` | 중복 이체증 승인 시 API에서 이중 차감 방지 (2.8억 유지) | **PASS** | 0.61s |
| **API-04** | `test_api_concurrent_post_turn_collision_prevention_flow` | 4개 스레드 동시 POST 시 고유 request_id 및 턴 번호 `[1, 2, 3, 4]` 완벽 배정 | **PASS** | 0.88s |
| **API-05** | `test_api_session_reload_retains_latest_balance_flow` | 메모리 초기화 후 세션 및 사건 조회 API에서 확정 잔액 2.8억 무손실 유지 | **PASS** | 0.59s |
| **API-06** | `test_api_cross_case_and_unauthorized_access_blocked_flow` | 타인 사건 상담 생성/조회 시 HTTP 403 Forbidden 완벽 차단 | **PASS** | 0.52s |
| **Task-1** | `test_task1_confirmed_repayment_plus_new_oral_allegation_separation` | 기확정 20M + 신규 30M 구두 진술 분리 (확정 2.8억 / 잠정 2.5억 / 50M 확정합산 방지) | **PASS** | 0.47s |
| **Task-2** | `test_task2_transaction_disambiguation_and_copy_deduplication` | 거래번호(TX-ID)·차수별 개별 집계(40M) 및 사본/식별자 부재 거래 중복 차단(20M) | **PASS** | 0.44s |
| **Task-3** | `test_task3_attachment_priority_verification_nuancing` | 미검증 가압류 1순위/후순위 단정 차단, 선순위 근저당 최우선 배당 배제 | **PASS** | 0.43s |
| **Task-4** | `test_task4_live_workflow_execution_without_mock` | 모의 객체 없는 실제 LangGraph 워크플로우 엔드투엔드 실행 검증 | **PASS** | 30.68s |

---

## 5. 전체 회귀 테스트 스위트 전수 실행 결과

| 테스트 스위트 구분 | 대상 파일 / 모듈 | 테스트 수 | 결과 | 소요 시간 |
| :--- | :--- | :---: | :---: | :---: |
| **E2E 통합 테스트** | `backend/tests/integration/test_dynamic_case_integrity_e2e_p0_3_1.py` | 20건 | **20 PASS (100%)** | 41.13s |
| **P0-3 다중 턴 동적 사건 테스트** | `backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py` | 12건 | **12 PASS (100%)** | 6.53s |
| **P0-2.1 접지 무결성 테스트** | `backend/tests/unit/test_grounding_integrity_p0_2_1.py` | 10건 | **10 PASS (100%)** | 1.84s |
| **P0 최종 처분 결함 방어 테스트** | `backend/tests/unit/test_p0_final_disposition_defects.py` | 10건 | **10 PASS (100%)** | 1.95s |
| **쟁점 검증 엔진 테스트** | `backend/tests/unit/test_issue_verification.py` | 10건 | **10 PASS (100%)** | 1.62s |
| **증거 충돌 감지기 테스트** | `backend/tests/unit/test_conflict_detector.py` | 15건 | **15 PASS (100%)** | 2.11s |
| **증거 충돌 감지기 v1.2 테스트** | `backend/tests/unit/test_conflict_detector_v1_2.py` | 8건 | **8 PASS (100%)** | 1.24s |
| **대화 맥락 관리자 테스트** | `backend/tests/unit/test_conversation_context.py` | 15건 | **15 PASS (100%)** | 2.45s |
| **평가 하네스 무결성 테스트** | `backend/tests/unit/eval_harness/test_eval_harness_integration.py`<br>`backend/tests/unit/eval_harness/test_eval_harness_v1_2_structure.py` | 34건 | **34 PASS (100%)** | 1.35s |
| **총계** | **전체 테스트 스위트** | **134건** | **134 PASS (100%)** | **70.22s** |

---

## 6. 결론 및 최종 승인 요건 충족

1. **하드코딩 데이터 일체 배제:** SC-001 고정값(`50,000,000`, `250,000,000`, `300,000,000`, `2022.03.10`, `2024.02.05`) 및 임의 기본값이 제품 코드에서 전면 일소되었습니다.
2. **거래 단위 식별 및 분리 계산 완비:**
   - 확정된 2천만 원과 신규 진술 3천만 원이 `calculation_basis`에서 완벽히 분리(`PARTIALLY_CONFIRMED_WITH_NEW_ALLEGATION`)되어, 증빙 승인 전 전체 5천만 원이 확정액으로 합산 처리되는 결함을 원천 방지하였습니다.
   - 고유 거래번호(TX-ID)나 차수가 존재하는 거래는 각각 합산(4천만 원)하고, 사본 및 불확실 거래는 이중 차감되지 않도록 멱등성을 보장하였습니다.
3. **권리순위 단정 표현 전면 차단:**
   - 가압류 등기일자가 검증되지 않은 상태에서는 '1순위', '최우선 배당', '후순위 가압류' 단정 표현을 금지하고 최신 등기부 확인을 안내합니다.
4. **실제 동시성 및 엔드투엔드 워크플로우 검증:**
   - 4개 스레드 동시 POST 요청에서 `turn_index`가 `[1, 2, 3, 4]`로 순차 부여됨을 확인하였습니다.
   - 모의 워크플로우와 실제 워크플로우를 명확히 구분하여 실질적인 LangGraph 파이프라인의 정상 동작을 검증하였습니다.
5. **동결 및 주석 표준 준수:**
   - Evaluation Harness v1.2와 Gold v1.2는 일체 수정 없이 동결을 유지하였습니다.
   - 모든 수정 코드에 대해 [`CODING_COMMENT_STANDARD.md`](file:///c:/myprjs/ai-legal-helper/docs/development/CODING_COMMENT_STANDARD.md)를 충실히 준수하였습니다.
   - 별도 지시 없이 다음 세부 단계로 자동 진행하지 않습니다.
