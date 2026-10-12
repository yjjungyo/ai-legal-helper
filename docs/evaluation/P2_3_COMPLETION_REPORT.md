# AI Legal Helper — P2.3 완료보고서

## 1. 개요
- **단계**: P2.3 — Evidence Intelligence
- **목표**: 사건 증거 파일 업로드, AI 기반 사실/주장 추출, 리뷰 UI 및 충돌 분석, LangGraph에 검증 근거 주입 구현

## 2. 작업 내용 및 결과
- **데이터베이스 (PostgreSQL)**
  - `models.py`에 `EvidenceDocument`, `EvidenceSpan`, `EvidenceClaim`, `EvidenceSpanClaimLink`, `EvidenceReview`, `EvidenceLink` 모델 추가.
  - `alembic revision --autogenerate`로 새로운 모델 테이블 구조 생성 및 `alembic upgrade head` 수행.
- **백엔드 (FastAPI + LangGraph)**
  - 증거 파일(PDF, DOCX, TXT) 업로드 및 파싱 모듈 구현 (`evidence_ingestion.py`).
  - LLM 기반 증거 문구 파싱 및 주장(`EvidenceClaim`) 추출 로직 구현 (`evidence_extractor.py`).
  - 사용자 리뷰를 통한 상태 변경 및 Case 모델 적용(`evidence_manager.py`).
  - API 라우터(`/cases/{case_id}/evidence/*`) 연동 및 BackgroundTasks 사용.
  - `legal_workflow.py` 의 `supervisor_initialize_node` 업데이트를 통해 승인된 증거 내역을 `case_context`로 편입.
  - `Verification Agent`의 시스템 프롬프트를 수정하여 법률 근거와 사건 증거 출처를 별도로 검증하도록 지침 강화.
- **프론트엔드 (React)**
  - `EvidenceSection.tsx`를 통해 파일 업로드, 문서 목록 표시, AI가 추출한 사실 목록(Spans 포함) 표시 구현.
  - 추출 사실에 대한 '승인/수정 승인/반려' UI 기능 연동.
  - `App.tsx`의 Detail View 탭에 증거 섹션 통합 완료.
- **통합 테스트**
  - `test_evidence.py`를 통해 Case 생성 -> Evidence 파일 업로드 -> Extract API 호출 -> Claims 조회 등 E2E 흐름을 테스트하고 안정성 확보 (모든 테스트 PASS).

## 3. 한계점 및 보완 사항
- `pdfplumber` 및 `python-docx` 파싱이 매우 복잡한 포맷에서는 일관되지 않을 수 있으므로, P2.4나 향후 단계에서 Vision 기반 문서 인식 등을 추가 도입 고려.
- 사용자의 대규모 파일 동시 업로드에 대비한 비동기 작업 처리 큐(Celery 등) 연동 고려 필요.

