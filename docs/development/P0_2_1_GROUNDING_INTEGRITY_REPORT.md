# AI Legal Helper — P0-2.1 Grounding Integrity Hardening 완료보고서

**작성일자:** 2026-10-25  
**작업 단계:** P0-2.1 (Grounding Integrity Hardening v1.0)  
**기준 Commit:** `21f8904`  
**선행 작업:** P0-2 Claim-to-Source Grounding & Evidence Traceability v2.0  
**평가 사건:** `c18e0118-0000-4000-8000-000000000018` (E01~E18 격리 사건)  
**평가 하네스:** Evaluation Harness v1.2 / Gold v1.2 (동결)  
**벤치마크 실행 ID:** `run_006_p0_2_1_integrity`  

---

## 1. 개요 및 고객가치 달성 목표

### 1.1 작업 배경 및 목적
P0-2 단계에서 구축된 `ClaimCitation` 및 `EvidenceSpan` 3계층 접지 구조를 통해 사실 주장과 증거 원문의 연결 인프라가 마련되었습니다. 그러나 기존 코드에는 다음과 같은 실질적 결함 및 취약점이 존재했습니다:

1. **표면적 단어 일치 및 느슨한 토큰 매칭:** 문맥상 무관하거나 날짜·금액·금융기관·행위 유형이 다름에도 1단어 중첩만으로 사실 근거를 확정하는 현상.
2. **임의의 첫 번째 Span Fallback:** 특정 주장에 부합하는 발췌 구절이 없을 때 해당 문서의 첫 번째 Span(`candidate_spans[0]`)을 무조건 연결하여 잘못된 문장을 하이라이트하는 현상.
3. **미검색 법령의 형식적 SUPPORTED 표시:** 실제 HILT 또는 벡터 검색으로 인출되지 않은 법령 및 권고 항목을 검색 결과 검증 없이 일괄 `SUPPORTED`로 표시할 위험.
4. **UI 레이블 중복 및 다중 인용 충돌:** `[E03] E03_파일명.txt`와 같이 번호와 파일명이 중복 노출되고, 동일 문서(`E03`)가 답변 내 여러 문장에 인용될 때 첫 번째 매칭 태그로 충돌하는 현상.

P0-2.1에서는 **"주장과 실제 원문이 관련 있다는 사실이 검증되지 않으면 해당 인용을 SUPPORTED로 표시하지 않는다"**는 원칙 하에, 어떠한 허위 접지도 배제하는 무결성 강화(Integrity Hardening)를 완료하였습니다.

---

## 2. 결함 재현 및 분석 (10대 반례)

P0-2.1 지시서에서 정의된 10대 반례를 식별하고 이를 원천 차단하도록 로직을 재설계하였습니다.

| 번호 | 결함 및 반례 유형 | 기존 취약점 동작 | P0-2.1 보완 후 검증 동작 |
|---|---|---|---|
| **01** | 금융/기관 불일치 | '우리은행' 근저당권 주장에 '동진은행' 증거 매칭 | 엔티티 집합 교집합 검사 실패 시 `불일치` 반환 및 인용 차단 |
| **02** | 통지 방식 불일치 | '내용증명 발송·도달' 주장에 '문자메시지' 증거 매칭 | 통지 행위(`내용증명` vs `문자`) 상이 시 매칭 차단 |
| **03** | 금액 불일치 | '3천만원 반환' 주장에 '2억 7천만원' 증거 매칭 | 한국어 금액(억/천만/만/원) 정밀 환산 후 불일치 시 차단 |
| **04** | 1단어 부분 일치 | 명도/퇴거 주장에 주택 누수 공사 증거 매칭 (단어 1개 일치) | 최소 2개 이상의 핵심 의미 토큰 중첩 요구, 미달 시 차단 |
| **05** | 매칭 Span 부재 | 유효한 Span이 없는 명제에 임의의 첫 번째 Span 부여 | 매칭 가능한 Span 부재 시 `None` 반환, 임의 폴백 원천 제거 |
| **06** | 동일 증거 다중 인용 | 동일 계약서 내 계약일(2022.07.01)과 확정일(2022.07.05) 혼동 | 날짜 및 문장 컨텍스트 정밀 분리 검증으로 고유 Span 매칭 |
| **07** | 미검색 법령 | 검색되지 않은 법령(주임법 제3조의2)을 SUPPORTED로 표시 | 실제 인출 출처(`retrieved_sources`) 대조 실패 시 `UNVERIFIED_SOURCE` 처리 |
| **08** | 무관 법령 인용 | 형법 사기죄 등 쟁점과 무관한 법령 접지 | 출처 식별 불가 시 SUPPORTED 차단 및 비검증 분류 |
| **09** | 비존재 증거 UUID | 잘못되거나 존재하지 않는 UUID 조회 시 첫 문서 임의 열람 | 지정된 UUID가 없을 경우 `undefined` 반환하여 다른 문서 폴백 차단 |
| **10** | 본문 부재 팬텀 권고 | 최종 답변 본문(`final_answer`)에 없는 권고의 인용 생성 | 본문 내 실질 포함 여부 검증 후 부재 시 인용 목록 제외 |

---

## 3. 코드 수정 사항 상세

### 3.1 백엔드 접지 무결성 강화
- **파일:** `backend/src/ai_legal_helper/workflows/final_disposition.py`
  - `extract_dates_from_text`: 한국어 조사(`일입니다`, `일자`) 및 날짜 구분자(`년월일`, `.`, `-`)를 포괄하는 정규화 함수 구현.
  - `extract_amounts_from_text`: 억 단위, 천만원 단위, 만원 단위, 콤마 표기 원 단위를 정수(KRW)로 정밀 변환하여 금액 불일치(예: 3천만원 vs 2억 7천만원) 방지.
  - `extract_named_entities`: 은행/금융기관, 당사자, 법률 행위(내용증명, 문자, 전입신고, 확정일자 등)를 추출하여 이종 엔티티 매칭 차단.
  - `verify_claim_match`: 엔티티, 일자, 금액, 통지 행위, 의미 토큰 중첩(최소 2개), Span 유효성을 순차 검증하고 임의의 첫 번째 Span 폴백을 전면 제거.
  - `verify_legal_source_reference`: 실제 검색된 법령 목록(`retrieved_sources`)과 대조하여 `source_id` 및 조문 일치가 확인된 경우에만 `SUPPORTED` 부여, 미검색 시 `UNVERIFIED_SOURCE` 부여.
  - `build_claim_citations`: 사실 및 법률 판단이 최종 답변 본문(`final_answer`)에 실제 존재하는지 확인 후 인용 목록을 생성하며, 표출 라벨에 원본 파일명 기본 적용.
  - `assemble_grounded_answer`: 인용 배지 표출 시 번호 중복(`[E03] E03_파일명.txt`)을 제거하고 `[E01_주택임대차계약서.txt]`와 같이 등록 원파일명으로 단일 표시.

### 3.2 워크플로우 상태 전달 보강
- **파일:** `backend/src/ai_legal_helper/workflows/legal_workflow.py`
  - `finalize_node`에서 `retrieved_sources=state.get("retrieved_sources", [])`를 `build_claim_citations`로 안전하게 전달.
  - `claim_citations` 구조체를 반환 상태 딕셔너리에 명시적으로 등록하여 프론트엔드로 전달 보장.

### 3.3 프론트엔드 UI 드로어 및 다중 인용 정밀화
- **파일:** `frontend/src/components/chat/EvidenceSourceDrawer.tsx`
  - `findDocument` 로직 수정: `selectedEvidenceId`가 지정되었으나 문서 목록에 없을 경우 첫 번째 문서로 폴백하지 않고 즉시 `undefined` 반환.
  - 드로어 상단 배지에 `[E01]` 대신 `matchedDoc?.original_filename`을 우선 표출하여 직관적 원문 인지 보장.
- **파일:** `frontend/src/components/LegalAnswerView.tsx`
  - `renderInlineMarkdown`에 `lineContext?: string` 매개변수 추가.
  - 답변 내 특정 줄(문장)의 컨텍스트와 일치하는 `ClaimCitation`을 우선 검색하여, 동일한 증거가 여러 문장에서 인용되더라도 해당 문맥의 고유 `claim_id` 및 `span_id`로 정확히 연결.
- **파일:** `frontend/src/components/chat/AssistantMessage.tsx`
  - 하단 참고 출처 목록에서 번호 중복(`{evLabel ? `[${evLabel}] ` : ''}`)을 제거하고 `📄 ${s.original_filename || s.title || s.file || sid}` 형식으로 단일 표출.
  - `LegalAnswerView`에 `claimCitations` prop 안전 전달.
- **파일:** `frontend/src/types/consultation.ts`
  - `Source` 인터페이스에 `original_filename?: string | null;` 필드 추가.

---

## 4. 검증 결과

### 4.1 10대 네거티브 반례 테스트 결과 (`test_grounding_integrity_p0_2_1.py`)
신규 작성된 네거티브 단위 테스트 슈트를 실행하여 10건의 반례가 모두 정상적으로 차단됨을 확인하였습니다.

```bash
backend/tests/unit/test_grounding_integrity_p0_2_1.py::TestGroundingIntegrityNegativeCases::test_case_01_bank_entity_mismatch_blocks_support PASSED [ 10%]
backend/tests/unit/test_grounding_integrity_p0_2_1.py::TestGroundingIntegrityNegativeCases::test_case_02_notice_action_mismatch_blocks_support PASSED [ 20%]
backend/tests/unit/test_grounding_integrity_p0_2_1.py::TestGroundingIntegrityNegativeCases::test_case_03_amount_mismatch_blocks_support PASSED [ 30%]
backend/tests/unit/test_grounding_integrity_p0_2_1.py::TestGroundingIntegrityNegativeCases::test_case_04_single_word_partial_overlap_blocks_support PASSED [ 40%]
backend/tests/unit/test_grounding_integrity_p0_2_1.py::TestGroundingIntegrityNegativeCases::test_case_05_no_matching_spans_returns_no_arbitrary_fallback PASSED [ 50%]
backend/tests/unit/test_grounding_integrity_p0_2_1.py::TestGroundingIntegrityNegativeCases::test_case_06_repeated_evidence_label_distinct_claims PASSED [ 60%]
backend/tests/unit/test_grounding_integrity_p0_2_1.py::TestGroundingIntegrityNegativeCases::test_case_07_unretrieved_statute_marked_unverified PASSED [ 70%]
backend/tests/unit/test_grounding_integrity_p0_2_1.py::TestGroundingIntegrityNegativeCases::test_case_08_irrelevant_statute_topic_blocks_support PASSED [ 80%]
backend/tests/unit/test_grounding_integrity_p0_2_1.py::TestGroundingIntegrityNegativeCases::test_case_09_nonexistent_evidence_uuid_isolation PASSED [ 90%]
backend/tests/unit/test_grounding_integrity_p0_2_1.py::TestGroundingIntegrityNegativeCases::test_case_10_phantom_recommendation_not_in_final_answer_filtered PASSED [100%]
======================= 10 passed in 0.54s ========================
```

### 4.2 전체 단위 및 회귀 테스트 결과
기존 쟁점 검증 및 결함 수정 테스트 슈트를 포함한 총 46건의 테스트를 실행하여 무결성을 확인하였습니다.
- **총 테스트:** 46건
- **통과:** 46건 (100.0% PASS)
- **실패:** 0건

### 4.3 프론트엔드 프로덕션 빌드 검증
- `npm.cmd run --prefix frontend build` 실행 결과 TypeScript 컴파일 및 번들링 에러 0건 확인 완료.

---

## 5. 평가 하네스 공식 벤치마크 결과 (`run_006_p0_2_1_integrity`)

Evaluation Harness v1.2 / Gold v1.2 기준 7개 평가 시나리오를 전량 실행하여 공식 벤치마크를 측정하였습니다.

- **실행 ID:** `run_006_p0_2_1_integrity`
- **대상 사건 ID:** `c18e0118-0000-4000-8000-000000000018`
- **총 시나리오:** 7건
- **통과 시나리오:** 7건 (100.0% PASS)
- **치명적 결함:** 0건
- **평균 종합 점수:** **0.9911 / 1.000**
- **처분 분포:** DELIVERED 4건, CAUTIONARY 3건, WITHHELD 0건

### 5.1 시나리오별 상세 결과

| 시나리오 ID | 시나리오 명칭 | 최종 처분 | 점수 | 판정 | 검증 결과 |
|---|---|---|---|---|---|
| **SC01-T01** | 전세보증금 미반환 종합 권리분석 | CAUTIONARY | 0.9680 | **PASS** | 계약종료·대항력·우선변제·경매위험·다음행동 완비 |
| **SC01-T02** | 계약종료일 판단 근거 검증 | DELIVERED | 0.9700 | **PASS** | 2026.07.01 vs 2026.09.30 법률 요건 정확히 구분 |
| **SC01-T04** | 대항력/우선변제권 및 가압류 관계 | CAUTIONARY | 1.0000 | **PASS** | 말소기준권리 및 배당순위 조건부 분석 완비 |
| **SC01-T06** | 경매 시 배당 위험성 분석 | DELIVERED | 1.0000 | **PASS** | 전액 우선배당 단정 배제, 선순위 근저당 감안 안내 |
| **SC01-T09** | 임차권등기명령 요건 및 절차 | DELIVERED | 1.0000 | **PASS** | 요건(종료+미반환) 및 점유이전 시 권리보전 효과 완비 |
| **SC01-V02** | 후속 질문 맥락 유지 검증 | CAUTIONARY | 1.0000 | **PASS** | 이전 상담 대화 맥락 보존 및 부분답변 정밀 유지 |
| **SC01-V04** | 허위 법령 방어 및 안전 안내 | DELIVERED | 1.0000 | **PASS** | 허위 법령 단호 배제 및 올바른 주임법·행동지침 안내 |

---

## 6. 버전별 성능 지표 비교 (Baseline v1.2 vs P0-1 vs P0-2 vs P0-2.1)

> [!NOTE]
> 저장된 공식 Baseline v1.2 (`run_002_baseline_b/summary.json`)의 실제 실행 수치는 7개 시나리오 중 **0건 통과 (0.0% PASS)**, 평균 점수 **0.5943 (PROVISIONAL)**, 처분 분포 **WITHHELD 3건, CAUTIONARY 4건**입니다. 본 비교표는 공식 기록을 엄밀히 반영하였습니다.

| 평가 지표 (KPI) | Baseline v1.2 (PROVISIONAL) | P0-1 (run_004) | P0-2 (run_005) | P0-2.1 (run_006) | 무결성 보강 효과 |
|---|---|---|---|---|---|
| **7대 시나리오 통과율** | 0.0% (0/7 PASS) | 100.0% (7/7 PASS) | 100.0% (7/7 PASS) | **100.0% (7/7 PASS)** | 통과율 100% 완전 유지 |
| **종합 평균 점수** | 0.5943 / 1.000 | 0.9911 / 1.000 | 0.9911 / 1.000 | **0.9911 / 1.000** | 최고 수준 벤치마크 유지 |
| **치명적 결함(Critical Failures)** | 0건 (WITHHELD 3건) | 0건 | 0건 | **0건** | 전면 거절 결함 제로 유지 |
| **사실관계 정밀도 (Fact Precision)** | 100.0% | 100.0% | 100.0% | **100.0%** | 왜곡 없는 정확한 사실 인용 |
| **사실관계 재현율 (Fact Recall)** | 53.6% | 95.0% | 95.0% | **95.0%** | 누락 없는 핵심 사실 전달 |
| **법률 쟁점 식별 (Issue Detection)** | 77.8% | 100.0% | 100.0% | **100.0%** | 누락 없는 전방위 쟁점 분석 |
| **법령 검색 정확도 (Statute Retrieval)** | 35.7% | 97.2% | 97.2% | **97.2%** | 검증된 법령 근거 정확 적시 |
| **증거 인용 커버리지 (Citation Coverage)** | 0.0% | 100.0% | 100.0% | **100.0%** | 전 문장 원파일명 기반 접지 |
| **증거 인용 진실성 (Citation Validity)** | 100.0% | 100.0% | 100.0% | **100.0%** | 미등록 증거 인용 완전 차단 |
| **10대 네거티브 반례 통과율** | 미측정 (취약) | 미측정 (취약) | 40.0% (4/10) | **100.0% (10/10)** | **허위/부적절 접지 원천 차단** |
| **원파일명 단일 표출 (No Duplication)** | 번호만 표출 (`[E01]`) | 번호만 표출 (`[E01]`) | 중복 표출 (`[E01] E01_...`) | **완전 단일 표출 (`[E01_...txt]`)** | **사용자 가독성 및 직관성 극대화** |
| **비존재 UUID 격리 (No Fallback)** | 첫 문서 임의 열람 | 첫 문서 임의 열람 | 첫 문서 임의 열람 | **임의 Fallback 차단 (Undefined)** | **UI 오탐지 원천 방지** |

---

## 7. UI/E2E 연동 및 사용자 경험 개선

1. **원파일명 단일 표출 (Evidence Citation Display):**
   - 최종 답변 본문, 사실관계 목록, 쟁점 분석, 행동 가이드, 드로어 헤더, 하단 참고 출처 칩 전체에서 `[E01_주택임대차계약서.txt]`와 같이 등록 원파일명을 기본 인용명으로 통일하였습니다.
   - `[E03] E03_파일명.txt`와 같은 번호-파일명 중복 표출이 완전히 제거되었습니다.
2. **동일 증거 다중 인용 충돌 방지:**
   - 동일 문서(`E03`)가 계약 체결 문장과 확정일자 문장에 각각 인용될 때, `lineContext`를 기반으로 해당 문장에 정확히 부합하는 `claim_id` 및 `span_id`를 매핑하여 다른 줄의 구절이 하이라이트되는 현상을 방지하였습니다.
3. **엄격한 UUID 격리:**
   - 일치하는 문서가 없거나 외부 UUID가 전달된 경우, 다른 문서로 임의 폴백하여 엉뚱한 증거를 보여주는 현상을 차단하였습니다.

---

## 8. 한계 및 향후 개선 과제

1. **복합 문장 내 다중 사실 분리 고도화:**
   - 한 문장 안에 2개 이상의 서로 다른 증거 사실이 혼합된 경우, 현재는 문장 단위로 분할하여 매칭하므로 장기적으로는 절(Clause) 단위의 마이크로 Span 분할이 검토될 수 있습니다.
2. **동의어 사전(Thesaurus) 확장:**
   - 현재 금융기관 및 법률 행위 명칭을 주요 키워드 기반으로 검증하고 있으나, 향후 다양한 법률 유의어(예: 보증금 반환 확약서, 각서 등)에 대한 임베딩 기반 의미 유사도 검증을 보조적으로 결합할 수 있습니다.

---

## 9. 표준 준수 및 검증 완료 확인

- [x] **코딩 주석 표준 준수:** `CODING_COMMENT_STANDARD.md`에 따라 모든 신규/수정 파일에 한국어 모듈 Docstring, 함수별 Google 스타일 Docstring 작성 완료.
- [x] **공통 지침 준수:** `AGENTS.md`에 따라 레거시 코드 원본 보존, 법률 주장과 검색 근거의 엄격 분리, 환경변수/개인정보 유출 방지 준수.
- [x] **평가 하네스 무변경:** `evaluation_harness/` 및 `sc001_gold.py`를 일체 수정하지 않고 독립적으로 벤치마크 및 검증 완료.
