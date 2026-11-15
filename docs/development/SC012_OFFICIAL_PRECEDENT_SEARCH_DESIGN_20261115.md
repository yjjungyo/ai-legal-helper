# 3단계 공식 판례 검색 파이프라인 설계 / Gemini 협업 기준
기준 브랜치: `feat/official-precedent-search-sc012-20261115` (2단계 `fix/semantic-issue-planner-sc012-20261115`에서 분기). 1단계 증거 격리 개발 제외.

## 핵심 원칙
1. **출처 유형은 명시적 구조화 계약**: 검증기가 `source_type=STATUTE|PRECEDENT|BOTH`를 선택한다. 법률 효과는 regex로 결정하지 않는다. 판례가 필요할 때 기존 법령 검색만 반복하지 않는다.
2. **추가 LLM 호출 없음**: 기존 문서 검증기 요청 형식에 `source_type`, `precedent_query`를 추가한다. `precedent_query`는 개인정보/개별 사실이 아닌 2~5개 법률 개념만 담는 짧은 검색어다. 불확실하면 재검색하지 않고 부족으로 남긴다.
3. **공식 2단계 조회**: 법제처 `lawSearch.do?target=prec&type=XML&search=2` 목록 → 실제 id로 `lawService.do?target=prec&type=XML&ID=...` 판결요지·판시사항·본문 조회. 인증 `LAW_OPENAPI_KEY`, HTTPS, 제한 시간/시도/결과 개수.
4. **신뢰와 적용 구분**: 목록에서 발견했다는 이유로 `PRECEDENT` Source 확정 금지. 상세 응답에서 id/사건번호/법원/선고일자/판시·요지·본문 확인, 등록된 메타데이터로 Source 생성. 판례는 존재하더라도 사안과의 유사성 및 적용 법리는 별도 4단계 포섭/Verifier 검증 필요.
5. **승인·감사 경계**: 판례 조회도 기존 HITL 승인 전에는 수행 금지. 승인 화면에 법령/판례 유형과 검색어를 표시; 한 번 승인한 쟁점만 재호출. 출처 이름뿐 아니라 `source_id`, `source_url`, `case_number`, `decision_date`, `court`, `content`, `retrieval_method` 유지. OpenAPI 키·사건 개인 이름 로그 금지.
6. **기존 법령 흐름 불변**: `pending_searches`의 기존 법령 인터페이스는 유지하고 판례는 별도 `pending_precedent_searches`. 기존 `statute_search_results`에 판례를 끼워 넣어 법령 전용 temporal 코드를 오염시키지 않는다. `precedent_search_results`와 `retrieved_sources`에 병렬 관리.
7. **상태전이 보존**: post-verification에서 판례만 검색해도 `re_analyze`로 복귀해야 한다. 승인 거절/API 장애/검색 결과 없음은 조문/판례 인용을 창작하지 않고 기존 안전한 경로 사용.
8. **중복/지연 관리**: 키는 출처 유형+검색어별 SHA256으로 구분하여 조문 검색 이력과 충돌 방지. 한 번의 API 요청에서 최대 3~4개의 상세 판결문을 받고 최대 2회 search attempt를 재사용. 같은 판례 ID 중복 병합 금지.

## 코드 설계
- `tools/official_precedent_search.py` 신규: API 호출, XML 응답 파싱, list/detail 식별자 대조, 검색어 보호 및 Source 생성.
- `agents/document_verification_prompt.py` 수정: `legal_search_requests`의 `source_type`, `precedent_query` 추가. 기본 `STATUTE`; `BOTH`이면 동일 이슈의 조문+판례 각각 검색.
- `workflows/document_search.py`: 구조화 요청 정규화, 승인·검색·이력·Source 병합, 판례 결과와 법령 결과 구분. 부칙·시행일 계산은 법령 출처만 입력한다.
- `workflows/document_consultation.py`: 신규 판례 요청의 HITL/재검색 분기, 검색 결과 있을 때 후속 재분석.
- `workflows/legal_workflow.py`: 검색 승인 화면과 판례 승인 상태, 판례검색 결과를 경로 판단과 UI 상태에 연결.
- `workflows/state.py`: 판례 승인·결과·이력 필드 TypedDict 추가. 2단계 변경과 호환.
- `backend/tests/unit/test_official_precedent_search.py` 신규: HTTP 없음 mock XML, source integrity, key masking, 실패/거절/중복, 판례 단독/법령 혼합, 관련 없는 판례 검색 실패, 판시사항/판결요지 빈 상세 거부, workflow route.
- `docs/evaluation/SC012_STEP3_PRECEDENT_PIPELINE_REPORT_20261115.md` 작성.

## 수용기준
- 실제 공식 API 응답과 구조화된 판례 요청을 통해 법령 조문 없는 경우에도 `PRECEDENT` 출처를 찾을 수 있음.
- 사용자의 사건명/사실관계가 API 검색어로 원문 전송되지 않으며, 검색 중 API 키가 진단에 남지 않음.
- 승인 거절 상태에서 외부 API 호출 0회.
- 신규 판례 Source가 citation audit에서 사건번호를 유효한 공식 인용 후보로 인식.
- 호출·토큰·전체 latency의 개선 주장은 실제 E2E 이후에만 기록.
- 심층 판례요건 포섭(4단계)과 검증 루프 제어(5단계)는 별도로 진행.
