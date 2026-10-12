# P3.5 Feature Inventory

## 실 구현 상태 조사 결과

| Feature | Status | 확인 사항 |
|---------|--------|-----------|
| 회원가입·로그인·로그아웃 | IMPLEMENTED | `/api/v1/auth/*` API 구현 및 React AuthProvider 통과 완료 |
| 사건 등록·조회·수정 | IMPLEMENTED | `CaseWorkspace` UI 및 `cases.py` API 연결 완료 |
| AI 상담 | IMPLEMENTED | `ChatSection.tsx` 및 `process_new_statement` 워크플로우 작동 확인 |
| Fact Extraction | IMPLEMENTED | AI 상담을 통한 `Fact` 추출 모델 동작 |
| Timeline | PARTIAL | DB 상 `Event` 모델은 존재하나 Timeline 시각화 기능 확인 필요 |
| Evidence Upload | IMPLEMENTED | `EvidenceSection.tsx` 및 파일 메타데이터 저장 작동 |
| Evidence Review | IMPLEMENTED | 승인(`REVIEW_STATUS`) 절차 DB 레벨 구현됨 |
| 법률 분석 | IMPLEMENTED | `LegalIssue` 추출 및 상태 반영 로직 동작 |
| GraphRAG | IMPLEMENTED | `Neo4j` 벡터/그래프 하이브리드 통합 및 `EvidenceGraph.tsx` UI 구현 완료 |
| Action Plan | IMPLEMENTED | `ActionPlanSection.tsx` 와 `/cases/{case_id}/actions/plan` 통합 |
| Legal Document Generation | IMPLEMENTED | `DocumentSection.tsx`에서 LangGraph 기반 문서 생성 |
| Document Revision | IMPLEMENTED | `DocumentRevision` DB 테이블 반영 및 버전 관리 로직 적용됨 |
| Document Verification | IMPLEMENTED | `DocumentState` 내 검증 로직 구현됨 |
| DOCX Export | IMPLEMENTED | `export_docx` 백엔드 함수 지원 |
| PDF Export | MISSING | `pdf` 출력 백엔드 기능 누락, 구현 필요 |
| 사건별 접근 통제 | IMPLEMENTED | P3.4를 통해 글로벌 `Depends(get_case_for_user)` 적용 |
| 감사 로그 | IMPLEMENTED | `AuditLog` 객체 저장 체계 완료 |
| 재시작 후 데이터 복원 | IMPLEMENTED | PostgreSQL, Chroma, Neo4j 퍼시스턴트 적용 |

### 주요 필요 액션
1. **PDF Export 백엔드 기능 개발:** `document_exporter.py` 내 `export_pdf` 함수 추가
2. **프론트엔드 연동 확인:** Timeline UI 및 Export 버튼 작동 상태 점검
3. **Docker Compose & Windows 스크립트 기반 구성:** E2E 테스트 및 배포를 위한 스크립트 작성

