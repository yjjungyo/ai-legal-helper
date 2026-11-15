# SC-012 5단계 — 검증·검색·재작성 루프의 실제 진행 여부 기반 종료 설계

작성: 2026-11-15 | 브랜치: `feat/verification-progress-stop-sc012-20261115` | 4단계 기반: `feat/legal-subsumption-audit-sc012-20261115`

## 소스상 문제
1. `document_consultation.next_verification_step`: PASS 외에는 신규 출처가 없어도 3회 재작성. 근거 미확보 `LEGAL_SOURCE_MISSING` 등도 표현만 바꾸면서 같은 검증 반복 가능.
2. `legal_workflow.statute_search_result_condition`: 검색 결과 0건 `NOT_FOUND/PARTIAL_SUCCESS`인 경우에도 `re_analyze`로 재진입. 이미 가진 조문/판례와 내용이 같은 결과도 다시 재작성 가능.
3. `revise_node` → `verification_node`는 수정 초안·출처가 불변이어도 비싼 검증 LLM을 재호출.
4. 4단계 법률요건 포섭/판례 비교로 각 검증 호출의 중요도 및 토큰이 늘었기 때문에 의미없는 반복 제거가 우선이다.

## 설계 결정 (이유와 영향)
- **진행 상태는 Python 구조 체크, 법률해석은 LLM**: 실패 사유·출처 증감·초안 동일성 같은 객관적 사항만 해시로 판단. 날짜/선후순위/부칙 의미/상속책임 등의 실질 법률 판단을 규칙으로 교체하지 않음.
- **검색 무진전**: POST_VERIFICATION 이후 실제 새 Source ID가 0개인 경우 `search_delta_count=0`로 기록. 직전 검증이 법률 근거 부족 상태라면, 검색 결과를 조작하지 않고 `insufficient`로 안전 종료. PRE_ANALYSIS에서는 기존 `run_agents` 경로 유지. 검색 출처가 1개라도 추가되면 재분석 유지. 기존 모의 상태와 하위호환 위해 `search_delta_count` 부재 시 기존 분기를 유지.
- **재작성 무진전**: 수정 초안이 바이트 단위로 같을 때 `revision_no_progress=True` 및 로그에 원인 코드만 남김. 해당 결과를 다시 LLM 검증하기 전에 현재 답변·원문·질문·검증 스냅샷이 동일하고 DB 문서가 여전히 승인 상태인지 확인하여 *기존 검증 결과 재사용*. 원문/질문/확정일/임차인 권리 변화 등 맥락이 달라지면 재검증 강제.
- **검증 결함 무진전**: 같은 Source Manifest + 동일 결함 목록(검증 결과의 구조화 status, reason, unsupported claim 상태, application_audit reason codes, 질문 coverage, citations 오류)이 한 번 이상 재발할 때 `verification_no_progress=True`. 단순 문구 교정으로 출처·법리·포섭이 변하지 않은 재작성 연쇄를 끊는다. 개별 의견문구 자체를 정답으로 하드코딩하지 않음.
- **우선순위**: 기술 오류/Temporal BLOCK은 기존 안전 경로 우선(특히 `TEMPORAL_SEMANTIC_CONTRADICTION`은 수정 기회 보장), PASS→finalize, *새 승인 가능한 검색 요청*→HITL 검색, 그 뒤 무진전/기존 횟수 제한. 법률 근거 없는 초안을 임의 PASS 처리하지 않음.
- **종료 시 부분답변**: `finish_answer`의 기존 스냅샷·claim·Temporal·인용·법률효과 검사를 그대로 유지. 불충분한 법리의 초안을 그대로 공개하지 않고 WITHHELD; 안전한 경우 기존 검증된 설명만 CAUTIONARY 보존. 재작성 횟수 단순 축소 금지.
- **출처 동일성의 기준**: 실제 `source_id`와 `content`의 해시. 검색 결과 0건에 이전 등록 출처만 재사용된 것은 신규 진전으로 보지 않음. 버전이 다르면 새로운 source_id 필요. 출처 충돌은 기존 Source Registry 검증으로 차단.
- **턴간 격리**: `supervisor_initialize_node`가 상담을 새로 시작할 때 무진전 역사, 검색 신규 출처수, 동일 초안 표시 초기화. Graph State에 필드 선언해 Checkpointer/HITL 재개 후에도 적용.
- **호출 수**: 새 LLM 호출 추가 없음. 최적화 게이트는 문자열 SHA256/리스트 정규화만 수행. 유효한 새 판례/법령이 들어오면 재작성 1회와 독립 검증 필수.

## 순서 및 테스트
1. `workflows/verification_progress.py` 신규 순수 함수: 근거 source delta, 검증결함 fingerprint, 이전 검증 캐시 승인 여부 (매니페스트·질문·초안·검증 스냅샷 포함).
2. `document_search.py`: `search_delta_count`, `search_added_source_ids` 기록. 검색/권한 정책 변경 금지.
3. `legal_workflow.py`: POST_VERIFICATION 신규 근거 없을 때 안전 분기; 새 판례 우선 보호; state 초기화.
4. `document_consultation.py`: 동일 초안 감지·상태 기록, 동일 자료 검증 LLM 생략, 구조화 결함 반복 루프 차단. 변경 전에 `validate_document_snapshot` 확인하며 기존 Temporal 검사 재호출.
5. `state.py`: 새 상태 선언 및 테스트.
6. CI: 소스별 코드리뷰/단위 테스트. 재작성 요청 의도적으로 달라질 때 진행하는 반례, 부칙/판례 검색 후 다시 검증하는 반례, 승인 거절 차단, 원문 변경/질문 변경 시 cache 금지.
7. 수동 E2E: SC-012~013 실제 Trace latency/tokens/source delta 및 최종 정답률 측정 전에는 개선 수치 단정 금지.

## 안전 경계
- 1단계 사용자가 처리 중인 증거 격리 수정 안 함.
- 3단계 판례 조회·HITL 승인 범위·4단계 `application_checks` 검증 규칙 우회 금지.
- 출처 부족·시행일 미확정에 대한 단정 답변 금지.
- 5단계의 목표는 재호출 수가 아니라 **신규 근거·초안 변화·새로운 검증정보가 없는 반복 제거**.
