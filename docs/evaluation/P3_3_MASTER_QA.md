# AI Legal Helper — P3.3 Master QA

## 1. 요구사항 검증
- **통합 Case Workspace (React + TS)**: ✅ `react-router-dom`을 적용하여 단일 워크스페이스 형태로 모든 기능(Overview, Chat, Facts, Evidence, Graph, Action, Docs)을 탭 메뉴로 통합 완료. 화면 새로고침에도 탭과 사건 ID가 URL로 유지됨.
- **AI 상담과 사건 데이터 연결**: ✅ `ChatSection`을 분리하고, 사건 단위로 컨텍스트를 유지.
- **Workflow Orchestrator 설계**: ✅ 파생 상태(Derived State)를 계산하는 로직을 `/workflow/status` 엔드포인트로 통합 구현. 순서를 강제하지 않으면서도 가장 많이 진척된 단계로 상태를 표시 가능.
- **오류 처리 및 통합 테스트**: ✅ 404 Not Found 및 DB 오류 핸들링. pytest 기반으로 Workflow API 연동 확인 완료.

## 2. P3.3 AI Master 평가 자료 기록
### 기능별 화면을 사건 중심 Workspace로 통합한 이유
파편화되어 있던 Action, Document, Evidence, Graph 등의 메뉴를 묶어, 사용자가 여러 창이나 리스트를 오가지 않고도 한 화면에서 자신의 법률 문제(Case) 해결에 집중할 수 있도록 하기 위함입니다. URL 라우팅 기반으로 딥링킹이 가능하여 진행 중인 화면으로 언제든 돌아올 수 있습니다.

### API 중복 제거 및 구조 개선 사항
기존에는 사건, 사실관계, 증거, 액션 등의 상태를 클라이언트가 각각 `GET`으로 호출해 합쳐야 했으나, `Workflow Orchestrator`(`/api/v1/cases/{case_id}/workflow/status`)가 이를 단일 API 콜로 취합하여 계산한 후 반환하도록 백엔드 구조를 개선했습니다.

### 비동기 분석 상태 관리 설계
서버 내 LangGraph 분석은 시간이 소요되므로, DB에 `IN_PROGRESS`를 기록하고 클라이언트는 `Workflow` API나 개별 자원 API를 주기적으로 폴링하는(Polling) 아키텍처를 도입할 수 있는 확장 가능한 파운데이션을 마련했습니다.

## 3. 남은 과제 / 기술 부채
- 문서 생성, 분석 등의 비동기 작업에 대한 HTTP Polling(또는 WebSockets/SSE) 로직이 프론트엔드 React Query/SWR 등에 실제로 반영되어야 합니다 (기반 구조는 완료).
- 현재 `App.tsx` 구조 상 Error Boundary를 적용하여 특정 탭이 다운되었을 때 전체 Workspace가 중단되지 않도록 보호하는 조치가 추후 요구됩니다.

