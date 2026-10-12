# P3.1 Legal Action Intelligence 구현 로그

## 구현 항목
1. **데이터베이스 모델 설계 (PostgreSQL)**
   - `LegalAction`, `ActionRequirement`, `ActionDependency`, `ActionDeadline`, `ActionRevision` 모델 생성
   - Alembic 마이그레이션 (`a909c01c8356_add_action_domain_models`) 반영

2. **LegalActionPlanner (Agent)**
   - `src/ai_legal_helper/agents/action_planner.py` 구현
   - Pydantic을 이용한 구조화된 출력(Structured Output) 적용
   - 주택 임대차 분쟁용 Action Catalog 정의

3. **Deadline Engine**
   - `src/ai_legal_helper/agents/deadline_engine.py` 구현
   - LLM 대신 파이썬 `datetime`과 `dateutil.relativedelta`를 사용한 결정론적 계산
   - 계약 종료일 등을 추출하여 `LEGAL_DEADLINE`, `RECOMMENDED_DATE` 산출

4. **Action Service 통합 및 REST API**
   - `src/ai_legal_helper/case_intelligence/action_service.py` 구현하여 Action Plan 생성 로직 작성
   - `src/ai_legal_helper/api/routes/cases.py`에 `POST /{case_id}/actions/plan` 및 `GET /{case_id}/actions` 엔드포인트 추가
   - `src/ai_legal_helper/api/schemas/action.py` 추가

5. **Neo4j Graph Sync 연동**
   - `src/ai_legal_helper/database/graph_sync.py` 업데이트
   - `RECOMMENDS_ACTION`, `HAS_REQUIREMENT`, `DEPENDS_ON_ACTION`, `REQUIRES_EVIDENCE` 관계 동기화 로직 추가

6. **React UI 연동**
   - `frontend/src/api/actionClient.ts` 작성
   - `frontend/src/components/ActionPlanSection.tsx` 뷰 추가
   - `App.tsx`의 사건 상세 화면에 Action Plan 탭 포함

## 해결된 이슈
- LLM에 날짜 계산을 맡겼을 때 생길 수 있는 수학적 오류를 파이썬의 `DeadlineEngine` 분리로 해결함.
- Action Plan의 구조를 정의하기 위해 Pydantic의 List 구조를 사용하여 `ActionPlanResponse`로 반환받고 이를 DB에 1:N으로 저장함.

