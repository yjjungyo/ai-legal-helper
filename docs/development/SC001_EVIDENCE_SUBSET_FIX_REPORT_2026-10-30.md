# SC-001 증거 일부 등록 단계 상담 오류 수정 보고서

- 작성일: 2026-10-30
- 범위: E01~E03 기초 자료 분석에서 발생한 의도 오분류·종료 오판·최종 답변 조립·출처 표시
- 상태: 코드 수정 및 격리 회귀 검증. 실제 Azure 상담 전체 경로 검증과 구분한다.
- 분석 근거: [읽기 전용 검토 보고서](../evaluation/SC001_E01_E03_RESPONSE_FAILURE_REVIEW_2026-10-30.md)

## 1. 수정 결과

등록 자료 분석 요청에서 ‘입금’이라는 단어만으로 임대인의 일부 반환 진술을 만들던 경로를 차단했다. 계약서의 일반 반환 조항과 최초 약정 기간 만료를 실제 계약 종료의 입증으로 사용하지 않게 했다. 최종 답변은 검증된 종료 사유를 유지하고, 미확인 상황에서 소송·임차권등기·지연손해금 이율을 새로 생성하지 않는다.

기초 자료 분석은 당사자·목적물·계약기간·보증금·지급·입주·전입·확정일자 항목을 우선 정리한다. 현재 상태에 관한 당사자 진술과 원본·갱신·통지·실제 반환 내역의 확인 필요성을 별도로 보여준다. 증거 공백 레코드가 없다는 이유로 자료가 충분하다고 출력하지 않는다.

## 2. 주요 변경

| 파일 | 변경 |
|---|---|
| `backend/src/ai_legal_helper/case_intelligence/consultation_semantics.py` | 자료 검토 요청, 방향이 확인되는 실제 반환 진술, 일반 의무·조건·예정·부정 문장을 구분하는 공통 규칙 추가 |
| `backend/src/ai_legal_helper/agents/intent_analyzer.py` | 후속 턴에도 자료 검토 요청은 새 분석으로 처리. LLM이 원질문을 일부 변제 주장으로 잘못 재작성한 경우 교정 |
| `backend/src/ai_legal_helper/case_intelligence/settlement_calculator.py` | 갱신 상태 UNKNOWN / IMPLICIT_RENEWAL / NOT_RENEWED 구분. 기존 불리언은 호환을 위해 유지 |
| `backend/src/ai_legal_helper/agents/issue_verifier.py` | 일반 계약 조항·최초 만기·발송 완료를 실제 종료와 구분. 효력일 미확인 시 확정 차단. 통지 도달과 종료·이행기 판단 분리 |
| `backend/src/ai_legal_helper/workflows/final_disposition.py` | 원질문만으로 사용자 변동 진술 판별. 검증된 권고 재사용. 기본 소송·이율 안내 제거. 사실 항목별 커버리지, 미확인 진술·원본 확인 표시, 검증 의견 충돌 시 종료 판단 조건부 조정 |
| `backend/src/ai_legal_helper/workflows/legal_workflow.py` | 쟁점 없는 기초 분석에서도 위험 초안 재노출 방지. 전체 초안 PASS가 쟁점 미확인을 덮지 않게 처리. 조정된 쟁점 상태를 응답에도 반영 |
| `frontend/src/components/LegalAnswerView.tsx` | 빈 문서명이 다른 증거에 부분 일치하여 잘못 연결되는 조건 차단 |

의도 분석 로그에서는 상담 원문 일부 대신 의도·길이만 기록한다. 계산상 지급·반환 차액은 계속 표시하되 현재 청구권·이행기 확정과 구분한다.

출처 목록은 `파일명 [증거번호] (형식)`으로 출력한다. 파일명이 인용 버튼 밖의 일반 텍스트에도 남아 버튼 복사 동작에 의존하지 않는다. 기존에 사용자가 복사한 `(TXT)` 표시의 정확한 발생 경로를 실서비스에서 재현한 것은 아니다.

## 3. 회귀 검증

신규 백엔드 테스트: `backend/tests/unit/test_evidence_subset_consultation.py`.

- 대화 유무와 무관한 자료 분석 의도 보존, LLM 재작성 오류 교정.
- 최초 지급·반환 방향 미상·질문·부정 진술에서 허위 일부 반환 진술 미생성.
- 실제 일부 반환 및 날짜가 포함된 반환 진술의 잠정 계산 유지.
- 일반 반환 조항, 최초 기간 경과, 부정 문장, 해지 통고 발송 완료만으로 종료 VERIFIED 금지.
- 당사자·계약기간·지급·전입·확정일자 및 미확인 진술 표시.
- 검증된 종료 원인 유지, 검증 쟁점 0건에서 자동 소송 안내 미생성.
- 통지 도달만 확인되고 갱신 경위가 없을 때 종료 효과 미확정.
- 실제 `finalize_node`와 조립기를 연결하여 PASS·빈 쟁점에도 위험 초안 미노출 및 품질 상태 보존.

신규 프런트 테스트: `frontend/tests/legal-answer-view.test.cjs`.

- 실제 TSX 인용 렌더러를 메모리에서 변환·실행하여 빈 이름 증거의 오연결 차단 확인.
- 실제 React 렌더링 결과에서 인용 버튼을 제외해도 세 파일명이 남는지 확인.

기존 테스트의 안전 기준도 갱신했다. 정상 종료를 검증하는 양성 fixture는 단순 발송 완료가 아니라 실제 도달·비갱신·종료가 입증된 사례로 명확히 했다. 조건부 검증 의견을 강제 확정으로 치환하거나 검증 결과 없이 고정 절차를 요구하던 기대값은 제거했다. 출처 중복 검사 및 실제 검증 권고 개수 제한은 유지했다. 증거 원본·평가자 자료·Gold 데이터는 변경하지 않았다.

### 실행 명령

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
backend/.venv/Scripts/python.exe -m pytest backend/tests/unit/test_evidence_subset_consultation.py backend/tests/unit/test_issue_verification.py backend/tests/unit/test_p0_recovery_gate1.py backend/tests/unit/test_p0_recovery_gate2.py backend/tests/unit/test_p0_recovery_gate3.py backend/tests/unit/test_case_independence_counterexamples.py backend/tests/unit/test_intent_analyzer.py backend/tests/unit/test_multi_turn_dynamic_case_p0_3.py backend/tests/unit/test_p0_final_disposition_defects.py -q -p no:cacheprovider
```

```powershell
# frontend 디렉터리에서 실행
node --test tests/legal-answer-view.test.cjs
npm.cmd run build
```

검증 결과 수치는 아래 최종 점검에 기록한다. 프런트 빌드에는 500 kB 초과 번들 경고가 있으며 빌드는 성공했다. PowerShell의 npm.ps1 실행 정책 제약은 npm.cmd로 실행하여 해결했고 시스템 정책은 변경하지 않았다.

## 4. 기존 전체 스위트 실패의 분리

전체 단위 테스트를 확장 실행했을 때 추가 실패를 발견해 관련 기대값과 실제 변경을 점검했다. 다음 7건은 수정 전 HEAD의 제품 소스를 별도 임시 디렉터리에 복사하여 실행해도 실패했다. 작업 중인 소스를 되돌리거나 기존 테스트를 삭제·skip 처리하지 않았다.

| 기존 실패 테스트 | 확인 범위 |
|---|---|
| `test_hilt_statute_search.py::test_t07_checkpointer_state_persistence_and_resume` | 실제 라우터 LLM 연결에 의존하며 현재 네트워크 제약에서 ERROR 반환 |
| `test_official_statute_search.py::test_search_official_statutes_real_api_housing_lease` | 실제 외부 법령 API 의존. HEAD에서도 실패 |
| `test_official_statute_search.py::test_search_official_statutes_civil_act_exact_match` | 실제 외부 법령 API 의존. HEAD에서도 실패 |
| `test_official_statute_search.py::test_search_official_statutes_dynamic_missing_issues_boost` | 실제 외부 법령 API 의존. HEAD에서도 실패 |
| `test_p0_ver_01_regression.py::test_p0_ver_01_statute_query_verification_pass` | 실제 LLM 연결에 의존. HEAD에서도 실패 |
| `test_polling_trace_filtering.py::test_polling_consultation_skips_langfuse_and_info_log` | 기대한 DEBUG 로그 호출 수와 실제 동작 불일치. HEAD에서도 실패 |
| `test_rag_citation_standard.py::test_t03_existing_document_but_unsupported_claim_fails` | 무관한 문서에 대한 인용 거절 기대값 미충족. HEAD에서도 실패 |

마지막 인용 검사 실패는 기존 제품의 별도 잔여 결함이다. 이번 수정이 전체 인용 검사의 법률 정확성까지 해결했다고 보고하지 않는다. 위 7건을 명령의 `-k`로 제외한 확장 회귀도 별도로 실행하며 전체 무조건 PASS와 구분한다.

## 5. 적용 및 한계

- 기존에 저장된 잘못된 답변·추출 사실은 소급 수정하지 않았다. 백엔드의 변경 코드 로드 후 새 상담 응답부터 생성 로직이 적용된다.
- 실제 사용자의 case_id·conversation_id에 저장된 추출 Fact와 최신 Azure 응답은 조회·재실행하지 않았다. 현재 환경의 외부 연결 제약과 별개로 실제 서비스에서 E01~E03만 연결된 새 요청의 trace 확인이 필요하다.
- 새로 추가한 진술 판별은 보수적인 규칙이다. 다양한 표현에서 미분류가 생길 수 있으며 지급 방향이 불명확하면 사실을 만들어내기보다 추가 확인해야 한다.
- 법률 명제와 사건 사실을 구분하는 이번 방어가 모든 법률 포섭 오류를 제거하는 것은 아니다. 기존 인용 검사 잔여 결함과 실제 문서 추출 품질은 별도 한계다.
- 신규 외부 패키지 도입 없음. 의존성 파일 변경 대상 없음. 신규 공통 모듈은 기존 표준 라이브러리만 사용한다.
- 변경 코드에 한국어 모듈 설명·함수 문서·주요 분기 이유를 반영하여 주석 표준을 점검했다.
- 모델·배포·환경변수·DB·원본 증거·Gold는 변경하지 않았고 별도 다음 개발 단계로 진행하지 않았다.

## 6. 최종 점검

| 점검 | 결과 |
|---|---|
| 최종 관련 백엔드 9개 파일, 단위·최종노드 연동 | **142 passed**, 경고 2건 |
| 프런트 실제 렌더러·파일명 보존 | **2 passed** |
| 프런트 TypeScript·Vite 빌드 | **성공**, 번들 크기 경고 |
| 확장 백엔드 회귀 | **441 passed, 7 deselected**, 경고 8건 |
| 수정 전 HEAD의 별도 원인 확인 | 8건 중 **7 failed, 1 passed**. 위 표의 기존 실패 7건 재현 |
| git diff --check | 성공 |
| 실제 사용자 사건의 Azure·DB·브라우저 전체 E2E | **NOT_TESTED** |

확장 회귀에서는 위 7개 테스트 이름을 `-k 'not ... and not ...'`로 제외했다. 확장 실행의 수집 이후 최초 기간이 ‘만료되었다’는 표현의 반례 1건을 추가하고 만료 표현을 종료 입증에서 제외하는 조건을 보완했으며, 최종 관련 142건은 그 보완을 포함한 결과다. 전체 현재 스위트 무조건 PASS로 보고하지 않는다.
