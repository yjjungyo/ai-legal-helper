# P3.2 Document Domain Model

## 1. 개요
P3.2 Legal Document Intelligence 단계에서 법률문서(내용증명 등) 초안의 상태, 버전 관리, 출력 파일을 관리하기 위한 PostgreSQL 데이터베이스 모델 설계입니다.

## 2. 테이블 스키마

### 2.1 LegalDocument
단일 법률문서 단위를 나타내며, `Case`와 `LegalAction`(선택)에 종속됩니다.
- `id` (String, PK, UUID)
- `case_id` (String, FK -> cases.id)
- `action_id` (String, FK -> legal_actions.id, nullable)
- `document_type` (String): 예) "내용증명", "계약해지통보"
- `title` (String): 문서 제목
- `status` (String): DRAFT, PENDING_REVIEW, APPROVED, REJECTED, EXPORTED
- `current_revision_id` (String, FK -> document_revisions.id, nullable)
- `created_at` (DateTime)
- `updated_at` (DateTime)

### 2.2 DocumentRevision
문서의 특정 버전을 나타냅니다. AI가 생성한 초안과 사용자가 수정한 버전을 구분하며, 모든 수정은 새로운 리비전으로 저장됩니다.
- `id` (String, PK, UUID)
- `document_id` (String, FK -> legal_documents.id)
- `revision_number` (Integer): 순차 증가
- `content` (Text): 렌더링된 텍스트 본문
- `structured_content` (JSON): 섹션별 구조화된 데이터 (수신인, 발신인, 본문 등)
- `generation_context_version` (Integer): 이 초안 생성 시점의 Case 버전 (Case.version)
- `verification_status` (String): UNVERIFIED, PASS, WARNING, FAIL, NEEDS_USER_CONFIRMATION
- `created_at` (DateTime)

### 2.3 DocumentSourceLink
문서 특정 리비전의 한 부분(문장/섹션)이 어떤 사건 정보(사실, 증거, 법률 쟁점)에 기반하는지 추적합니다.
- `id` (String, PK, UUID)
- `document_revision_id` (String, FK -> document_revisions.id)
- `section_id` (String): 문서 내 섹션/단락 식별자
- `source_type` (String): FACT, EVIDENCE, LEGAL_ISSUE
- `source_id` (String)
- `evidence_span_id` (String, nullable)
- `verification_status` (String)

### 2.4 DocumentReview
사용자나 Verification Agent가 리비전에 대해 남긴 검토 내역(리뷰 코멘트 및 승인 상태)을 기록합니다.
- `id` (String, PK, UUID)
- `document_revision_id` (String, FK -> document_revisions.id)
- `review_status` (String): APPROVED, REJECTED, CHANGES_REQUESTED
- `review_comment` (Text)
- `reviewed_at` (DateTime)

### 2.5 DocumentExport
승인된 문서를 DOCX나 PDF로 출력한 결과물의 메타데이터를 저장합니다.
- `id` (String, PK, UUID)
- `document_revision_id` (String, FK -> document_revisions.id)
- `file_format` (String): DOCX, PDF
- `file_path` (String): 내부 스토리지 또는 S3 경로
- `checksum` (String): 위변조 방지 SHA256
- `created_at` (DateTime)

