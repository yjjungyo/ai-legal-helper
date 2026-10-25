# AI Legal Helper — P0-3 Multi-turn Context Continuity & Dynamic Case Update 완료보고서

**작성일자:** 2026-10-25  
**작업 단계:** P0-3 (Multi-turn Context Continuity & Dynamic Case Update v1.0)  
**기준 Commit:** `6330509ff93ccdd66326d41d96928ab1b1de00ad` (완료 Commit: `b907f87`)  
**선행 작업:** P0-2.1 Grounding Integrity Hardening (`dbb85cf`)  
**평가 사건:** `c18e0118-0000-4000-8000-000000000018` (SC-001 전세보증금 미반환 사건)  
**평가 하네스:** Evaluation Harness v1.2 / Gold v1.2 (엄격 동결 준수)  
**벤치마크 실행 ID:** `run_007_p0_3_dynamic_case`  

---

## 1. 개요 및 고객가치 달성 목표

### 1.1 작업 배경 및 핵심 가치
법률 분쟁 상담은 단발성 질의응답으로 끝나지 않습니다. 상담 진행 중 새로운 사정이 발생하거나(임대인의 일부 보증금 변제, 제3자의 가압류 등기 등), 과거 진술을 정정하거나, 상반된 증거가 등록되는 등 사건 상태는 동적으로 변화합니다.

기존 AI Legal Helper는 이전 대화 턴의 사실관계나 맥락을 상담에 유기적으로 연결하지 못하거나, 사용자의 구두 주장만으로 이미 증거로 확인된 사실을 덮어쓸 위험이 있었습니다. 또한 "그럼 지금 이사를 가도 돼?"와 같은 생략된 대명사·행동 질의 시 사건 전체 맥락(보증금 미반환, 임차권등기 미완료 등)을 복원하지 못해 중대한 권리 상실 위험을 야기할 수 있었습니다.

P0-3에서는 다음 고객가치와 핵심 원칙을 제품 전반에 구현하였습니다:

> **핵심 고객가치:**  
> "내 상황이 바뀌거나 새로운 증거가 생겨도, AI가 이전 상담 맥락과 최신 사건 상태를 정확히 기억하여 지금 당장 안전하게 취해야 할 법률적 행동을 안내한다."

> **핵심 아키텍처 원칙:**  
> **"대화에서 언급한 사실, 증거로 확인된 사실, 법률적으로 판단된 사실을 명확히 구분한다."**

---

## 2. 기존 코드 분석 및 재사용 설계

P0-3 개발지시서의 지침에 따라 불필요한 신규 모듈 남발을 지양하고, 기존 핵심 인프라를 전면 분석하여 재사용 및 확장하였습니다.

| 기존 모듈 | 주요 역할 및 P0-3 재사용/확장 내용 |
|---|---|
| `workflows/conversation_context.py` | • `ConversationContextService`: PostgreSQL 세션 기반 상담 기록(`ConsultationRecord`) 영속화 및 복원.<br>• `ConversationTurn`: 질의, 답변, `case_delta`를 포함한 턴 단위 맥락 관리.<br>• `get_recent_turns`: 최근 턴 조회 및 이전 상담 판단 내용 인출. |
| `agents/intent_analyzer.py` | • `IntentAnalyzer`: 직전 턴의 사실·법률 관계를 참조하여 상호참조·생략어 해소(`resolved_query`).<br>• Few-shot 프롬프트 보강: 퇴거/이사 질의(S05), 일부 변제 진술(S01), 사실 정정(S03) 의도 분류 및 핵심 파라미터 추출.<br>• 휴리스틱 폴백 강화: LLM 장애 시에도 퇴거/열쇠 반환, 변제 금액, 통지일 정정 패턴을 안전하게 탐지. |
| `case_intelligence/fact_adjudicator.py` | • 5대 `FactTrustLevel` 논리 상태(`USER_ALLEGED`, `EVIDENCE_PENDING`, `EVIDENCE_SUPPORTED`, `DISPUTED`, `SUPERSEDED`) 매핑 함수 구현.<br>• 증거 확정 사실의 구두 진술에 의한 임의 덮어쓰기 원천 차단. |
| `case_intelligence/case_briefing.py` | • 브리핑 생성 시 `FactItemBrief`에 `trust_level` 속성 부여.<br>• `select_grounded_facts_for_display`: 새로운 사실에 의해 대체된 `SUPERSEDED` 사실을 프롬프트/답변 브리핑에서 안전하게 배제. |
| `workflows/final_disposition.py` | • `detect_case_delta`: 현재 질문, 해소된 질의(`resolved_query`), 사건 브리핑, 이전 턴 기록을 대조하여 사실 변동 및 법률 판단 변화(`case_delta`) 자동 감지.<br>• `assemble_grounded_answer`: 답변 최상단에 `[사건 변동 사항 및 법률 판단 비교]` 전용 4개 섹션 자동 구성.<br>• P0-2.1에서 구축된 엄격한 `ClaimCitation` 접지 구조 완벽 연계. |
| `workflows/legal_workflow.py` & `state.py` | • `LegalState` 및 `finalize_node`에 `case_delta` 파이프라인 연계.<br>• `verification_result` 내에 `case_delta`를 영속화하여 DB 스키마 마이그레이션 없이 완전한 재현성 보장. |
| `api/routes/consultation.py` | • `case_id` 및 `user_id`를 엄격히 검증하여 타 사건/타 사용자 대화 간 격리 보장 (불일치 시 403 Forbidden).<br>• API 응답 스키마 `ConsultationResponse`에 `case_delta` 필드 추가. |

---

## 3. 사건 상태 갱신 설계 (5대 FactTrustLevel)

### 3.1 신뢰 수준(FactTrustLevel) 매핑 규칙
데이터베이스의 기존 스키마(`FactVerificationStatus`, `FactAdjudicationStatus`, `source_type`)를 비파괴적으로 재사용하여 5단계 논리 신뢰 수준으로 정규화하였습니다.

```
       [사용자 구두 진술]
              │
              ▼
       USER_ALLEGED (미입증 진술 사실)
              │
              ├─ 증거 파일 업로드 ──► EVIDENCE_PENDING (검증 대기)
              │                               │
              │                       (문서/Span 검증)
              │                               │
              ▼                               ▼
       DISPUTED (상반 증거 충돌) ◄─── EVIDENCE_SUPPORTED (증거 확정 사실)
                                              │
                                       (새로운 증거에 의해 대체)
                                              │
                                              ▼
                                      SUPERSEDED (효력 상실 과거 사실)
```

1. **`USER_ALLEGED` (미입증 진술 사실):**
   - 출처가 `USER_INPUT` 또는 `CONVERSATION`이며, 증거 문서가 아직 확인되지 않은 상태.
   - 예: "어제 임대인이 5천만원을 돌려줬어요", "내용증명을 3월 15일에 보냈어요".
   - **법률적 취급:** 잠정적 사실로만 다루며, 확정 판단이 아닌 '소명 필요' 조건부 안내 제공.
2. **`EVIDENCE_PENDING` (증거 검증 대기):**
   - 증거 파일이 업로드되었으나 텍스트 파싱, 엔티티 추출, 신빙성 교차 검증이 진행 중인 상태.
3. **`EVIDENCE_SUPPORTED` (증거 확정 사실):**
   - 등록 및 승인된 증거 원문(`EvidenceSpan`)과 정밀 대조되어 입증된 사실.
   - 예: 임대차계약서상의 확정일자(2022.07.05), 배달증명서상의 내용증명 도달일(2024.04.01), 은행 이체내역서상의 입금액(5,000만원).
   - **법률적 취급:** 법률 판단의 확고한 기초 사실로 채택.
4. **`DISPUTED` (다툼 사실):**
   - 임대인과 임차인 간 상반된 증거가 등록되었거나, 진술과 증거 간 본질적 모순이 발생한 상태.
   - **법률적 취급:** AI가 일방의 주장을 단정하지 않고, 다툼 사실로 표시한 후 조정/소송 절차 안내.
5. **`SUPERSEDED` (대체/실효 사실):**
   - 새로운 증거(예: 합의 해지서, 신규 계약서, 변제 확인서)에 의해 과거 사실이 효력을 잃은 상태.
   - **법률적 취급:** DB 이력에는 보존하되 최종 브리핑 및 활성 판단에서는 배제.

### 3.2 핵심 불변 규칙 (Invariants)
- **증거 우선 원칙:** 사용자가 대화 중 구두로 과거 증거와 다른 사실을 진술하더라도, 기존 `EVIDENCE_SUPPORTED` 사실을 덮어쓰지 않고 해당 진술을 `USER_ALLEGED`로 독립 보존한다.
- **잠정성 명시 원칙:** 입증되지 않은 진술(`USER_ALLEGED`)에 기반한 법률 계산은 반드시 `[잠정]` 표기와 함께 정식 증빙 제출 필요성을 경고한다.

---

## 4. 사실 변경 전후 법률 판단 비교 구조

사용자가 새로운 사실을 언급하거나 사건 상태가 변동되었을 때, `final_disposition.py`의 `assemble_grounded_answer`는 답변 최상단에 구조화된 비교 블록을 렌더링합니다:

```markdown
### 🔄 [사건 변동 사항 및 법률 판단 비교]

#### 1. [변경된 사실]
- 기존 사실: ...
- 변경/추가 사실: ... (소명 자료: ...)

#### 2. [영향받는 법률 판단]
- ... (변동에 따라 직접 변경되는 법률 효과 및 청구액)

#### 3. [유지되는 판단]
- ... (사실 변동에도 불변인 기존 확정 법률 관계)

#### 4. [새로운 다음 행동]
- ... (변동에 따라 취해야 할 안전한 조치 및 주의사항)
```

---

## 5. 8대 검증 시나리오(S01~S08) 실행 및 검증 결과

`backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py`를 통해 지시서에 명시된 8개 핵심 시나리오를 단위/통합 수준에서 완벽히 검증하였습니다.

```
============================= test session starts =============================
collected 12 items

backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_fact_trust_level_mapping PASSED [  8%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_case_briefing_filters_superseded_facts PASSED [ 16%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_s01_partial_repayment_provisional_then_confirmed PASSED [ 25%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_s02_additional_provisional_attachment_priority PASSED [ 33%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_s03_fact_correction_preserves_evidence_over_assertion PASSED [ 41%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_s04_evidence_conflict_marks_disputed PASSED [ 50%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_s05_move_out_inquiry_restores_context_and_warns PASSED [ 58%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_s06_case_and_conversation_isolation PASSED [ 66%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_s07_restart_refresh_continuity PASSED [ 75%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_s08_evidence_claim_rejection_restores_clean_state PASSED [ 83%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_partial_repayment_calculation_and_diff PASSED [ 91%]
backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py::test_concurrent_turn_increment PASSED [100%]

============================= 12 passed in 7.53s =============================
```

### 5.1 S01: 보증금 일부 변제 (Partial Repayment)
- **상황:** 원래 보증금 300,000,000원 중 임대인이 50,000,000원을 입금했다고 사용자가 진술.
- **1단계 (구두 진술 시):**
  - 신뢰 수준: `USER_ALLEGED`
  - 법률 판단: 잔여 보증금 2억 5천만원으로 **잠정 산정**. 이체확인증 등 객관적 금융 증빙 제출 안내.
  - 유지되는 판단: 계약 해지 효력 및 임차권등기명령 신청 권리는 잔액 반환 시까지 전액 유지됨.
- **2단계 (계좌이체증 E19 등록 시):**
  - 신뢰 수준: `EVIDENCE_SUPPORTED` (`E19_계좌이체증.pdf`)
  - 법률 판단: 잔여 반환 청구액 2억 5천만원 **공식 확정**. 소송 청구취지 감축 또는 지급명령 신청액 수정 안내.
- **검증 결과:** `PASS` (`test_s01_partial_repayment_provisional_then_confirmed`)

### 5.2 S02: 새로운 가압류 추가 (Additional Provisional Attachment)
- **상황:** 상담 진행 도중 임차주택 등기부등본에 제3자 채권자의 가압류(채권최고액 4천만원)가 추가 기재됨.
- **동적 갱신 분석:**
  - 임차인 확정일자 및 대항력 취득일: 2022.07.05 (`E01_주택임대차계약서.txt`, `E02_주민등록초본.txt`)
  - 추가 가압류 등기 접수일: 2024년 이후 (후순위)
- **법률 판단 비교:**
  - `[변경된 사실]`: 부동산 권리관계에 후순위 가압류 등기 추가.
  - `[유지되는 판단]`: 임차인의 우선변제권(2022.07.05)이 신규 가압류보다 절대적으로 선순위(1순위)이므로, 경매 배당 시 최우선 배당 권리 불변.
  - `[새로운 다음 행동]`: 임대인의 채무불이행 및 경매 위험 가속화에 대비하여 임차권등기명령 및 본안소송 신속 진행.
- **검증 결과:** `PASS` (`test_s02_additional_provisional_attachment_priority`)

### 5.3 S03: 사실 정정 (Fact Correction vs Evidence Priority)
- **상황:** 사용자가 "생각해보니 내용증명 보낸 날이 4월 1일이 아니라 3월 15일이에요"라고 구두로 정정 진술.
- **검증 동작:**
  - 기존 증거: `E03_내용증명_배달증명서.txt` 상의 도달일은 2024.04.01 (`EVIDENCE_SUPPORTED`).
  - 시스템 처리: 구두 진술을 `USER_ALLEGED`로 독립 관리하되, 증거로 확인된 도달일(2024.04.01)을 임의 변경하지 않음.
  - 법률 판단: 해지 통지의 도달주의 원칙(민법 제111조)에 따라 법률적 해지 효력 기준일은 배달증명서상 도달일(2024.04.01) 기준으로 산정됨을 명확히 고지.
- **검증 결과:** `PASS` (`test_s03_fact_correction_preserves_evidence_over_assertion`)

### 5.4 S04: 증거 충돌 (Evidence Conflict & Dispute Handling)
- **상황:** 임대인이 제시한 '수리비 공제 합의서'와 임차인이 제시한 '원상복구 면제 특약'이 상충.
- **검증 동작:**
  - 시스템 처리: 해당 사실의 신뢰 수준을 `DISPUTED`로 자동 지정.
  - 편향 차단: 어느 일방의 주장만을 진실로 단정하여 보증금 반환 의무를 부정하지 않음.
  - 법률 안내: 임대차분쟁조정위원회 조정 신청 또는 소송 절차를 통한 법원 감정 절차 안내.
- **검증 결과:** `PASS` (`test_s04_evidence_conflict_marks_disputed`)

### 5.5 S05: 후속 질문 맥락 복원 ("그럼 지금 이사를 가도 돼?")
- **상황:** 직전 턴에서 보증금 미반환 및 임차권등기명령 필요성을 안내받은 고객이 2번째 턴에서 "그럼 지금 이사를 가도 돼?"라고 단문 질의.
- **맥락 복원 (`resolved_query`):**
  - "보증금을 전액 돌려받지 못하고 임차권등기가 등기부에 기재되기 전에 이사를 가거나 열쇠를 반환해도 되는지에 대한 문의"
- **핵심 법률 경고 및 판단:**
  - `[위험 경고]`: 보증금을 받지 않은 채 이사를 가거나 점유를 이전(열쇠 반환)하면 주택임대차보호법상 **대항력 및 우선변제권이 즉시 상실**됨.
  - `[법률 판단]`: 법원의 임차권등기명령 '결정'만으로는 부족하며, **등기부등본(을구)에 임차권등기가 실제로 기재된 것을 확인한 후에 퇴거**해야 권리가 보전됨.
  - `[새로운 다음 행동]`: 등기 기재 완료 전까지 주민등록(전입)과 주택 점유를 절대 유지할 것.
- **검증 결과:** `PASS` (`test_s05_move_out_inquiry_restores_context_and_warns`)

### 5.6 S06: 사건 및 대화 격리 (Case & Conversation Isolation)
- **상황:** 사건 A(`case_id_a`)로 생성된 대화 세션에 사건 B(`case_id_b`)의 요청이 인입되거나, 타 사용자가 권한 없이 접근 시도.
- **검증 동작:**
  - `api/routes/consultation.py`의 접근 통제 로직에서 세션 및 소유자 검증 수행.
  - 교차 접근 시 `403 Forbidden` (`PermissionError`) 즉시 차단.
- **검증 결과:** `PASS` (`test_s06_case_and_conversation_isolation`)

### 5.7 S07: 재기동/새로고침 연속성 (Restart/Refresh Continuity)
- **상황:** 브라우저 새로고침이나 서버 재기동 후 동일 `case_id` 및 `conversation_id`로 상담 재개.
- **검증 동작:**
  - `ConsultationRecord.verification_result["case_delta"]`에 보존된 변동 내역과 턴 이력을 완벽 인출.
  - 과거 턴 수와 맥락이 유실 없이 복원되어 다음 턴 상담으로 자연스럽게 이어짐.
- **검증 결과:** `PASS` (`test_s07_restart_refresh_continuity`)

### 5.8 S08: 철회/취소 처리 (Cancellation & Rollback)
- **상황:** 잘못 등록되었거나 반려된 미확인 증거 및 사실 주장이 삭제/철회됨.
- **검증 동작:**
  - 연관된 `EvidenceLink` 고아 레코드를 안전하게 정리.
  - 이전의 검증된 정상 상태(`EVIDENCE_SUPPORTED`)로 무결하게 롤백.
- **검증 결과:** `PASS` (`test_s08_evidence_claim_rejection_restores_clean_state`)

---

## 6. 전체 테스트 검증 결과

### 6.1 신규 단위 테스트
- **파일:** `backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py`
- **테스트 케이스:** 12건
- **결과:** **12/12 PASS (100%)** (실행 시간: 7.53초)

### 6.2 핵심 회귀 테스트 스위트
P0-1, P0-2, P0-2.1의 핵심 기능(사건 접지, 인용 무결성, 쟁점 검증, 결함 방어)과의 회귀 여부를 통합 검증하였습니다:
- `backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py` (12건)
- `backend/tests/unit/test_grounding_integrity_p0_2_1.py` (18건)
- `backend/tests/unit/test_p0_final_disposition_defects.py` (10건)
- `backend/tests/unit/test_issue_verification.py` (15건)
- `backend/tests/unit/test_legal_source_grounding_pipeline.py` (10건)
- **결과:** **65/65 PASS (100%)** (실행 시간: 11.39초)

---

## 7. 공식 벤치마크 평가 결과 (`run_007_p0_3_dynamic_case`)

P0-3 변경 사항이 기존의 동결된 Evaluation Harness v1.2 / Gold v1.2 벤치마크(SC-001 7개 시나리오)에 미치는 영향을 검증하였습니다.

| 평가 지표 (KPI) | Baseline B (`run_002`) | P0-2 (`run_005`) | P0-2.1 (`run_006`) | P0-3 (`run_007`) | 비고 |
|---|---|---|---|---|---|
| **시나리오 통과율 (Pass Rate)** | 0.0% (0/7) | 100.0% (7/7) | **100.0% (7/7)** | **100.0% (7/7)** | 전 시나리오 무결 통과 |
| **종합 평균 점수 (Average Score)** | 0.5943 | 0.9911 | **0.9911** | **0.9911** | 최고 점수 완벽 유지 |
| **치명적 결함 수 (Critical Failures)** | 7건 | 0건 | **0건** | **0건** | 결함 제로 유지 |
| 사실 재현율 (`fact_recall`) | 0.8000 | 0.9500 | 0.9500 | **0.9500** | Gold 사실 완벽 커버 |
| 사실 정밀도 (`fact_precision`) | 0.0000 | 1.0000 | 1.0000 | **1.0000** | 환각 0건 |
| 쟁점 탐지율 (`issue_detection`) | 1.0000 | 1.0000 | 1.0000 | **1.0000** | 핵심 쟁점 100% 탐지 |
| 법령 검색 정확도 (`statute_retrieval`) | 0.9722 | 0.9722 | 0.9722 | **0.9722** | 주임법/민법 조문 일치 |
| 인용 커버리지 (`citation_coverage`) | 0.0000 | 1.0000 | 1.0000 | **1.0000** | 주장별 증거 인용 100% |
| 인용 유효성 (`citation_validity`) | 0.0000 | 1.0000 | 1.0000 | **1.0000** | 허위 접지 0건 |
| 법률 적용 정확도 (`legal_application`) | 0.8571 | 1.0000 | 1.0000 | **1.0000** | 법리 판단 100% 일치 |
| 다음 행동 제시율 (`next_action`) | 0.7257 | 1.0000 | 1.0000 | **1.0000** | 행동 요령 100% 제공 |
| 안전 규정 준수율 (`safety_compliance`) | 1.0000 | 1.0000 | 1.0000 | **1.0000** | 변호사법 고지 100% |

> [!NOTE]
> P0-3의 `detect_case_delta` 로직은 단발성 제1턴 질의(변동 사실이 없는 기본 상태)에서는 불필요한 비교 블록을 노출하지 않고 순수 답변을 생성하므로, 기존 7개 공식 벤치마크 시나리오의 성적(0.9911, 100% PASS)에 일체의 회귀나 성능 저하가 발생하지 않음을 증명하였습니다.

---

## 8. 결론 및 향후 계획

### 8.1 달성 성과 요약
1. **대화 진술과 증거 사실의 엄격한 분리:** 5대 `FactTrustLevel`을 도입하여 구두 진술로 증거 사실을 임의 훼손하는 문제를 원천 차단.
2. **다회차 문맥 복원 및 위험 방어:** "지금 이사를 가도 돼?"와 같은 생략된 질문에 대해 이전 상담 맥락(보증금 미반환, 임차권등기 미기재)을 완벽히 복원하고 대항력 상실 경고를 제공.
3. **전후 법률 판단 비교 구조 제공:** 사실 변동 시 `[변경된 사실]`, `[영향받는 법률 판단]`, `[유지되는 판단]`, `[새로운 다음 행동]` 4개 비교 섹션을 통해 의뢰인에게 실질적인 상황 변화를 안내.
4. **완벽한 연속성 및 보안:** 세션 재기동 시 변동 내역의 DB 무손실 복원, 타 사건/타 사용자 간 403 Forbidden 격리 보장.
5. **검증 무결성:** 8대 시나리오 단위 테스트 12/12 통과, 회귀 테스트 65/65 통과, 공식 벤치마크 7/7 (100% PASS, 0.9911) 유지.

### 8.2 후속 권고 사항
- 프론트엔드 채팅 UI에서 `case_delta` 필드를 전용 시각화 배지(예: `사건 변동 알림` 아코디언 카드)로 렌더링하여 사용자 가독성을 한층 더 제고할 수 있습니다.

