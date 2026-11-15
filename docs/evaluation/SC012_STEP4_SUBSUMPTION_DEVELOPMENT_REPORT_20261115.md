# AI Legal Helper — 4단계 범용 법률요건 포섭 강화 개발·코드리뷰 보고서

- 작성: 2026-11-15
- 작업 브랜치: `feat/legal-subsumption-audit-sc012-20261115`
- 기준: 3단계 공식 판례 검색 브랜치 `feat/official-precedent-search-sc012-20261115` (Draft PR #31)
- 이번 단계 리뷰: Draft PR #32 `https://github.com/yjjungyo/ai-legal-helper/pull/32`
- 설계·Gemini 인계 문서: `docs/development/SC012_LEGAL_SUBSUMPTION_DESIGN_20261115.md`
- **사용자가 직접 담당하는 1단계 증거 격리/Trace 정합성은 수정하지 않았음. 5단계 재작성 루프 최적화도 아직 미구현.**
- 수행 결과는 소스와 실제 CI 로그 기준. E2E 운영 모델 품질 개선 수치/SC-012 답변 PASS는 현재 주장하지 않음.

## 1. 선행 실패의 원인 (3단계까지의 소스 기준)

### 최초 확인한 원인
1. `document_answer.py`는 5단계 포섭 지침을 이미 포함한다. 하지만 실제 검증 JSON은 법률효과마다 요건·사실 자료·예외·판례 유사성 판단을 구조화해 기록하지 않았다.
2. `verification.py`에는 `P0-VER-01` 자동 PASS 승격이 있어 법령·판례 출처가 존재하고 LLM이 claims를 SUPPORTED라 표시하면, 판례의 사실 차이/법정 요건 검토 누락이 남아도 PASS로 바뀔 가능성이 있었다.
3. `grounding_context.py`는 공식 판례 `court/case_number/decision_date` 메타를 검증 프롬프트에서 생략하고 재작성 시 판례 원문을 150자로 줄일 가능성이 있어, 판례 요건 및 중요한 구별사실을 충분히 비교할 수 없었다.
4. `issue_verifier.py` 일반 쟁점 `else`는 '확인 사실 하나 + 법령 출처 존재'만으로 **`VERIFIED`**를 반환하여, SC-012과 같은 `ISSUE_SEMANTIC_*`에서도 실제 법률요건 포섭 이전에 확정 상태를 만들 수 있었다.

### 핵심 해결 방향
**검색된 판결의 존재 → 법률 규범 요건 → 적용에 필요한 사건 사실 → 예외/반대사실 → 이 사건에 대한 결론**의 증명 경로를 명시적으로 보존한다. 법률 명칭·시나리오 번호·사용자 날짜·금액의 regex/if로 포섭 결과를 계산하지 않는다. 실질적 해석은 독립 LLM Verifier가 수행하고 Python은 각 요소가 실제 Source Registry와 사용자 원문에 연결되었는지를 감사한다.

## 2. 개발 변경 파일

| 파일 | 수행 내용 및 불변 조건 |
|---|---|
| `backend/src/ai_legal_helper/agents/subsumption_audit.py` **신규** | `audit_legal_applications`: 실제 LEGAL_APPLICATION.claim 단위로 검증 원문·규범출처·요건상태·증거 인용·예외·판례 적용 비교의 필드 및 Source 존재성을 검사. 누락한 주장은 PASS 불허. 법률결론의 참/거짓은 regex로 결정하지 않음 |
| `backend/src/ai_legal_helper/agents/document_verification_prompt.py` | 기존 검증기 단일 LLM 출력에 `application_checks` 포함하도록 요건/예외/판례 차이 검토 요청. 일반 법률 설명과 사건 법률효과 분리. JSON 예시의 `{{...}}` LangChain template escaping 적용 |
| `backend/src/ai_legal_helper/agents/verification.py` | Pydantic 하위 호환 `application_checks=[]`, `application_audit={}`. 기존 P0-VER-01 자동 PASS 승격 이전 감사. 포섭 누락 주장만 `UNSUPPORTED`로 강등, 관련 REVISE 지침/Trace 감사 요약 생성. 전반적인 법령 시점/인용 검사 로직은 유지 |
| `backend/src/ai_legal_helper/agents/document_answer.py` | 판시 법리와 현재 사건의 유사·상이한 결정적 사실 및 예외를 실제 답변에 연결하도록 지침 강화. 검증 결과의 구조화 오류를 부분 재작성으로 전달. 신규 LLM 호출 없음 |
| `backend/src/ai_legal_helper/rag/grounding_context.py` | 판례 서지 메타 `court/case_number/decision_date`를 Writer/Verifier에 표시, 판례 텍스트를 재작성 시 스니펫으로 축약하지 않음 |
| `backend/src/ai_legal_helper/agents/issue_verifier.py` | 범용/신규 의미 Issue에서 사실·법령 출처가 모두 있다는 사실만으로 `VERIFIED` 반환 금지. `CONDITIONAL` + `GENERAL_SOURCES_PRESENT_SUBSUMPTION_UNCHECKED`, 이후 통합 Verifier 판단 유도 |
| `backend/tests/unit/test_legal_subsumption_audit.py` **신규** | 원문/출처/요건/사실 누락, 공식판례 요지, 부정적 결론, 조건부, SC-013 경매, 노동법, 기존 LLM 검증 통합 및 템플릿 렌더링 테스트 |
| `.github/workflows/legal-subsumption-regression.yml` **신규** | Python 3.11 py_compile, 구조 포섭·판례·법령·문서·Issue 회귀 검사 |

코드에는 `SUBSUMPTION-01~08` 식별 주석으로 불변식 및 수정 사유를 명시했다.

## 3. 위험 분석과 설계 절충

**정확도**: 판례 사건번호/출처 ID를 찾았다는 이유로 법률효과를 확정할 수 없다. 같은 계약 유형이라도 법적 주체, 상속·당사자 승계, 권리 설정/효력 발생 순위, 예외·경과규정이 다를 수 있다. LLM은 *실질적 규범 해석*을, Python은 *출처 연결 유무*를 맡는다.

**조건부 판단**: UNKNOWN 요건이 있는 사건을 무조건 전면 WITHHELD로 만들지 않는다. 답변에 실제 조건이 명시되고 법률 규범 근거가 연결된 경우 구조적 `CONDITIONAL` 판단을 허용한다. 반대로 UNKNOWN인데 확정 결론을 말하면 포섭 감사에 실패한다. NOT_MET는 법적 효과의 부정 결론을 지지할 수도 있으므로 regex로 모두 부정하지 않는다.

**비용**: 추가 LLM/그래프 노드 없음. 기존 Verifier 응답의 `application_checks` 필드가 늘어 출력 토큰 증가는 가능하다. 기존 장문 판례는 최초 API 수집 한도 내에서만 유지; 입력 토큰 증가 여부는 실제 Langfuse 비교가 필요하다.

**변경 리스크**: 이전에 포섭 체크 없이 SUPPORTED로 검증되던 법률효과 주장은 REVISE될 수 있다. 따라서 실제 모델이 JSON 필드를 안정적으로 생성하는지 사용자 E2E 평가가 필요하다. 출처 검증 없이 기존 PASS를 보존하기 위해 이 검사를 우회하는 것은 금지.

**기존 기능과 관계**: 공식 법령 시점 판정·부칙 재인출·HITL·증거 승인 로직을 바꾸지 않았다. 일반 법령 설명(LEGAL_RULE)은 추가 포섭 감사를 강제하지 않는다. 첫 턴과 후속 쟁점 모두 법률효과가 있는 경우만 해당한다.

## 4. 수행한 CI 및 디버깅 이력

- 첫 CI `https://github.com/yjjungyo/ai-legal-helper/actions/runs/43675277212`: 포섭 신규 검사 자체는 통과했으나, 검증 프롬프트에 도입한 JSON 샘플의 단일 `{`와 `}`가 LangChain 템플릿 변수로 해석되어 여러 기존 문서 상담 검증이 INSUFFICIENT로 종료하는 오류 발견. `8902ab66`에서 템플릿 escape 수정, 별도 렌더링 단위 테스트 추가.
- 템플릿 수정 후 `https://github.com/yjjungyo/ai-legal-helper/actions/runs/43675368546`: **125 passed, 3 failed**. 실패 3개는 변경되지 않은 기존 함수의 안내문구 기대값 2개(`test_verification_prompt_diet.py`)와 Github hosted runner에 필요한 로컬 ChromaDB 민사집행법 인덱스가 없는 환경 의존 테스트 1개(`test_stage2_statute_retrieval.py::test_stage2_local_first_prefetch_civil_execution_act`). 포섭 변경과 별도로 기술적으로 구분한다.
- 일반 IssueVerifier 자동 VERIFIED 승격을 추가 보완한 뒤 `7a04b9c6` CI `https://github.com/yjjungyo/ai-legal-helper/actions/runs/43675613882`: **127 passed, 3 failed** (동일한 기존/환경 문제만 잔존). 모든 신규 포섭 테스트와 기존 문서 상담·판례 검색 연동 테스트는 통과.
- `test_trace_dae222e6_quality_and_latency.py` 과거 PASS 테스트는 가압류를 발견했다는 사용자 진술과 **현재 우선변제권 존속 판단에 필요한 요건 사실**을 구별하도록 보완했다. 현재 점유/주민등록 유지 확인 자료와 `application_checks`를 연결한 조건을 검증했다.
- `test_issue_verification.py`: 일반 `ISSUE_GENERAL_LEGAL`이 출처만으로 `VERIFIED`가 되면 요건 포섭 안전성 위반이다. 실제 규칙에 맞게 CONDITIONAL 기대값을 수정했다.
- `test_evidence_grounding_p3.py`: 개인 사건 사실을 확인하지 않은 임차권등기명령 일반 조문 설명은 `LEGAL_RULE`로 분류. 테스트용 JSON 문자열 안으로 Python 주석이 실수로 포함되어 파싱 오류를 유발했으나 `e7c76bc9`에서 제거해 재검증했다.
- `test_document_answer_prompt_no_case_hardcoding.py`: 근저당이 임차인보다 앞선 질문을 매수인 인수 확정으로 잘못 답한 가짜 PASS 테스트는 정당한 REVISE 판정으로 변경했다. 반면 2023 전입·거주/2025 근저당 사례에는 관련 법령과 실제 선후 사실, 예외를 명시한 포섭 자료를 제공해 PASS가 유지되는지 검증했다.
- 광범위 CI에 이전부터 존재하던 **법령 1건 기대값 오류**를 `test_official_statute_versions_p4.py`에서 정정(`REGRESSION-COMPANION-01`). 현재 공식 법령 소스는 조문에 같은 MST의 부칙을 1+1 동반 검색하므로, 조문과 부칙을 모두 허용하는 것이 정확하며 두 출처 모두 가짜 PDF/페이지를 생성하지 않는지 검사한다. **법령 조회 로직은 변경하지 않았다**.
- 표적 CI 최초의 3가지 기존/환경 실패도 원인별 **테스트 계약만** 정비했다.
  - `test_verification_prompt_diet.py` 2개: 실제 경량화 안내문구인 '초안 미인용 부수 증거'로 기대값 수정. 생산 데이터 축약 로직 변경 없음.
  - `test_stage2_statute_retrieval.py` 1개: 로컬 ChromaDB 설치를 전제하지 않고 모의 Local-First 인덱스를 주입하여 핵심 법령·조문 조회/병합 계약을 검증. 실제 인덱스 연결은 사용자 통합 테스트에서 확인.
- **현재 최종 코드의 CI 결과** (코드 HEAD `ca1f6ee0`, 보고서 갱신 전):
  - <https://github.com/yjjungyo/ai-legal-helper/actions/runs/43676792733> **Legal Subsumption Regression: 130 passed, 2 warnings, 0 deselected** (Python 3.11, 3.30초).
  - <https://github.com/yjjungyo/ai-legal-helper/actions/runs/43676792765> **Official Precedent Search Regression: 107 passed, 2 warnings**.
  - <https://github.com/yjjungyo/ai-legal-helper/actions/runs/43676792696> **Semantic Judgment Safety Regression: 첫 잡 176 passed, 최종 광범위 잡 299 passed / 3 skipped / 2 warnings**.
  - **3개 관련 CI 모두 성공**. 순수 테스트 숫자의 중복은 있으므로 130+107+299를 '총 고유 테스트 수'라고 해석해서는 안 된다.
- 이전 여러 CI 실패는 수정 전 중간 커밋의 실제 결과다. 테스트 성공을 얻기 위해 판례 검색·부칙·법률요건 검증의 보호 장치를 우회하지 않았으며, 모든 보완 내역을 별도 커밋으로 남겼다.
- 실제 법제처 `prec` 운영 API+등록 사건 DB+LLM 통합 상담은 실행하지 않았으므로 **SC-012의 법률 최종 답변 PASS/정답률·호출시간 감소는 미검증**이다.

## 5. 사용자 수동 E2E 검증 항목

1. 브랜치/PR #32의 전체 변경 사항을 확인하고 SC-012 증거 단계는 사용자가 직접 재현한다.
2. 판례 `PRECEDENT` Source의 판시사항·판결요지·법원·선고일·사건번호가 실제 Verifier context에 들어갔는지 확인한다.
3. Verifier의 `application_checks`에 질문에 대한 `LEGAL_APPLICATION.claim`별 `legal_effect, rule_source_ids, requirements, exception_analysis, precedent_analyses, conclusion_status`가 채워졌는지 확인한다.
4. 판례가 공동임대인과 공동상속인 중 누구에게 적용되는지, 상속재산분할의 내부/대외효력 차이를 별도 사실요건으로 구분한 후 법률효과가 결론으로 나타나는지 점검한다.
5. SC-013에서 2021 근저당 / 2023 전입의 시계열을 실제 증거와 대조했는지, 근거 없는 선순위 대항력 결론이 자동 PASS되지 않는지 확인한다.
6. 단순 조문 질문, 정상 분할변제, 임금 체불 등 비임대차 질문이 회귀하지 않는지 확인한다.
7. 실제 Langfuse의 추론 지연/토큰 수/답변 정확도를 비교해 구조화 출력 비용 대비 품질 개선을 분석한다.
8. 근거가 충분하지 않으면 안전하게 REVISE/INSUFFICIENT를 유지한다. 5단계의 반복 재작성 루프 제한은 별도 변경이다.

## 6. Gemini 협업 메모
- 새 필드 구조를 없애서 과거 PASS를 얻도록 '문구만 손질'하는 수정 금지.
- 포섭의 진위 판단을 키워드 및 regex로 이동하지 말 것.
- 답변 결과, 검증 주장, `application_checks`, 관련 판례 Source ID를 서로 다른 계층으로 보존.
- 다음 단계는 **5번 불필요한 재작성 루프 최적화**. 이번 단계와 혼합하지 않음.
