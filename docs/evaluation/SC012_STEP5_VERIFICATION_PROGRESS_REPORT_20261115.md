# SC-012 5단계: 검증·검색·재작성 무진전 루프 최적화 개발·영향도·코드리뷰 보고서

- 작성일: 2026-11-15
- 기준: 4단계 `feat/legal-subsumption-audit-sc012-20261115` (PR #32)
- 개발: `feat/verification-progress-stop-sc012-20261115`, Draft PR #33
- 설계/Gemini 인계: `docs/development/SC012_STEP5_VERIFICATION_PROGRESS_DESIGN_20261115.md`
- 소스코드 기준 분석. 2026-11-15 SC-012 Trace는 재현 테스트의 출발점이며 최종 원인은 코드로 확인한다.
- 사용자가 직접 처리 중인 1번 증거 격리 및 사건 원문 상태 관리 로직은 본 단계에서 변경하지 않음.

## 1. 소스에서 확인한 반복의 원인

1. `document_consultation.next_verification_step`은 검증 실패가 실제로 개선되는지 확인하지 않고 `revision_count < 3`이면 계속 재작성했다. 검색 자체는 `pending_searches`로 보호되지만, 승인 가능한 새 검색이 없을 때 비슷한 답변을 여러 번 재작성할 수 있었다.
2. `legal_workflow.statute_search_result_condition`의 POST_VERIFICATION 분기는 법령 조회 결과가 0건이라도 `NOT_FOUND/PARTIAL_SUCCESS` 상태에서 재분석으로 보냈다. 같은 조문/판례가 반복 반환되어 `statute_search_results`가 비지 않았을 때도 새 출처인지 구별하지 않았다.
3. `revise_node` → `verification_node` 직접 엣지 때문에 수정 모델이 원본 초안을 그대로 돌려줘도 기존 검증 LLM이 다시 호출됐다.
4. 3단계 판례 검색 및 4단계 법률요건 포섭 덕분에 1회 검증의 내용은 더 엄격해졌다. 잘못된 답변을 검증 없이 성공 처리해서 비용을 아끼는 것은 해법이 아니다.

## 2. 설계 원칙

- **진전의 객관적 지표만 확인**: 새 법령·판례가 원문 Source Registry에 추가됐는지, 초안이 실제로 달라졌는지, 검증기에서 실패하는 법률·사건 주장의 상태가 달라졌는지 판단.
- **법률적 의미 판정은 유지**: 상속/경매/시행일/시간 순위에 대한 regex·조건문 정답 판정 추가 없음. LLM Verification의 의미 분석과 4단계 `application_checks` 유지.
- **HITL 우선**: 신규 허가 가능한 법령·판례 요청이 있으면 중복 결함 때문에 검색을 생략하지 않음. 승인 거절 시 외부 호출 우회 금지.
- **동일 검증 결과 재사용 최소 요건**: 답변 SHA256, 질문 원문+복원 문맥, 원문 출처 매니페스트 SHA256·건수, 검토 기준일, 질문 전체 검증 여부 일치 + 승인 문서 DB 스냅샷 유지 + 기존 검증 결과 SHA256 일치.
- **캐시 금지 항목**: 기술 검증 실패, 명시적 Temporal 의미 재심사, 실제 적용시점 충돌, 공식 법령 API 장애, 새로운 법령·판례/증거/질문 원문.
- **안전 종료**: 반복 결함이 발견되면 추가 LLM 없이 기존 `finish_answer`로 이동해 원문·출처·상충·시점·법률효과 검사를 재통과할 때만 부분 안내. 치명적 법률 오류가 남으면 WITHHELD. 검증 REVISE를 PASS로 임의 승격 금지.
- **추가 LLM 호출 0회**. 해시 비교와 상태전이만 변경. E2E의 실제 지연·토큰 절감률은 Langfuse로 측정해야 한다.

## 3. 개발 파일과 코드 리뷰

| 파일 | 수정 기능 | 영향도 및 보전 사항 |
|---|---|---|
| `workflows/verification_progress.py` (신규) | `added_legal_source_ids`, `verification_input_hash`, `verification_defect_signature`, `can_reuse_verification` | 법리 판단하지 않는 구조 지표/SHA256 검증; 출처 원문은 상태에 중복 저장 금지 |
| `workflows/state.py` | 진행 이력·무진전 플래그·실제 신규 출처수 필드 선언 | LangGraph Checkpointer에 필드 보존, HITL 재개 뒤 상태 정상 전달 |
| `workflows/legal_workflow.py` | 초기 턴 진행 이력 리셋; 공식 검색 실행 후 추가 `STATUTE/PRECEDENT` 출처 ID 계산; POST_VERIFICATION 검색 무진전이면 ReAnalyze 생략 | 기존 PRE_ANALYSIS 검색 유지; 새 공식 원문 확보 시 재분석/검증 그대로 수행; 신규 `execute_statute_search→finalize` 안전 엣지 등록 |
| `workflows/document_consultation.py` | 재작성 결과 및 출처 Manifest 불변 판정; 조건부 검증 결과 재사용; 동일 구조 결함 재발시 재작성 한도 이전 조기 종료 | 검증 LLM 신규 호출 없음; DB 승인 스냅샷/질문/원문 불변 검사; 동일 법리 오류의 무한 반복을 막되 새로운 검색 우선 |
| `backend/tests/unit/test_step5_verification_progress.py` (신규) | 정상·반례 재현, API/Source Registry 변경, 캐시 안전, HITL, Temporal, 진전 지표, 실제 노드 통합 | 실제 코드 대신 Mock을 사용하며 최종 법률 정확도 입증으로 해석하지 않음 |
| `.github/workflows/verification-progress-regression.yml` (신규) | 기존 2·3·4단계 및 법령·부칙·판례·문서 상담 회귀 실행 | 부칙/시행일 검증 해제 없이 기존 정상 동작 확보 |

핵심 주석: `STEP5-PROGRESS-01~09`, `STEP5-TEST-01~02`.

## 4. 코드 영향도 검토

### 상담 품질
- **개선되는 경우**: 1회 검증과 재작성 후 LLM이 초안을 바꾸지 않거나, 문구만 달라지고 법률요건/출처 불일치가 동일하거나, API가 이미 검색된 판례를 반복 반환하는 경우.
- **보존되는 경우**: 새 판례/부칙/법령을 얻었다면 `search_delta_count > 0`, 반드시 기존 작성기로 재분석하고 독립 검증기로 확인. 법령 적용 시점이 변하거나 검증이 기술 오류로 끝나면 캐시 금지.
- **주의 사항**: 검색 실패 후 이미 존재하는 출처만 이용한 답변을 더 알기 쉽게 바꾸는 기능은 일부 축소될 수 있다. 기존 검증된 부분만 남기는 safe finalization과 실제 E2E 재현으로 확인이 필요하다. 불확실한 판단을 정확하다며 전달하는 우회 방법은 채택하지 않았다.

### 성능
- 변경된 무진전 경로에서 필요 없던 **재분석 1회**와 동일 입력 **검증 1회**까지 차단할 수 있다. 단 두 경로를 동일 상담에서 모두 소비했다면 중복 계산을 피해야 한다.
- 법령/판례 원문 검색 결과가 실제 신규 1건 이상인 경로에서는 해당 검증 호출을 절감하지 않는다.
- LangGraph 노드 추가 없음. SQL DB, 법령 임베딩, 법제처 API 요청 횟수/승인 정책 변경 없음.

### 기존 상담 상태 및 안전
- 신규 상담 시작 시 `verification_progress_history=[]`, 나머지 진행 플래그 초기화. 세션의 과거 검증을 이번 질문에 재사용하지 않음.
- `verify_answer`가 모든 승인 문서의 상태·해시를 다시 확인하고 Source Manifest를 기존 Writer와 비교한 후에만 검증 결과 재사용. 출처 ID·본문이 달라지면 불일치로 차단.
- `finish_answer`는 여전히 검증 응답 해시, 출처 목록 및 법률 주장 상태/Temporal BLOCK을 최종 확인한다. PASS 승격 자동화 코드를 추가하지 않음.
- 공식 검색이 실패한 경우 원문이 확보되지 않았는데도 판례가 있다고 꾸미거나 조건 충족으로 강등하는 코드 없음.

## 5. 테스트 단계 및 발견 오류

- 1차 CI `https://github.com/yjjungyo/ai-legal-helper/actions/runs/43677795891`: **175 passed, 4 failed**. 새 검증 캐시 테스트 픽스처가 승인 사건 증거를 실제 `case_evidence_briefing.source_documents`가 아니라 일반 `retrieved_sources`에 넣어 Writer/Verifier source manifest가 불일치. **운영 코드 문제가 아닌 모의 자료 구성 오류**로 확인.
- `STEP5-TEST-01`: 위 fixture를 승인된 문서로 작성하고 `document_sources`를 통해 검증기와 동일한 원문 Manifest를 생성하도록 수정. 2차 CI `https://github.com/yjjungyo/ai-legal-helper/actions/runs/43677937317`: **179 passed, 2 warnings, 0 failures**.
- 추가 `STEP5-TEST-02`: `execute_statute_search_node` Mock 통합에서 신규 법령·판례/중복 API 응답의 `search_delta_count` 및 후속 그래프 분기를 직접 확인. 모두 성공.
- **최종 코드 HEAD `9f46630b`(이후 보고서 커밋만 추가)의 GitHub Actions 5개 전부 통과**:
  - `Verification Progress Regression`: **182 passed / 2 warnings, 0 failed** — <https://github.com/yjjungyo/ai-legal-helper/actions/runs/43678020867>.
  - `Official Precedent Search Regression`: **107 passed / 2 warnings** — <https://github.com/yjjungyo/ai-legal-helper/actions/runs/43678020782>.
  - `Conversation Context Regression`: **46 passed / 2 warnings** — <https://github.com/yjjungyo/ai-legal-helper/actions/runs/43678020924>.
  - `Semantic Issue Planner Regression`: **25 passed / 2 warnings** — <https://github.com/yjjungyo/ai-legal-helper/actions/runs/43678020763>.
  - `Semantic Judgment Safety Regression`: **176 passed (첫 잡); 299 passed / 3 skipped / 2 warnings (광범위 잡)** — <https://github.com/yjjungyo/ai-legal-helper/actions/runs/43678020759>.
- CI 간 테스트 중복이 있으므로 `182+107+46+25+299`를 고유 테스트 총수로 오인하지 않는다. 3개의 스킵은 전체 법률 안전성 잡의 기존 스킵이며 5번 신규 테스트 제외가 아니다.
- **추가 LLM 호출 도입 0회.** Mock 결과에서는 (a) 동일 원문 재작성 시 2번째 검증기 호출 방지, (b) 공식 검색의 신규 법률 출처 0건 시 `re_analyze` 분기 제거, (c) 서로 다른 질의·증거·검토일·새 조문·판례가 추가되는 반례에서는 캐시 금지와 필수 재분석 유지 확인.
- 시간·토큰 절감 수치 및 SC-012/013 답변 정답률은 실운영 LLM+법제처 API E2E/동일 시나리오 비교 전 **미측정**. CI 숫자를 정답률 또는 비용 절감률이라고 해석하면 안 된다.

## 6. 수동 E2E 확인 항목

1. SC-012 원문 사실과 상속인 정보가 포함된 질문/자료를 그대로 등록하고 1단계 사용자 처리 결과를 사용한다.
2. 동일 판례 검색어가 반복되었을 때 Source ID 새 출처가 0이면 재분석하지 않는지 Langfuse 확인.
3. 새 판례 1개 이상 추가한 경우 `re_analyze→verification`이 반드시 다시 실행되고 4단계의 `application_checks`가 남는지 확인.
4. 법률요건 정보 추가 없이 같은 오류로 재작성될 때 `verification_no_progress`와 실제 재작성 횟수 비교.
5. 검색 없는 답변 재작성 초안이 동일할 경우 검증 호출 생략, 문서/질문 변경 시 재검증하는지 확인.
6. SC-013 근저당/전입 날짜를 잘못 적용한 답변이 똑같은 검증 상태를 반복해도 최종 PASS 처리되지 않는지 확인.
7. 법령 부칙 시행일의 적용 대상·적용례와 실제 사건 기준일이 다르면 임의 PASS 및 캐시를 차단하는지 확인.
8. baseline vs step5 평균/95p 응답 시간, 입력·출력 토큰, 법률 적합성 및 WITHHELD 빈도를 **동일한 시나리오·출처 버전** 기준으로 비교.

## 7. 다음 단계
- 최종 GitHub Actions 결과에 따른 코드리뷰/테스트 수정.
- 사용자가 수행하는 SC-012/013 E2E 이후 Langfuse에서 품질과 토큰·지연 개선 수치 확정.
- 1번 증거 원문 격리(사용자 처리) 및 이전 변경 PR #31/#32의 순차 병합 검토는 별도.


## 8. 조기 종료에 따른 최종 답변 안전장치 보강 (추가 코드리뷰)

- 기존 `finish_answer`는 `status=REVISE`여도 다른 주장이 SUPPORTED이면 일부 경우 CAUTIONARY로 보존한다. 5단계 검색·재작성 조기 종료로 해당 분기가 더 자주 실행될 가능성이 있어 **단순 주장 존재 여부뿐 아니라 검증된 전체 질문의 충족 여부를 필수로 확인**해야 한다.
- `STEP5-FINAL-01 / Gemini`: 아래 명시적 미해결 문제가 하나라도 있으면 부분 답변 PASS 승격을 차단:
  - 질문별 `question_coverage[].answered=false`이면서 실제 답변에 제한 사항이 기재되지 않음
  - 검증기가 요구한 Full Coverage 목록 자체가 없거나, `consistency_checks`의 필수 4개 검사(결론·시간선·의사표시·출처)가 빠짐/실패함
  - 4단계 `application_audit.failed_claims` 또는 `findings` 존재
  - 유효하지 않은 판례/법령/사건 인용 또는 `CASE_FACT/CASE_INFERENCE`의 UNSUPPORTED 주장
- `STEP5-FINAL-02 / Gemini`: `verify_answer`가 현재 질문이 엄격한 전 질문 Coverage 검증을 요구했는지 `required_question_coverage`에 명시. 후속 행동 안내 등 기존 축소 검증 경로에는 불필요하게 전체 4개 일관성 검사를 강제하지 않는다.
- 중요한 반대 사례: 답변에서 조건·법률 근거 부재를 **실제로 명시**하고 해당 질문이 `answerable=false, limitation_disclosed=true`로 검증된 경우 기존 조건부 답변은 CAUTIONARY로 계속 허용.
- 새 회귀 테스트: `test_early_finalize_*` (질문 미응답, 질문 coverage 목록 통째 누락, 일관성 검증 누락, 판례/법률요건 포섭 누락, 허위 인용, 미입증 사실, 안전한 조건부 답변 보존).
- 이 방어선은 결함이 있는 초안을 사용자가 받지 않도록 하는 **전달 단계 보호**일 뿐, 결함을 `PASS`로 바꾸거나 법률의 진위를 regex로 결정하지 않는다.
