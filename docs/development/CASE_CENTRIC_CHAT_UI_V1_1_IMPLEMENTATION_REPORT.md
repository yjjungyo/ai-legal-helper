# Case-Centric Chat UI/UX & Persistent Conversation v1.1 구현 완료 보고서

- **프로젝트:** AI Legal Helper
- **개발 도구:** Antigravity (Pair Programming Agent)
- **기준 지시서:** AI Legal Helper 개발지시서 v1.1 (P0)
- **분석 기준 커밋:** `95a1d4a7f24476f88ede807d98425eb516d15a43`
- **시안 참조:** `ai_legal_helper_case_chat_ui.html`
- **작성일자:** 2026-10-24
- **보고 상태:** 구현 및 단위/통합 테스트 전건 완료 (P0 전수 달성)

---

## 1. 개요 및 구현 배경

AI Legal Helper는 일회성 질문에 답변하는 단순 챗봇이 아니라, 사건 등록부터 종결까지 사실관계, 증거, 상담, 법적 대응 문서 작성을 지속적으로 수행하는 **사건 중심 법률 AI 에이전트(Case-Centric Legal AI Agent)**이다.

기존 v1.0 UI는 ChatGPT와 유사하게 매번 `+ 새 대화 시작` 버튼을 통해 분기된 세션을 생성하고 과거 이력과 현재 작업창이 상하로 분리되는 구조를 취하고 있었다. 이로 인해:
1. 사건 하나에 여러 상담 세션이 파편화되어 과거 상담 맥락이 유실됨.
2. 새 대화 시작 시 이전 상담에서 검토된 법적 쟁점과 분석 결과가 단절됨.
3. 진행 중인 상담 카드와 과거 이력 카드가 상하로 중복 생성되어 사용성 저하.
4. 답변 내 증거 인용(`[E01]`, `[E02]`)을 클릭하여 원문과 발췌 사실을 즉시 열람할 수 있는 인터랙션 부재.

이에 따라 본 작업에서는 **사건 중심 단일 지속 대화 구조(Case = One Persistent Conversation)**로의 전면 개편을 단행하였다.

---

## 2. 핵심 아키텍처 및 데이터 모델 변경 내역

### 2.1 데이터베이스 스키마 확장 (Alembic Migration)
- **`cases.primary_conversation_id` (String(100), Nullable, Indexed)**:
  - 사건당 하나의 영구적인 상담 대화 스레드를 식별하기 위한 대표 대화 세션 ID.
  - 상담 요청 시 `case_id`를 기반으로 `primary_conversation_id`를 자동 조회 및 재사용하여 단일 스레드로 수렴시킴.
- **`consultations.progress` (JSON, Nullable)**:
  - LangGraph 6단계의 실시간 실행 상태(`PENDING`, `RUNNING`, `COMPLETED`, `WAITING_APPROVAL`, `SKIPPED`, `FAILED`), 단계별 시작/완료 일시, 메시지를 영구 보존.
- **마이그레이션 파일**:
  - `backend/alembic/versions/a73ae746b0c0_add_case_chat_v1_1_fields.py` 생성 및 `alembic upgrade head` 성공 반영.

### 2.2 Pydantic & TypeScript 스키마 동기화
- **단계별 6대 상태 정의 (`ConsultationStepStatus`)**:
  - `PENDING`, `RUNNING`, `COMPLETED`, `WAITING_APPROVAL`, `SKIPPED`, `FAILED`
- **단계 및 진행 모델 (`ConsultationStep`, `ConsultationProgress`)**:
  - `ConsultationStep`: `step_id`, `title`, `status`, `started_at`, `completed_at`, `message`
  - `ConsultationProgress`: `request_id`, `current_step`, `steps`, `updated_at`
- **`ConsultationResponse`**:
  - `progress: Optional[ConsultationProgress]` 필드 추가 반영.

---

## 3. 백엔드 파이프라인 및 LangGraph 고도화

### 3.1 자가 참조 법령 검증 결함 수정 (`issue_verifier.py`)
- **결함 내용**: 기존 검증 로직에서 초안 답변(`draft_answer`)에 기재된 법령명이 RAG 검색 출처(`source_texts`)에 실제로 존재하지 않음에도, 초안 답변 텍스트 자체를 검증 텍스트로 합산하여 스스로 검증을 통과하는 자가참조(Self-referential) 버그 발생.
- **수정 조치**: 법령 검증 대상을 `source_texts`로 엄격히 한정하여 RAG 또는 OpenLaw HILT를 통해 실제 입수된 법령 조문만 유효 검증 처리하도록 개선.

### 3.2 HILT 분기 및 실시간 단계 스트리밍 (`legal_workflow.py`)
- `verification_condition`: `candidate_laws`가 존재하고 필수 법령이 누락된 경우, `CAUTIONARY` 판정이라도 `statute_search_approval` 노드로 분기하도록 보장.
- `run_legal_consultation` & `_execute_consultation`: `on_step_callback` 콜백 파라미터를 추가하여 LangGraph 노드 전이 시 실시간으로 DB 및 인메모리 `ConsultationProgress`가 즉시 갱신되도록 파이프라인 연결.

### 3.3 사건 메모리(Case Memory) 및 보안 격리 (`conversation_context.py`)
- `load_conversation_context`:
  - `case_id` 기준 사건 메타데이터(`title`, `case_type`, `status`, `confirmed_facts_count`, `evidences_count`)를 조회하여 `case_memory` 구축.
  - 타 사건 또는 비인가 사용자의 세션 접근 차단(Security Isolation).
- `format_context_for_prompt`:
  - 과거 상담 발췌 시 최상단에 **"원칙: 과거 AI 답변은 작성 당시의 잠정 조언이며 사실 원본이 아닙니다. 최신 Fact 및 등록 증거가 과거 답변과 충돌할 경우 최신 증거가 항상 우선합니다."** 가이드를 강제 주입하여 최신 팩트 우선 원칙(Latest Fact Primacy) 확립.

### 3.4 상담 라우터 단일 스레드 최적화 (`consultation.py`)
- `POST /api/v1/consultations`: 사건의 `primary_conversation_id` 자동 할당 및 초기 6단계 프로그레스 생성.
- `GET /api/v1/cases/{case_id}/consultations`: 시간순 오름차순(`created_at.asc()`)으로 정렬하여 반환, 각 레코드의 `progress` 필드 복원.

---

## 4. 프론트엔드 모듈화 아키텍처 (`frontend/src/components/chat/`)

HTML 프로토타입 시안(`ai_legal_helper_case_chat_ui.html`)을 기반으로 재사용 가능하고 유지보수가 용이한 독립형 컴포넌트들을 구축하였다.

| 컴포넌트 | 파일 경로 | 주요 역할 및 기능 |
|---|---|---|
| **CaseChatHeader** | `components/chat/CaseChatHeader.tsx` | 상단 고정 헤더. 사건명, 진행 상태 배지, 실제 등록 증거/확정 사실/누적 상담 건수 동적 배지 표시 |
| **ChatMessageList** | `components/chat/ChatMessageList.tsx` | 시간순 대화 스트림. 날짜별 구분선 자동 렌더링, 신규 메시지 수신 시 부드러운 하단 자동 스크롤, 빈 상태 추천 질문 칩 제공 |
| **ChatMessage** | `components/chat/ChatMessage.tsx` | 단일 상담 턴(Turn) 통합 렌더러 (`UserMessage` + `AssistantMessage`) |
| **UserMessage** | `components/chat/UserMessage.tsx` | 우측 정렬된 블루 그라데이션 말풍선, 턴 번호 및 발송 시각 표기 |
| **AssistantMessage** | `components/chat/AssistantMessage.tsx` | 좌측 정렬 비서 응답. 진행 중/승인 대기 시 `ConsultationProgress` 표시, 완료 시 `LegalAnswerView`로 인플레이스 전이 |
| **ConsultationProgress** | `components/chat/ConsultationProgress.tsx` | 6단계 LangGraph 진행 상태 체크리스트(아이콘/스피너), HILT 승인 대기 인라인 박스(법령 목록, 승인/건너뛰기 액션) |
| **ChatComposer** | `components/chat/ChatComposer.tsx` | 하단 고정형 질문 입력창. Textarea 자동 높이 조절(최대 140px), Enter 전송, Shift+Enter 줄바꿈, **한글 IME 조합 방어(`e.nativeEvent.isComposing`)** |
| **EvidenceCitation** | `components/chat/EvidenceCitation.tsx` | `[E01]`, `[E02]` 등 인라인 증거 번호 클릭 배지 |
| **EvidenceSourceDrawer** | `components/chat/EvidenceSourceDrawer.tsx` | 우측 슬라이드오버 패널. 증거 문서명, 메타데이터, 추출 사실(Claims), 텍스트 발췌(Spans), 증거 탭 바로가기 링크 제공 (ESC 키 닫기) |
| **ChatDateDivider** | `components/chat/ChatDateDivider.tsx` | 날짜 변경 시점 한국어 표준 일자("YYYY년 MM월 DD일 요일") 구분선 렌더링 |
| **LegalAnswerView** | `components/LegalAnswerView.tsx` | 8대 권장 구성요소 마크다운 파서 내 `[E01]` 증거 태그 감지 및 클릭 핸들러 연동 |
| **useConsultation** | `hooks/useConsultation.ts` | 단일 `messages` 배열 기반 지속 대화 훅. 자동 폴링 및 새로고침 영속성 보장, `startNewConversation` 완전 제거 |
| **ChatSection** | `components/ChatSection.tsx` | 위 모듈들을 조립하는 메인 컨테이너 컴포넌트 |
| **chat.css** | `components/chat/chat.css` | 시안 규격을 준수한 레이아웃, 배지, 스크롤, 모바일 반응형 미디어 쿼리 (<768px) 스타일시트 |

---

## 5. 검증 시나리오 매트릭스 (UI01 ~ UI26)

| 테스트 ID | 검증 항목 | 검증 내용 및 결과 | 판정 |
|---|---|---|:---:|
| **UI01** | Case = One Persistent Conversation | 사건당 1개의 대화 스트림으로 모든 상담 기록 통합 유지 | **PASS** |
| **UI02** | '+ 새 대화 시작' 완전 제거 | 화면 및 훅에서 세션 리셋 및 신규 대화 시작 버튼 완전 제거 | **PASS** |
| **UI03** | 상단 고정 헤더 동적 카운트 | 사건명, 상태, 등록 증거 N건, 확정 사실 M건, 누적 상담 L건 실시간 표시 | **PASS** |
| **UI04** | 일자별 구분선 렌더링 | 날짜가 변경되는 시점에 한국어 일자 배지 중앙 정렬 표시 | **PASS** |
| **UI05** | 의뢰인 질문 말풍선 | 우측 정렬, 블루 그라데이션, 줄바꿈 보존, 발송 시각 및 턴 표기 | **PASS** |
| **UI06** | 법률 비서 답변 컨테이너 | 좌측 정렬, 저울 아바타, 검증 판정 배지(`VERIFIED`, `CAUTIONARY`, `WITHHELD`) 표기 | **PASS** |
| **UI07** | 실시간 6단계 체크리스트 | LangGraph 6개 노드 전이 시 스피너/체크마크 실시간 동기화 | **PASS** |
| **UI08** | HILT 법령 검색 승인 카드 | 승인 대기 시 후보 법령 목록 및 사유 인라인 표시 | **PASS** |
| **UI09** | 인플레이스 상태 전이 | 승인/거절 시 별도 카드 생성 없이 동일 메시지 위치에서 전이 | **PASS** |
| **UI10** | 구조화 답변 렌더러 | 8대 권장 구성요소 카드 서식 및 볼드/코드/목록 마크다운 서식 지원 | **PASS** |
| **UI11** | 증거 인용 클릭 상호작용 | 본문 내 `[E01]` 클릭 시 우측 슬라이드오버 드로어 자동 개방 | **PASS** |
| **UI12** | 드로어 닫기 UX | ESC 키, ✕ 버튼, 배경 딤 영역 클릭 시 드로어 즉시 닫힘 | **PASS** |
| **UI13** | 드로어 실제 증거 매핑 | 목데이터 배제, 실제 등록 증거의 청구 사실 및 원문 발췌(스팬) 렌더링 | **PASS** |
| **UI14** | 하단 고정 대화 입력기 | 뷰포트 하단 고정, 스크롤 스트림과 분리된 안정적 영역 확보 | **PASS** |
| **UI15** | 한글 IME 조합 중복 방어 | `e.nativeEvent.isComposing` 검사를 통해 한글 입력 시 중복 전송 원천 차단 | **PASS** |
| **UI16** | 단축키 지원 | Enter 전송, Shift+Enter 줄바꿈 동작 | **PASS** |
| **UI17** | 입력창 비활성화 제어 | 상담 분석 중 입력창 및 전송 버튼 비활성화 및 안내 문구 노출 | **PASS** |
| **UI18** | 빈 대화 추천 질문 칩 | 첫 상담 시작 전 4대 법률 추천 질의 칩 제공 및 클릭 시 자동 입력 | **PASS** |
| **UI19** | 새로고침(F5) 영속성 복원 | 새로고침 시 전체 대화 이력 복원 및 진행 중 상담 자동 폴링 재개 | **PASS** |
| **UI20** | 모바일 반응형 규격 | 768px 미만 뷰포트에서 드로어 전폭(100vw) 전이 및 헤더 랩핑 | **PASS** |
| **UI21** | primary_conversation_id 영속화 | DB `cases.primary_conversation_id` 컬럼 반영 및 자동 재사용 | **PASS** |
| **UI22** | 시간순 오름차순(ASC) 일원화 | `GET /api/v1/cases/{case_id}/consultations` 과거부터 현재 순 정렬 반환 | **PASS** |
| **UI23** | 과거 턴 사건 메모리 프롬프트 주입 | Synthesizer/Router 프롬프트에 이전 턴 요약 및 사건 메모리 자동 주입 | **PASS** |
| **UI24** | 최신 팩트 우선 원칙 | 프롬프트에 과거 AI 답변보다 최신 확정 Fact가 우선함을 명시 | **PASS** |
| **UI25** | 보안 격리 (Security Isolation) | 타 사건 및 타 사용자 세션 접근 시 `PermissionError` 차단 | **PASS** |
| **UI26** | 기존 메타데이터 완벽 보존 | 기존 DB의 `request_id`, `conversation_id`, `turn_index` 무손실 보존 | **PASS** |

---

## 6. 테스트 수행 결과

### 6.1 백엔드 단위 및 통합 테스트 (Pytest)
- `backend/tests/unit/test_conversation_context.py`: **8 passed**
- `backend/tests/unit/test_hilt_statute_search.py`: **8 passed**
- `backend/tests/unit/test_issue_verification.py`: **25 passed**
- `backend/tests/unit/test_case_centric_chat_api.py`: **5 passed**
- **전체 백엔드 테스트 스위트 전원 통과 (총 296 passed, 0 failed)**

### 6.2 프론트엔드 빌드 (TypeScript & Vite)
- `npm run build --prefix frontend`: **성공 (0 errors)**
  - `dist/assets/index-CP0mEHOc.js` 및 CSS 정상 빌드 완료.

---

## 7. 주석 및 코딩 표준 준수 확인 (`CODING_COMMENT_STANDARD.md`)

- **Python**: 모든 신규/수정 파일(`conversation_context.py`, `legal_workflow.py`, `consultation.py`, `issue_verifier.py`, `test_case_centric_chat_api.py`)에 한국어 모듈 Docstring 및 Google 스타일 함수/클래스 Docstring 작성.
- **TypeScript/React**: 신규 모듈화 컴포넌트(`CaseChatHeader.tsx`, `ChatMessageList.tsx`, `ChatMessage.tsx`, `UserMessage.tsx`, `AssistantMessage.tsx`, `ConsultationProgress.tsx`, `ChatComposer.tsx`, `EvidenceCitation.tsx`, `EvidenceSourceDrawer.tsx`, `ChatDateDivider.tsx`, `useConsultation.ts`)에 표준 TSDoc 작성 및 주요 조건 분기/상태 전이 이유 명시.
- 민감 정보(API Key, 사용자 원문 등) 주석 및 로그 미노출 확인.

---

## 8. 결론

지시서 **AI Legal Helper 개발지시서 v1.1**의 모든 요구사항(P0-01 ~ P0-08, P1-01 ~ P1-03 및 UI01 ~ UI26)을 완벽히 충족하였으며, 사건당 단일 지속 대화(One Persistent Conversation) 아키텍처 구축을 성공적으로 완료하였습니다.

