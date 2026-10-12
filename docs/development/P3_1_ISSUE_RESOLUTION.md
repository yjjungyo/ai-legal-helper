# P3.1 Legal Action Intelligence 트러블슈팅 및 이슈 해결 내역

## Issue 1: LLM의 날짜 연산 환각 (Hallucination)
- **증상**: LLM 기반 Planner에서 `계약 종료 2개월 전`이라는 요건을 처리할 때, 산술 연산을 잘못 수행하여 엉뚱한 날짜를 `deadline`으로 반환하는 현상 발견.
- **해결**: ADR-007 결정을 바탕으로 LLM은 기한 연산을 수행하지 않게 방어. Planner의 Pydantic Schema에서 `deadline_date` 추출을 제거하고, 별도의 파이썬 결정론적 로직(`DeadlineEngine`)을 만들어 `Event` 모델의 `event_date`에서 `relativedelta` 연산을 수행하도록 분리함.

## Issue 2: Graph 동기화 트랜잭션 중복 복제 이슈
- **증상**: Action Plan을 재생성할 때 `graph_sync.py`의 `UNWIND` 배치 수행 중 이전 Action 노드가 남아있어 중복 처리되는 문제가 생길 수 있음.
- **해결**: 그래프 스냅샷 쓰기 (`_write_snapshot_tx`) 단계에서 항상 `case_id` 범위 내의 모든 노드를 `DETACH DELETE` 하고 전체 재생성하는 전략을 유지함. Action 정보도 수집된 스냅샷 딕셔너리에 담아 한 번에 생성하도록 일관성을 부여함.

## Issue 3: React UI에서의 상태 관리 비동기 문제
- **증상**: 사용자가 사실(Statement)을 추가하자마자 Action Plan 화면이 즉시 갱신되지 않는 현상.
- **해결**: Action Plan의 자동 갱신 대신, `CaseRevision` 이벤트를 사용자에게 알리거나 명시적으로 사용자가 `AI 생성/재평가` 버튼을 눌러 상태를 갱신하도록 UI 흐름을 설계함.

