# P4.1 Verifier-Guided HILT 법령 검색 — 06. T-01 ~ T-08 시나리오별 실행 결과

## 1. 개요
본 문서는 `backend/tests/unit/test_hilt_statute_search.py` 및 전체 통합 테스트 스위트를 통해 실행 검증된 **T-01 ~ T-08 시나리오별 검증 결과**를 상세히 기록한다.

---

## 2. 시나리오별 검증 결과 요약

| 테스트 ID | 시나리오 명칭 | 핵심 검증 항목 | 실행 결과 |
| :---: | :--- | :--- | :---: |
| **T-01** | 내부 RAG 충분 사건 | Verifier PASS 시 HILT 승인 노드 진입 없이 `finalize` 직행 | **PASS** |
| **T-02** | 특별법 누락 사건 | `LEGAL_SOURCE_MISSING` 감지 시 HILT 인터럽트 노드 진입 | **PASS** |
| **T-03** | 사용자 승인 시나리오 | 외부 검색 실행, 공식 조문 병합, 재분석 후 최종 답변 생성 | **PASS** |
| **T-04** | 사용자 거절 시나리오 | 외부 검색 차단, 판단 유보 안내 후 `insufficient` 안전 종료 | **PASS** |
| **T-05** | 외부 검색 결과 부재 | 공인 API 조회 실패 시 허위 답변 없이 `insufficient` 안전 종료 | **PASS** |
| **T-06** | 허위 법령 인용 차단 | 미검증 조문 및 출처 차단, `citation_existence_rate` 0.0 기록 | **PASS** |
| **T-07** | Checkpointer 상태 복원 | 인터럽트 상태 보존 및 `Command(resume=...)` 정상 재개 | **PASS** |
| **T-08** | 서버 재시작 복원 검증 | 세션 종료/재시작 후에도 DB 승인 대기 상태 유지 및 복원 | **PASS** |

---

## 3. 시나리오별 세부 분석

### 3.1 T-01: 내부 RAG 충분 사건
- **조건**: 민법상 임대인 수선의무 질문, 내부 ChromaDB에 민법 조문 존재.
- **실행 경로**: `START` → `supervisor_initialize` → `route` → `plan` → `run_agents` → `synthesize` → `verification` → `finalize` → `END`
- **검증**: `verification_condition`이 `finalize`를 반환하며 HILT 노드(`statute_search_approval`)로 우회하지 않음.

### 3.2 T-02: 특별법(주택임대차보호법) 누락 사건
- **조건**: 묵시적 갱신 후 계약 해지 효력 시점 질문, 내부 RAG에 주택임대차보호법 부재.
- **검증 결과**:
  - `status`: `INSUFFICIENT`
  - `reason_code`: `LEGAL_SOURCE_MISSING`
  - `candidate_laws`: `["주택임대차보호법"]`
  - `verification_condition`이 `statute_search_approval` 노드로 정확히 라우팅됨.

### 3.3 T-03: 사용자 승인 시나리오
- **조건**: 사용자 승인(`approval_status == 'APPROVED'`).
- **실행 경로**: `statute_search_approval` → `execute_statute_search` → `re_analyze` → `verification` → `finalize`
- **검증 결과**:
  - `search_official_statutes`가 호출되어 `주택임대차보호법 제6조의2 제2항(3개월)` 조문 확보.
  - `retrieved_sources`에 표준 `STATUTE` 스키마로 병합됨.
  - `re_analyze` 노드에서 해당 조문과 출처(`주택임대차보호법_제6조의2.txt, p.1`)를 반영한 플레인 텍스트 초안 재작성 완료.

### 3.4 T-04: 사용자 거절 시나리오
- **조건**: 사용자 거절(`approval_status == 'REJECTED'`).
- **실행 경로**: `statute_search_approval` → `insufficient` → `END`
- **검증 결과**:
  - 외부 API 검색을 절대 호출하지 않음.
  - 현재 보유한 불완전한 근거로 섣불리 단정하지 않고 판단 유보 및 전문가 상담 권고 텍스트를 생성하여 안전 종료.

### 3.5 T-05: 외부 법령 검색 결과 부재
- **조건**: 외부 공인 법령 시스템에서도 해당 조문을 찾지 못한 경우.
- **검증 결과**:
  - `warnings`에 "공식 법령 원문 검색 시스템에서 요청하신 법령의 해당 조문을 찾지 못했습니다." 추가.
  - `statute_search_result_condition`에 의해 `insufficient` 노드로 분기되어 허위 조문 생성을 원천 방지.

### 3.6 T-06: 허위 법령 인용 차단
- **조건**: 답변 초안에 실제 검색되지 않은 `가짜법령.pdf` 또는 임의의 판례 번호 포함.
- **검증 결과**:
  - `audit_citations_and_claims`가 `unverified_citations`로 포착.
  - `citation_existence_rate` 0.0 기록.
  - `sanitize_unverified_citations`에 의해 답변 본문에서 허위 인용이 깨끗이 제거됨.

### 3.7 T-07: Checkpointer 상태 복원 및 Resume
- **조건**: 첫 번째 invoke에서 인터럽트 발생 후, 두 번째 invoke에서 `Command(resume={"approved": True})` 전송.
- **검증 결과**:
  - 1차: `status == "APPROVAL_REQUIRED"`, `__interrupt__` 이벤트 정상 감지.
  - 2차: 그래프가 처음부터 다시 실행되지 않고 중단되었던 `statute_search_approval` 지점에서 정확히 재개되어 `status == "SUCCESS"` 도달.

### 3.8 T-08: 서버 재시작 후 복원 검증
- **조건**: PostgreSQL DB에 승인 대기 레코드 기록 후 세션을 완전히 종료하고 새 세션으로 복원.
- **검증 결과**:
  - `status: "APPROVAL_REQUIRED"`, `candidate_laws: ["주택임대차보호법"]`이 무손실 복원됨.

### 3.9 추가 검증: 법제처 법령 검색 도구 고도화 및 인용 정제 검증 (T-09, T-10, T-11)
- **T-09: 법령명 완전 일치 검증 (`test_search_official_statutes_civil_act_exact_match`)**:
  - 조건: `open.law.go.kr` XML 응답에 `난민법`과 `민법`이 함께 포함된 경우.
  - 검증: `clean_law_name == law.findtext('법령명한글')` 완전 일치 로직을 통해 `난민법` 오매칭을 원천 차단하고 `민법` 본문 및 조문을 정확히 파싱함.
- **T-10: 동적 IR 가중치 및 조문 랭킹 검증 (`test_search_official_statutes_dynamic_missing_issues_boost`)**:
  - 조건: 주택임대차보호법 조문 목록 중 `제3조의4`, `제6조`, `제6조의2` 등이 경쟁할 때, `missing_issues=["묵시적 갱신 후 계약 해지 통보 효력"]` 전달.
  - 검증: 특정 도메인 하드코딩 키워드 없이 대상 법령명(주택, 임대차) 감쇄(0.2x~0.3x) 및 `missing_issues` 토큰(묵시적, 갱신, 해지) 2.0x/15.0x 부스팅을 적용하여 `제6조의2 (묵시적 갱신의 경우 계약의 해지)`가 31.0점으로 1위 랭크 및 검색 결과 최상단에 반환됨.
- **T-11: 이중 괄호 인용 및 정화 검증 (`test_t07_double_parentheses_and_punctuation_clean_citation`)**:
  - 조건: LLM 답변 초안에 `((주택임대차보호법.pdf, p.1))` 형태의 중복 괄호 인용이 생성된 경우.
  - 검증: 개선된 `CITATION_PATTERN` 및 외곽 기호 정제를 통해 `unverified_citations` 오류 없이 정상 매칭(PASS)되며, 허위 인용 치환 시에도 `[근거 미확인])` 등의 괄호 잔여물 없이 깨끗하게 정화됨.

---

## 4. Pytest 실행 통계
```
collected 63 items

backend\tests\unit\test_agentic_adaptive_rag.py .....                    [  7%]
backend\tests\unit\test_aop.py .......                                   [ 19%]
backend\tests\unit\test_deadline_engine.py ....                          [ 25%]
backend\tests\unit\test_hilt_statute_search.py ........                  [ 38%]
backend\tests\unit\test_langfuse.py ...                                  [ 42%]
backend\tests\unit\test_llm_tracking.py ....                             [ 49%]
backend\tests\unit\test_observability_enhanced.py .........              [ 63%]
backend\tests\unit\test_official_statute_search.py .....                 [ 71%]
backend\tests\unit\test_rag_citation_standard.py .......                 [ 82%]
backend\tests\unit\test_top10_audit_fixes.py ...........                 [100%]

======================= 63 passed, 7 warnings in 71.08s =======================
```
기존 52개 테스트에 HILT 및 법령 검색·인용 정제 단위 테스트 11개를 포함하여 총 63개 테스트가 **100% PASS**를 기록하였다.

