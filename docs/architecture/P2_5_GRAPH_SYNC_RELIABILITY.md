# P2.5 Graph Sync Reliability Design

## 1. 개요
P2.4의 백그라운드 스레드 기반 동기화(`safe_sync_case`)는 실패 시 재시도 메커니즘이 없어 네트워크 일시 단절 시 그래프 데이터가 영구적으로 불일치할 위험이 있습니다. 이를 해결하기 위해 PostgreSQL Outbox 패턴을 도입하여 동기화 작업의 신뢰성을 보장합니다.

## 2. PostgreSQL Outbox 패턴 도입
- **모델 (`GraphSyncTask`):** `case_id`, `status`(PENDING, PROCESSING, COMPLETED, FAILED), `retry_count`, `created_at`, `updated_at` 등을 포함하는 테이블을 신설.
- **이벤트 발행:** 사건 상태가 변경되는 API(증거 업로드, 검토, 진술 추가 등)에서 직접 `safe_sync_case`를 호출하지 않고, 같은 트랜잭션 안에서 `GraphSyncTask`를 생성(`status='PENDING'`)합니다.
- **작업 처리 (Worker):**
  - FastAPI의 BackgroundTask나 스케줄러(또는 단순 스레드 루프)가 주기적으로 `PENDING`, `FAILED`(단, 재시도 횟수 이내) 작업을 가져옵니다.
  - `SELECT ... FOR UPDATE SKIP LOCKED` 를 활용해 중복 실행을 방지합니다.
  - 작업을 `PROCESSING`으로 변경 후 `sync_case_to_graph`를 호출합니다.
  - 완료 시 `COMPLETED`, 실패 시 `FAILED`로 변경 및 `retry_count` 증가.

## 3. 버전 충돌 방지 및 불일치 탐지
- **사건 버전 관리:** `Case.version` 필드를 활용하거나, 최종 업데이트 시점(updated_at)을 비교하여 과거 작업이 최신 업데이트를 덮어쓰지 않도록(또는 순서가 꼬이지 않도록) 보장합니다.
- 동기화는 사건 단위 전체 재구축(멱등성 보장)이므로, 큐에 여러 변경 이벤트가 쌓여 있더라도 **최근 데이터 기준 1회만 처리**하도록 최적화(Debouncing)할 수 있습니다.

## 4. 복구 (Recovery)
- 서버 재시작 시 `PROCESSING` 상태로 멈춰 있는 작업을 `PENDING`으로 롤백하거나 일정 시간 경과 시 재시도.
- 관리자 API로 실패한 작업을 강제로 재시도할 수 있는 엔드포인트 제공.

