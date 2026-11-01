# Evidence Conflict Detector — 발언 화행 판정 정합성 보강

## 문제 재현
사건에서 상대방의 보증금 반환 일정 문의, 임대인의 분할 반환 제안, 새 임차인 모집 방침, 임차인의 분할안 거절, 후속 대안 모색까지 5쌍의 정상적인 경과가 `CONTRADICTS`로 표시되었다.

## 원인
- `SemanticFact.to_proposition()`은 기본적으로 `STATEMENT/REQUEST/PROPOSAL/NOTICE` 위주로 변환하므로 `QUESTION/REJECTION/PLAN` 화행이 소실될 수 있었다.
- 정밀 `extract_semantic_proposition()`에는 화행 구분 규칙이 별도로 존재하지만, 실 상충 판정의 `compare_fact_identity()` 경로에서 호출하지 않았다.
- '보증금 반환'이라는 같은 주제어가 두 발언의 동일 명제를 의미하지 않는데, 같은 이벤트 유형/공유 토큰으로 상충 후보에 들어갈 수 있었다.

## 구현
1. `fact_semantics._enrich_proposition_speech_act`를 하나의 화행 정규화 루틴으로 정의. 기존 SemanticFact 비교 경로와 정밀 명제 추출 경로가 모두 동일하게 사용한다.
2. `QUESTION`, `PROPOSAL`, `REJECTION`, `REQUEST`, `PLAN`, `ACCEPTANCE`, `PROMISE`를 구분하고 '동의할 수 없다고', '가능한지 문의', '다른 방법을 찾겠다는' 등 일반적인 활용형을 수용한다.
3. 서로 다른 비이행 화행은 동일 명제가 아니면 `DIFFERENT_CONTEXT / DISTINCT_SPEECH_ACTS`로 필터링한다.
4. '동의했다' 대 '동의하지 않았다'처럼 **동일 인물이 동일한 동의 행위를 정면으로 부정하는 경우**에는 게이트를 열어 후속 직접 모순 검사를 수행한다.
5. 기존 금액·날짜 비교, 실제 이행/미이행 대립, 제안과 반환 곤란 상태의 별개 판단 경로를 유지한다. 새로운 LLM 호출은 없고 스키마/DB 마이그레이션도 불필요하다.
6. `[CONFLICT_PAIR]` DEBUG 로그에 양쪽 원문·비교 가능성·reason_code·ID를 기록한다. DEBUG에는 개인정보가 포함될 수 있으므로 운영 로그 권한/보존기간을 준수한다.

## 검증
- 새 `test_repayment_dialogue_conflict_regression.py`: 5쌍 정·역방향, 화행 정규화, 실제 금액 상충과 반환 이행/미이행 상충 보호, 이전 제안·곤란 진술 회귀.
- 기존 `test_installment_proposal_conflict_regression.py`: 5건 DB 레거시 `CONTRADICTS`에 대한 API·GraphRAG 필터링, `reconcile_case_conflicts` dry-run/실행 검증 (테스트용 SQLite에서만 실행).
- CI: `conflict-semantic-regression.yml`은 기존 v1.1/v1.2 회귀까지 실행.

## 운영 복구
**이번 커밋은 운영 DB의 상태를 직접 변경하지 않는다.** 이미 저장된 오탐 링크와 `Fact.verification_status=DISPUTED`는 별도로 점검해야 한다.

1. 테스트 환경에서 해당 사건 ID의 상충 API, 원천 EvidenceLink, FactAdjudication 상태를 조회한다.
2. `reconcile_case_conflicts(db, case_id=<실제 사건 ID>, dry_run=True)`로 정리될 링크·상태를 미리 확인한다.
3. 정상 상충(동일 보증금 2억 vs 3억, 동일 시점 실제 이행 vs 미이행)이 유지되는지 확인한다.
4. PostgreSQL 백업 및 검토 후에만 dry_run=False를 실행하고 Neo4j 동기화를 확인한다.
5. 재실행시 변경 건수가 0인 멱등성을 확인한다.

> 의미 추출은 규칙 기반이므로 발언 시점/당사자/동일 대상이 불명확한 경우에는 함부로 확정 상충을 생성하지 않아야 한다. UI는 원본 증거명과 근거 Span을 보존한다.
