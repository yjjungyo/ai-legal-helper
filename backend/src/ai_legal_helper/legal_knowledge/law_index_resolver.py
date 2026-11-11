# -*- coding: utf-8 -*-
"""P12-2: DB-only Law Index Resolver. No network, Chroma or HITL bypass.

The index answers whether a local *candidate* is available; it never grants
legal applicability. Official history freshness and addenda remain mandatory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_legal_helper.legal_knowledge.index_jobs import (
    LawArticleCoverage, LawHistorySnapshot, LawVersionIndex, OfficialLawIndexJob,
)
from ai_legal_helper.rag.temporal_applicability import parse_legal_date


@dataclass(frozen=True)
class LawIndexDecision:
    status: str
    law_id: str
    event_date: str | None
    mst: str | None = None
    article_ids: tuple[str, ...] = ()
    missing_articles: tuple[str, ...] = ()
    official_lookup_required: bool = True
    reason_codes: tuple[str, ...] = ()
    snapshot_id: str | None = None

    def as_dict(self) -> dict:
        return {
            "status": self.status, "law_id": self.law_id,
            "event_date": self.event_date, "mst": self.mst,
            "article_ids": list(self.article_ids),
            "missing_articles": list(self.missing_articles),
            "official_lookup_required": self.official_lookup_required,
            "reason_codes": list(self.reason_codes),
            "snapshot_id": self.snapshot_id,
        }


class LawIndexResolver:
    """Fail-closed local version/coverage preflight before legal RAG.

    A successful decision is INDEX_READY_CANDIDATE, not APPLICABLE.
    The downstream temporal resolver must check article dates and addenda.
    """

    def __init__(self, session: Session, *, max_history_age_days: int = 7,
                 now: Optional[datetime] = None):
        if max_history_age_days < 0:
            raise ValueError("INVALID_HISTORY_MAX_AGE")
        self.session = session
        self.max_history_age_days = max_history_age_days
        self.now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    def resolve(self, *, law_id: str, event_date: str | None,
                article_ids: tuple[str, ...] | list[str] = (),
                event_type: str | None = None) -> LawIndexDecision:
        articles = tuple(dict.fromkeys(str(x).replace(" ", "").strip()
                                           for x in article_ids if str(x).strip()))
        parsed = parse_legal_date(event_date)
        def result(status: str, *reasons: str, mst: str | None = None,
                   snapshot_id: str | None = None,
                   missing: tuple[str, ...] = ()) -> LawIndexDecision:
            return LawIndexDecision(
                status=status, law_id=law_id, event_date=parsed.isoformat() if parsed else None,
                mst=mst, article_ids=articles, missing_articles=missing,
                official_lookup_required=True, reason_codes=tuple(reasons),
                snapshot_id=snapshot_id,
            )

        if not law_id or not law_id.strip():
            return result("LAW_UNCONFIRMED", "LAW_ID_MISSING")
        if parsed is None or not event_type:
            return result("EVENT_UNCONFIRMED", "EVENT_DATE_OR_TYPE_MISSING")
        # A cached snapshot is usable only when the complete official history was
        # verified recently. checked_through is the *coverage horizon*, not checked_at.
        snapshot = self.session.scalar(
            select(LawHistorySnapshot)
            .where(LawHistorySnapshot.law_id == law_id)
            .order_by(LawHistorySnapshot.checked_at.desc(), LawHistorySnapshot.id.desc())
            .limit(1)
        )
        if snapshot is None:
            return result("HISTORY_MISSING", "OFFICIAL_HISTORY_NOT_CACHED")
        checked_at = snapshot.checked_at
        if checked_at is None:
            return result("HISTORY_STALE", "HISTORY_CHECK_DATE_MISSING",
                          snapshot_id=snapshot.id)
        if checked_at.tzinfo is not None:
            checked_at = checked_at.astimezone(timezone.utc).replace(tzinfo=None)
        now = self.now
        if now.tzinfo is not None:
            now = now.astimezone(timezone.utc).replace(tzinfo=None)
        if (snapshot.completeness_status not in ("COMPLETE", "INCOMPLETE")
                or snapshot.source_target != "eflaw"
                or not snapshot.fingerprint
                or not snapshot.pages_fetched
                or snapshot.official_version_count is None):
            return result("HISTORY_INCOMPLETE", "OFFICIAL_HISTORY_NOT_COMPLETE",
                          snapshot_id=snapshot.id)
        if (checked_at > now or now - checked_at > timedelta(days=self.max_history_age_days)
                or snapshot.checked_through is None
                or snapshot.checked_through.date() < parsed):
            return result("HISTORY_STALE", "OFFICIAL_HISTORY_REFRESH_REQUIRED",
                          snapshot_id=snapshot.id)

        # An official history with multiple effective branches for one MST
        # cannot be represented by the single-date LawVersionIndex schema.
        # Never silently select one branch as the governing version.
        from ai_legal_helper.legal_knowledge.index_jobs import LawVersionEffectiveBranch
        branches = list(self.session.scalars(select(LawVersionEffectiveBranch).where(
            LawVersionEffectiveBranch.source_snapshot_id == snapshot.id,
            LawVersionEffectiveBranch.law_id == law_id,
        )).all())
        by_mst = {}
        for branch in branches:
            by_mst.setdefault(branch.mst, set()).add(branch.effective_date)
        if snapshot.completeness_status == "INCOMPLETE" and snapshot.error_code != "MULTI_EFFECTIVE_DATE_PER_MST":
            return result("HISTORY_INCOMPLETE", "OFFICIAL_HISTORY_NOT_COMPLETE", snapshot_id=snapshot.id)
        if snapshot.completeness_status == "INCOMPLETE":
            # Multi-effective-date history is a complete *list* of branches,
            # but not enough to prove which article text governs an event.
            # Return a grounded MST candidate for diagnostic/review use only.
            if snapshot.error_code != "MULTI_EFFECTIVE_DATE_PER_MST":
                return result("HISTORY_INCOMPLETE", "OFFICIAL_HISTORY_NOT_COMPLETE",
                              snapshot_id=snapshot.id)
            if not branches or len(by_mst) != snapshot.official_version_count:
                return result("HISTORY_INCOMPLETE", "EFFECTIVE_BRANCH_COUNT_MISMATCH",
                              snapshot_id=snapshot.id)
            eligible = []
            for branch in branches:
                effective = parse_legal_date(branch.effective_date)
                promulgated = parse_legal_date(branch.promulgation_date)
                if effective is None or promulgated is None:
                    return result("VERSION_AMBIGUOUS", "BRANCH_DATE_INVALID",
                                  snapshot_id=snapshot.id)
                if effective <= parsed:
                    if promulgated > parsed:
                        return result("VERSION_AMBIGUOUS", "RETROACTIVE_REVIEW_REQUIRED",
                                      snapshot_id=snapshot.id)
                    eligible.append((effective, branch.mst))
            if not eligible:
                return result("INDEX_MISSING", "NO_VERSION_EFFECTIVE_BY_EVENT",
                              snapshot_id=snapshot.id)
            latest = max(date for date, _ in eligible)
            mst_set = {mst for date, mst in eligible if date == latest}
            if len(mst_set) != 1:
                return result("VERSION_AMBIGUOUS", "MULTIPLE_MST_SAME_EFFECTIVE_DATE",
                              snapshot_id=snapshot.id)
            return result(
                "ARTICLE_BRANCH_REVIEW_REQUIRED",
                "MULTI_EFFECTIVE_DATE_PER_MST",
                "ARTICLE_AND_ADDENDA_BRANCH_SELECTION_REQUIRED",
                mst=next(iter(mst_set)), snapshot_id=snapshot.id,
            )
        if any(len(dates) > 1 for dates in by_mst.values()):
            return result("VERSION_AMBIGUOUS", "MULTI_EFFECTIVE_DATE_PER_MST",
                          snapshot_id=snapshot.id)
        if len(branches) != snapshot.official_version_count:
            return result("HISTORY_INCOMPLETE", "EFFECTIVE_BRANCH_COUNT_MISMATCH",
                          snapshot_id=snapshot.id)

        versions = list(self.session.scalars(
            select(LawVersionIndex).where(
                LawVersionIndex.law_id == law_id,
                LawVersionIndex.source_snapshot_id == snapshot.id,
            )
        ).all())
        if not versions:
            return result("INDEX_MISSING", "NO_OFFICIAL_VERSIONS", snapshot_id=snapshot.id)
        # A missing or malformed version entry means the snapshot cannot establish
        # that this is the latest applicable version. Never silently skip it.
        if len(versions) != snapshot.official_version_count:
            return result("HISTORY_INCOMPLETE", "VERSION_COUNT_MISMATCH",
                          snapshot_id=snapshot.id)
        candidates = []
        for version in versions:
            effective = parse_legal_date(version.list_effective_date)
            promulgated = parse_legal_date(version.promulgation_date)
            if effective is None or promulgated is None:
                return result("VERSION_AMBIGUOUS", "VERSION_DATE_INVALID",
                              snapshot_id=snapshot.id)
            if effective <= parsed and promulgated > parsed:
                return result("VERSION_AMBIGUOUS", "RETROACTIVE_REVIEW_REQUIRED",
                              snapshot_id=snapshot.id)
            if effective <= parsed:
                candidates.append((effective, version))
        if not candidates:
            return result("INDEX_MISSING", "NO_VERSION_EFFECTIVE_BY_EVENT",
                          snapshot_id=snapshot.id)
        # Future versions with the same earliest effective date but different
        # MSTs can affect transitional provisions. Do not treat the selected
        # past MST as conclusively safe without resolving that ambiguity.
        future = []
        for version in versions:
            effective = parse_legal_date(version.list_effective_date)
            if effective is not None and effective > parsed:
                future.append((effective, version))
        if future:
            next_date = min(eff for eff, _ in future)
            if len({v.mst for eff, v in future if eff == next_date}) != 1:
                return result("VERSION_AMBIGUOUS", "MULTIPLE_FUTURE_MST_SAME_EFFECTIVE_DATE",
                              snapshot_id=snapshot.id)
        newest_date = max(eff for eff, _ in candidates)
        newest = [version for eff, version in candidates if eff == newest_date]
        if len({v.mst for v in newest}) != 1:
            return result("VERSION_AMBIGUOUS", "MULTIPLE_MST_SAME_EFFECTIVE_DATE",
                          snapshot_id=snapshot.id)
        version = newest[0]
        if (version.index_status != "READY"
                or version.xml_identity_status != "VERIFIED"
                or not version.official_xml_hash
                or len(version.official_xml_hash) != 64
                or version.chunk_count <= 0):
            return result("INDEX_MISSING", "VERSION_NOT_READY",
                          mst=version.mst, snapshot_id=snapshot.id)
        job = self.session.scalar(select(OfficialLawIndexJob).where(
            OfficialLawIndexJob.law_id == law_id,
            OfficialLawIndexJob.mst == version.mst,
            OfficialLawIndexJob.status == "READY",
        ))
        if job is None or job.chunk_count != version.chunk_count:
            return result("INDEX_INCOMPLETE", "WORKER_COVERAGE_NOT_CONFIRMED",
                          mst=version.mst, snapshot_id=snapshot.id)
        if not articles:
            return result("INDEX_INCOMPLETE", "ARTICLE_SCOPE_MISSING",
                          mst=version.mst, snapshot_id=snapshot.id)
        coverage = list(self.session.scalars(select(LawArticleCoverage).where(
            LawArticleCoverage.law_id == law_id,
            LawArticleCoverage.mst == version.mst,
        )).all())
        if (len(coverage) != version.chunk_count
                or any(not c.vector_id or not c.content_hash for c in coverage)):
            return result("INDEX_INCOMPLETE", "VECTOR_COVERAGE_MISMATCH",
                          mst=version.mst, snapshot_id=snapshot.id)
        available = {c.article_id.replace(" ", "") for c in coverage}
        missing = tuple(a for a in articles if a not in available)
        if missing:
            return result("INDEX_INCOMPLETE", "REQUESTED_ARTICLE_NOT_INDEXED",
                          mst=version.mst, snapshot_id=snapshot.id, missing=missing)
        if "부칙" not in available:
            return result("INDEX_INCOMPLETE", "ADDENDA_COVERAGE_NOT_CONFIRMED",
                          mst=version.mst, snapshot_id=snapshot.id)
        return LawIndexDecision(
            status="INDEX_READY_CANDIDATE", law_id=law_id,
            event_date=parsed.isoformat(), mst=version.mst,
            article_ids=articles, official_lookup_required=False,
            reason_codes=("TEMPORAL_APPLICABILITY_REVIEW_REQUIRED",),
            snapshot_id=snapshot.id,
        )
