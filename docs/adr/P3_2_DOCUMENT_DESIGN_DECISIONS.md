# Architecture Decision Record: P3.2 Document Intelligence

## 1. Decision: Immutable Document Revisions
### 대안 1: 단일 본문 필드 덮어쓰기
- 장점: 구현이 단순하다.
- 단점: AI가 수정한 부분과 사용자가 수정한 부분을 추적할 수 없고, 버전 롤백이 불가하다.

### 대안 2: Revision 이력 유지 방식
- **결정**: 모든 문서 수정(AI 재생성 포함)은 새로운 `DocumentRevision`을 생성합니다.
- **이유**: 법률 문서는 단어 하나의 차이로 결과가 달라질 수 있으므로, 변경 이력을 추적 가능하게 남겨 신뢰성을 담보해야 합니다.

## 2. Decision: Structured Content Generation
### 대안 1: 전체 마크다운 텍스트 통째로 생성
- 장점: LLM 호출 1회로 빠름.
- 단점: DOCX/PDF 출력 시 포맷 제어가 매우 어려우며 사실 검증이 힘들다.

### 대안 2: Pydantic을 이용한 구조화(JSON) 생성
- **결정**: 수신인, 발신인, 청구 취지, 본문 섹션별로 분리된 구조를 LLM이 채우도록 강제합니다.
- **이유**: 검증 로직이 섹션 단위로 이루어질 수 있고, `python-docx`에서 서식을 입힐 때 명확히 제어할 수 있습니다.

## 3. Decision: Human-in-the-Loop 의무화
- 문서 생성 후 "자동 외부 발송(메일 전송 등)"을 시스템 내에서 차단합니다.
- 법률 행위의 직접적인 주체는 반드시 사용자(Human)여야 하므로, AI 결과물은 "DRAFT" 상태로만 남으며 사용자의 명시적 승인(`review_status='APPROVED'`)이 있어야만 Export를 허용합니다.

