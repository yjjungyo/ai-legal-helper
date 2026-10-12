# AI Legal Helper — P3.2 Legal Document Intelligence 개발지시서 v1.0

**프로젝트:** `C:\myprjs\ai-legal-helper`  
**개발 단계:** P3.2 — Legal Document Intelligence  
**핵심 목표:** 사건 분석과 Action Plan을 기반으로 법률문서 초안을 생성하고, 근거 검증·사용자 검토·버전 관리·파일 출력을 지원한다.

## 1. 개발 원칙

1. P0~P3.1 기능과 기존 React UI를 유지한다.
2. `C:\myprjs\ai-legal-agent` 원본 프로젝트는 수정하지 않는다.
3. PostgreSQL을 문서 상태 및 버전의 Source of Truth로 사용한다.
4. 기존 Evidence GraphRAG와 Action Planner를 재사용한다.
5. AI가 생성한 문서는 반드시 `DRAFT` 상태에서 시작한다.
6. 승인된 사실, 사용자 주장, AI 추론을 구분한다.
7. 검증되지 않은 날짜·금액·인명·법률 조항을 임의 생성하지 않는다.
8. 문서 작성과 외부 발송은 분리한다. 이번 단계에서는 자동 발송하지 않는다.
9. 법률적 판단에 불확실성이 있으면 경고 및 사용자 확인 항목을 표시한다.
10. 기존 한글 주석 표준과 개발지시서 버전 관리 규칙을 준수한다.

## 2. 구현 범위

우선 대한민국 주택 임대차 분쟁에 필요한 문서 유형을 구현한다.

### 필수

- 임대차보증금 반환 요구 내용증명
- 임대차계약 종료 통지서
- 사건 사실관계 및 타임라인 정리서
- 증거목록 및 증거설명서

### 확장 가능 구조

- 임차권등기명령 신청 준비자료
- 지급명령 신청 준비자료
- 보증금 반환 청구소송 준비자료

법원 제출용 서식의 자동 완성은 이번 단계에서 필수 구현하지 않는다. 향후 공식 서식과 필수 기재사항을 검증한 뒤 확장한다.

## 3. Document Domain Model

PostgreSQL에 문서 관련 모델을 설계한다.

### LegalDocument

- `id`
- `case_id`
- `action_id`
- `document_type`
- `title`
- `status`
- `current_revision_id`
- `created_at`
- `updated_at`

### DocumentRevision

- `id`
- `document_id`
- `revision_number`
- `content`
- `structured_content`
- `generation_context_version`
- `verification_status`
- `created_at`

### DocumentSourceLink

- `id`
- `document_revision_id`
- `section_id`
- `source_type`
- `source_id`
- `evidence_span_id`
- `verification_status`

### DocumentReview

- `id`
- `document_revision_id`
- `review_status`
- `review_comment`
- `reviewed_at`

### DocumentExport

- `id`
- `document_revision_id`
- `file_format`
- `file_path`
- `checksum`
- `created_at`

기존 모델과 중복되는 경우 재사용한다.

Alembic 마이그레이션을 적용한다.

## 4. Document Generation Pipeline

다음 처리 흐름을 구현한다.

1. 사용자가 Action Plan에서 문서 작성 선택
2. 사건 및 Action 상태 확인
3. 승인된 사실과 증거 조회
4. 관련 법률 쟁점 및 법적 근거 조회
5. 문서 유형별 필수 정보 검사
6. 부족한 정보에 대한 확인 질문 생성
7. 구조화된 문서 초안 생성
8. 사실·증거·법률 근거 검증
9. 사용자 검토 및 수정
10. 승인된 버전의 DOCX/PDF 출력

LLM 생성 결과는 Pydantic 스키마로 검증한다.

문서 유형별 템플릿과 생성 로직을 분리하여 확장 가능하게 설계한다.

## 5. 내용증명 생성기

전세보증금 미반환 사건을 대표 시나리오로 구현한다.

필수 입력:

- 발신인
- 수신인
- 임대차 목적물
- 임대차계약 체결일 및 기간
- 보증금 금액
- 계약 종료 통지 관련 사실
- 반환 요구 내용
- 관련 증거
- 문서 작성일

문서 구성:

1. 제목
2. 수신인 및 발신인
3. 임대차계약의 주요 내용
4. 계약 종료 관련 사실
5. 보증금 반환 요구
6. 증거 및 관련 경위
7. 필요한 경우 법적 조치 안내
8. 최종 요청사항
9. 작성일 및 발신인 표시

문서 유형과 실제 사용 목적에 따라 항목을 조정할 수 있도록 한다.

특히 다음을 구분한다.

- 확인된 계약 사실
- 당사자가 주장하는 사실
- 상대방의 진술
- 법률적 판단
- 향후 조치 예정

상대방의 진술이나 법률적 평가를 확정 사실로 바꾸지 않는다.

## 6. 법률문서 검증

`DocumentVerification` 모듈을 구현한다.

### 사실 검증

- 금액과 날짜가 사건 정보와 일치하는가?
- 문서에 등장하는 당사자가 정확한가?
- 사건에 없는 사실이 추가되지 않았는가?
- 인용한 증거가 실제 존재하는가?
- 증거가 현재 사건에 속하는가?
- 증거의 승인 상태가 유효한가?
- 원본 EvidenceSpan과 인용 내용이 일치하는가?

### 법률 근거 검증

- 법령 및 판례 식별자가 유효한가?
- 해당 근거가 문서의 법률 주장과 관련 있는가?
- 확인되지 않은 법률 요건을 확정적으로 기재하지 않았는가?
- 법적 기한과 일반적인 권고 시점을 구분했는가?
- 법률 근거의 기준일과 최신성을 확인했는가?

### 검증 결과

- `PASS`
- `WARNING`
- `FAIL`
- `NEEDS_USER_CONFIRMATION`

검증 실패나 필수 정보 누락이 있으면 최종 승인 및 공식 문서 출력을 제한한다.

사용자에게 어떤 항목이 문제인지 구체적으로 표시한다.

## 7. 문서 수정 및 버전 관리

- AI 초안과 사용자 수정본을 구분한다.
- 모든 수정은 새로운 Revision으로 저장한다.
- 이전 버전을 덮어쓰지 않는다.
- 변경된 문장을 비교할 수 있어야 한다.
- 사용자 승인 시 승인한 정확한 Revision을 기록한다.
- 승인 후 내용 변경 시 다시 검토하도록 한다.
- 사건 정보 변경으로 기존 문서가 오래된 상태가 되면 재검토 필요 표시한다.
- 사용자의 직접 수정 내용을 AI 재생성 과정에서 무단 삭제하지 않는다.

## 8. DOCX 및 PDF 출력

Python 기반 문서 출력 기능을 구현한다.

### DOCX

- `python-docx` 사용
- 한글 문서 레이아웃
- 제목, 본문, 날짜, 발신인 표시
- 문단 및 줄 간격 관리
- 사용자 수정 가능

### PDF

- 서버 환경에서 재현 가능한 PDF 생성 방식 사용
- 한글 글꼴 및 줄바꿈 검증
- DOCX와 PDF의 내용 일치 검사
- 페이지 넘침 및 누락 검증

문서 내용에 포함된 개인정보가 로그나 임시 파일에 노출되지 않도록 처리한다.

출력 파일은 해당 사건과 문서 Revision에 연결한다.

## 9. FastAPI

다음 API를 구현한다.

- 문서 초안 생성
- 사건별 문서 목록
- 문서 상세 조회
- 문서 수정
- 문서 Revision 목록
- Revision 비교
- 문서 검증
- 문서 승인
- DOCX 다운로드
- PDF 다운로드

모든 API는 사건 ID와 문서 소속 관계를 검증한다.

문서 생성 및 검증의 오류 상태를 명확하게 반환한다.

## 10. React UI

기존 Case Workspace에 `Documents` 탭을 추가한다.

필수 기능:

- Action Plan에서 문서 작성 시작
- 문서 유형 선택
- 부족한 정보 확인
- AI 초안 생성
- 문서 편집
- 증거 및 법률 근거 확인
- 검증 결과 표시
- 버전 비교
- 사용자 승인
- DOCX/PDF 다운로드

UI는 기존 디자인과 일관성을 유지한다.

문서가 아직 검증되지 않았을 때 사용자에게 명확히 알린다.

## 11. LangGraph 연동

문서 작성은 다음과 같은 별도 워크플로우로 구성한다.

- `document_context_node`
- `document_requirements_node`
- `document_generation_node`
- `document_verification_node`
- `document_review_gate_node`

기존 Supervisor, Verification Agent, GraphRAG를 재사용한다.

무한 재시도를 방지하기 위해 검증 후 재생성 횟수를 제한한다.

문서 승인 단계는 반드시 사용자가 수행한다.

## 12. 테스트

필수 테스트:

1. 정상적인 보증금 반환 요구 내용증명 생성
2. 계약 종료 통지일 누락
3. 보증금 금액 불일치
4. 수신인 정보 누락
5. 다른 사건 증거 참조
6. 반려된 증거 인용
7. 존재하지 않는 법률 조항 인용
8. 사용자 수정 후 Revision 생성
9. 승인 이후 수정 시 재검증
10. 사건 정보 변경 시 문서 재검토
11. DOCX 한글 출력
12. PDF 한글 출력
13. 출력 파일 내용 일치
14. 파일 다운로드 접근 제한
15. Neo4j 장애 시 Fallback
16. 기존 P0~P3.1 회귀 테스트

테스트 건수, PASS/FAIL, 실행 명령 및 주요 로그를 기록한다.

## 13. AI Master 평가 대비

이번 단계에서 다음을 설명할 수 있어야 한다.

- 왜 단순 프롬프트로 문서를 생성하지 않았는가?
- 문서의 각 문장이 어떤 사건 사실 및 증거에 근거하는가?
- 사용자 승인과 자동 검증을 분리한 이유는 무엇인가?
- AI가 생성한 잘못된 법률 주장을 어떻게 차단하는가?
- 사건 변경 시 기존 문서를 어떻게 관리하는가?
- 문서 생성 자동화가 실제로 시간을 얼마나 절약하는가?
- DOCX/PDF 생성의 품질을 어떻게 검증했는가?

가능하면 수작업 작성과 AI 지원 작성의 시간을 동일한 시나리오로 비교한다.

측정하지 않은 성과를 수치로 주장하지 않는다.

## 14. 필수 산출물

- `docs/instructions/P3_2_LEGAL_DOCUMENT_INTELLIGENCE_INSTRUCTION_v1.0.md`
- `docs/architecture/P3_2_DOCUMENT_ARCHITECTURE.md`
- `docs/architecture/P3_2_DOCUMENT_DOMAIN_MODEL.md`
- `docs/adr/P3_2_DOCUMENT_DESIGN_DECISIONS.md`
- `docs/development/P3_2_IMPLEMENTATION_LOG.md`
- `docs/development/P3_2_ISSUE_RESOLUTION.md`
- `docs/evaluation/P3_2_TEST_REPORT.md`
- `docs/evaluation/P3_2_MASTER_QA.md`
- `docs/evaluation/P3_2_COMPLETION_REPORT.md`

기존 개발지시서 인덱스도 갱신한다.

## 15. 완료 기준

- 4개 필수 문서 유형의 초안 생성
- 사건·증거·법률 근거 연결
- Document Verification
- 사용자 검토 및 Revision 관리
- DOCX/PDF 출력
- React Documents UI
- 테스트 및 회귀 검증
- AI Master 평가용 구현·검증 근거 확보

