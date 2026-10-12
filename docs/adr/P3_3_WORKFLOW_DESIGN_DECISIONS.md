# AI Legal Helper — P3.3 Workflow Design Decisions

## 1. 개요
P3.3 단계에서는 분리된 여러 기능(상담, 증거 분석, 법률 분석, 대응, 문서)을 하나의 유연한 워크플로우로 통합한다. 이 과정에서 도출된 핵심 설계 결정 사항을 기록한다.

## 2. 워크플로우 상태 관리 (Workflow State Management)

### 결정 사항: **파생 상태(Derived State) 기반의 동적 상태 계산**
사건의 작업 흐름 상태(`CASE_CREATED`, `FACTS_IN_REVIEW`, `ACTION_PLAN_READY` 등)를 판단할 때, `Case` 테이블에 명시적인 `status` 컬럼을 둬서 강제로 업데이트하는 대신, 연관 데이터들의 상태를 합산하여 파생 상태로 계산한다.

#### 이유
- 사용자가 정해진 순서대로만 작업하지 않기 때문에(예: 문서 생성 후 다시 사실을 추가하는 경우) 상태가 역행하거나 복잡하게 전이될 수 있다.
- PostgreSQL을 Source of Truth로 유지하면서, 데이터 간 정합성 오류(예: 증거는 없는데 상태는 `ANALYSIS_COMPLETED`인 경우)를 원천 차단하기 위함.
- UI 레벨에서 진행도를 표시하기에는 파생 상태가 훨씬 더 유연하고 정확하다.

#### 대안
- LangGraph 내부 상태 저장소(Checkpointer) 사용: 프론트엔드가 상태를 쿼리하기 너무 복잡해짐. 기각.

## 3. 화면 탐색 및 컨텍스트 유지 (UX Navigation)

### 결정 사항: **Single Page Workspace (React Router + 탭 기반 네비게이션)**
React Router를 활용하여 `/:caseId/workspace/:tab` 형태의 라우팅 구조를 채택한다.

#### 이유
- URL을 통해 특정 사건의 특정 화면(예: 그래프 화면)으로 직접 접근(Deep Linking)할 수 있다.
- 화면 새로고침 시에도 사건 컨텍스트(ID 및 현재 보고 있던 탭)가 복원된다.
- 전역 컨텍스트(Context API)를 사용하여 데이터를 캐싱함으로써, 탭 간 전환 시 API 중복 호출과 로딩 화면을 방지할 수 있다.

## 4. 비동기 작업 및 백그라운드 폴링 (Async Processing)

### 결정 사항: **클라이언트 측 HTTP Polling + UI 진행 상태 표시**
문서 생성이나 법률 분석 등 오래 걸리는 작업이 진행 중일 때, 웹소켓(WebSocket) 대신 주기적인 HTTP Polling으로 상태를 확인한다.

#### 이유
- P3 MVP 단계에서 인프라(Redis Pub/Sub 등) 추가 없이 가장 안정적이고 구현이 단순하다.
- FastAPI의 백그라운드 태스크나 LangGraph의 비동기 호출 상태를 DB(`LegalAction`이나 `LegalDocument`의 `status='IN_PROGRESS'`)에 기록해 두고, 폴링으로 확인한다.
- 추후 요구사항이 복잡해질 때 SSE(Server-Sent Events)로 쉽게 전환이 가능하다.

## 5. 데이터 재검토(Stale Data) 알림 로직

### 결정 사항: **Timestamp 비교를 통한 Outdated 판별**
최근 수정된 `Fact`나 `Evidence`의 `updated_at`이 기존 `ActionPlan`이나 `LegalDocument`의 `created_at`보다 최신일 경우, 사용자에게 "기존 분석/문서가 최신 사실을 반영하지 않고 있습니다. 재검토가 필요합니다"라는 경고 표시를 띄운다.

#### 이유
- 복잡한 버전 관리나 의존성 그래프 추적 없이 직관적이고 빠르게 구현 가능하다.
- 데이터의 변경이 잦은 법률 사건의 특성을 고려할 때, 무조건 덮어쓰지 않고 사용자에게 인지시키는 것이 원칙에 부합한다.

