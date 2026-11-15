# SC-012 범용 Issue Planner 2단계 개발·코드리뷰·검증 보고서

- 작성일: 2026-11-15
- 대상 브랜치: `fix/semantic-issue-planner-sc012-20261115`, 기준 main: `f8f497477dedf605dff5e13d3b16eb4a9f7dd6f0`
- 검토 PR: https://github.com/yjjungyo/ai-legal-helper/pull/30 (Draft)
- 개발 설계·Gemini 협업 설명: `docs/development/SC012_SEMANTIC_ISSUE_PLANNER_DESIGN_20261115.md`
- 작업 범위: **2단계**(범용 Issue Planner 개선)만. **1단계 증거 격리·Trace 정합성은 사용자가 직접 처리하기로 하여 이번 브랜치·PR에서 제외**.
- 추가 단계(판례 검색, 법률요건 포섭, 재작성 개선)는 구현하지 않았고, 이 보고서만으로 SC-012 최종 법률 답변의 정확성을 보증하지 않는다.

## 1. 원인 확인

- SC-012 2차 실제 Trace에서 질문은 '공동상속인의 보증금 반환채무가 지분별인지 각자 전액인지'를 묻는다.
- 기존 `issue_planner.py`의 `분할` + `보증금` 범위 없는 키워드 결합은 '상속재산분할'을 임대인의 분할변제 제안으로 잘못 계획한다.
- `반환`만으로 `ISSUE_LEASE_TERMINATION`을 추가하여 계약 만기일 쟁점이 과도하게 끼어든다.
- `legal_workflow.py::run_agents_node`는 사건 제목 자체를 검색어에 붙인다. SC-012 평가 사건명에 정답 표현 '불가분채무'가 들어가 있어 검색 오염 또는 정답 누출이 발생할 수 있다.
- 사건 브리핑과 Trace가 확인해 준 문제이지만, Trace 실행 commit과 최신 main은 다르므로 추론의 최종 기준은 현재 브랜치 소스다.

## 2. 설계 및 실제 변경

### A. 기존 의도 분석 LLM 재사용

**파일** `backend/src/ai_legal_helper/agents/intent_analyzer.py`

- 기존 후속 상담의 Intent Analyzer LLM **1회 호출**에서 의미 기반 `legal_issue_outlines`도 함께 출력하도록 요청.
- 주어진 질문에서 독립적으로 검토할 중립적 법률 쟁점 질문 `question`, 필요한 사실 `required_fact_keys`, 검색·검증 대상 후보 조문 `candidate_statutes`만 추출.
- Pydantic `IntentDecision`에 optional 기본값 `[]` 부여: 기존 LLM 응답과 backwards compatibility.
- JSON 배열/객체 타입·길이·중복·최대 4건을 검증하고 비정상 항목을 제거. 새로운 LLM 호출·그래프 노드 추가 없음.
- 특정 사건명, 판례번호, 상속법 결론을 프롬프트/규칙으로 하드코딩하지 않음.
- 중요한 신뢰 경계: LLM 추론 항목은 *검색 계획 후보*이지 검증된 법률 규범 또는 법적 결론이 아니다.

### B. 중립적 IssueTask 생성

**파일** `backend/src/ai_legal_helper/workflows/issue_planner.py`

- `plan_legal_issues(question, briefing)`의 기존 2인자 호출은 동작 그대로 보존.
- 선택적 `semantic_outlines`, `focus_current_question`, `original_question`을 추가.
- 후속 특정 질문은 구조화된 의미 윤곽으로 IssueTask를 생성. 기존 임대차 반환·분할·경매 등의 광범위 문자열 트리거와 섞어 무관한 Issue를 생성하지 않는다.
- 구조화 LLM 필드가 없을 때는 현재 사용자의 원문을 `ISSUE_CURRENT_QUESTION`으로 우선 보존; 짧은 후속 입력은 문맥 복원 질의로 처리.
- `_match_facts_and_evidences`를 그대로 활용해 의미 쟁점의 fact_id 및 증거 라벨을 연결.
- 위조/미등록 증거 참조 검사는 빠뜨리지 않고 **사용자 원문**에서 수행.
- 후보 조문은 **`candidate_statutes`에 검색 힌트로 전달**하는 동시에 **`required_statutes`에 '실제로 확인해야 할 조문'**으로 명시. 왜냐하면 현재 `issue_verifier.py`는 `required_statutes`만 retrieved_sources와 대조하므로 이 목록이 항상 비어 있으면 모든 의미 기반 Issue에서 법률 근거 검증이 불가능해진다.
- 반드시 `verified_statutes` / `applicable_statutes` / `cited_statutes`는 빈 채로 시작. 외부 검증 없이 LLM 후보를 확정 근거로 승격시키지 않는다.

### C. 워크플로우 연결 및 검색 데이터 정화

**파일** `backend/src/ai_legal_helper/workflows/legal_workflow.py`

- `supervisor_initialize_node`: 이미 존재하는 Intent Analyzer의 `legal_issue_outlines`를 Issue Planner에 전달. 추가 분석 노드 없음.
- Intent Analyzer의 case_hint에는 평가 정답이 섞일 수 있는 **사건 제목 제거**, 사건 분야 메타데이터만 전달.
- `run_agents_node` RAG 쿼리를 **사용자 원문 → 문맥 복원 질의 → 최대 3개 중립적 법률 질문**으로 재구성. **사건 제목은 검색어에서 제거**.
- Source-of-Truth는 승인된 사건 사실과 검증 가능한 법령/판례 원문이다. 사건명·LLM 제안 자체는 법률 출처가 아니다.

## 3. 영향도 및 호환성 코드 리뷰

| 대상 | 영향 | 점검 요점 |
| --- | --- | --- |
| SC-012 2차 후속 상담 | 직접 | '상속재산분할'의 분할변제 오분류 차단, 법률 질문 보존 |
| 기존 정당한 분할반환 질의 | 회귀 주의 | 첫 턴의 기존 `ISSUE_INSTALLMENT_PROPOSAL` 동작 유지, 후속은 의미 분해로 전환 |
| SC-013 경매 | 회귀 주의 | 첫 턴의 경매 분해 규칙 유지, 후속은 대항력 취득 시점에 대한 중립 질문 |
| 노동·일반 채무 | 긍정 영향 | 법률 분야별 하드코딩 없이 동일 스키마 적용 |
| IssueVerifier | 핵심 영향 | `required_statutes`를 비우면 항상 조건부로 떨어지는 결함을 리뷰에서 발견하여 조문 검증 대상을 전달하도록 수정 |
| Retrieval | 직접 | 사건명 검색어 제거, 원문/의도/핵심 쟁점 순서 준수 |
| QA/최종답변 검증 | 변경 없음 | 단순 Issue 개선만으로 검증 실패/성공의 신뢰도는 보장하지 않음 |
| 부칙/시행일 | 변경 없음 | 기존 temporal source 처리 코드 미변경 |
| 1단계 E2E 재현 | 범위 제외 | 사용자가 직접 재현하며 이번 PR에 코드/테스트 포함하지 않음 |

### 주의 및 향후 논의
- 첫 턴에서는 여전히 기존 저비용 키워드 계획(LLM 추가 호출 없음)을 유지한다. **이번 구현의 의미 기반 계획은 후속 질문에 우선 적용**. 첫 턴까지 의미 분석을 확대하려면 지연·토큰 증가를 수치로 비교하고 별도 승인해야 한다.
- 의미 기반 Issue의 법률 후보가 잘못되면 검색 실패·검증 보류가 가능하다. 조문/판례를 실제 검색한 후 법률 요건에 적용하는 3~4단계 개발이 뒤따라야 한다.
- 새 Issue ID는 `ISSUE_SEMANTIC_01` 등으로, 기존 `issue_verifier.py`의 일반 분기에 진입한다. 전문 규칙 기반 자동 결론은 사용하지 않고 원문 법령 확인에 의존한다.

## 4. 테스트 계획과 실행 증거

### 추가 테스트
`backend/tests/unit/test_semantic_issue_planner_sc012.py`

- SC-012 '상속재산분할'이 임대인 분할변제·계약 종료로 바뀌지 않는지.
- 의미분해 누락 시 현재 질문 보존 / 중복·비정상 입력 / 제한된 이슈 개수.
- 실제 분할반환 제안, SC-013 권리 선후 중립성, 노동법 등 비임대차 확장성.
- 가짜 증거 인용 검출 유지.
- 구형 IntentDecision 스키마 호환, 동일 LLM 1회 호출 및 JSON 파싱 안전성.
- 후보 조문만으로 `verified_statutes`를 채우지 않으며, 실제 출처가 없을 때 IssueVerifier는 해당 조문을 미확보로 기록.

### CI 실행
- 신규: `.github/workflows/semantic-issue-planner-regression.yml`: Python 3.11 소스 컴파일, 테스트 파일 및 기존 쟁점·의도 분석 회귀.
- 기존: Conversation Context Regression, Semantic Judgment Safety Regression 및 법령·증거 연계 워크플로우 검사도 PR에서 실행.
- 최초 CI 커밋 `49275f6`: Syntax compile 통과, 새 회귀 포함 **22 passed / 2 failed**, 두 실패 모두 *새 테스트 픽스처에 필수 title 필드를 누락한 작성 실수*. `508926d2`에서 수정.
- 같은 최초 CI의 Semantic Judgment Safety Regression은 **298 passed / 1 failed / 3 skipped**. 남은 오류 `test_official_statute_versions_p4.py::test_undated_legacy_official_xml_no_longer_fabricates_pdf_page`는 변경하지 않은 법령 검색의 *조문+부칙 2건* 반환과 테스트의 *1건 기대* 불일치로, Issue Planner 관련 로직 변경에 직접 원인이 없음을 파일 diff로 확인. 별도 법령 검색 품질 이슈로 추적 필요.
- 수정된 `508926d2`에 대한 Semantic Issue Planner Regression 및 Conversation Context Regression 등 **5개 관련 검사 성공** 확인.
- 새로운 법령 후보가 출처 없이 VERIFIED 되지 않는 검증기 보호 테스트를 1개 추가한 `84f6906`에 대해 **Semantic Issue Planner Regression 25 passed, 2 warnings (Python 3.11, 1.61초)** 확인: https://github.com/yjjungyo/ai-legal-helper/actions/runs/43672392180
- 동일 `84f6906` 커밋의 GitHub Actions 6개 중 **5개 성공**: Semantic Issue Planner Regression, Conversation Context Regression, Temporal RAG P6 HITL workflow, Temporal RAG P7 evidence bundle, Temporal RAG P8 verification.
- **1개 실패 (별도 기존 법령 테스트)**: Semantic Judgment Safety Regression: `1 failed, 298 passed, 3 skipped`. `backend/tests/unit/test_official_statute_versions_p4.py::test_undated_legacy_official_xml_no_longer_fabricates_pdf_page`가 조문 + 부칙 2건 실제 반환에 대해 1건을 기대하여 실패. 이번 PR에서 `official_statute_search.py`, `test_official_statute_versions_p4.py`는 수정하지 않았음. https://github.com/yjjungyo/ai-legal-helper/actions/runs/43672392135
- 그러므로 **이번 변경의 표적 회귀는 PASS, 전체 PR CI는 미완전(5/6)**으로 표기한다. unrelated CI 실패를 숨기거나 본 PR에서 법령 기능 수정으로 섞지 않는다.

## 5. 수동 검증 및 다음 단계

1. PR #30의 최종 CI와 diff를 검토한다.
2. 사용자가 SC-012 2차 질문을 자신의 격리된 증거 상태에서 다시 실행하고 `supervisor_initialize_node.issue_tasks`에 의미 기반 Issue가 있는지 검사한다.
3. 검색 질의에 정답이 들어간 사건 제목 및 임대인 분할변제 제안 질문이 없는지 Trace로 확인.
4. 법령/판례 근거가 부족해 최종 답변이 INSUFFICIENT라면 **이는 2단계의 실패와 동일하지 않다**. 3단계 판례 검색 파이프라인에서 후속 개선해야 한다.
5. 성능 KPI(LLM 호출·토큰·지연), 답변 품질 최종 통과 여부는 실제 통합 재현 후 기록한다.

본 변경은 Draft PR로 유지하며 사용자 요청 전 main에 병합하지 않는다. Gemini는 코드 주석 ISSUE-SEMANTIC-01~06, 설계서, 이 보고서 및 PR diff를 순서대로 확인할 것.
