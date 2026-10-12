# AI Legal Helper — P3.3 Issue Resolution

## 1. 프론트엔드 라우팅 적용 중 기존 코드 호환성 문제
- **이슈 사항**: 기존 `App.tsx`는 `view`라는 로컬 상태('list', 'detail', 'chat')로 화면을 전환하고 있었으나, P3.3 요구사항인 통합 워크스페이스(탭 구조)를 위해서는 URL 기반 라우팅이 필수적이었음. 
- **해결 방안**: `npm install react-router-dom` 명령어를 통해 라우터를 설치하려 했으나 PowerShell Execution Policy 문제로 에러 발생. `npm.cmd`를 명시적으로 호출하여 해결함. 이후 기존 `App.tsx` 코드를 `CaseList.tsx`와 `CaseWorkspace.tsx`, `ChatSection.tsx` 등으로 모듈화하여 `React Router` 기반 컴포넌트로 마이그레이션함.

## 2. 워크플로우 상태 관리의 Source of Truth 문제
- **이슈 사항**: 사건의 현재 진행 단계를 어디에 저장할지가 문제됨. `Case` 테이블에 `status` 컬럼을 명시적으로 둘 경우, 사용자가 순서를 뛰어넘어 문서 생성을 먼저 한 후 다시 사실관계를 추가할 때 상태를 역행시키거나 동기화 오류를 발생시킬 위험이 높음.
- **해결 방안**: DB에 하드코딩된 상태 컬럼을 두지 않고, `/workflow/status` 요청이 들어올 때마다 연관된 엔티티(Fact, Evidence, Action, Document)들의 레코드 수를 동적으로 계산(Derived State)하여 상태를 반환하도록 설계(ADR 반영).

## 3. 테스트 Fixture 의존성 문제
- **이슈 사항**: 새로 작성한 `test_workflow_orchestrator.py`에서 기존 통합 테스트의 Fixture를 재사용하려 했으나 로드되지 않음.
- **해결 방안**: `test_workflow_orchestrator.py` 내부에 `TestingSessionLocal`과 DB 설정 코드를 명시하고, 독립적인 `setup_case_and_action` Fixture를 직접 구현하여 모듈 단위 의존성을 제거하고 테스트 안정성을 확보함.

