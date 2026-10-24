# Issue-Level Verification & Evidence-Grounded Consultation v1.0 완료보고서

## 1. 개요 및 개발 목적

- **프로젝트:** AI Legal Helper
- **저장소:** `yjjungyo/ai-legal-helper`
- **기준 커밋:** `a4afd2274d03a634692914ec46f954ee3ecd3dc3`
- **우선순위:** P0 (핵심 상담 기능 결함 수정 및 증거 기반 답변 고도화)
- **개발 도구:** Antigravity

### 1.1 해결된 핵심 결함
실제 사건(`17c5bb1d-183e-450b-ab3e-64ced1e3d70e`: 17건의 증거 문서, 237건의 확정 사실, 83건의 타임라인 이벤트)에서 사용자가 복합 상담을 요청했을 때, 기존 시스템은 다음 치명적 결함으로 인해 연속 두 차례(07:43, 08:49) 모두 **`WITHHELD(판단 유보)`**를 반환하며 사용자에게 실질적인 법률 조언을 전혀 제공하지 못했습니다.

1. **전체 답변 일괄 기각(All-or-Nothing Monolithic Failure):**
   - 임대차계약 해지, 보증금 지급, 대항력/확정일자 취득, 가압류 등 핵심 사실관계가 명백히 입증되었음에도, '경매 배당금 예상액'이나 '지연손해금 법정 조문' 등 일부 부차적/추정적 쟁점의 법령 청크가 부족하다는 이유로 전체 답변이 `insufficient` 노드로 분기되어 전면 기각됨.
2. **정적 안내문 치환 및 등록 증거 무시:**
   - `insufficient_node`에서 이미 계약서(E01)와 이체영수증(E03)이 승인·등록되어 있음에도 불구하고, 하드코딩된 기계적 3개 불릿("임대차계약서를 확보하세요" 등)으로 답변을 덮어씌움.
3. **출처 레지스트리 전면 증발:**
   - `insufficient_node`가 `sources: []`, `cited_sources: []`로 초기화하여 기등록된 증거 목록조차 사용자 UI에서 사라짐.
4. **증거 식별자 부재:**
   - AI 답변 초안 및 검증기가 참조할 결정론적이고 안정적인 표시용 증거 번호(`E01`, `E02` 등) 매핑 체계가 없어, 증거 인용 감사(Citation Grounding)가 불가능했음.

---

## 2. 주요 아키텍처 및 구현 컴포넌트

### 2.1 CaseEvidenceBriefing (`case_intelligence/case_briefing.py`)
- PostgreSQL의 `Case`, `Party`, `Fact`, `Event`, `EvidenceDocument`, `EvidenceClaim`, `EvidenceAssessment`, `FactAdjudication`, `EvidenceGap`을 단일 구조화 브리핑 모델로 취합.
- `assign_evidence_labels`: 기존 파일명의 `E01_...`, `E02_...` 접두사를 최우선 보존하고 미라벨 문서는 순차적 E번호를 자동 부여하여 1:1 결정론적 매핑 보장.
- 증명력 분리: `FactAdjudication` 상태에 따라 객관적 입증 사실(`EVIDENCE_SUPPORTED`, `CORROBORATED`), 당사자 단순 주장(`PARTY_ALLEGED`), 미입증 사실(`EVIDENCE_INCOMPLETE`), 실제 상충 분쟁(`GENUINELY_DISPUTED`)을 엄격히 분리하여 LLM Synthesizer와 Verifier에 공급.

### 2.2 Issue Planner (`workflows/issue_planner.py`)
- 사용자 복합 질문을 의미적·법률적으로 독립된 쟁점 단위로 분해:
  1. `ISSUE_LEASE_TERMINATION`: 임대차계약 종료 시점 및 보증금 반환의무 발생
  2. `ISSUE_ATTACHMENT_RANKING`: 가압류 등재와 임차인의 대항력·우선변제권 순위 관계
  3. `ISSUE_AUCTION_DIVIDEND_RISK`: 경매 시 보증금 회수 위험 및 배당 요구 법률관계 (추정적 쟁점)
  4. `ISSUE_RIGHT_PRESERVATION`: 대항력 유지 및 임차권등기명령 신청
  5. `ISSUE_INSTALLMENT_PROPOSAL`: 임대인의 분할 지급 제안 거절 및 지연손해금 청구
  6. `ISSUE_NEXT_ACTIONS`: 우선순위별 실무 조치 사항
- 일반 질의 폴백: 임대차 외 도메인(저작권, 일반 채권 등)에 대해 `ISSUE_GENERAL_ANALYSIS` 단일 쟁점으로 안전하게 전환.
- 쟁점별 관련 확정 사실 ID(`relevant_fact_ids`) 및 증거 라벨(`relevant_evidence_labels`) 자동 매칭.

### 2.3 Issue-Level Verification Engine (`agents/issue_verifier.py`)
- **사실 검증(Fact Verification)과 법률 검증(Legal Verification) 분리:**
  - 사실 검증: 외부 법령 없이도 `CaseEvidenceBriefing`의 확정 사실 및 `source_registry` 라벨 일치 여부를 독립 검증.
  - 법률 검증: 검색된 공식 법령 조문과의 매칭을 평가.
- **5대 쟁점 상태 분류:**
  - `VERIFIED`: 사실과 법령이 모두 확고히 뒷받침됨.
  - `CONDITIONAL`: 핵심 사실은 입증되었으나 시세/낙찰가 변동에 따른 추정이 수반되거나 최신 등기부 대조가 필요한 쟁점.
  - `NEEDS_EVIDENCE`: 필수 사실 또는 핵심 증거(등기부 등)가 결손된 쟁점.
  - `NEEDS_LEGAL_SOURCE`: 사실은 확인되었으나 적용 조문 검색이 필요한 쟁점.
  - `BLOCKED`: 허위/미등록 증거(`[E99]` 등) 인용 또는 명백한 사실 모순으로 차단된 쟁점.

### 2.4 Final Disposition & Partial Answer Assembly (`workflows/final_disposition.py`)
- **최종 판정 3계층 (P0-05):**
  - `DELIVERED`: 모든 쟁점이 `VERIFIED`인 경우.
  - `CAUTIONARY`: 검증 완료 쟁점과 조건부/증거보완 쟁점이 혼재된 경우 -> 검증된 분석을 보존하고 주의사항을 덧붙여 사용자에게 답변 전달.
  - `WITHHELD`: 모든 쟁점이 `BLOCKED` 또는 증거 결손인 극단적 경우에만 제한적 유보.
- **부분 답변 조립 (`assemble_grounded_answer`):**
  - [1. 사건 종합 판단 및 핵심 결론]
  - [2. 등록 증거 기반 확인된 사실관계] (E01~E17 인용 포함)
  - [3. 쟁점별 법률 분석 및 판단] (검증 완료 쟁점의 실체적 분석 보존)
  - [4. 보완이 필요한 증거 (Evidence Gaps)] (이미 등록된 서류는 재요구하지 않고 실제 미제출 서류만 명시)
  - [5. 안전한 실무적 다음 행동 가이드] (전입/점유 유지, 최신 등기부 열람, 임차권등기명령 순차 절차)
- **동적 판단 유보 (`build_dynamic_withheld_answer`):**
  - 판단 유보 시에도 하드코딩 템플릿 대신 실제 등록 증거 목록과 입증된 사실관계를 온전히 출력하고, 등록 증거 출처 목록(`cited_sources`)을 보존.

### 2.5 API, Schema 및 프론트엔드 연동
- **`backend/src/ai_legal_helper/api/schemas/consultation.py`:**
  - `Source.evidence_label` 필드 추가.
  - `ConsultationResponse`에 `issue_results`, `verified_facts`, `missing_evidence`, `evidence_citations` 추가.
- **`backend/src/ai_legal_helper/api/routes/consultation.py`:**
  - 비동기 백그라운드 태스크 및 DB 영구 저장 레코드에 쟁점별 검증 필드 완벽 매핑.
- **`frontend/src/`:**
  - `frontend/src/types/consultation.ts` 타입 확장.
  - `frontend/src/components/ChatSection.tsx`에 쟁점별 검증 현황 뱃지(`VERIFIED`: 녹색, `CONDITIONAL`: 보라색, `NEEDS_EVIDENCE`: 노란색, `BLOCKED`: 적색) 및 `[E01]` 증거 번호 뱃지 렌더링.
  - Vite + TypeScript 빌드 통과.

---

## 3. 검증 결과

### 3.1 C01 ~ C25 전용 단위 테스트 스위트 (100% PASS)
`backend/tests/unit/test_issue_verification.py`:
- `test_c01_assign_evidence_labels_with_prefixes` PASSED
- `test_c02_assign_evidence_labels_auto_sequential` PASSED
- `test_c03_build_case_evidence_briefing` PASSED
- `test_c04_briefing_to_prompt_context` PASSED
- `test_c05_plan_legal_issues_multi_issue` PASSED
- `test_c06_plan_legal_issues_matches_relevant_facts` PASSED
- `test_c07_plan_legal_issues_matches_evidence_labels` PASSED
- `test_c08_plan_legal_issues_general_fallback` PASSED
- `test_c09_verify_issue_verified_when_facts_and_law_present` PASSED
- `test_c10_verify_issue_conditional_for_speculative_predictions` PASSED
- `test_c11_verify_issue_needs_evidence_when_facts_missing` PASSED
- `test_c12_verify_issue_blocked_when_unregistered_evidence_cited` PASSED
- `test_c13_fact_verifier_operates_without_statutes` PASSED
- `test_c14_legal_verifier_matches_statutes` PASSED
- `test_c15_citation_audit_requires_labels` PASSED
- `test_c16_speculative_prediction_control` PASSED
- `test_c17_determine_final_disposition_delivered` PASSED
- `test_c18_determine_final_disposition_cautionary` PASSED
- `test_c19_determine_final_disposition_withheld` PASSED
- `test_c20_assemble_grounded_answer_preserves_verified` PASSED
- `test_c21_assemble_grounded_answer_includes_missing_evidence` PASSED
- `test_c22_assemble_grounded_answer_includes_safe_next_actions` PASSED
- `test_c23_build_dynamic_withheld_answer_includes_facts_and_evidence` PASSED
- `test_c24_insufficient_node_preserves_sources` PASSED
- `test_c25_multi_issue_workflow_no_monolithic_failure` PASSED
**결과: 25개 테스트 전원 통과 (0.50초 소요)**

### 3.2 기존 회귀 테스트 스위트 (100% PASS)
- `test_evidence_adjudication.py` (28 tests PASSED)
- `test_conflict_detector_v1_2.py` (16 tests PASSED)
- `test_parties_timeline_sync.py` (19 tests PASSED)
**결과: 63개 회귀 테스트 전원 통과 (21.92초 소요)**

### 3.3 프론트엔드 빌드 정합성 검증
`npm.cmd run build --prefix frontend`:
- TypeScript 컴파일(`tsc -b`) 및 Vite 번들링 성공 (`dist/` 정상 생성, 에러 0건).

---

## 4. 코딩 표준 및 규칙 준수 점검

1. **`CODING_COMMENT_STANDARD.md` 준수:**
   - 모든 신규 파이썬 모듈(`case_briefing.py`, `issue_planner.py`, `issue_verifier.py`, `final_disposition.py`, `test_issue_verification.py`)에 한국어 모듈 개요, 주요 기능, 클래스/함수별 Google 스타일 docstring 작성 완료.
2. **`AGENTS.md` 원칙 준수:**
   - 검증되지 않은 가공 정보를 사실로 보고하지 않음.
   - 개인정보 및 민감 키 로그 비노출.
   - 단일 도메인(주택임대차) 하드코딩 지양 및 일반 법률 질의에 대한 확장성 확보.
