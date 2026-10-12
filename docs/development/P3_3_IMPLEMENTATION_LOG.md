# AI Legal Helper — P3.3 Implementation Log

## 1. 개요
- **단계**: P3.3 Case Workflow & UX Integration
- **목표**: 파편화되어 있던 P0~P3.2 기능들을 단일 사건 기반의 통합 워크스페이스(Workspace) 환경으로 구성하고 작업 상태(Workflow State)를 관리한다.

## 2. 주요 구현 내용

### 2.1 통합 Case Workspace UI 개발
- **라우팅 도입**: `react-router-dom` 패키지를 설치하고, `App.tsx`를 리팩토링하여 URL 기반 라우팅 지원 (`/`, `/:caseId/workspace/:tab`).
- **탭 네비게이션 구조**:
  - `Overview`: 사건 요약 및 상태
  - `Chat`: 기존 채팅 컴포넌트 (`ChatSection.tsx` 분리)
  - `Facts`: 사실 관계 및 타임라인
  - `Evidence`: 증거 업로드 및 검토
  - `Graph`: 증거 그래프 시각화
  - `Action Plan`: 대응 계획
  - `Documents`: 문서 초안 생성 및 다운로드
- **스타일링**: 탭 기반 네비게이션 및 Workspace 컨테이너 CSS (`App.css`) 적용.

### 2.2 Workflow Orchestrator (Backend)
- **라우터 추가**: `src/ai_legal_helper/api/routes/workflow.py` 파일 생성.
- **파생 상태(Derived State) 계산 로직 구현**:
  - `Fact`, `EvidenceDocument`, `LegalAction`, `LegalDocument` 테이블 레코드의 존재 유무를 기반으로 `CASE_CREATED`, `FACTS_IN_REVIEW`, `EVIDENCE_IN_REVIEW`, `ACTION_PLAN_READY`, `DOCUMENT_DRAFTED` 상태를 동적으로 계산.
- **API 엔드포인트**: `GET /api/v1/cases/{case_id}/workflow/status` 엔드포인트를 노출하여 클라이언트가 현재 작업 흐름을 파악할 수 있도록 구현.
- **라우터 등록**: `main.py`에 `workflow` 라우터 포함 완료.

### 2.3 통합 테스트 작성
- `tests/integration/test_workflow_orchestrator.py` 생성.
- `setup_case_and_action` 피쳐(Fixture)를 활용해 DB에 Action이 있는 경우 동적으로 `ACTION_PLAN_READY` 상태가 계산되는지 성공적으로 검증 (pytest 100% 통과).

