# Temporal Legal RAG — P6 LangGraph 선행 법령 검색 및 HILT 연결

기준선: P5 main 439b37e505b1fb2e2efffa798c25803aeb9b8897

## 구현 범위

1. plan → statute_search_plan → (기존 Agent 또는 기존 HILT 승인) 분기
2. 로컬 P2 Law Catalog와 P5 Event Resolver에서 공식 법령ID/명칭·단일 사건일을 확인한 질문만 PRE_ANALYSIS 계획
3. PRE_ANALYSIS HILT 요청 본문에 승인 대상 법령명·기준일·이벤트 유형 표시
4. 승인 없는 OpenLaw 호출 금지. 허가받은 법령 집합 외 자동 확장 금지
5. 승인 후 P4 공식 검색에 사건 as-of 날짜 전달
6. 검색 결과를 P5 Temporal Law Resolver가 검사해 temporal_resolution 저장
7. 선행 공식 원문을 다음 Agent/Vector 검색 결과로 덮어쓰지 않도록 수정
8. 선행 법령 검색 실패 시 기존 Agent → Synthesize → Verification 경로로 복귀
9. 기존 Verification 단계의 사후 HILT 및 Checkpointer Resume 유지
10. 기존 8개 전문 Agent 구조와 외부 Tool 명칭 변경 없음

## 보안·안전

- 사전 검색계획 단계는 외부 OpenLaw API에 절대 접근하지 않는다.
- 카탈로그 데이터가 없거나 DB 장애, 사건일/법령명이 모호하면 SKIP 처리하고 기존 검색 흐름을 사용한다.
- 실제 외부 검색은 approval_status APPROVED이면서 승인된 대상 법령명 내에서만 실행한다.
- 사전 검색 성공 자체를 법률 적용 확정으로 표시하지 않는다. P5 결과에는 UNCONFIRMED가 남을 수 있다.
- 사건일 없이 일반 질문을 하는 경우 P4 날짜 지정 검색으로 강제 전환하지 않는다.
- 후속 P8 Verification에서 신법 시행일 단정·미확인 적용례에 대한 차단을 완료해야 한다.

## 데이터 계약

LegalState 신규 필드:
- law_search_plan: status, phase, candidate_laws, law_ids, as_of_date, event_type, reason_code
- statute_search_phase: PRE_ANALYSIS / POST_VERIFICATION (기존 사후 검증 경로는 None 허용)
- temporal_resolution: status, event, decisions, missing_evidence

## 회귀 검증

- P6 신규 테스트: 승인 미확보 차단, 승인 집합 위변조 차단, 사전 검색의 사건 기준일 전파
- 기존 HILT 정상 PASS, 승인, 거절, 검색 결과 없음, 조문 참조 정규화
- P5 사건 기준일 테스트
- 실제 운영 OpenLaw·PostgreSQL·LangGraph Checkpointer E2E 및 사용자 화면 직접 시연은 아직 수행되지 않음

## 다음 단계

P7: 공식 법령 근거를 Agent/답변 생성기와 연결하고 버전별 Source Bundle을 만든다.
P8: Verification에서 P5 3상 판정을 활용해 시행예정 규정 오적용을 차단한다.
P9: 공식 법령 버전별 비동기 인덱싱.
P10: 레거시 Vector 메타데이터 검증·마이그레이션.
P11: SC-001 및 시점별 Gold Set의 품질·지연·토큰·정확성 실측.
