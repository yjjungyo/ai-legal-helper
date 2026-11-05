# P12 Temporal Law Retrieval — 통합 검증 계획 (미실행)

> 상태: 테스트 케이스 정의만 완료. DB 마이그레이션·테스트 실행은 사용자 승인 전 보류.

## 검증 전제
- PostgreSQL 전용 평가 DB, Chroma 평가 컬렉션, 가짜 공식 XML 및 mock LLM 사용
- 공식 법령 API 호출은 HILT 승인 경로만 허용. 단위/통합 테스트는 네트워크 차단
- 법령ID, MST, 사건일, 조문ID, 부칙 근거, 출처 vector ID를 각 Trace에 기록
- 모든 미확정 상황은 법률 적용 확정이 아닌 `SOURCE_TEMPORAL_UNCONFIRMED` 또는 더 엄격한 상태로 귀결

## 회귀 시나리오

| ID | 조건 | 기대 결과 |
|---|---|---|
| T01 | 동일 MST를 2회 인덱싱 | unique violation 없음, 커버리지 개수 동일, 검토 결과 보존 |
| T02 | 동일 본문의 부칙 2개 | 각기 다른 vector ID로 보존, 충돌 없음 |
| T03 | 동일 법령 연혁 스냅샷을 2회 저장 | 서로 다른 snapshot_id로 분기 보존 |
| T04 | 동일 MST에 시행일 분기 2개 | 단일 시행일로 축약 금지, HISTORY_INCOMPLETE 또는 검토 필요 |
| T05 | 2025-01 시행 조문, 2025-09 사건 | 해당 시점 후보로 선택, 부칙 적용 검토 필수 |
| T06 | 2025-07 개정, 2025-08 시행 조문, 2025-09 사건 | 최신 조문 후보 검색, 개정 전 조문 혼합 금지 |
| T07 | 사건일보다 조문 시행일이 늦음 | ARTICLE_NOT_YET_EFFECTIVE |
| T08 | 조문 시행일이 비어 있음 | ARTICLE_DATE_UNCONFIRMED |
| T09 | LLM이 출처에 없는 시행일을 제시 | 후보 폐기, UNCONFIRMED |
| T10 | 부칙의 상대 날짜·경과조치 | 자동 적용 확정 금지, REVIEW_REQUIRED |
| T11 | 서로 다른 법령 2개, 같은 제3조 | 법령ID×조문별 커버리지 각각 확인 |
| T12 | 한 법령만 조회 성공 | 누락 법령 표시, 공식 조회 권고 유지 |
| T13 | 모든 법령 근거 확보, 부칙 검토만 남음 | 재조회 반복 권고하지 않되 TEMPORAL_UNCONFIRMED |
| T14 | Chroma 장애 | RETRIEVAL_ERROR, 공식 법령 부재로 오판 금지 |
| T15 | 이력 최신성 기간 초과 | HISTORY_STALE, 공식 연혁 재확인 필요 |
| T16 | XML 해시와 기존 MST가 불일치 | 저장 거부, 기존 READY 상태 무단 유지 금지 |
| T17 | 시행일 문자열 2026년 01월 05일 | 2026-01-05로 정규화해 원문 대조 |
| T18 | LLM 추출 후보와 원문 조문시행일 충돌 | 원문 우선, 충돌 검토 필요 |
| T19 | 사건일/사건유형 누락 | EVENT_UNCONFIRMED, 법률 적용 확정 금지 |
| T20 | 부칙 검토 필요 상태의 검색 출처 | 출처 단위 applicability_status=UNCONFIRMED |

## 실행 순서 (추후 승인 시)
1. Python import/compile 및 정적 분석
2. Alembic upgrade/downgrade를 평가 DB에서만 검증
3. 위 T01–T20 단위 테스트 및 통합 테스트
4. SC-001(시간 순서 3회 상담), SC-002(단일 상담), 최신 시행일 질의 E2E
5. Langfuse Trace별 정합성·지연시간·토큰·재조회 횟수 확인
6. 실패 원인 수정 후 동일 Gold Set 회귀 재검증

## 미해결 설계 이슈
- 법령 목록 시행일과 개별 조문 시행일의 차이, 다단계 시행 MST 처리
- 미래 사건일의 연혁 조회 범위와 checked_through 의미
- 부칙 적용례/경과조치의 법률적 판단과 승인 정책
- LLM 시행일 후보의 원문 span 및 검토 이력 영속화
- Worker의 Chroma upsert와 PostgreSQL commit 사이 원자성/복구 전략

위 이슈는 통합 테스트 통과 전까지 완료 처리하지 않는다.
