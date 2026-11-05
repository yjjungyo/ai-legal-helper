# -*- coding: utf-8 -*-
"""P12-6: Persist complete HILT-authorized eflaw history without network calls.

A history snapshot proves only what the official version list returned. It
never proves article applicability or that a version is embedded in Chroma.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from ai_legal_helper.legal_knowledge.index_jobs import LawHistorySnapshot, LawVersionIndex, LawVersionEffectiveBranch
from ai_legal_helper.tools.official_statute_versions import VersionLookup

logger = logging.getLogger(__name__)


def store_complete_history(session, lookup: VersionLookup, *, law_id: str) -> dict:
    """Atomic local persistence; caller must have completed HILT-approved lookup.

    Same MST with multiple official effective dates cannot fit the current
    law_version_index unique(law_id,mst) schema. Record an INCOMPLETE
    snapshot, never silently collapse the conflicting dates.
    """
    if lookup.status != "CANDIDATES_FOUND" or not lookup.versions:
        return {"status": "SKIPPED", "reason_code": "OFFICIAL_HISTORY_NOT_COMPLETE"}
    versions = list(lookup.versions)
    if (not law_id or any(v.law_id != law_id for v in versions)
            or lookup.total_count is None
            or lookup.total_count != len(versions)
            or lookup.pages_fetched < 1):
        return {"status": "SKIPPED", "reason_code": "HISTORY_IDENTITY_OR_COUNT_UNCONFIRMED"}
    by_mst = {}
    for version in versions:
        by_mst.setdefault(version.mst, set()).add(version.list_effective_date)
    multi_date = any(len(dates) > 1 for dates in by_mst.values())
    canonical = sorted(
        (v.as_dict() for v in versions),
        key=lambda item: (item["mst"], item["list_effective_date"]),
    )
    fingerprint = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    snapshot = LawHistorySnapshot(
        id=str(uuid.uuid4()), law_id=law_id, checked_at=now,
        checked_through=now, source_target="eflaw",
        completeness_status="INCOMPLETE" if multi_date else "COMPLETE",
        pages_fetched=lookup.pages_fetched,
        official_version_count=len(by_mst),
        error_code="MULTI_EFFECTIVE_DATE_PER_MST" if multi_date else None,
        fingerprint=fingerprint,
    )
    session.add(snapshot)
    for version in versions:
        session.add(LawVersionEffectiveBranch(
            id=str(uuid.uuid4()), law_id=law_id, mst=version.mst,
            effective_date=version.list_effective_date,
            promulgation_date=version.promulgation_date,
            history_code=version.history_code,
            source_snapshot_id=snapshot.id,
        ))
    # Do not overwrite a previously verified XML identity or indexing status.
    # For ambiguous multi-date MSTs, no rows are bound to this snapshot:
    # the resolver will fail closed until the schema supports branches.
    if not multi_date:
        for version in versions:
            row = session.scalar(select(LawVersionIndex).where(
                LawVersionIndex.law_id == law_id,
                LawVersionIndex.mst == version.mst,
            ))
            if row is None:
                row = LawVersionIndex(
                    id=str(uuid.uuid4()), law_id=law_id, mst=version.mst,
                    list_effective_date=version.list_effective_date,
                )
                session.add(row)
            # An existing READY vector index was built from a particular
            # official version. If history metadata now differs, the worker
            # must revalidate/reindex it before the resolver can reuse it.
            identity_changed = (
                row.index_status == "READY"
                and (row.list_effective_date != version.list_effective_date
                     or (row.promulgation_date and row.promulgation_date != version.promulgation_date))
            )
            if identity_changed:
                row.index_status = "STALE"
                row.xml_identity_status = "UNCONFIRMED"
            row.promulgation_date = version.promulgation_date
            row.list_effective_date = version.list_effective_date
            row.history_code = version.history_code
            row.source_snapshot_id = snapshot.id
    session.commit()
    return {
        "status": snapshot.completeness_status,
        "snapshot_id": snapshot.id,
        "version_count": len(by_mst),
        "reason_code": snapshot.error_code,
    }


def store_approved_lookup(lookup: VersionLookup) -> dict:
    """Best effort persistence; never interfere with immediate official answer."""
    if not lookup.versions:
        return {"status": "SKIPPED"}
    from ai_legal_helper.database.session import SessionLocal

    try:
        with SessionLocal() as session:
            return store_complete_history(
                session, lookup, law_id=lookup.versions[0].law_id,
            )
    except Exception as exc:
        logger.warning("[OFFICIAL_HISTORY_CACHE] persistence unavailable type=%s",
                       type(exc).__name__)
        return {"status": "UNAVAILABLE", "reason_code": type(exc).__name__}
