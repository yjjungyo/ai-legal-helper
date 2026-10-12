# P2.2 Case Intelligence 단계 완료보고서

## 1. 개요
본 보고서는 AI Legal Helper 프로젝트의 **P2.2 — Case Intelligence & Timeline Engine** 개발 단계 완료를 보고한다.
단발성 질의응답을 제공하던 기존 엔진(P2.1)에 사건별 맥락(당사자, 사실관계, 법률 쟁점, 시간적 흐름)을 추출 및 저장(영속화)하는 기능을 추가하여, 장기적이고 맥락 기반의 AI 법률 자문이 가능해졌다.

## 2. 개발 목표 및 달성 여부

| 항목 | 달성 | 비고 |
|---|:---:|---|
| 사건 생성 및 영속 저장 | O | PostgreSQL 17 (Docker), psycopg 3, SQLAlchemy 적용 완료 |
| 당사자·사실관계 구조화 | O | `Fact Extractor` (JSON Pydantic 파싱) 도입 완료 |
| 사건 타임라인 생성 | O | 추출된 `Fact`를 바탕으로 `Timeline Builder` 연동 완료 |
| 법률 쟁점 / 정보 부족 탐지 | O | 추가 확인이 필요한 사실을 식별하여 반환 로직 적용 완료 |
| 신규 진술에 따른 사건 업데이트 | O | 동시성 충돌 방지(Optimistic Locking) 적용 및 `CaseRevision` 이력 관리 |
| 사건 기반 Supervisor 분석 | O | `legal_workflow.py`에서 DB 조회 및 `case_context` 주입 완료 |
| React 사건 관리 UI | O | 목록, 상세(팩트/타임라인), 채팅 탭 통합 (`App.tsx`, `CaseClient.ts`) 완료 |
| 기존 P0~P2.1 회귀 없음 | O | DB 마이그레이션 적용 완료 및 기존 법률 엔진 재작성 없음 |
| 상세 한글 주석 표준 준수 | O | 모듈, 클래스, 함수 레벨의 `CODING_COMMENT_STANDARD.md` 준수 완료 |

## 3. 핵심 아키텍처 및 구현
1. **PostgreSQL Database**:
   - `SQLAlchemy`를 통해 `Case`, `Party`, `Fact`, `Event`, `LegalIssue`, `CaseRevision`의 6개 엔터티 설계.
   - 데이터베이스는 Windows + Docker Desktop 기반으로 실행되며 포트 `127.0.0.1:5432`와 `pgdata` 볼륨을 통해 데이터를 영구 저장.
   - `Case` 모델에 `version` 컬럼과 `__mapper_args__`를 적용하여 다중 클라이언트 환경에서 발생할 수 있는 동시 수정 충돌을 방지(Optimistic Locking).
   - Alembic을 활용한 마이그레이션 환경 구축 및 테스트 DB 분리 완료.
2. **Case Intelligence Service**:
   - 사용자가 새로운 진술을 추가하면 `FactExtractor`가 Azure OpenAI LLM에 JSON 스키마를 요구하여 당사자와 사실관계를 분류.
   - `TimelineBuilder`가 날짜를 분석해 이벤트를 구성.
   - `CaseManager`가 DB 트랜잭션 단위로 롤백을 통제.
3. **Supervisor Workflow Context Injection**:
   - `supervisor_initialize` 노드에서 제공된 `case_id`로 DB를 쿼리하여 `case_context`를 구성.
   - 이를 전문 에이전트(Specialist)의 `chat_brief` 파라미터에 혼합하여 제공함으로써, 과거에 확정된 사건 정보가 끊임없이 참조되도록 설계.
4. **React Frontend Workspace**:
   - `useConsultation` 훅을 확장하여 활성 `caseId`를 넘기도록 수정.
   - FastAPI (`cases.router`)를 통해 프론트엔드와 통신.

## 4. 추후 과제 (P2.3 대비)
- **개인정보 비식별화**: DB 저장 단계 전 사용자 정보(이름, 전화번호 등)를 가명 처리하는 컴포넌트 도입.
- **다중 사용자 시스템**: 현재는 로컬 환경의 단일 사용자 체제로 가정되어 있으나, 인증(Auth)이 추가되면 사건 소유자(Owner) 식별 로직이 필요함.
- **RAG 문서 업데이트 로직**: 사건 정보가 갱신될 때 관련 최신 법령/판례를 재검색해 캐싱하는 구조 최적화 가능.

---
**P2.2의 모든 목표가 달성되었으므로 검토 후 승인을 요청합니다.**

