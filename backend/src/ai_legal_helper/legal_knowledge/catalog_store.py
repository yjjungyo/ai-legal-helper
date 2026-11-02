# -*- coding: utf-8 -*-
"""
P2 법령명 카탈로그 영속화·증분 동기화 (PostgreSQL SQLAlchemy).

[설계]
- 공식 법령ID 기준 Upsert. 법령일련번호 MST는 목록의 참고 버전이지 기본키가 아니다.
- 공식 별칭과 관리자 검토 별칭을 분리. 타 법령에 같은 별칭이 있어도 중복을
  강제로 하나로 합치지 않고 Resolver에서 AMBIGUOUS로 처리하도록 보존한다.
- 페이지 단위 커밋과 이력 기록으로 중단·재시도 시 기존 성공 페이지를 보존한다.
- 실패·조회건수 미확인·최대 페이지 중단을 카탈로그 동기화 '완료'로 표시하지 않는다.
- 법령 원문이나 사건 데이터는 저장하지 않으며 기존 테이블을 삭제하지 않는다.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ai_legal_helper.database.models import (
    LawCatalogEntry, LawCatalogAlias, LawCatalogSyncRun,
)
from ai_legal_helper.legal_knowledge.law_catalog import (
    CatalogError,
    LawCatalogPage,
    fetch_law_catalog_page,
    normalize_law_name,
)
from ai_legal_helper.utils.datetime_utils import get_kst_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncSummary:
    """동기화 범위와 실패 이유를 명시해 전체 수집을 과장하지 않는다."""

    run_id: str
    status: str
    total_expected: Optional[int]
    items_seen: int
    pages_completed: int
    error_code: Optional[str] = None


class LawCatalogStore:
    """호출자가 제공한 Session을 사용해 다른 DB와 트랜잭션을 분리한다."""

    def __init__(self, session: Session):
        self.session = session

    def all_entries(self) -> list[LawCatalogEntry]:
        """로컬 법령명/약칭 목록. Runtime에서는 **외부 공식 검색을 하지 않는다**."""
        statement = select(LawCatalogEntry).options(selectinload(LawCatalogEntry.aliases))
        return list(self.session.scalars(statement).all())

    def upsert_page(self, page: LawCatalogPage) -> int:
        """공식 목록 한 페이지를 기존 메타데이터를 손상시키지 않고 갱신한다.

        DB commit은 호출자 책임이다. 페이지 파싱이 먼저 완료된 경우에만 호출된다.
        """
        now = get_kst_now()
        for item in page.items:
            row = self.session.get(LawCatalogEntry, item.law_id)
            if row is None:
                row = LawCatalogEntry(
                    law_id=item.law_id,
                    official_name=item.official_name,
                    name_key=item.name_key,
                    source_target="law",
                    created_at=now,
                )
                self.session.add(row)
            # 동명 법령이 아닌데 임의로 ID를 재사용하지 않는다. 공식 응답의 ID만 기준.
            row.official_name = item.official_name
            row.name_key = item.name_key
            row.law_type = item.law_type or row.law_type
            row.current_mst = item.mst or row.current_mst
            row.short_name = item.short_name or None
            row.promulgation_date = item.promulgation_date
            row.list_effective_date = item.list_effective_date
            row.promulgation_number = item.promulgation_number or None
            row.ministry_name = item.ministry_name or None
            row.history_code = item.history_code or None
            row.detail_url = item.detail_url or None
            row.last_seen_at = now
            row.updated_at = now
            # 공식 약칭 변경 시 이전 공식 약칭은 더 이상 자동 검색에 이용하지 않는다.
            # REVIEWED(관리자가 명시 승인) 별칭은 API 갱신으로 삭제하지 않는다.
            existing_official = {
                a.alias_key: a for a in row.aliases if a.source == "OFFICIAL"
            }
            kept = [a for a in row.aliases if a.source != "OFFICIAL"]
            valid = normalize_law_name(item.short_name)
            if valid and valid != item.name_key:
                # 동일 공식 별칭을 업데이트할 때 기존 행을 재사용한다.
                # 삭제 후 같은 unique 키로 다시 INSERT하면 flush 순서에 따라
                # UniqueConstraint 오류가 발생할 수 있으므로 반드시 reuse 한다.
                entry = existing_official.get(valid)
                if entry is None:
                    entry = LawCatalogAlias(
                        law_id=item.law_id,
                        alias_name=item.short_name,
                        alias_key=valid,
                        source="OFFICIAL",
                    )
                else:
                    entry.alias_name = item.short_name
                kept.append(entry)
            row.aliases = kept
        return len(page.items)


def sync_official_catalog(
    session: Session,
    *,
    api_key: str,
    max_pages: int = 0,
    query: Optional[str] = None,
    fetch_xml: Optional[Callable[[str], Optional[bytes]]] = None,
) -> SyncSummary:
    """관리자의 **명시적인 실행**으로 공식 목록을 페이지 단위로 수집한다.

    max_pages=0이면 공식 totalCnt를 끝까지 따라가되 1000페이지 절대 상한을 둔다.
    양수이면 지정 페이지까지만 수집한다. 부분 수집은 PARTIAL로 기록한다.
    기본 경로에서 HILT 승인 없이 이 함수를 호출하지 않는다.
    """
    if not api_key:
        raise ValueError("LAW_OPENAPI_KEY_MISSING")
    if not isinstance(max_pages, int) or not 0 <= max_pages <= 1000:
        raise ValueError("INVALID_MAX_PAGES")
    if query is not None and (not query.strip() or len(query) > 100):
        raise ValueError("INVALID_CATALOG_QUERY")

    run_id = str(uuid.uuid4())
    started = LawCatalogSyncRun(
        id=run_id, target="law", query_text=query, total_expected=None,
        items_seen=0, pages_completed=0, status="RUNNING",
        started_at=get_kst_now(),
    )
    session.add(started)
    session.commit()

    expected: Optional[int] = None
    seen = 0
    pages = 0
    failures = 0
    seen_law_ids: set[str] = set()
    error_code: Optional[str] = None
    limit = max_pages or 1000
    status = "PARTIAL"

    for page_number in range(1, limit + 1):
        try:
            page = fetch_law_catalog_page(
                page_number, api_key=api_key, query=query, fetch_xml=fetch_xml
            )
            if expected is None:
                expected = page.total_count
            elif page.total_count is not None and expected != page.total_count:
                raise CatalogError("CATALOG_TOTAL_CHANGED")
            if page.skipped_count:
                failures += page.skipped_count
            # 페이지가 겹치거나 동일 법령 ID가 중복 제공되면 전체 목록 일부가
            # 누락되었을 수 있으므로 totalCnt에 도달해도 COMPLETE로 확정하지 않는다.
            for item in page.items:
                if item.law_id in seen_law_ids:
                    failures += 1
                seen_law_ids.add(item.law_id)
            # 건수가 남았는데 빈 페이지가 오면 무한 루프/잘못된 완료 처리 금지.
            if page.returned_count == 0 and expected and seen < expected:
                raise CatalogError("PREMATURE_EMPTY_PAGE")
            store = LawCatalogStore(session)
            store.upsert_page(page)
            seen += page.returned_count
            pages += 1
            run = session.get(LawCatalogSyncRun, run_id)
            run.total_expected = expected
            run.items_seen = seen
            run.pages_completed = pages
            session.commit()
            if expected is not None and seen >= expected:
                status = "COMPLETE" if failures == 0 and seen == expected else "PARTIAL"
                if status != "COMPLETE":
                    error_code = "INVALID_OR_MISMATCHED_RECORDS"
                break
        except (CatalogError, ValueError) as exc:
            session.rollback()
            error_code = str(exc)
            status = "FAILED" if pages == 0 else "PARTIAL"
            break
        except Exception as exc:
            session.rollback()
            logger.exception("[LAW_CATALOG] 동기화 장애 | page=%d | exception=%s",
                             page_number, type(exc).__name__)
            error_code = "DATABASE_OR_RUNTIME_ERROR"
            status = "FAILED" if pages == 0 else "PARTIAL"
            break
    else:
        if expected is None:
            error_code = "TOTAL_COUNT_UNCONFIRMED"
        elif seen < expected:
            error_code = "PAGE_LIMIT_REACHED"
        else:
            status = "COMPLETE" if failures == 0 and seen == expected else "PARTIAL"
            if failures:
                error_code = "SKIPPED_INVALID_RECORDS"

    if expected is None and status == "PARTIAL":
        error_code = error_code or "TOTAL_COUNT_UNCONFIRMED"
    run = session.get(LawCatalogSyncRun, run_id)
    run.total_expected = expected
    run.items_seen = seen
    run.pages_completed = pages
    run.status = status
    run.error_code = error_code
    run.finished_at = get_kst_now()
    session.commit()
    logger.info("[LAW_CATALOG] sync=%s status=%s pages=%d count=%d expected=%s",
                run_id, status, pages, seen, expected)
    return SyncSummary(run_id, status, expected, seen, pages, error_code)
