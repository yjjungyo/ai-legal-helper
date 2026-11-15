# SC-012 4단계: 법률요건 포섭 감사 구조 설계 및 Gemini 인계

- 작성일 2026-11-15
- 작업 브랜치 `feat/legal-subsumption-audit-sc012-20261115`, 출발 브랜치 `feat/official-precedent-search-sc012-20261115`(3단계 판례 검색)
- **1번 증거 격리·Trace 정합성은 사용자가 직접 실행하므로 수정 범위에서 제외**. 5번 재작성 횟수/루프 최적화 또한 이번 단계 범위 밖.
- 최종 권위는 최신 Python 소스. 과거 SC-012 Trace는 현상·테스트 근거일 뿐.

## 소스 확인 결과
- `document_answer.py::DOCUMENT_ANSWER_SYSTEM`에는 이미 5단계 법률요건 대입 지침이 있다. 다만 본문 문장으로만 남는다.
- `document_verification_prompt.py`에는 4단계 의미 포섭 지침이 있으나 `VerificationOutput`에는 법률효과별 *요건 충족 표*와 *판례 사실차이*에 대응하는 구조화 필드가 없다.
- `verification.py::run_verification`의 P0-VER-01은 법률 핵심 주장 SUPPORTED + 타 결함 없음만으로 REVISE를 PASS로 되돌릴 수 있다. 출처 ID 존재는 적법한 요건 포섭의 증명이 아니다.
- 3단계 `PRECEDENT` Source에는 `court/case_number/decision_date`가 들어오지만 `format_grounding_sources` 프롬프트 메타에는 포함되지 않는다. `prune_sources_for_consultation`은 재작성 시 미인용 판례도 150자로 줄여 법리를 못 읽게 할 위험이 있다.
- `IssueVerifier`의 레거시 개별 규칙은 도메인 한정이며 후속 의미 이슈 `ISSUE_SEMANTIC_* `에 대해 결정적인 증거 포섭을 대신하지 못한다. 규칙 매핑을 늘리는 대신 공통 검증 레이어를 사용한다.

## 4단계 설계 원칙
1. **규범과 사실의 분리**: 사건 주장·주민등록일·계약서와 법령·판시사항은 타입을 섞지 않는다.
2. **사건별 결론 하드코딩 금지**: SC-012/SC-013, 조문번호, 임대차 외 도메인, 특정 날짜·채무액에 따라 법률효과를 조건문으로 결정하지 않는다.
3. **실질 판단은 기존 독립 LLM 검증기의 동일 호출**: 법률 효과의 각 요건·예외·사건 사실·판례 적용 범위를 의미적으로 판단. Python은 출처 ID·원문 인용·구조 완결성·판정 정합성을 확인. 요건의 참/거짓을 regex로 판단하지 않는다.
4. **원문 중심**: 법률 주장, 규범 원문, 승인 사건 문서, 현재 질문의 직접 진술만 신뢰. 과거 답변/사건명/검색어를 결론의 증거로 사용 금지.
5. **법률요건 포섭 체인**: claim(실제 답변의 원문) → effect(구체적 법률효과) → rule_source_ids(실제 STATUTE/PRECEDENT) → requirements(요건·확인 상태·자료) → exceptions(예외 검토) → precedent_analyses(판시 법리와 사건 차이) → conclusion_status.
6. **요건 불명 시 조건부**: 미확인 사실은 충족으로 승격하지 않는다. 답변이 조건을 실제로 밝혔고 규범이 조건부 효과를 뒷받침한다면 CONDITIONAL이 적법할 수 있다. 확정적 결론은 그런 식으로 구제하지 않는다.
7. **Citation != Subsumption**: 실존하는 판례/법령 출처 한 건만으로 요건 검증 완료가 아니다. 공식 판례 서지 정보 역시 적용 가능성 증명의 대체물이 아니다.
8. **불완전 데이터의 FAIL-CLOSED**: `application_checks` 누락·출처가 다른 타입·검증되지 않은 판례·근거 없는 요건·차이 미검토 등은 해당 LEGAL_APPLICATION claim을 UNSUPPORTED로 표시하고 전체 PASS/자동 PASS 승격 차단.
9. **일반 법령 질의/사실 소개 보호**: LEGAL_RULE만 있는 답변, USER_STATEMENT, CASE_FACT, RECOMMENDATION에는 법률요건 포섭 표를 강제하지 않는다.
10. **토큰·지연 통제**: LLM 호출·LangGraph 노드 추가 금지. 핵심 6~8개 중 법률 적용 주장에 한해 압축된 문구/출처 ID/요건 상태 기록. 판례 본문은 재작성 시 온전히 전달(검색이 반환한 상한 내).
11. **단계별 격리**: 법령 temporal 판단·부칙 linked retrieval 변경 금지. 기존 단위 테스트와 CI로 회귀 점검. 5번 루프 변경 없음.

## 데이터 계약(기존 Verifier JSON 선택 필드 기본 [])
`application_checks` 배열, 항목:
- `claim`: 검증 대상 답변의 LEGAL_APPLICATION 원문과 동일.
- `legal_effect`: 주장한 효과. 확정 여부를 미리 가정하지 않는다.
- `rule_source_ids`: 실제 검색된 STATUTE/PRECEDENT 출처 ID 목록.
- `requirements`: 각 `requirement`, `status=MET|NOT_MET|UNKNOWN`, `fact_source_ids`(사건 증거 ID), `fact_quote`(현재 질문에서 인용한 진술 또는 출처 본문 연속 인용), `reason`; MET일 때 검증된 사실 출처 또는 현재 질문의 원문 인용 필수.
- `exception_analysis`: 예외·반대사실 검토 결과. 해당 예외 없으면 그 이유 명시.
- `precedent_analyses`: 인용된 판례 source_id마다 핵심 법리, 사건과 공통의 결정적 사실, 중요한 차이, `applicability=SIMILAR|DISTINGUISHABLE|UNCERTAIN` 및 그 이유.
- `conclusion_status=SUPPORTED|CONDITIONAL|UNSUPPORTED`: 확정 주장이면서 핵심 요건 UNKNOWN/NOT_MET이면 SUPPORTED 금지. CONDITIONAL인 경우 `condition_in_answer`는 실제 답변의 연속 인용문이어야 한다.

**검증 게이트**: `LEGAL_APPLICATION` claim은 정확한 check와 최소 1개 실제 법률 출처·요건 및 예외 검토가 있어야 한다. 판례 출처가 rule_source_ids에 있는 경우 본문이 있는 실제 PRECEDENT인지 확인하고 최소 1개의 precedent_analysis와 출처 참조·비교를 요구. 충족/미충족 결정 자체는 LLM의 의미 검증이 담당한다. 구조가 통과해도 PASS로 승격시키지 않는다.

## 구현 위치
- 신규 `agents/subsumption_audit.py`: 출처·요건·판례 적용·조건부 설명의 교차 참조 감사. 유저가 작성한 법률효과의 참/거짓을 regex로 계산하지 않는 순수 함수.
- `agents/verification.py`: 구조화 `application_checks` 필드 추가 + 기존 LLM 검증 결과 내부에 사후 감사 실행. 누락 시 claim UNSUPPORTED, PASS 및 P0-VER-01 자동 승격 금지. Trace에도 건수/사유 기록.
- `agents/document_verification_prompt.py`: 기존 LLM 호출의 출력에 요건별 구조화 결과 추가.
- `agents/document_answer.py`: 검증 사유를 최초 작성 및 부분 수정에 적용, 판례의 적용 범위·사실차이·예외를 사용자 답변에 간단히 설명.
- `rag/grounding_context.py`: 판례 메타가 verifier까지 전달되도록 확장; 재작성시 판례 본문 다이어트 금지.
- `backend/tests/unit/test_legal_subsumption_audit.py`: 정상/누락/비관련/판례 오적용/조건부/직접 진술/시점/근거 타입과 실제 verifier 통합 검증.
- GitHub CI + 개발보고서 `docs/evaluation/SC012_STEP4_SUBSUMPTION_DEVELOPMENT_REPORT_20261115.md`.

## 완료 기준
- SC-012에 기존 공식 판례 Source가 있더라도 요건/예외/공동임대인·공동상속인의 사실 차이가 검토되지 않으면 PASS 안 됨.
- SC-013에서 근저당/대항요건 선후를 사실 증거와 대조하지 않고 '선순위 임차인'이라고 확정하면 검증 단계에서 포섭 미충족으로 남음.
- 실제 판례 및 법령 없이 법률 결론 통과 불가. 다만 원문에서 근거 확인되고 조건문이 정확한 경우에는 조건부 안내 가능.
- 기존 법령 검색·부칙 시행일·일반 법령 설명·노동/민사 모두 작동, 자동화 통과 내역/잔여 CI 실패를 각각 기록. E2E 실제 사용자 확인 전 '정확도 개선' 또는 SC-012 최종 PASS 선언 금지.
