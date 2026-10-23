# Evidence Conflict Detection Engine v1.1 — 결함 수정 및 안정화 완료보고서

- **작성일:** 2026-10-23
- **대상 프로젝트:** `yjjungyo/ai-legal-helper`
- **기준 커밋:** `688b0794d6e59cb9370350fa088d953cce0b12e5`

---

## 1. 수정 및 신규 생성 파일 목록

| 구분 | 파일 경로 | 변경 요약 |
|---|---|---|
| DB 모델 | `backend/src/ai_legal_helper/database/models.py` | `EvidenceClaim`에 `subject_key`, `predicate_key`, `scope`, `temporal_context`, `structured_slots` 구조화 슬롯 컬럼 추가 |
| DB 마이그레이션 | `backend/alembic/versions/f7c8a912b304_add_structured_conflict_fields_to_evidence_claims.py` | `evidence_claims` 테이블 5개 컬럼 및 인덱스 추가 (`alembic upgrade head` 적용 완료) |
| 상충 탐지 엔진 | `backend/src/ai_legal_helper/case_intelligence/conflict_detector.py` | 금액·날짜 의미 역할(Semantic Role) 분리, 달력 유효성 검증(`datetime.date`), 부정 범위(`NEGATIVE`/`DOUBLE_NEGATIVE`/`REPORTED_NEGATIVE`) 세분화, Stage 3 LLM 검증 안전 폴백, `reconcile_case_conflicts()` 안전장치·`dry_run`·변경 감사 로그 고도화 |
| 증거 추출기 | `backend/src/ai_legal_helper/case_intelligence/evidence_extractor.py` | 추출 단계에서 구조화 슬롯(`subject_key`, `predicate_key`, `scope`, `temporal_context`, `structured_slots`)을 `EvidenceClaim`에 영속화하고 `POTENTIAL_CONFLICT` 링크 분리 기록 |
| 리뷰 매니저 | `backend/src/ai_legal_helper/case_intelligence/evidence_manager.py` | `APPROVE`/`EDIT`/`REJECT` 시 소유권 검증, 단독 지지 Fact 정리 및 다중 지지 Fact 보존, `DISPUTED` 상태 재계산, `Fact.occurred_at` 반영 및 타임라인(`Event`) 재구축, 단일 트랜잭션 원자성 보장 |
| 그래프 동기화 | `backend/src/ai_legal_helper/database/graph_sync.py` | `EvidenceClaim` 구조화 슬롯 스냅샷 포함 및 확정 관계(`SUPPORTS`, `CONTRADICTS`)만 Neo4j에 투영 |
| GraphRAG | `backend/src/ai_legal_helper/rag/graph_rag.py` | `find_contradictions()`에서 승인된 Claim 조건 강화 및 상충 진술(`contradicting_statement`) 반환 보강 |
| 법률 워크플로우 | `backend/src/ai_legal_helper/workflows/legal_workflow.py` | `verification_node` 및 `verification_condition`에서 질문 핵심 Fact 상충 시 `EVIDENCE_CONFLICT` 판정 및 처분 상태(`DELIVERED` / `CAUTIONARY` / `WITHHELD`) 게이팅 연계 |
| 증거 API | `backend/src/ai_legal_helper/api/routes/evidence.py` | `review_evidence_claim` 소유권 검증 강화, `get_evidence_conflicts`에서 `CONTRADICTION`/`POTENTIAL_CONFLICT` 분리 및 원문 Span 위치(`page_number`, `paragraph_index`, `text_excerpt`) 반환, `delete_evidence` 다중 지지 Fact 보존 |
| 프론트엔드 UI | `frontend/src/components/EvidenceSection.tsx` | 상충 API 호출 실패 시 명시적 오류 배너 표시, **확정 상충(`CONTRADICTION`)** 카드와 **추가 확인 필요(`POTENTIAL_CONFLICT`)** 카드 분리 및 출처 문서명·Span 위치 표시 |
| 테스트 | `backend/tests/unit/test_conflict_detector.py` | 필수 테스트 `T01`~`T16` 및 다중 금액·시점 맥락·Verifier 게이팅 통합 시나리오 검증 |

---

## 2. DB 마이그레이션 내역

- **Revision ID:** `f7c8a912b304` (Revises: `d17d31661e36`)
- **적용 대상 테이블:** `evidence_claims`
- **추가 컬럼 및 인덱스:**
  - `subject_key VARCHAR` (`ix_evidence_claims_subject_key`)
  - `predicate_key VARCHAR` (`ix_evidence_claims_predicate_key`)
  - `scope VARCHAR DEFAULT 'CASE_GLOBAL'` (`ix_evidence_claims_scope`)
  - `temporal_context VARCHAR`
  - `structured_slots JSON`
- **적용 결과:** `alembic upgrade head` 정상 완료 및 기존 데이터 호환성 확인.

---

## 3. P0 / P1 항목별 구현 결과

| 항목 ID | 요구사항 요약 | 구현 결과 | 상태 |
|---|---|---|---|
| **P0-01** | Comparability & Rule Verification 고도화 (금액·날짜 역할 분리, 달력 유효성 검증, 부정 범위 세분화) | `extract_amount_roles()`(10개 의미 역할), `extract_dates_with_validation()`(`datetime.date` 검증 + 8개 날짜 역할), `analyze_polarity_and_predicate()`(`AFFIRMATIVE`/`NEGATIVE`/`DOUBLE_NEGATIVE`/`REPORTED_NEGATIVE`) 구현 | **완료 (PASS)** |
| **P0-02** | 추출된 구조화 필드(`subject`, `predicate`, `scope`, `temporal_context`, `structured_slots`) 전 구간 영속화 | `EvidenceClaim` 모델 저장 → `evidence_extractor.py` → `evidence_manager.py` → `conflict_detector.py` → `graph_sync.py` → `evidence.py` 전 구간 연결 | **완료 (PASS)** |
| **P0-03** | Claim 수정(`EDIT`)·반려(`REJECT`) 시 데이터 정합성 복구 및 소유권 검증 | `_cleanup_previous_claim_effects()`, `_recalculate_case_disputed_facts()`, `_rebuild_case_timeline()` 구현 및 `expected_case_id`/`expected_evidence_id` 소유권 검증 적용 | **완료 (PASS)** |
| **P1-01** | Stage 3 Selective LLM Verification 연결 및 안전 폴백 | `_verify_pair_with_llm()` Langfuse 연동 및 LLM 예외 발생 시 강제 `CONTRADICTION` 없이 `POTENTIAL_CONFLICT`(`LLM_VERIFICATION_UNAVAILABLE`)로 안전 폴백 | **완료 (PASS)** |
| **P1-02** | `POTENTIAL_CONFLICT` 상태 전 구간 일관 처리 | `EvidenceLink(link_type="POTENTIAL_CONFLICT")` 분리 저장, `Fact.verification_status="DISPUTED"` 오적용 방지, Neo4j 확정 관계 전용 투영 유지 | **완료 (PASS)** |
| **P1-03** | Evidence Conflict → Verifier 게이팅 연계 | 질문 핵심 Fact 상충 시 단정적 초안은 `REVISE`(`EVIDENCE_CONFLICT`) → 미해소 시 `WITHHELD`, 상충 명시 조건부 초안은 `CAUTIONARY`, 부수적 상충은 경고 후 `DELIVERED` | **완료 (PASS)** |
| **P1-04** | `reconcile_case_conflicts()` 안전성·멱등성·`dry_run` 고도화 | `case_id=None` 시 `allow_all_cases=True` 필수화, `dry_run=True` 롤백 시뮬레이션, 변경 전후 `changes` 감사 기록 및 `GraphSyncTask` 큐 연동 | **완료 (PASS)** |
| **P1-05** | Frontend 상충 UI 분리 및 API 오류 배너 표시 | `EvidenceSection.tsx`에서 `conflictError` 배너, **확정 상충** vs **추가 확인 필요** 카드 분리, 문서명 및 `[p.X, 문단 Y]` 위치 표시 | **완료 (PASS)** |

---

## 4. 필수 테스트 (T01 ~ T16) 및 엣지케이스 검증 결과

실행 명령:
```bash
python -m pytest backend/tests/unit/test_conflict_detector.py backend/tests/unit/test_evidence_structured_graphrag.py -v
```

| 테스트 ID | 시나리오 | 기대 결과 | 실제 결과 | 판정 |
|---|---|---|---|---|
| **T01** | 서로 다른 문서의 고유 제목 (`주택임대차계약서` vs `퇴거 요청 문자`) | `DIFFERENT_CONTEXT` (`DOCUMENT_LOCAL_METADATA`) | `DIFFERENT_CONTEXT` | **PASS** |
| **T02** | 같은 금액의 다른 표기 (`300,000,000원` vs `3억 원`) | `CONSISTENT` (`NORMALIZED_AMOUNT_MATCH`) | `CONSISTENT` | **PASS** |
| **T03** | 약정 보증금(`3억 원`) vs 일부 반환 금액(`2억 원을 반환`) | `CONTRADICTION` 금지 (`DIFFERENT_CONTEXT`) | `DIFFERENT_CONTEXT` (`DIFFERENT_AMOUNT_ATTRIBUTE`) | **PASS** |
| **T04** | 동일 계약서상 보증금 불일치 (`3억 원` vs `2억 원`) | `CONTRADICTION` (`MUTUALLY_EXCLUSIVE_AMOUNT`) | `CONTRADICTION` | **PASS** |
| **T05** | 날짜 + 금액 복합 문장 (`2026-09-30 3억 반환 요청` vs `2026-10-15 3억 반환 요청`) | `CONSISTENT` 금지 (`POTENTIAL_CONFLICT`) | `POTENTIAL_CONFLICT` (`SAME_AMOUNT_BUT_DATE_DISCREPANCY`) | **PASS** |
| **T06** | 동일 행위 직접 긍정 vs 직접 부정 (`반환하였다` vs `반환하지 않았다`) | `CONTRADICTION` (`OPPOSITE_POLARITY_ON_SAME_SUBJECT`) | `CONTRADICTION` | **PASS** |
| **T07** | 이중 부정(`거절하지 않았다`) 및 간접화법 부정(`반환할 수 없다고 통보`) | 단순 극성 반전 오탐 방지 (`CONTRADICTION` 금지) | `DIFFERENT_CONTEXT` (`DIFFERENT_NEGATION_SCOPE_OR_SPEECH_ACT`) | **PASS** |
| **T08** | Claim 승인 → Fact F1 생성 → Claim 수정(`EDIT`) | 단독 지지 기존 Fact F1 삭제, 새 Fact F2 생성 및 쟁점 참조 정리 | F1 삭제 및 F2 생성 확인 | **PASS** |
| **T09** | Claim A, B 공동 지지 Fact F2에서 Claim A만 반려(`REJECT`) | Fact F2 유지, Claim A 링크만 제거 | F2 유지 및 Claim B 지지 유지 확인 | **PASS** |
| **T10** | 단독 지지 Claim B 반려(`REJECT`) | Fact F2, 관련 EvidenceLink, 타임라인 Event 모두 정리 | Fact·Link·Event 0건 정리 확인 | **PASS** |
| **T11** | PostgreSQL `EvidenceLink` + `EvidenceClaim` 중복 상충 | API 조회 결과 중복 없이 1건 반환 | 1건 반환 확인 | **PASS** |
| **T12** | Neo4j 비활성(`driver=None`) 시 Fallback | PostgreSQL 기반 상충 조회 정상 동작 | 정상 반환 확인 | **PASS** |
| **T13** | Stage 3 LLM 검증 중 예외/타임아웃 발생 | 강제 `CONTRADICTION` 없이 `POTENTIAL_CONFLICT` 폴백 | `POTENTIAL_CONFLICT` (`LLM_VERIFICATION_UNAVAILABLE`) | **PASS** |
| **T14** | `reconcile_case_conflicts()` 안전장치·`dry_run`·2회 실행 멱등성 | 2회차 실행 시 추가 변경 0건 | 2회차 모든 변경 카운트 `0` 확인 | **PASS** |
| **T15** | 다른 사건/문서의 `claim_id`로 리뷰 요청 (소유권 검증) | `ValueError` 및 `HTTPException(400)` 거부 | 거부 확인 | **PASS** |
| **T16** | 비정상 달력 날짜 (`2026년 2월 31일 지급`) | 유효 날짜 정규화 금지 및 `INSUFFICIENT_INFORMATION` 반환 | `INSUFFICIENT_INFORMATION` (`INVALID_CALENDAR_DATE`) | **PASS** |
| **Edge/P1-03** | 한 문장 내 다중 금액(보증금/계약금/잔금), 시점 변경, Verifier 게이팅 | 역할별 정확 분리 및 `WITHHELD`/`CAUTIONARY` 분기 | 전 항목 통과 | **PASS** |

---

## 5. 실제 사건 복구 전후 비교 결과

대상 사건(`f8c3d8a5-fad6-47ec-b987-77f31bd0379a`, 문서 `E01_주택임대차계약서.txt` 및 `E05_퇴거_및_보증금_반환_요청_문자.txt`):

| 지표 | 복구 전 (v1.0 이전) | v1.1 복구 및 슬롯 백필 후 |
|---|---|---|
| 오탐 `CONTRADICTS` 링크 수 | 14건 | **0건** (금액 일치 2건은 `SUPPORTS`로 전환, 별개 사실 12건은 제거) |
| 오탐 `CONTRADICTION_CANDIDATE` Claim 수 | 14건 | **0건** (`DOCUMENT_STATES` 복원 및 구조화 슬롯 백필 완료) |
| 오탐 `DISPUTED` Fact 수 | 2건 | **0건** (`DOCUMENT_VERIFIED` 복원 완료) |
| `/cases/{case_id}/evidence/conflicts` 반환 건수 | 17건 (중복 포함 오탐) | **0건** (`contradiction_count: 0`, `potential_conflict_count: 0`) |
| 2회차 `reconcile_case_conflicts()` 실행 시 변경 건수 | - | **0건** (멱등성 검증 완료) |

---

## 6. 주석 표준(`CODING_COMMENT_STANDARD.md`) 준수 점검

- **Python 모듈 (`conflict_detector.py`, `evidence_extractor.py`, `evidence_manager.py`, `graph_sync.py`, `graph_rag.py`, `legal_workflow.py`, `evidence.py`):**
  - 한국어 모듈 개요 Docstring 및 Google 스타일 함수·클래스 Docstring 작성 완료.
  - 3단계 상충 판정 파이프라인, 금액·날짜 역할 분리, 부정 범위 해석, 리뷰 상태 전이 및 고아 Fact 정리 이유(Why)를 주석에 명시.
- **TypeScript/React (`EvidenceSection.tsx`):**
  - 한국어 JSDoc/TSDoc 주석 유지 및 갱신 완료.
- **보안 점검:**
  - API Key, 개인정보, 하드코딩된 사건 텍스트·금액·날짜 없음.

---

## 7. 남은 기술적 한계 및 후속 권고사항

1. **복합 표(Table) 및 스캔 이미지 OCR 내 수치 맥락 추출:** 현재 금액·날짜 역할 분류는 텍스트 문맥 윈도우와 LLM 구조화 추출을 결합하여 동작하므로, 표 구조가 깨진 OCR 텍스트에서는 Stage 3 선택적 LLM 검증(`CONFLICT_LLM_VERIFICATION_ENABLED=true`)을 활성화하면 정확도를 높일 수 있다.
2. **당사자(Party) 자동 승격 연계:** 현재 `EvidenceClaim(claim_type="PARTY_INFO")` 승인 시 `Fact` 및 `Event` 타임라인은 자동 갱신되며, 향후 `PARTY_INFO` Claim에서 정규화된 당사자 성명·역할을 `Party` 테이블에도 자동 병합하면 사건 요약 탭의 당사자 목록 편의성을 추가로 높일 수 있다.
