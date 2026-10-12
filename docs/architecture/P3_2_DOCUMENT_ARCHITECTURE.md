# P3.2 Legal Document Intelligence Architecture

## 1. 시스템 개요
P3.2 Legal Document Intelligence는 사건 맥락과 Action Plan을 바탕으로 사용자에게 적합한 법률 문서 초안을 생성하고, 검증, 버전 관리, 출력까지 이어지는 엔드투엔드 파이프라인을 구축하는 모듈입니다.

## 2. 주요 아키텍처 컴포넌트

### 2.1 Document Generation Pipeline (LangGraph)
단순한 프롬프트 호출이 아니라, 아래의 Node들로 구성된 상태 기반 파이프라인(Workflow)입니다.
- **Context Collection Node**: 사건 정보(사실, 증거, 쟁점) 수집 및 GraphRAG 컨텍스트 결합.
- **Requirements Node**: 생성하려는 문서(예: 내용증명)의 필수 요건 검사 및 사용자 확인 필요 항목 도출.
- **Generation Node**: 검증된 정보를 바탕으로 Pydantic 스키마 형태의 구조화된 초안 생성.
- **Verification Node**: 생성된 초안의 사실 관계 오류, 인용 증거 오류 검증 및 환각 차단.
- **Gate Node**: 검증 결과에 따라 재작성 지시 또는 문서 저장소(DB)로 DRAFT 이관.

### 2.2 Document Persistence Layer (PostgreSQL)
- `LegalDocument`, `DocumentRevision` 등 구조화된 스키마를 통해 기존의 "생성 후 망각" 방식과 달리 지속적 관리를 수행합니다.
- 변경 불가능한(Immutable) Revision 방식을 채택하여 사용자의 수작업 변경 이력을 모두 추적합니다.

### 2.3 Verification Engine
- 이전 P2.1, P3.1에서 도입된 Verification Agent를 확장합니다.
- 특히 생성된 문서의 문장들이 실제 `DocumentSourceLink`로 이어지게 하여, "이 주장은 증거 A에서 나왔음"을 시스템적으로 검증합니다.

### 2.4 Exporter Module (DOCX / PDF)
- `python-docx` 및 PDF 변환 도구를 통해 데이터베이스에 저장된 승인된 리비전을 물리적 파일로 변환합니다.
- 서식과 템플릿 로직이 파이썬 코드로 캡슐화되어 일관성 있는 레이아웃을 보장합니다.

## 3. 데이터 및 제어 흐름
1. React UI에서 "문서 생성" 요청 -> FastAPI `POST /cases/{case_id}/documents`
2. LangGraph Pipeline 구동
3. 초안 완성 및 DB 저장 (`DocumentRevision` v1 생성)
4. UI에서 사용자 검토, 필요 시 수정 및 승인 (새로운 Revision 생성)
5. 최종 승인 시 FastAPI `POST /documents/{doc_id}/export` 호출하여 PDF/DOCX 반환

