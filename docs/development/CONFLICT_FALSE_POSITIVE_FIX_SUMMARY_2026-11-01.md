# 상충 증거 오판정 개선 요약 (2026-11-01)

**프로젝트:** AI Legal Helper · Evidence Structured GraphRAG  
**상태:** 소스 수정 및 자동 회귀 테스트 완료 / 운영 사건 DB 재검증 대기  
**소스 커밋:** [76f792a](https://github.com/yjjungyo/ai-legal-helper/commit/76f792ac5ce0015ccc7d7265bfb265317ab4ec3d)  
**테스트:** [Evidence Conflict Semantic Regression](https://github.com/yjjungyo/ai-legal-helper/actions/runs/41278297524) — **61 passed, 실패 0, 경고 2, 4.10초**

## 1. 발견된 문제

보증금 반환과 관련된 서로 다른 발언이 공통 주제어를 포함한다는 이유로 5건의 **확정 상충(CONTRADICTION)**으로 잘못 표시됨.

| # | 잘못 상충으로 분류된 비교 | 수정 후 테스트 결과 |
|---|---|---|
| 1 | 반환 일정 문의 ↔ 분할 반환 제안 | `DIFFERENT_CONTEXT` |
| 2 | 새 세입자 구하기 우선 방침 ↔ 분할 반환 제안 | `DIFFERENT_CONTEXT` |
| 3 | 반환 일정 문의 ↔ 분할 반환 거절 | `DIFFERENT_CONTEXT` |
| 4 | 새 세입자 구하기 우선 방침 ↔ 분할 반환 거절 | `DIFFERENT_CONTEXT` |
| 5 | 분할 반환 제안 ↔ 다른 방법 모색 | `DIFFERENT_CONTEXT` |

문의 → 제안 → 거절 → 대안 모색은 **양립 가능한 의사표시·후속 대응**이므로 동일 명제의 정면 모순으로 보아서는 안 됨.

## 2. 원인

- `SemanticFact.to_proposition()`을 통한 실제 상충 비교 경로에서 `QUESTION`, `REJECTION`, `PLAN` 등 세부 화행이 소실될 수 있었음.
- 정밀 의미 추출 경로와 기존 상충 판정 경로가 화행 분석 규칙을 공유하지 않았음.
- `보증금 반환`이라는 공통 표현을 **동일한 행위·사실**의 증거로 지나치게 해석할 위험이 있었음.
- `동의할 수 없다고 밝혔다`, `가능한지 문의하였다`, `다른 방법을 찾겠다는` 등의 일반적 표현 처리가 불충분했음.

## 3. 개선 사항

| 구분 | 주요 변경 |
|---|---|
| 화행 정규화 | `fact_semantics.py`의 `_enrich_proposition_speech_act()` 추가 및 정밀 추출·Fact 비교 경로에서 공통 사용 |
| 비교 관문 | 서로 다른 문의·제안·거절·계획 등을 `DIFFERENT_CONTEXT / DISTINCT_SPEECH_ACTS`로 분류 |
| 정상 모순 보존 | 동일 보증금의 상이한 원금, 같은 시점의 반환·미반환 등 실제 상충 탐지 유지 |
| 상세 로깅 | `conflict_detector.py`에 `[CONFLICT_PAIR]` DEBUG 로그 (진술 원문, ID, 비교 가능성, 판정 사유) |
| 회귀 테스트 | 제보 5쌍 정·역방향 + 기존 v1.1/v1.2 + API·GraphRAG·복구 함수 테스트 |
| 자동 검증 | `.github/workflows/conflict-semantic-regression.yml` 신규 도입 |

## 4. 검증 결과와 한계

- **61개 자동 테스트 통과, 실패 없음.** 이번 5건은 정·역방향 오탐이 발생하지 않도록 검증.
- 저장된 오래된 `CONTRADICTS` 관계를 API/GraphRAG에서 재검증하는 회귀 테스트도 통과.
- 추가 LLM 호출 없음, DB 스키마 변경 없음.
- **실제 운영 사건 DB 및 브라우저 E2E는 아직 검증하지 않음.** 자동 테스트 통과와 운영 데이터 정리는 별개.

## 5. 운영 후속 조치

1. 최신 백엔드 배포 후 해당 사건의 상충 증거 화면 재조회.
2. PostgreSQL `EvidenceLink`, `Fact.verification_status`, `FactAdjudication` 및 Neo4j `CONTRADICTS` 상태 확인.
3. `reconcile_case_conflicts(..., dry_run=True)`로 정리 예상 내역 확인.
4. 정상 상충이 보존되는지 검증하고, **백업·승인 이후** 필요한 경우에만 `dry_run=False` 실행.
5. Neo4j 동기화, 재조회, 멱등성 검증.

**주의:** 이번 소스 수정만으로 운영 PostgreSQL·Neo4j의 과거 오탐 데이터가 자동 삭제된 것은 아님.

## 6. 평가 증빙 요약

**문제(5건 오탐) → 원인(화행 유실 및 동일 주제/동일 명제 혼동) → 해결(화행 정규화·비교 관문 강화) → 검증(61 passed) → 후속(실제 사건 DB 재검증)**

상세 기술 보고서: [CONFLICT_SPEECH_ACT_NORMALIZATION_REPORT.md](./CONFLICT_SPEECH_ACT_NORMALIZATION_REPORT.md)
