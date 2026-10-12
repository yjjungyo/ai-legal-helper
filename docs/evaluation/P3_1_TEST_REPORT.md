# P3.1 Legal Action Intelligence 테스트 보고서

## 단위 테스트 (Unit Tests)
- `tests/unit/test_deadline_engine.py` 작성 및 통과
- **테스트 케이스**:
  - `test_find_lease_end_date`: 이벤트 목록에서 계약 종료일을 성공적으로 추출하는지 확인.
  - `test_calculate_deadline_no_date`: 기한을 알 수 없는 경우 `UNKNOWN`이 반환되는지 확인.
  - `test_calculate_deadline_notice`: 내용증명/갱신거절 통지에 대해 계약 종료 2개월 전의 정확한 마지노선 날짜가 도출되는지 검증.
  - `test_calculate_deadline_lawsuit`: 소송 및 보증금 반환 요구가 계약 종료 익일부터 권고되는지 확인.

## 통합 및 E2E 기능 테스트
1. **API 동작 확인**:
   - `POST /cases/{case_id}/actions/plan` 호출 시 LLM 파싱 성공 및 DB(PostgreSQL) 저장.
   - `GET /cases/{case_id}/actions` 호출 시 1:N 구조(요건, 기한, 선행조건 등) 리턴 정상.
2. **Neo4j 그래프 동기화**:
   - Action Plan 생성 시 백그라운드로 그래프 동기화가 이루어지며, `LegalAction`, `ActionRequirement`, `ActionDependency` 노드 및 관계 생성 확인.
3. **UI 렌더링**:
   - 프론트엔드 React UI에서 Action Plan 섹션 클릭 시 "Action Plan AI 생성/재평가" 호출 및 리스트 표출 정상 동작.

## 한계점 및 향후 과제
- `LegalActionPlanner`에서 기존 사건 데이터의 상태를 덮어쓰고 있는데, 사용자가 특정 상태(예: COMPLETED)를 갱신해 둔 경우 이를 어떻게 유지하며 Revision할지 상세 비교 로직(Diff)이 향후 필요함.

