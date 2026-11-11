# Law Index First Temporal RAG — 상세 설계 v1.0

상태: 설계 확정 제안 / 구현 및 테스트 미실행
대상: ai-legal-helper (기존 P2/P3/P4/P5/P9 재사용)

## 1. 불변 조건
- 모든 상담의 법령 근거는 쟁점별 법률효과 발생일(event_date)과 사건 유형(event_type)에 맞게 확인한다. 사건일 미확정이면 APPLICABLE 판정 금지.
- 공포일, 법령 전체 시행일, 조문 시행일, 적용례·경과규정, 실제 사건 적용성을 구분한다.
- PostgreSQL에 버전이 있다는 사실 또는 vector 검색 점수가 높다는 사실만으로 적용 확정 금지.
- 공식 연혁 조회는 기존 HITL 승인 정책을 준수한다. 승인 전 외부 호출 없음.
- 공식 조회 성공 시 원문을 상담에 바로 제공하고, 별도 Worker가 나중에 전체 버전을 임베딩한다.
- 공식 조회 실패, 불완전 연혁, 버전 충돌은 UNCONFIRMED로 종료. 무근거 구버전 자동 대체 금지.
- 8개 분야 Agent, 공통 Law Retrieval Service, 기존 컬렉션 및 평가 데이터 격리 유지.

## 2. 기존 코드 재사용
- law_catalog.py / catalog_store.py / law_resolver.py: PostgreSQL 법령명·법령ID 카탈로그.
- tools/official_statute_versions.py: eflaw 연혁 페이지 완전성 검증, 사건일 후보 MST 선택.
- tools/official_statute_asof.py: MST 원문과 해당 부칙 확보.
- legal_knowledge/temporal_resolver.py 및 rag/temporal_applicability.py: 사건일·조문 시행일·적용례 검증.
- legal_knowledge/retrieval_service.py: ChromaDB 공통/분야 검색; **외부 공식 API 호출 금지 유지**.
- legal_knowledge/index_jobs.py / index_worker.py: PostgreSQL 중복 작업 및 별도 Worker, law_docs_global 전체 버전 인덱싱.
- workflows/document_search.py: HITL 승인 후 공식 검색 진입점.

## 3. 신규 책임: LawIndexResolver
입력: [{law_id 또는 공식명, article_ids, event_date, event_type, issue_id}], history_policy.
출력: issue_id별 INDEX_READY_VERIFIED / INDEX_MISSING / HISTORY_STALE / VERSION_AMBIGUOUS / EVENT_UNCONFIRMED / INDEX_INCOMPLETE, resolved_mst, indexed_article_ids, official_lookup_required, reason_codes.

호출 순서:
1) Router/Planner: 쟁점별 사건일·유형 및 법령 후보를 추출. 법령 미특정 시 기존 vector를 **후보 발견 용도**로만 사용.
2) PostgreSQL 카탈로그에서 공식 law_id 확정(동명이법·별칭 충돌은 보류).
3) PostgreSQL 연혁 확인 상태와 버전·조문 커버리지 조회. 사건일 이전 최신 시행일만으로 유효성을 확정하지 않는다.
4) 공식 연혁의 신뢰 가능한 스냅샷과 이벤트 기준일이 일치하고 해당 조문 인덱스가 READY이면 law_id+mst+article_id 필터로 Chroma 검색.
5) 인덱스 부재, 커버리지 부족, 연혁 불확실/만료, 조문 변경, 예외적 소급/경과규정 의심이면 HITL 승인된 공식 연혁 검색 경로로 전달.
6) 공식 조회 원문과 부칙을 Temporal Resolver에 전달. 확정된 조문만 적용 근거로, 미확정은 명시적 조건부 근거로 구분.
7) 검증된 출처만 분야 Agent에 전달; 응답에는 조문별 적용 사건일, 공식 버전, 부칙 근거, 검증 상태 포함.
8) 새 공식 버전은 DB 작업 큐에 enqueue. 사용자 응답은 Worker 완료를 기다리지 않는다.

## 4. PostgreSQL 확장 (기존 카탈로그·작업 테이블 유지)
A. law_history_snapshots
- id PK, law_id FK, checked_at, source_target, completeness_status, checked_through, pages_fetched, official_version_count, error_code, fingerprint
- 법령별 연혁 전체 페이지를 확인한 결과만 COMPLETE. 단순 checked_at만으로 영구 신뢰 금지.
- 갱신 정책: 마지막 확인 시점과 사건일/상담일/법령 변경 감지 상태를 함께 검토. 미확인 기간이 있으면 공식 재확인 필요.

B. law_version_index
- (law_id,mst) unique; promulgation_date, list_effective_date, history_code, source_snapshot_id, official_xml_hash, xml_identity_status, index_status, indexed_at, chunk_count.
- 상태: DISCOVERED → FETCHED → INDEXING → READY / FAILED / RETRY_PENDING.
- READY는 공식 XML identity 확인 + Chroma upsert 완료 + 커버리지 검증 후에만 설정.
- 기존 official_law_index_jobs와 중복 상태 모델을 만들지 않도록, 구현 시 작업 테이블을 참조/확장하는 뷰 또는 최소 컬럼 확장 우선.

C. law_article_coverage
- (law_id,mst,article_id,content_hash) unique, vector_id, article_effective_date, effective_date_basis, effective_to, applicability_review_status, indexed_at.
- 조문 원문, 부칙 및 경과규정의 출처 식별자 유지. 동일 조문이라도 MST가 다르면 독립 저장.
- 원문 일부만 수록했는데 전체 버전 READY로 오인하지 않도록 인덱스 범위 기록.

D. 필요한 인덱스
- law_history_snapshots(law_id,checked_at DESC)
- law_version_index(law_id,list_effective_date,mst)
- law_article_coverage(law_id,mst,article_id)
- official_law_index_jobs(law_id,mst) 기존 unique 재사용.

## 5. Chroma 메타데이터
law_id, statute_name, mst(version_id), article, promulgation_date, law_effective_date,
article_effective_date, effective_date_basis, addendum_id, applicability_rule_id,
transitional_rule_id, content_hash, source_url, retrieval_method.
- 부칙 검증 완료 상태와 사건별 APPLICABLE 판정은 별도 관리: 특정 사건일 적용성은 원문 고유 속성이 아니다.
- metadata key 형식/nullable 제약에 맞춰 직렬화하고 Chroma filter는 law_id+mst 중심.
- vector 결과의 MST와 공식 선택 MST가 다르면 임의 사용 금지. 조문별 적용례 예외는 Resolver 검토.

## 6. 캐시와 공식 검색 정책
- 캐시 HIT 조건: (a) 법령ID 확정 (b) 사건일 관련 공식 연혁 검증 범위 충분 (c) 필요한 조문 원문·부칙 커버리지 확보 (d) 해당 버전 READY (e) Temporal Resolver에서 적용성 검증.
- 사건일이 2025-09-15인데 2025-06까지만 확인한 로컬 연혁이면 HIT 금지.
- 법령의 2025-01 시행본만 존재하고 2025-08 시행 개정본이 확인되면 공식 8월 버전과 조문 비교.
- 반대로 2025-04 시행본만 존재하고 2025-02 사건이면 1월 시행본 공식 연혁 조회.
- 2025-07 공포·2025-08 시행 개정법이라도 특정 조문은 부칙의 단계적 시행/적용례/경과규정에 따라 구 조문이 적용될 수 있다.
- 법령명 검색 결과가 없는 경우도 공식 검색 승인 요청 경로를 거친다.
- 공식 API 불가 또는 승인 거절 시 '현재 적용 법령 확인 불가'를 명시; 기존 조문을 확정 근거로 승격하지 않는다.

## 7. 비동기 인덱싱
- 공식 상담 조회 완료 → enqueue_version(law_id,mst) → 별도 프로세스 Worker.
- Worker는 전체 공식 XML 재조회 및 law_id/MST/법령명 교차검증 → 전체 조문/부칙 분리 → 시행일 메타 저장 → Chroma upsert → 커버리지 검증 → DB READY 커밋.
- 원문을 상담 시 이미 확보한 경우 보안·무결성 검증된 임시 원문 참조로 재사용 가능하나, 상담 일부 검색 결과를 전체 버전으로 오인 금지.
- 중복 작업 idempotent, lease/재시도, 장애 복구, 원문 해시 기반 변경 감지. 동기 응답은 Worker를 기다리지 않는다.
- 멀티스레드 fire-and-forget 대신 기존 PostgreSQL 작업 큐와 독립 Worker 프로세스 유지.

## 8. 구현 순서
P12-1: 기존 DB 모델·Alembic·index_worker 상태 매핑, 추가 스키마 최소화.
P12-2: LawIndexResolver (DB-only, 외부 호출 없음)와 인덱스 커버리지 API.
P12-3: Planner → LawIndexResolver → 승인된 공식 조회 / 버전 필터 RAG 라우팅.
P12-4: Temporal Resolver 검증 출처만 Agent로 전달, 구버전 교체 및 부칙 포함.
P12-5: Worker READY/커버리지 트랜잭션 및 신규 공식 원문 백그라운드 등록.
P12-6: 공식 연혁 신선도/부분 동기화/오류 처리, Langfuse 추적.
P12-7: 회귀 테스트 작성 후 사용자 승인 시 일괄 실행.

## 9. 필수 테스트 (작성 후 실행 보류)
- 2025-02 사건 / 로컬 2025-04 시행본만 존재 → 공식 2025-01 버전 조회.
- 2025-09 사건 / 로컬 2025-01 시행본만 존재 → 공식 2025-08 버전 조회.
- 동일 MST 내 조문별 단계적 시행, 부칙 경과규정에 따른 구법 적용.
- 연혁 페이지 누락, 같은 시행일 다중 MST, 법령ID 불일치, 날짜 미확정.
- 로컬 READY이나 연혁 스냅샷 STALE, 조문 일부만 임베딩, Chroma 실패 시 READY 금지.
- 공식 검색 승인 미획득 시 외부 호출 0건.
- 첫 상담 공식 조회 후 Worker 등록, 다음 상담 인덱스 HIT 및 재사용.
- 8개 분야 Agent 동일 공통 게이트 통과, 기존 평가 데이터 격리.

## 10. 성공 지표
- Temporal correctness: 사건일 적용 불확정 근거의 확정 답변 사용 0건.
- Index HIT rate / official fallback rate / historical version mismatch detection.
- First answer latency vs cached answer latency, Worker indexing delay, duplicate job count.
- Trace: issue_id,event_date,event_type,law_id,vector_mst,official_mst,history_snapshot_id,decision_reason,source_id.
- 모든 수치는 실제 E2E 평가로 산출하고 임의 목표 달성값을 기록하지 않는다.
