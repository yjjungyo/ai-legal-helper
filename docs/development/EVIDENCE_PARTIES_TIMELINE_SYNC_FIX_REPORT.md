# AI Legal Helper — Evidence → Facts → Parties / Timeline 자동 생성 및 동기화 개선 완료보고서

- **작성일:** 2026-10-23
- **기준 브랜치:** `main`
- **대상 범위:** P0 (Evidence → Facts → Parties / Timeline 자동 생성 및 생명주기 정합성) + P1 (기존 사건 Backfill 복구 및 UI/API 연동) + 필수 검증 시나리오 (T01~T18)

---

## 1. 문제 원인 요약

기존 시스템에서 증거 문서(`EvidenceDocument`) 업로드 및 `EvidenceClaim` 승인 이후 확정 사실(`Fact`)은 정상 생성되었으나 당사자(`Party`)와 타임라인(`Event`)이 생성되지 않거나 비정상 동작하던 근본 원인은 다음 4가지였다.

1. **증거 승인 경로의 `Party` 생성 로직 부재 (`evidence_manager.py`):**
   - 일반 진술 입력(`manager.process_new_statement`)에만 LLM 기반 `Party` 추출이 존재했고, 증거 검토 승인(`process_evidence_review`) 경로에는 `PARTY_INFO` 사실을 `Party` 테이블로 변환·동기화하는 로직이 전혀 없었다.
2. **단일 날짜 필드에 종속된 타임라인 빌더 (`timeline.py`):**
   - `build_timeline_from_facts()`가 `Fact.occurred_at`이 비어 있으면 본문(`Fact.statement`)에 명확한 날짜나 기간(`2022년 3월 1일부터 2024년 2월 28일까지`)이 있어도 이벤트를 생성하지 못했으며, 같은 날짜의 서로 다른 법적 행위(`잔금 지급기일`, `임대차 기간 시작`, `주택 인도 예정일`)를 단일 이벤트로 뭉개어 첫 문장만 남기는 정보 손실이 있었다.
3. **일관되지 않은 엔티티 동기화 호출:**
   - `APPROVE`, `EDIT`, `REJECT`, `delete_evidence`, `process_new_statement` 경로가 각각 개별적으로 동작하거나 `db.query(Event).filter_by(case_id=...).delete()`로 수동 이벤트까지 일괄 삭제하는 문제가 있었다.
4. **기생성 사건(Legacy Case)의 미복구 상태:**
   - 이미 `Fact`만 생성되어 저장된 기존 사건(`Test Case` 등)을 재스캔하여 `Parties`와 `Timeline`을 채우는 복구(Backfill) 도구가 없었다.

---

## 2. 수정 파일 및 스키마 변경 내역

### 2.1 데이터베이스 모델 및 마이그레이션
- [`backend/src/ai_legal_helper/database/models.py`](../../backend/src/ai_legal_helper/database/models.py)
  - `Party` 모델 확장:
    - `source_type` (`MANUAL`, `STATEMENT_EXTRACTED`, `EVIDENCE_DERIVED`)
    - `verification_status` (`VERIFIED`, `DOCUMENT_VERIFIED`, `PARTY_ASSERTED`, `UNVERIFIED`)
    - `related_fact_ids` (JSON), `related_claim_ids` (JSON)
  - `Event` 모델 확장:
    - `occurrence_status` (`ACTUAL`, `SCHEDULED`, `REQUESTED`, `NEEDS_VERIFICATION`)
    - `source_type` (`MANUAL`, `STATEMENT_EXTRACTED`, `EVIDENCE_DERIVED`)
- [`backend/alembic/versions/b8e41c73d905_add_party_and_event_provenance_fields.py`](../../backend/alembic/versions/b8e41c73d905_add_party_and_event_provenance_fields.py)
  - `parties` 및 `events` 신규 컬럼 추가 및 기존 레코드 기본값 백필(`alembic upgrade head` 적용 완료).

### 2.2 백엔드 핵심 모듈
- [`backend/src/ai_legal_helper/case_intelligence/entity_sync.py`](../../backend/src/ai_legal_helper/case_intelligence/entity_sync.py) *(신규)*
  - `extract_parties_from_facts()`: `PARTY_INFO` 우선 스캔 및 타 유형 Fact 보강 추출, 어순 무관 `(name, role)` 정규화, 일반 명사/행위 서술 배제(`T04`), 실체적 법률 역할(`임대인`, `임차인`, `원고`, `피고`, `채권자`, `채무자`, `사용자`, `근로자` 등)과 보조 역할(`발신자`, `수신자`, `작성자`) 및 연락처 병합(`T02`, `T03`), 대립 당사자 관계(`party_relationship`) 자동 추론.
  - `synchronize_case_parties()`: 수동(`MANUAL`) `Party`를 보존하면서 증거 파생(`EVIDENCE_DERIVED`) `Party`를 추가·갱신·제거.
  - `synchronize_case_timeline()`: 수동(`MANUAL`) `Event`를 보존하면서 최신 `Fact` 집합으로부터 타임라인 재구축 및 `Fact.occurred_at` 보강.
  - `synchronize_case_entities()`: 단일 트랜잭션 내 `Parties` + `Timeline` 통합 동기화.
  - `rebuild_case_entities(db, case_id, dry_run=True)`: 기존 사건의 누락된 `Fact`·`Party`·`Event` 복구 및 Neo4j 동기화 큐 등록.
- [`backend/src/ai_legal_helper/case_intelligence/timeline.py`](../../backend/src/ai_legal_helper/case_intelligence/timeline.py)
  - `extract_events_from_fact()` 및 `build_timeline_from_facts()` 고도화:
    - `conflict_detector.extract_dates_with_validation` 연동으로 무효 달력 날짜(`2026년 2월 31일` 등) 배제(`T08`).
    - 기간 문장(`YYYY년 M월 D일부터 YYYY년 M월 D일까지`)을 `계약 시작`과 `계약 종료` 2개의 개별 이벤트로 분리(`T06`).
    - 동일 날짜의 서로 다른 법적 행위(`지급기일`, `계약 시작`, `인도 예정일`, `퇴거 예정`, `반환 요청 기한`, `통지 발송` 등)를 별도 `Event`로 보존(`T07`).
    - 실제 발생(`ACTUAL`), 예정/기일(`SCHEDULED`), 요청 기한(`REQUESTED`), 확인 필요(`NEEDS_VERIFICATION`) 구분.
- [`backend/src/ai_legal_helper/case_intelligence/evidence_manager.py`](../../backend/src/ai_legal_helper/case_intelligence/evidence_manager.py)
  - `process_evidence_review()`(`APPROVE` / `EDIT` / `REJECT`) 및 `_rebuild_case_timeline()`에서 `synchronize_case_entities()`를 원자적으로 호출하여 증거 상태 변경 즉시 `Fact`, `Party`, `Event`, `Neo4j` 동기화 큐가 일관되게 갱신되도록 수정.
- [`backend/src/ai_legal_helper/case_intelligence/manager.py`](../../backend/src/ai_legal_helper/case_intelligence/manager.py)
  - `process_new_statement()`에서 전체 `Event` 무조건 삭제를 제거하고 `synchronize_case_entities()`를 호출하여 수동 데이터 보존 및 당사자·타임라인 동기화 수행.
- [`backend/src/ai_legal_helper/api/routes/cases.py`](../../backend/src/ai_legal_helper/api/routes/cases.py) & [`backend/src/ai_legal_helper/api/schemas/case.py`](../../backend/src/ai_legal_helper/api/schemas/case.py)
  - `PartySchema`, `EventSchema` 확장.
  - `GET /cases/{case_id}` 조회 시 `facts`는 존재하나 `parties`와 `events`가 비어 있는 레거시 사건 자동 복구 및 `POST /cases/{case_id}/rebuild-entities` 엔드포인트 추가.
- [`backend/src/ai_legal_helper/database/graph_sync.py`](../../backend/src/ai_legal_helper/database/graph_sync.py)
  - Neo4j 스냅샷 투영 시 `Party`(`party_relationship`, `source_type`, `verification_status`) 및 `Event`(`occurrence_status`, `source_type`) 메타데이터 포함.

### 2.3 프론트엔드 UI 연동
- [`frontend/src/types/case.ts`](../../frontend/src/types/case.ts) & [`frontend/src/pages/CaseWorkspace.tsx`](../../frontend/src/pages/CaseWorkspace.tsx)
  - `FactsTab`에서 당사자 역할·상대방 관계·보조 노트(연락처, 발신/수신 역할) 표시 및 타임라인 이벤트의 `event_type`·`occurrence_status` 배지(`예정/기일`, `요청 기한`, `실제 발생`, `확인 필요`) 시각화.
  - `facts` 및 `overview` 탭 전환 시 최신 사건 상세 데이터 자동 갱신.

---

## 3. 실제 사건(`Test Case`) 복구 전후 결과 비교

대상 사건 ID: `f8c3d8a5-fad6-47ec-b987-77f31bd0379a`

| 구분 | 복구 전 | 복구 후 (`rebuild_case_entities`) | 2차 실행 (멱등성 검증) |
|---|---:|---:|---:|
| **확정 사실 (Facts)** | 75건 | 75건 | 75건 |
| **당사자 (Parties)** | **0명** | **2명** | **2명** (추가/삭제 0) |
| **타임라인 (Events)** | **0건** (초기) | **16건** | **16건** (중복 누적 0) |

### 3.1 복구된 당사자 (Parties)
1. **박정훈 (`임대인`)**
   - 관계: `임대차계약 당사자 (상대방 임차인: 이수현)`
   - 노트: `연락처: 010-4826-1357 | 문서/대화상 역할: 수신자`
   - 검증 상태: `DOCUMENT_VERIFIED` (`EVIDENCE_DERIVED`)
2. **이수현 (`임차인`)**
   - 관계: `임대차계약 당사자 (상대방 임대인: 박정훈)`
   - 노트: `연락처: 010-7254-9142 | 문서/대화상 역할: 발신자`
   - 검증 상태: `DOCUMENT_VERIFIED` (`EVIDENCE_DERIVED`)

### 3.2 복구된 주요 타임라인 이벤트 (Timeline)
- `2022-02-20` | `계약 체결` (`ACTUAL`) — 이 문서는 2022년 2월 20일 체결된 주택임대차계약서이다.
- `2022-02-20` | `지급기일` (`SCHEDULED`) — 계약금 지급기일은 2022년 2월 20일이다.
- `2022-03-01` | `계약 시작` (`SCHEDULED`) — 임대차 기간 시작 (2022-03-01)
- `2022-03-01` | `인도 예정일` (`SCHEDULED`) — 주택 인도 예정일은 2022년 3월 1일이다.
- `2022-03-01` | `지급기일` (`SCHEDULED`) — 잔금 지급기일은 2022년 3월 1일이다.
- `2024-02-28` | `계약 종료` (`SCHEDULED`) — 임대차 기간 종료 (2024-02-28)
- `2026-04-01` | `통지 발송` (`ACTUAL`) — 2026년 4월 1일 10시 24분에 이수현이 메시지를 보냈다.
- `2026-04-01` | `통지 발송` (`ACTUAL`) — 2026년 4월 1일 13시 10분에 박정훈이 메시지를 보냈다.
- `2026-04-03` | `통지 발송` (`ACTUAL`) — 2026년 4월 3일 18시 20분에 이수현이 다시 메시지를 보냈다.
- `2026-04-04` | `통지 발송` (`ACTUAL`) — 2026년 4월 4일 9시 7분에 박정훈이 메시지를 보냈다.
- `2026-07-18` | `법적 절차` (`ACTUAL`) — 가압류 등기 접수일은 2026년 7월 18일이다.
- `2026-09-25` | `사실 발생` (`ACTUAL`) — 통화일시 및 보증금 전액 반환 곤란 취지 통화 (2건)
- `2026-09-30` | `반환 요청 기한` (`REQUESTED`) — 이수현은 2026년 9월 30일에 맞춰 전세보증금 3억 원의 반환을 요청하였다. (관련 Fact 4건 병합)
- `2026-09-30` | `퇴거 예정` (`SCHEDULED`) — 이수현은 개인 사정으로 2026년 9월 30일에 이사 나가야 한다고 통지하였다.
- `2026-10-02` | `사실 발생` (`ACTUAL`) — 열람일은 2026년 10월 2일이다.

---

## 4. 테스트 결과 (T01 ~ T18)

테스트 파일: [`backend/tests/unit/test_parties_timeline_sync.py`](../../backend/tests/unit/test_parties_timeline_sync.py)

| 테스트 ID | 검증 항목 | 결과 |
|---|---|---|
| **T01** | 기본 당사자 추출 (`임대인은 박정훈이다`, `임차인은 이수현이다`) | **PASS** |
| **T02** | 당사자 중복 제거 및 보조 역할(`수신자`)·연락처 병합 | **PASS** |
| **T03** | 어순 다른 당사자 문장 처리 (`임대인은 박정훈이다`, `임대인 박정훈`, `박정훈은 임대인이다`) | **PASS** |
| **T04** | 이름 미확정 사실 보호 (`임대인은 보증금 반환을 지연했다` 등에서 쓰레기 Party 미생성) | **PASS** |
| **T05** | 단일 날짜 이벤트 생성 (`occurred_at=None` 상태에서 본문 날짜 추출 및 `SCHEDULED` 분류) | **PASS** |
| **T06** | 기간 문장 이벤트 분리 (`2022-03-01` 계약 시작 / `2024-02-28` 계약 종료 분리 및 Fact ID 연결) | **PASS** |
| **T07** | 동일 날짜 다중 이벤트 보존 (`2022-03-01` 잔금 지급기일, 계약 시작, 인도 예정일 3건 모두 보존) | **PASS** |
| **T08** | 잘못된 달력 날짜 방어 (`2026년 2월 31일` 및 날짜 없는 사실에서 이벤트 미생성) | **PASS** |
| **T09** | `EvidenceClaim` `EDIT` 정합성 (`박정훈` → `김정훈` 수정 시 이전 단독 근거 Party 제거 및 갱신) | **PASS** |
| **T10** | `EvidenceClaim` `REJECT` 정합성 (단독 근거 Claim 반려 시 Fact, Party, Event 모두 제거) | **PASS** |
| **T11** | 다중 근거 Claim `REJECT` 보호 (2개 승인 Claim 중 1개만 반려 시 Party·Fact 유지) | **PASS** |
| **T12** | 수동(`MANUAL`) Party / Event 보호 (증거 동기화 시 수동 데이터 삭제·덮어쓰기 방지) | **PASS** |
| **T13** | 멱등성 검증 (`synchronize_case_entities` 3회 연속 실행 시 중복 누적 0건) | **PASS** |
| **T14** | 기존 사건 복구(`rebuild_case_entities`) `dry_run=True` 미리보기 및 `dry_run=False` 반영 검증 | **PASS** |
| **T15 & T16** | `CaseDetailSchema` 직렬화 및 `Overview`/`Facts` 탭 데이터 일관성 검증 | **PASS** |
| **T17** | Neo4j 스냅샷(`collect_case_snapshot`) 내 `parties`, `events`, `event_fact_links`, `event_order` 검증 | **PASS** |
| **T18** | 타 법률 도메인(민사소송 `원고`/`피고`, 법인명 `주식회사 한빛테크`, 근로계약 기간) 범용성 검증 | **PASS** |

---

## 5. 코딩 주석 표준 준수 점검

- [`docs/development/CODING_COMMENT_STANDARD.md`](CODING_COMMENT_STANDARD.md)에 따라 신규·수정된 Python 모듈(`entity_sync.py`, `timeline.py`, `evidence_manager.py`, `manager.py`, `cases.py`, `models.py`, `schemas/case.py`)에 한국어 모듈 개요 및 Google 스타일 함수/클래스 Docstring을 작성하였다.
- 프론트엔드 TypeScript/React(`CaseWorkspace.tsx`, `case.ts`) 주석 및 타입 정의를 최신 동작에 맞게 갱신하였다.
- 로그 및 주석에 API Key, 개인정보 원문 등 민감정보를 기록하지 않았다.

