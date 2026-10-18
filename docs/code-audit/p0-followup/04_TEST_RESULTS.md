# P0 핵심 결함 4건 테스트 결과 보고서

**문서 번호:** `docs/code-audit/p0-followup/04_TEST_RESULTS.md`  
**작성 일자:** 2026-10-18  
**대상 저장소:** `yjjungyo/ai-legal-helper`

---

## 1. 테스트 실행 요약

| 테스트 세트 | 테스트 파일 | 실행 건수 | 결과 | 소요 시간 |
|---|---|---|---|---|
| **신규 P0 검증** | `tests/unit/test_p0_followup_defects.py` | 14건 | **14 Passed** (100%) | 5.37s |
| **기존 P0 회귀** | `tests/unit/test_p0_defects_reproduction.py` | 8건 | **8 Passed** (100%) | 4.12s |
| **기존 P1 회귀** | `tests/unit/test_p1_defects_reproduction.py` | 6건 | **6 Passed** (100%) | 3.85s |
| **기존 P2 회귀** | `tests/unit/test_p2_defects_reproduction.py` | 3건 | **3 Passed** (100%) | 2.91s |
| **HILT 공식 검색** | `tests/unit/test_hilt_statute_search.py` | 8건 | **8 Passed** (100%) | 39.26s |
| **프론트엔드 빌드**| `npm run build` (`tsc -b && vite build`) | 1,071 모듈 | **성공 (에러 0건)** | 190ms |
| **총 계** | - | **39건** | **전체 통과 (100%)** | - |

---

## 2. 신규 P0 테스트 케이스 상세 결과표 (`test_p0_followup_defects.py`)

| ID | 테스트 함수명 | 검증 내용 | 수정 전 | 수정 후 | 판정 |
|---|---|---|---|---|---|
| **V-01** | `test_v01_v02_prompt_does_not_contain_forced_official_statute_pass` | `VERIFICATION_PROMPT` 내 공식 검색 강제 PASS 문구 제거 검증 | FAILED | **PASSED** | PASS |
| **V-02** | `test_v02_v03_post_verification_rejects_pass_when_claims_unsupported` | UNSUPPORTED 주장 감지 시 결정론적 PASS 거부 및 REVISE 강등 | PASSED | **PASSED** | PASS |
| **V-04** | `test_v04_unsupported_claim_fails_pass` | 존재하는 출처이나 본문 불일치 시 PASS 거부 | FAILED | **PASSED** | PASS |
| **V-05** | `test_v05_rejects_pass_when_claims_list_is_empty` | 주요 주장 목록(claims) 비어있을 시 검증 완료 오인 차단 | FAILED | **PASSED** | PASS |
| **V-06** | `test_v06_uncertain_claim_leads_to_revise` | 결론에 영향 주는 UNCERTAIN 주장 시 PASS 거부 및 보완 지침 | FAILED | **PASSED** | PASS |
| **V-07** | `test_v07_verifier_syntax_error_fails_safe` | 검증 LLM 문법 오류 시 FAIL-OPEN 방지 (INSUFFICIENT 안전 차단) | PASSED | **PASSED** | PASS |
| **A-01** | `test_a01_delivered_when_verified_pass` | 검증 PASS 시 DELIVERED 답변 및 출처 정상 산출 | PASSED | **PASSED** | PASS |
| **A-02** | `test_a02_a05_insufficient_node_does_not_contain_unverified_draft` | `insufficient_node`에서 미검증 초안 고객 노출 완전 배제 | FAILED | **PASSED** | PASS |
| **A-06** | `test_a06_legacy_history_safe_fallback` | 과거 DB 레코드 호환 정책 (미검증 기록 임의 DELIVERED 차단) | PASSED | **PASSED** | PASS |
| **S-01** | `test_s01_s03_audit_separates_retrieved_and_cited_sources` | 10건 검색 중 1건 인용 시 cited_sources에 1건만 선별 수록 | FAILED | **PASSED** | PASS |
| **S-02** | `test_s02_chunk_preservation_and_deduplication` | 동일 문서 3개 청크 검색 시 원본 청크 100% 보존 및 출처 정돈 | PASSED | **PASSED** | PASS |
| **S-04** | `test_s04_unverified_article_citation_audit` | 검색 결과에 없는 가짜 조문 인용 시 rejected_citations 수록 | PASSED | **PASSED** | PASS |
| **H-02** | `test_h02_h04_re_analyze_prompt_neutral_for_loan_dispute` | 대여금 사건(SC-003) 재분석 시 임차권등기명령/임대인 하드코딩 제거 | FAILED | **PASSED** | PASS |
| **H-03** | `test_h03_labor_dispute_hilt` | 노동 분쟁 사건 재분석 시 근로기준법 반영 및 도메인 혼입 방지 | PASSED | **PASSED** | PASS |

---

## 3. 프론트엔드 빌드 검증 증거

```bash
> frontend@0.0.0 build
> tsc -b && vite build

vite v8.3.4 building client environment for production...
transforming...
✓ 1071 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.45 kB │ gzip:   0.29 kB
dist/assets/index-yuEfVyxe.css    8.33 kB │ gzip:   2.41 kB
dist/assets/index-C0EYiRUF.js   554.45 kB │ gzip: 169.43 kB
✓ built in 190ms
```

