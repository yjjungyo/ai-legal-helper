# AI Legal Helper — 대화맥락 의미 복원 및 후속 상담 안전성 개선

- 작업일: 2026-11-15
- 기준: `main` / `65977b3243c5fedfee84954fc12c983571b86929`
- 작업 브랜치: `fix/semantic-conversation-context-20261115`
- 검토 PR: https://github.com/yjjungyo/ai-legal-helper/pull/29
- **상태: 병합 전 검증 단계 — 실제 E2E/성능 목표 확인 전 완료 처리 금지**

## 1. 근본 원인 (현행 소스 확인)

1. `legal_workflow.py`의 `_is_short_followup_request`, `_extract_proposal_from_answer`, `_resolve_multi_turn_task`가 후속 요청을 표현 목록, 말미 따옴표, 체크리스트 명사구로 강제 재작성. 임의 작업 생성·날짜 오해 가능.
2. `supervisor_initialize_node`의 `elif is_followup` 분기가 사건 브리핑/승인 증거 및 `issue_tasks`를 조회하는 `else`를 건너뜀. 후속 법률 분석에서 오히려 사건 사실 누락 가능.
3. 이전 답변 결론 150~250자 요약에서 사용자에게 제안한 **말미 작업**이 사라질 수 있음.
4. `messages`, `case_context`, `last_answer`에 같은 대화가 중복 전파. 이전 AI의 답변이 현재 사실/법령의 권위 있는 출처로 오용될 우려.
5. `analyze_consultation_intent(use_llm=True)`가 이미 있지만 운영 그래프의 `supervisor_initialize`에서 사용하지 않고 표현 기반 임시 함수를 추가했음.

## 2. 변경사항과 책임

| 파일 | 변경 | 품질 영향·안전대책 |
|---|---|---|
| `workflows/legal_workflow.py` | 표현별 후속 요청 함수/정규식/날짜 복원 삭제 | 사용자 `question` 불변, `resolved_query` 별도 유지 |
| `workflows/legal_workflow.py` | 후속 턴에 기존 `analyze_consultation_intent(use_llm=True)` 통합 | 새 노드 없이 의도+분야+참조 쟁점을 한 번에 해석, Router는 기존 분류 사용 |
| `workflows/legal_workflow.py` | 후속 사건상담의 증거 브리핑·쟁점 계획 재조회 | 최신 승인 원문/타임라인 재적용, 일반 법령 설명에는 불필요한 증거 로딩 회피 |
| `workflows/legal_workflow.py` | 이전 법령 인용을 `retrieved_sources`에 자동 승계하지 않음 | 이전 시행본·시점에 관한 오판 방지. 현재 검색 결과를 재검증 |
| `workflows/conversation_context.py` | `format_context_for_resolution` 추가 | 이전 3턴의 질문/결론+직전 답변 말미를 최대 3,200자로 제한; 인용이 아닌 참조 문맥 |
| `agents/intent_analyzer.py` | 제안 수락/새 쟁점/모호한 지시어를 LLM으로 판별 | 제안이 없으면 임의 작업 생성 금지. 후속 요청에서 법률 검색을 금지하던 분야 단어 규칙 제거 |
| `tests/unit/test_multi_turn_followup_resolution.py` | 정규식 함수 자체를 테스트하던 항목을 의미 복원 및 사건 증거 재조회 테스트로 교체 | 단문 수락, 독립 질문, 제안 없는 수락, WITHHELD, 사례 증거 조회 등 회귀 |
| `.github/workflows/conversation-context-regression.yml` | 변경 파일 문법 검사 및 관련 Pytest 자동 실행 | 병합 전 CI 확인 |

## 3. 실행 시 데이터 흐름

1. 원문 질문 `question`과 사건별 `ConversationContext` 확보
2. 이전 대화 없는 경우 기존 첫 질문 경로; 이전 대화 있는 경우 실제 직전 응답 말미와 최근 턴을 소형 컨텍스트로 의미 복원
3. `IntentDecision`의 의도, `resolved_query`, 분야, 사건 기반 모드, 시간 정보 획득
4. CASE_EVIDENCE인 경우 후속 요청 여부와 관계없이 현재 DB의 승인 원문 및 쟁점 목록 조회
5. 검색/전문분석/작성/검증은 원문 질문과 복원된 작업 목표를 구별하여 사용
6. 이전 AI 결론·인용은 확정된 법률 근거로 자동 승계하지 않음

## 4. 회귀 시나리오

- 직전 AI의 특정 제안을 수락하는 `그래 해줘` / `그렇게 해주세요`
- 제안이 없는 상태의 `네` — 임의 작업 생성 금지
- 이전 법률 주제와 무관한 독립 질문 — 이전 체크리스트 승계 금지
- `그럼 지금 이사해도 돼?` — 최신 사건 증거 로딩과 핵심 쟁점 계획
- 사실관계 정정, 등록 증거 추가, 이전 상담 `WITHHELD` 상태
- 연속 3턴에서 직전 작업의 재지시, 이전 법령 시행본 재검증
- E2E V6 SC-011~020 전반의 완주/시간/입력 토큰/검증 상태 회귀 비교

## 5. 영향과 남은 검증

- **정확도:** 임의 작업 생성 및 후속 질문의 사건 증거 누락 위험을 줄이도록 설계. 정량 향상은 검증 전 수치 주장 금지.
- **지연/비용:** 2턴 이후 의도 분석 LLM 1회가 추가된다. 대신 별도 Router 호출을 가능한 경우 생략. 실제 트레이스에서 비용·지연 측정 필요.
- **토큰:** 사건 맥락에 대화 답변을 이중 주입하지 않고, 의미 복원 입력을 3,200자로 제한. 전체 토큰 절감률은 별도 측정 필요.
- **유효성:** `event_date`는 후속 턴의 LLM 의미 판단 결과를 사용하고 법령 공포일/계약일 혼동을 금지. 실제 시행본 적용 판단은 기존 검증 단계 유지.
- **추가 확인:** 현재는 답변 말미를 의미 복원용으로 전송한다. 향후 제안 자체를 구조화해 저장하면 더 안전하나, DB 스키마 변경은 이번 PR에 포함하지 않는다.
- **전용 CI:** Conversation Context Regression의 Python 문법 검사 및 대화맥락·적응형 그래프·의도분석 테스트 통과(검증 커밋 `1956a16a`). 후속 커밋에도 동일 자동검증을 연결함.
- **관련 CI:** Temporal RAG P6/P7/P8 실행 PASS(검증 커밋 `1956a16a`).
- **전체 Safety CI:** 변경 전 초기 PR 실행에서 4건 실패 중 의도 분석기 `test_followup_action_promoted_when_evidence_synthesis_requested` 1건은 후속 안전 가드로 해결. 검증 커밋 `1956a16a` 기준 296 passed, 3 skipped, **3 failed**. 아래 3건은 본 PR에서 수정하지 않은 법령/문서 검증 경로에서 발생했으며 별도 원인 확인이 필요하다(기존 main의 동일 테스트 실패 여부는 미확인).
  1. `test_official_statute_versions_p4.py::test_undated_legacy_official_xml_no_longer_fabricates_pdf_page` — 예상 출처 수 1건, 실제 2건(부칙 포함)
  2. `test_document_answer_prompt_no_case_hardcoding.py::test_verification_demotes_llm_pass_when_qa_check_fails` — 예상 REVISE, 실제 PASS
  3. `test_document_answer_prompt_no_case_hardcoding.py::test_grounding_context_preserves_deep_counter_evidence_beyond_1500_chars_and_arbitrary_filename` — 장문 반대증거 구간 발췌 누락
- **실제 E2E:** 연결된 Azure LLM·법제처 API·사건 PostgreSQL·Langfuse 환경에서의 실통합 검증은 수행하지 않음. 통과로 기록하지 말 것.

## 6. 병합 기준

CI의 문법/단위/회귀 테스트 PASS, 최소 3턴의 실제 단문 수락 및 새 증거가 포함된 후속 사건상담 E2E PASS, 이전 E2E V6 대비 법률 정확성 저하 없음 및 입력 토큰/지연 영향 파악 후 병합한다.
