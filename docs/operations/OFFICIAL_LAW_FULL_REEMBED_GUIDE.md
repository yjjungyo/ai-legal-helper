# 공식 법령 전체 재임베딩 절차 (과제/로컬 환경)

> 적용 대상: `ai-legal-helper`의 공식 XML 법령 인덱스 `law_docs_global`. Windows PowerShell, 프로젝트 루트에서 실행. **실행 가이드이며 아직 실행하지 않았다.**
>
> 전제: 기존 공식 법령 벡터를 모두 버리고, 기존 작업 큐에 기록된 **법령ID/MST 목록을 재사용**해 새로 임베딩한다. 신규 법령은 공식 조회/승인 및 `enqueue_version()`을 통해 별도로 등록해야 한다.

## 핵심 원칙

- 임베딩 Worker는 ChromaDB에 벡터를 Upsert하고, 같은 작업에서 PostgreSQL의 `law_version_index`, `law_article_coverage`, `law_article_versions`, `law_transition_rules`를 자동 갱신한다. 수동으로 이 테이블에 조문을 다시 입력하지 않는다.
- 단, `official_law_index_jobs`의 기존 `READY` 작업은 Worker가 다시 선택하지 않으므로 **재임베딩 전 작업 상태 초기화가 필요**하다.
- 이 가이드는 공식 법령 컬렉션만 초기화한다. `law_docs_*`의 다른 분야 컬렉션, 사건/증거 DB, Neo4j, 법령 연혁 스냅샷은 지우지 않는다.
- **주의:** PostgreSQL과 ChromaDB는 하나의 원자적 트랜잭션이 아니다. 초기화/재임베딩 중에는 상담 API와 Worker를 중지한다.
- 테스트/평가용 DB에는 실행하지 않는다. 실제 DB 연결 대상부터 확인한다.

## 0. 준비 및 백업

PowerShell에서 프로젝트 루트로 이동한다.

```powershell
cd C:\path\to\ai-legal-helper
docker compose ps
docker compose exec -T postgres psql -U ai_user -d ai_legal_helper -c "SELECT current_database(), current_user;"
docker compose exec -T postgres psql -U ai_user -d ai_legal_helper -c "SELECT status, count(*) FROM official_law_index_jobs GROUP BY status ORDER BY status;"
docker compose exec -T postgres psql -U ai_user -d ai_legal_helper -c "SELECT count(*) FROM law_version_index;"
```

위의 `ai_user` / `ai_legal_helper`는 `docker-compose.yml` 기본값이다. `.env`에서 바꿨다면 명령도 변경한다.

상담/Worker 실행을 중지한 다음 백업한다. 예시(개발 환경):

```powershell
docker compose stop api frontend
New-Item -ItemType Directory -Force .\backup | Out-Null
docker compose exec -T postgres pg_dump -U ai_user -d ai_legal_helper -Fc > .\backup\ai_legal_helper_before_reembed.dump
```

ChromaDB는 `docker-compose.yml`에서 `./backend/data/chroma:/data`를 마운트한다. 삭제 전 해당 디렉터리도 별도 백업한다. 다른 Chroma 저장소를 사용하는 경우에는 **실제 연결된 저장소**를 백업한다.

## 1. 공식 법령 Chroma 컬렉션 초기화

`backend/.venv` 등 현재 프로젝트 Python 환경과 Chroma 연결 설정(`CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_PERSIST`)을 먼저 확인한다. **Worker와 동일한 설정**을 사용해야 한다. Docker Compose ChromaDB를 호스트에서 접근하는 기본값은 `127.0.0.1:8001`이다.

```powershell
cd backend
$env:CHROMA_HOST = "127.0.0.1"
$env:CHROMA_PORT = "8001"
@'
import os
import chromadb
client = chromadb.HttpClient(host=os.environ["CHROMA_HOST"], port=int(os.environ["CHROMA_PORT"]))
name = "law_docs_global"
existing = [getattr(x, "name", str(x)) for x in client.list_collections()]
print("before:", existing)
if name in existing:
    client.delete_collection(name)
    print("deleted:", name)
else:
    print("already absent:", name)
'@ | python -
cd ..
```

이 명령은 **`law_docs_global`만 삭제**한다. Docker 볼륨 전체 삭제(`docker compose down -v`)나 Chroma 데이터 디렉터리 전체 삭제는 하지 않는다. Worker는 다음 실행 시 `get_or_create_collection()`으로 컬렉션을 재생성한다.

> 로컬 `PersistentClient` 사용 시 위 HTTP 명령을 그대로 사용하지 않는다. Worker의 실제 `CHROMA_PERSIST` 경로로 `chromadb.PersistentClient(path=...)`를 생성해 **같은 컬렉션만** 삭제한다. 클라이언트가 다른 저장소를 가리키면 재임베딩 결과와 검색 결과가 달라진다.

## 2. PostgreSQL 인덱싱 상태 초기화

**중요:** 다음 SQL은 공식 법령 인덱싱 테이블의 전체 데이터를 초기화한다. 현재 `official_law_index_jobs`의 법령ID/MST 목록을 보존한 채 작업을 `PENDING`으로 되돌린다. 이미 큐에 기록된 법령 버전만 자동 재처리된다.

PowerShell에서 다음을 실행한다. 먼저 `cd`로 프로젝트 루트에 있는지 확인한다.

```powershell
@'
BEGIN;

DELETE FROM law_transition_rules;
DELETE FROM law_article_versions;
DELETE FROM law_article_coverage;

UPDATE law_version_index
SET index_status = 'DISCOVERED',
    xml_identity_status = 'UNCONFIRMED',
    official_xml_hash = NULL,
    indexed_at = NULL,
    chunk_count = 0;

UPDATE official_law_index_jobs
SET status = 'PENDING',
    attempts = 0,
    error_code = NULL,
    chunk_count = 0,
    lease_owner = NULL,
    finished_at = NULL,
    updated_at = CURRENT_TIMESTAMP;

COMMIT;
'@ | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U ai_user -d ai_legal_helper
```

`law_history_snapshots` 및 `law_version_effective_branches`는 공식 연혁 기록이므로 보존한다. `law_version_index.source_snapshot_id`도 보존한다. **연혁 기록이 실제로 완전한지는 별도 검증 대상**이다.

검증:

```powershell
docker compose exec -T postgres psql -U ai_user -d ai_legal_helper -c "SELECT status, count(*) FROM official_law_index_jobs GROUP BY status;"
docker compose exec -T postgres psql -U ai_user -d ai_legal_helper -c "SELECT (SELECT count(*) FROM law_article_coverage) AS coverage, (SELECT count(*) FROM law_article_versions) AS articles, (SELECT count(*) FROM law_transition_rules) AS addenda;"
```

## 3. 공식 법령 재임베딩

`backend/.env`의 `LAW_OPENAPI_KEY`, `DATABASE_URL`, 임베딩 모델/API 설정, Chroma 설정을 확인한다. Python 환경은 프로젝트에 설치된 venv를 활성화한다.

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python scripts/run_official_law_index_worker.py
python scripts/run_official_law_index_worker.py --execute
```

첫 명령은 DRY RUN이다. `--execute`는 **큐의 작업 1건만** 처리하므로, 여러 건은 반복 실행한다. 아래 반복문은 작업 상태가 `EMPTY`가 되면 멈춘다.

```powershell
while ($true) {
    $output = python scripts/run_official_law_index_worker.py --execute
    $exitCode = $LASTEXITCODE
    $output
    if ($exitCode -ne 0) {
        Write-Host "Worker 오류 또는 재시도 상태. 원인 확인 후 재실행하세요."
        break
    }
    if ($output -match '"status"\s*:\s*"EMPTY"') { break }
}
cd ..
```

`RETRY`는 다음 호출에서 재처리되고, `FAILED`는 자동 재처리되지 않는다. 실패한 작업을 확인하고 원인을 해결한 뒤 재등록/상태 조정한다. API 호출 및 임베딩 비용·시간이 발생할 수 있다.

## 4. 재임베딩 결과 검증

```powershell
docker compose exec -T postgres psql -U ai_user -d ai_legal_helper -c "SELECT status, count(*), sum(chunk_count) FROM official_law_index_jobs GROUP BY status ORDER BY status;"
docker compose exec -T postgres psql -U ai_user -d ai_legal_helper -c "SELECT index_status, count(*), sum(chunk_count) FROM law_version_index GROUP BY index_status ORDER BY index_status;"
docker compose exec -T postgres psql -U ai_user -d ai_legal_helper -c "SELECT count(*) FROM law_article_coverage;"
docker compose exec -T postgres psql -U ai_user -d ai_legal_helper -c "SELECT j.law_id, j.mst, j.status, j.chunk_count AS job_chunks, v.chunk_count AS version_chunks, (SELECT count(*) FROM law_article_coverage c WHERE c.law_id=j.law_id AND c.mst=j.mst) AS pg_chunks FROM official_law_index_jobs j LEFT JOIN law_version_index v ON v.law_id=j.law_id AND v.mst=j.mst ORDER BY j.law_id, j.mst;"
```

정상 기대값: 작업은 `READY`, 버전은 `READY`/XML `VERIFIED`, 작업의 `chunk_count` = 버전 `chunk_count` = 동일 법령ID/MST의 PG 커버리지 건수. ChromaDB `law_docs_global`의 전체 레코드 수와 PG 커버리지 건수도 비교한다. **건수 일치는 내용 일치의 충분조건이 아니므로**, 실제 검색 경로의 법령ID/MST/조문/해시 검증도 확인한다.

검증이 끝나면 중지했던 API/UI를 다시 시작한다.

```powershell
docker compose start api frontend
```

## 5. 주의 및 제한

1. 이 가이드는 **기존 작업 큐에 있는 법령 버전 재임베딩**이다. 작업 큐가 비어 있으면 자동으로 법령을 찾아 등록하지 않는다. 새 법령/버전은 공식 검색 및 승인 경로에서 등록한다.
2. `law_version_index`에만 존재하고 `official_law_index_jobs`에 없는 MST는 이 절차로 재임베딩되지 않는다. 초기화 전 두 테이블의 법령ID/MST 차이를 확인한다.
3. ChromaDB 삭제와 PostgreSQL 초기화 사이에는 서비스 정합성이 깨질 수 있으므로 상담/Worker 중지 상태에서 수행한다.
4. 공식 XML 조문별 시행일은 불명확하면 `UNCONFIRMED`로 남는다. 임베딩 완료(`READY`)가 법률상 적용 확정은 아니다.
5. 재임베딩 전에 `backend/.env`의 DB와 Chroma 연결 설정을 확인한다. 검색 프로세스와 Worker가 서로 다른 Chroma 인스턴스를 바라보면 검증에 실패한다.
6. `pg_dump -Fc`의 PowerShell 리다이렉션은 PowerShell 버전/인코딩에 따라 바이너리 백업을 손상시킬 수 있다. **실제 백업은 검증 가능한 방식(예: 컨테이너 안에서 파일 생성 후 `docker cp`)을 권장**한다.
