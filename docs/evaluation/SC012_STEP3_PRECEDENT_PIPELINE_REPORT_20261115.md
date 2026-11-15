# AI Legal Helper — 3단계 공식 판례 검색 파이프라인 개발·코드리뷰 보고서

- 작성일: 2026-11-15
- 개발 브랜치: `feat/official-precedent-search-sc012-20261115`
- 기준: 2단계 브랜치 `fix/semantic-issue-planner-sc012-20261115`, Draft PR #31
- **1단계 증거 격리 및 Trace 정합성 작업은 사용자가 직접 수행하므로 이번 코드 변경에 포함하지 않음**
- 기존 법령 API, 판례 API의 통신 규격은 국가법령정보 공동활용 공식 가이드와 대조: `https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=precListGuide`, `precInfoGuide`
- 실행 환경은 GitHub Actions Python 3.11 + 별도 UI CI. **법률 서비스와 실제 법제처 API를 연결한 DB+LLM E2E는 이 보고서 작성 시 미수행**.

## 1. 개발 배경 / root cause

SC-012 2차는 '공동상속인이 승계한 임대차보증금 반환채무를 지분별로 청구해야 하는지, 각자 전액 청구 가능한지' 질문한다. 검증기는 공동상속인 책임의 판례가 추가로 필요하다고 분석했지만, 기존 검색 요청은 `law_name`/조문을 중심으로 관리되어 공식 판례 본문을 실제 조회하지 못했다.

앞선 2단계는 오분류 Issue를 현재 질문 의미 기반으로 개선했으나 **판례 검색 도구 자체는 없었다**. 3단계에서는 검색 대상을 분리하여 공식 판례를 출처로 등록할 수 있도록 개선했다. 이는 법률적 사실·판례 적용 여부를 확정하는 것과는 다르다.

## 2. 설계 원칙 / Gemini 인계

1. **법률 규범과 판례·사건 사실의 출처 유형 분리** — STATUTE/BOTH/PRECEDENT 구조화 요청. 법률 결론을 정규식으로 판정하지 않는다.
2. **추가 LLM 호출 금지** — 기존 Document Verifier 호출의 JSON 출력에 `source_type`, `precedent_query`를 추가한다.
3. **HITL 동의** — 법령만 승인했다고 판례 조회를 허용하지 않는다. 승인 화면에는 현재 검색 대상과 판례 검색어를 표시한다. 사용자 승인과 동일한 검색어에만 원격 조회 허용.
4. **공식 API 이중 확인** — `lawSearch.do?target=prec&search=2` 목록 → `lawService.do?target=prec&ID=...` 상세. 목록만으로는 공식 인용 출처를 만들지 않는다.
5. **오인용 차단** — 상세 ID, 사건번호, 법원, 선고일자, 판시사항·요지·본문 확인 후 `PRECEDENT:<일련번호>` Source. 사건기록/법령본문/과거 대화에 나온 판례번호는 실제 검색된 판례가 아니다.
6. **검증/요건 포섭은 별도** — 판례 조회 성공만으로 PASS 또는 특정 사건의 법률 결론을 승인하지 않는다. 판례의 쟁점·법리·요건·사실 차이를 별도로 검증해야 한다(4단계).
7. **검색 비용 제어** — 일반 법률 개념 검색어 최대 2개, 판례 상세 최대 3개, 표준 조회 시간/재시도·중복 판례 ID 제거. 인명·날짜·번호 등 개인 사건 정보의 조회 유입을 보수적으로 차단.
8. **후속 흐름 복구** — 판례만 발견해도 `re_analyze`로 반환. 법령 전용 검색 결과·버전/부칙 판단은 건드리지 않는다.

## 3. 실제 파일별 변경 / 영향도

| 파일 | 내용 | 영향·안전장치 |
| --- | --- | --- |
| `backend/src/ai_legal_helper/tools/official_precedent_search.py` (신규) | 공식 판례 2단계 XML 조회, 목록 상세 일치·판례 번호 검증, 공적 출처 등록 | 인증 없는 호출/빈 원문/상이한 ID/비정상 선고일/타임아웃은 출처 0건으로 종료 |
| `backend/src/ai_legal_helper/agents/document_verification_prompt.py` | 구조화된 `STATUTE/PRECEDENT/BOTH` 요청과 비식별화된 판례 일반 법리 검색어 요구 | 임대차·상속·노동별 전용 분기 없음, 기존 LLM 호출 1회 유지 |
| `backend/src/ai_legal_helper/workflows/document_search.py` | 법령 요청과 판례 요청 별도 pending, 승인 범위·SHA256 이력, 유형별 검색·결과·출처 병합 | 기존 `pending_searches` 법령 계약 유지; 판례만 있거나 법령+판례 혼합에도 결과 누락 방지 |
| `backend/src/ai_legal_helper/workflows/document_consultation.py` | 판례 단독 요청도 승인/조회 분기 | 법령 `law_name` 빈 값만을 이유로 판례 요청 유실 금지 |
| `backend/src/ai_legal_helper/workflows/legal_workflow.py` | 승인 팝업 payload에 판례 검색어 명시, 승인 스코프 등록, 판례 결과 re_analyze 처리 | 기존 법령 HITL 방식을 재사용, 다른 쟁점 판례 검색에는 신규 승인 |
| `backend/src/ai_legal_helper/workflows/state.py` | `approved_precedent_search/queries`, `precedent_search_results/status/history` 타입 | LangGraph checkpoint 상태 간 공식 판례별 중복방지 |
| `backend/src/ai_legal_helper/agents/verification.py` | 판례 인용은 실제 PRECEDENT Source의 `case_number + content`가 있을 때만 존재성 인정 | 과거 CASE_EVIDENCE/STATUTE/대화 맥락에 적힌 판례번호만으로 가짜 판례 PASS 불가 |
| `frontend/src/types/consultation.ts`, `frontend/src/components/chat/ConsultationProgress.tsx` | 사용자 승인 전 조회 예정 판례 검색어 표시, 승인 버튼 구분 | 신규 판례 조회를 법령 검색 동의 뒤에 숨기지 않음 |
| `backend/tests/unit/test_official_precedent_search.py`, 신규 CI | 외부 통신 없는 공식 API 모의 응답·HITL·상태전이·오인용 테스트 | 기존 법령 및 문서 검증 테스트와 함께 실행 |
| 상위 설계서 | `docs/development/SC012_OFFICIAL_PRECEDENT_SEARCH_DESIGN_20261115.md` | Gemini 인계: PRECEDENT-03~11 주석 및 통합 단계 설명 |

## 4. 수행 테스트 및 코드 리뷰 사실

- 첫 CI: `Official Precedent Search Regression` **88 passed** (Python 3.11, 2.63초), 컴파일 통과. https://github.com/yjjungyo/ai-legal-helper/actions/runs/43673643019
- 개인정보 이름 보완 후 CI: **89 passed** (2 warnings, 3.16초). https://github.com/yjjungyo/ai-legal-helper/actions/runs/43673875895
- 추가 감사: 사건 자료 또는 법령 문장에 특정 판례번호가 있다는 사실만으로 `audit_citations_and_claims()`가 판례 출처 존재성 PASS를 인정하던 경로를 제거함. **공식 PRECEDENT Source에 의존하도록 수정**. 이를 검증하기 위한 신규 회귀 테스트 3개 추가.
- 이전 UI CI: `Frontend UI regression` 성공 (프론트 TypeScript build, lint 포함).
- 기존 광범위 `Semantic Judgment Safety Regression`에서는 이전 단계에서도 동일하게 발생한 **법령 조문+부칙 2건 반환 / legacy 테스트 1건 기대** 문제가 확인됨. 이번 판례 검색 코드와 무관한 항목으로 별도 관리. 전체 CI를 PASS로 오인하지 않음.
- **최종 commit의 CI 결과는 GitHub Actions 실행 결과를 기준으로만 추가 갱신**한다. 미실행/미확인 수치를 임의 기록하지 않는다.

## 5. 기능·안전 검증 체크리스트

- [x] 공식 법제처 문서에 `target=prec` 목록/상세 및 `search=2` 계약 존재 확인
- [x] 목록 상세 ID·사건번호/선고일자 검증 코드 구현
- [x] 법률 개념 검색어만 원격 전송하는 보수적 입력 검증 구현
- [x] 별도 HITL 승인 조건, 추가 승인 범위 제한 및 UI 표시 구현
- [x] PRECEDENT Source 등록·중복 제거·법령 출처와 분리
- [x] 판례만 반환 시 `re_analyze` 상태전이
- [x] 허위 판례 인용 방지를 위해 사건 문서 언급과 공식 판례 원문 출처 구분
- [ ] 인증된 실제 법제처 API 연동 확인 — 사용자 환경 자격증명 필요
- [ ] 실제 LLM Verifier가 `PRECEDENT/BOTH`와 법률 개념 검색어를 생성하는지 평가
- [ ] 신규 판례로 SC-012가 원문·법률요건 포섭·Verifier PASS까지 이어지는지 E2E 확인
- [ ] 4단계 판례 법률요건 포섭 및 5단계 불필요한 재작성 루프 최적화

## 6. 사용자 수동 E2E 테스트 절차 (3단계)

1. 코드 브랜치 `feat/official-precedent-search-sc012-20261115`에서 실행 환경 준비. `LAW_OPENAPI_KEY`가 법제처 공동활용 API에서 `prec` 조회 권한이 있는지 확인한다. 키를 Trace/보고서/채팅에 공유하지 않는다.
2. 기존과 동일한 SC-012의 적절한 턴별 사건 증거 조건에서 질문을 실행한다(증거 격리는 사용자가 직접 수행).
3. Langfuse Verifier 출력 `legal_search_requests`에 `source_type: PRECEDENT/BOTH` 및 `precedent_query`가 실제로 있는지 확인한다.
4. HITL 승인 화면에서 **판례 검색어**가 명시되는지 확인 후 승인한다.
5. `execute_statute_search_node`의 실행 결과에서 `precedent_search_status`, `precedent_search_results` 개수, `retrieved_sources[*].source_type=PRECEDENT`, `source_url`, `case_number` 확인.
6. `re_analyze_node`가 판례 근거를 읽고 재분석하는지 및 Verifier가 실제 판시 법리·사실 요건을 포섭하여 판단하는지 확인한다.
7. 판례가 검색되지 않거나 상세 원문이 부실하면 임의의 판례번호로 답변을 통과시키지 않아야 한다.
8. 정상적인 법령/부칙 검색과 SC-013 경매·노동 질의가 회귀하지 않는지 검사한다.

## 7. Gemini 협업 및 잔여 리스크

- 무분별하게 `검색어에 판례 문구가 있으면 판례 검색` 같은 정규식 판정을 추가하지 않는다. 검색 유형은 **Verifier의 구조화된 LLM 출력**으로 결정한다.
- 판례 API 반환은 공식 데이터지만 현재 사건과의 법률요건 부합 여부는 별도 판단. 4단계에서 판례 핵심 법리, 예외 요건, 당사자 관계, 사건 승인 사실을 비교할 것.
- LLM이 생성한 '일반 법률 검색어'에서 비정형 한국어 인명을 전부 자동 식별하는 것은 불가능하다. 현재 코드는 주민번호/계좌/날짜/이메일/기등록 당사자 명칭을 차단하지만, 제3자 이름이 미등록이거나 형식이 특이하면 추가 유출 위험이 남는다. 실제 운영에서는 개인정보 전송 정책 및 검증된 PII 검출 체계를 보강할 것.
- **OpenLaw API 인증과 연결 및 4단계 실제 포섭을 확인하기 전에는 전체 법률 답변 정확도 개선·서비스 배포 완료로 선언하지 않는다.**
