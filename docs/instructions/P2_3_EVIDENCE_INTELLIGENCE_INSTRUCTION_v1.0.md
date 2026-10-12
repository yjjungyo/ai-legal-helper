# AI Legal Helper — P2.3 Evidence Intelligence 개발지시서 v1.0

- 프로젝트: `C:\myprjs\ai-legal-helper`
- 담당: Gemini Antigravity
- 선행 단계: P2.2 Case Intelligence (보고서 기준 조건부 승인)
- 우선 도메인: 대한민국 주택임대차 분쟁
- 상태: 개발 착수 지시 / 구현 전
- 작성 목적: 증거 원본을 안전하게 관리하고 증거→사실→사건→쟁점의 추적 가능한 연결을 구축

## 1. 개발 목표 및 범위

P2.2에서 구축한 Case, Party, Fact, Event, LegalIssue, CaseRevision을 유지하면서, 사건별 증거 파일의 업로드·보관·추출·검토·연결·검색·인용 기능을 추가한다. 기존 P2.1 Supervisor 및 Verification과 연결한다. P2.4의 본격적인 GraphRAG 및 별도 그래프 DB는 이번 단계에서 구현하지 않는다.

**필수 MVP 입력:** PDF(텍스트 기반), DOCX, TXT, UTF-8 텍스트로 내보낸 문자·메신저 대화, 통화 녹취록 텍스트. 이미지 PDF와 사진은 파일을 수용하되 OCR은 별도 기능 플래그로 구분하고, 미지원 시 `EXTRACTION_UNAVAILABLE`을 명확히 표시한다. 실제 음성 파일의 STT, 법원 제출용 증거능력 판단, 자동 법률 결론은 이번 단계의 필수 범위가 아니다. 형식 지원 여부를 UI에서 명확히 표시한다.

## 2. 기존 시스템 및 기술 제약

- React + TypeScript, FastAPI, LangGraph, P0 AOP/LLM Gateway/TokenTracker 유지.
- PostgreSQL 17 + Docker Desktop(WSL2) + SQLAlchemy 2.x + Alembic 유지. DB는 사건·증거 메타데이터·관계·감사 이력의 정본이다.
- ChromaDB는 기존 **법률 지식 검색용**으로 유지. 사건 증거 검색 인덱스는 별도 네임스페이스/컬렉션과 엄격한 `case_id` 필터를 적용하며, 이번 단계에 필수는 아니다. 법령/판례와 사건 증거를 동일한 출처 유형으로 취급하지 않는다.
- 원본 파일은 로컬 파일 스토리지에 저장하고 PostgreSQL에는 메타데이터 및 경로/참조를 저장한다. 저장 경로는 환경변수로 설정하며 프로젝트 소스 및 Git 저장소에 원문을 커밋하지 않는다.
- 기존 `C:\myprjs\ai-legal-agent` 원본 및 DB는 수정하지 않는다.
- 개발·테스트·실행에 신규 유료 SaaS를 요구하지 않는다. Azure OpenAI는 기존 Gateway를 통해서만 호출한다.
- 로컬 단일 사용자 MVP를 유지하며 FastAPI는 기본적으로 loopback에만 바인딩한다. 인증 전에는 외부 공개를 금지한다.

## 3. 목표 처리 흐름

```text
React Evidence Workspace
  → FastAPI upload / list / review / link APIs
  → Evidence Ingestion Service
      → 파일 형식·크기·확장자/실제 내용 검증
      → 원본 SHA-256 산출 및 불변 저장
      → 텍스트/페이지/문단 추출
      → 위치 추적 가능한 EvidenceSpan 생성
      → PII 최소화 및 LLM 전송 정책 적용
      → LLM Evidence Extractor (후보 사실·당사자·일자·금액)
      → 출처 ID 및 스키마 검증
      → 사용자 검토(승인/수정/제외)
      → Fact / Event / LegalIssue 연결 + CaseRevision
  → Supervisor / Verification: 검토된 증거와 정확한 출처 위치만 전달
```

업로드 성공과 AI 추출 성공, 사용자 승인, 사건 반영은 서로 다른 상태로 관리한다. 파일 업로드 즉시 AI 추론을 확정 사실로 반영하지 않는다.

## 4. 데이터 모델

Alembic 마이그레이션으로 다음 구조를 추가한다. 명칭은 기존 모델 규칙과 충돌하지 않도록 조정할 수 있으나 의미는 유지한다.

### EvidenceDocument

`evidence_id`, `case_id`, `original_filename`, `safe_storage_key`, `media_type`, `size_bytes`, `sha256`, `status`, `source_kind`, `uploaded_at`, `extracted_at`, `extraction_version`, `error_code`, `metadata_json`.

- `status`: `UPLOADED`, `EXTRACTING`, `REVIEW_REQUIRED`, `APPROVED`, `FAILED`, `EXTRACTION_UNAVAILABLE` 등 명시적인 상태 전이.
- 파일명은 화면 표시용으로만 사용하며 저장 경로에 직접 연결하지 않는다.
- 원본 파일은 수정 불가로 취급한다. 교체 시 새 evidence ID와 해시를 생성한다.
- 해시 일치는 **동일 바이트 확인**이지 문서의 진정성·법적 증거능력 보증이 아니다.

### EvidenceSpan

`span_id`, `evidence_id`, `page_number`(nullable), `paragraph_index`(nullable), `char_start`/`char_end`(nullable), `text_excerpt`, `extractor_version`, `location_quality`.

- 페이지가 없는 TXT/대화록은 문단/행/문자 위치를 사용한다.
- 정확한 위치를 보장할 수 없으면 `location_quality=APPROXIMATE` 또는 `UNKNOWN`으로 기록하고 임의 페이지 번호를 만들지 않는다.
- 원문에서 추출한 텍스트와 위치를 연결할 수 있어야 한다.

### EvidenceClaim (추출 후보)

`claim_id`, `case_id`, `evidence_id`, `statement`, `claim_type`, `assertion_status`, `confidence`, `review_status`, `extractor_model`, `created_at`.

- `assertion_status`: `DOCUMENT_STATES`, `PARTY_ALLEGES`, `AI_INFERENCE`, `UNCERTAIN` 등으로 구분.
- `confidence`는 추출 모델의 추정 신뢰도이지 증거의 진실성이나 법적 증명력을 뜻하지 않는다.
- `review_status`: `PENDING`, `APPROVED`, `EDITED`, `REJECTED`.
- 후보마다 최소 하나 이상의 실제 `EvidenceSpan`을 연결한다. 연결 불가한 주장은 근거 부족 후보로 표시한다.

### EvidenceLink / EvidenceReview

- `EvidenceLink`: 승인된 Claim/Span과 기존 `Fact`, `Event`, `LegalIssue`의 연결. 관계 유형(`SUPPORTS`, `CONTRADICTS`, `CONTEXT`, `UNCERTAIN`) 및 생성 출처 기록.
- `EvidenceReview`: 사용자 검토 전후 값, 검토 시각, 처리 유형, 변경 이유 및 CaseRevision 참조. 수정/삭제는 이력으로 추적한다.
- 필요한 경우 명시적 연결 테이블을 사용해 참조 무결성을 유지한다.

## 5. 업로드·보관 보안

1. 확장자만 믿지 않고 MIME/파일 시그니처를 검사한다. 허용 형식·최대 용량·최대 페이지 수를 환경설정으로 제한한다.
2. `..`, 절대경로, 심볼릭 링크 등 경로 탈출을 방지한다. UUID 기반 저장 키를 사용한다.
3. 악성/손상 파일, PDF 암호화, DOCX 압축 폭탄, 비정상 인코딩을 안전하게 거부한다. 바이러스 검사는 미구현이면 한계를 명시한다.
4. SHA-256을 스트리밍 계산하고 파일을 원자적으로 저장한다. DB 기록 실패 시 고아 파일 정리 정책을 둔다.
5. 사건 삭제·증거 삭제 정책은 소프트 삭제/보존/복구 요구를 명시적으로 설계한다. 자동 영구 삭제는 구현하지 않는다.
6. 원본 파일과 추출 텍스트, 임베딩, 로그의 개인정보 노출 위험을 각각 검토한다. 원문은 허가된 로컬 저장소에만 두고, LLM 전송 전 필요한 최소 문맥만 전달한다.
7. 로그·Trace·에러 메시지에 파일 원문, 주민등록번호, 주소, 전화번호, API Key를 남기지 않는다. 원문 열람은 사건 범위로 제한한다.
8. 인증 미구현 상태에서는 단일 사용자 로컬 모드로 제한한다. `case_id`만 알면 외부에서 조회할 수 있는 서비스로 공개하지 않는다.

## 6. 텍스트 추출과 출처 위치

- PDF: 텍스트 기반 PDF의 페이지별 추출. 각 span에 페이지 번호를 기록한다.
- DOCX: 문단 순서 및 표 내용 처리; DOCX는 PDF와 같은 고정 페이지 번호를 임의 생성하지 않는다.
- TXT/대화록: 줄 번호 또는 문자 오프셋을 보존한다. 타임스탬프가 있는 대화록은 발화 시점과 문서 내 위치를 별도로 보관한다.
- 텍스트 추출 실패, 빈 파일, 스캔본, 암호화 문서, 깨진 인코딩은 구분된 오류 상태로 기록한다.
- 추출기 버전과 원본 해시를 함께 저장해 재처리 결과를 재현 가능하게 한다.
- OCR/STT를 나중에 추가할 수 있도록 extractor 인터페이스를 분리한다.

## 7. AI 증거 분석 및 사용자 검토

- 기존 LLM Gateway를 사용해 인물·역할·금액·날짜·행위·통지·진술·모순 후보를 추출한다.
- JSON 응답은 Pydantic으로 검증하고, JSON 파싱 실패·필드 누락·출처 ID 불일치에 대해 제한된 재시도 또는 검토 필요 상태로 전환한다.
- LLM이 존재하지 않는 span ID나 문서 내용을 만들어내면 저장/연결하지 않는다.
- 날짜는 원문 표기, 정규화 값, 정밀도, 불확실성을 분리한다. 통화일과 통화 중 언급된 사건 발생일을 혼동하지 않는다.
- `증거에 적힌 내용`과 `사실로 확인된 내용`을 구분한다. 예: 문자에 '돈을 돌려주겠다'는 발언이 있다고 해서 실제 지급을 완료했다고 기록하지 않는다.
- 기존 Fact와 중복/변경/상충하는 후보를 식별하되 자동 덮어쓰지 않는다.
- React에서 원문 일부와 위치를 함께 보여주고 승인·수정·제외한 뒤에만 기존 Case에 반영한다.
- 승인·수정은 하나의 DB 트랜잭션에서 Fact/Event/Link/CaseRevision과 함께 처리하고 optimistic locking 충돌을 사용자에게 표시한다.

## 8. 증거 충돌 분석

동일 사건에서 서로 다른 날짜, 금액, 당사자, 발언, 이행 여부가 발견되면 `CONTRADICTION_CANDIDATE`로 표시한다. 진술 불일치가 반드시 법률적 모순을 뜻하지는 않으므로 AI가 자동으로 어느 쪽이 참인지 결정하지 않는다. 서로 다른 문서의 정확한 span을 나란히 제시하고 사용자가 검토할 수 있게 한다.

## 9. Supervisor 및 Verification 연동

- 사건 기반 상담 시 `case_id`, `case_version`, 승인된 사실·증거 링크·출처 위치를 Supervisor State에 전달한다.
- Verification은 **법률 근거(법령·판례)**와 **사건 증거(계약서·대화록)**를 별도 출처 유형으로 검사한다.
- 법률 규범을 뒷받침하는 주장은 법률 근거가 필요하며, 사건 발생 사실을 뒷받침하는 주장은 사건 증거를 참조해야 한다.
- 출처가 없는 사실 주장을 `SUPPORTED`로 승격하지 않는다. 사용자 주장에만 기반한 내용은 그렇게 표시한다.
- 문서가 갱신되거나 검토 상태가 바뀌면 이전 분석이 어느 `case_version` 및 증거 버전을 사용했는지 기록한다.
- 기존 P2.1 최대 1회 재검토 제한, AOP 추적, 토큰 합산을 유지한다.

## 10. API 설계

기존 `/api/v1/cases/{case_id}` 하위에 다음 엔드포인트를 추가한다. 기존 API 스타일에 맞춰 조정 가능하다.

| Method | Endpoint | 목적 |
|---|---|---|
| POST | `/evidence` | 파일 업로드 |
| GET | `/evidence` | 사건별 증거 목록 |
| GET | `/evidence/{evidence_id}` | 증거 메타데이터·처리 상태 |
| GET | `/evidence/{evidence_id}/content` | 권한 확인 후 원본 또는 추출 내용 열람 |
| POST | `/evidence/{evidence_id}/extract` | 추출/재처리 요청 |
| GET | `/evidence/{evidence_id}/claims` | 추출 후보와 span 조회 |
| POST | `/evidence/{evidence_id}/reviews` | 승인·수정·제외 처리 |
| GET | `/evidence/conflicts` | 사건 내 충돌 후보 조회 |

실제 전체 경로는 `/api/v1/cases/{case_id}`를 앞에 붙인다. `case_id`와 `evidence_id`가 같은 사건에 속하는지 매 요청마다 검증한다. 긴 작업은 비동기 작업 상태를 노출하며 UI가 멈추지 않도록 한다.

## 11. React Evidence Workspace

- 사건 상세에 **증거** 탭 추가: 업로드, 형식/용량 안내, 목록, 추출 상태, 오류, 파일 해시, 원문 미리보기.
- 문서별 추출 사실 후보와 해당 원문 span을 나란히 표시.
- 후보별 승인/수정/제외, 관련 Fact/Event/Issue 연결 결과 표시.
- 충돌 후보는 관련 두 증거의 출처 위치를 비교 표시.
- 기존 상담 탭에서 증거가 사용된 답변은 출처 파일·페이지/문단 위치를 열어 확인 가능하게 구성.
- 복잡한 디자인보다 실제 동작하는 E2E 흐름을 우선한다.

## 12. 필수 테스트 및 검증

1. PostgreSQL 마이그레이션 적용/재실행 및 기존 P2.2 데이터 보존.
2. PDF(다중 페이지), DOCX, TXT/대화록의 추출과 정확한 span 위치.
3. 스캔 PDF·암호화 PDF·빈 파일·손상 파일·비허용 확장자·대용량 파일 실패 처리.
4. 동일 파일 해시, 서로 다른 파일 해시, 원본 재다운로드 무결성.
5. 경로 탈출, 사건 간 파일/메타데이터 접근, MIME 위장 방지.
6. 출처 없는 LLM 주장, 존재하지 않는 span ID, 잘못된 JSON, 모델 오류 처리.
7. 날짜 불확실성, 발언 시점과 사건 시점 구분, 금액 및 당사자 추출.
8. 사용자 승인/수정/제외 후에만 Fact/Event 반영.
9. Fact/Event/Link/CaseRevision 트랜잭션 롤백과 동시 수정 충돌.
10. 두 증거 간 모순 후보 표시와 원문 위치 비교.
11. Supervisor 및 Verification이 법률 출처와 사건 증거를 구분하는지 검증.
12. React 업로드→분석→검토→사건 반영→상담 E2E.
13. 기존 P0~P2.2 회귀 테스트, AOP/TokenTracker, 개인정보 로그 마스킹.
14. 합성 주택임대차 사례: 계약서 + 해지 통지 문자 + 보증금 반환 관련 대화록 + 내용증명 텍스트.
15. 주요 Python/TypeScript 코드의 한글 주석 표준 준수 확인.

테스트는 단위/통합/실제 Azure 호출/E2E를 구분해 결과와 실패 원인을 기록한다. 실제로 실행하지 않은 테스트를 PASS로 보고하지 않는다.

## 13. 한글 주석 작성 의무

작업 전 `AGENTS.md`와 `docs/development/CODING_COMMENT_STANDARD.md`를 읽는다. 모든 신규·수정 모듈에 모듈 개요, 클래스·함수 Docstring, 주요 분기·예외·트랜잭션·출처 위치 계산의 이유를 **상세한 한국어**로 기록한다. Python은 Google 스타일 Docstring, TypeScript/React는 TSDoc/JSDoc을 따른다. 코드 변경 시 주석을 동기화한다.

## 14. 문서·산출물

- `docs/instructions/P2_3_EVIDENCE_INTELLIGENCE_INSTRUCTION_v1.0.md` (본 문서)
- `docs/architecture/P2_3_EVIDENCE_ARCHITECTURE.md`
- `docs/architecture/P2_3_EVIDENCE_DATA_MODEL.md`
- `docs/architecture/P2_3_PROVENANCE_AND_SECURITY.md`
- `docs/adr/ADR-007-EVIDENCE-STORAGE-AND-PROVENANCE.md`
- `docs/development/P2_3_IMPLEMENTATION_LOG.md`
- `docs/development/P2_3_ISSUE_RESOLUTION.md`
- `docs/evaluation/P2_3_TEST_REPORT.md`
- `docs/evaluation/P2_3_COMPLETION_REPORT.md`

기존 문서를 임의 삭제하지 않는다. 설계 변경 시 지시서 버전과 ADR에 변경 사유를 기록한다.

## 15. 완료 기준 및 제출 지침

- [ ] PostgreSQL에 증거·위치·검토·연결 모델 및 Alembic 마이그레이션 구현
- [ ] 원본 보존, SHA-256, 파일 안전성·경로 검증
- [ ] PDF/DOCX/TXT 추출 및 출처 위치 추적
- [ ] AI 추출 결과에 대한 실제 span ID 검증 및 사용자 승인 흐름
- [ ] 사건 Fact/Event/LegalIssue/CaseRevision 연결 및 충돌 후보 탐지
- [ ] Supervisor/Verification의 법률 출처·사건 증거 구분
- [ ] React 증거 탭과 실제 API 통합
- [ ] 사건 간 격리, 개인정보 로그 보호, 실패·롤백·동시성 테스트
- [ ] 기존 기능 회귀 테스트와 상세 한글 주석 준수
- [ ] 실제 테스트 수치, 미구현 사항, 잔여 위험을 명시한 완료보고서 제출

**P2.3을 완료한 뒤 P2.4는 자동 시작하지 않는다. 완료보고서를 제출하고 검토를 기다린다.**
