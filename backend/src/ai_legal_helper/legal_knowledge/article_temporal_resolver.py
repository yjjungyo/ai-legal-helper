# -*- coding: utf-8 -*-
"""P12-12: DB-only, fail-closed article temporal applicability preflight.

This is not a legal conclusion. Transitional rules require separate review.
No official network requests, LLM invocations or Chroma operations.
"""
from __future__ import annotations

from dataclasses import dataclass
from sqlalchemy import select

from ai_legal_helper.legal_knowledge.index_jobs import LawArticleVersion, LawTransitionRule, LawVersionEffectiveBranch
from ai_legal_helper.legal_knowledge.law_index_resolver import LawIndexResolver
from ai_legal_helper.rag.temporal_applicability import parse_legal_date


@dataclass(frozen=True)
class ArticleTemporalDecision:
    status: str
    law_id: str
    mst: str | None
    event_date: str | None
    article_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    official_lookup_required: bool
    evidence_vector_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "status": self.status, "law_id": self.law_id, "mst": self.mst,
            "event_date": self.event_date, "article_ids": list(self.article_ids),
            "reason_codes": list(self.reason_codes),
            "official_lookup_required": self.official_lookup_required,
            "evidence_vector_ids": list(self.evidence_vector_ids),
        }


class ArticleTemporalResolver:
    """Requires the existing verified history and vector coverage preflight."""

    def __init__(self, session, *, index_resolver=None):
        self.session = session
        self.index_resolver = index_resolver or LawIndexResolver(session)

    def resolve(self, *, law_id: str, event_date: str | None,
                article_ids: tuple[str, ...] | list[str],
                event_type: str | None) -> ArticleTemporalDecision:
        base = self.index_resolver.resolve(
            law_id=law_id, event_date=event_date,
            article_ids=article_ids, event_type=event_type,
        )
        def decision(status: str, *reasons: str, vectors=()) -> ArticleTemporalDecision:
            return ArticleTemporalDecision(
                status=status, law_id=law_id, mst=base.mst,
                event_date=base.event_date, article_ids=base.article_ids,
                reason_codes=tuple(reasons), official_lookup_required=base.official_lookup_required,
                evidence_vector_ids=tuple(vectors),
            )
        branch_review = base.status == "ARTICLE_BRANCH_REVIEW_REQUIRED"
        if base.status not in ("INDEX_READY_CANDIDATE", "ARTICLE_BRANCH_REVIEW_REQUIRED") or not base.mst:
            return decision("INDEX_NOT_READY", *base.reason_codes)
        if not base.article_ids:
            return decision("ARTICLE_SCOPE_MISSING", "ARTICLE_SCOPE_REQUIRED")
        if branch_review:
            branches = list(self.session.scalars(select(LawVersionEffectiveBranch).where(
                LawVersionEffectiveBranch.law_id == law_id,
                LawVersionEffectiveBranch.mst == base.mst,
                LawVersionEffectiveBranch.source_snapshot_id == base.snapshot_id,
            )).all())
            if not branches or any(parse_legal_date(b.effective_date) is None for b in branches):
                return decision("ARTICLE_BRANCH_UNCONFIRMED", "EFFECTIVE_BRANCH_SOURCE_MISSING")
        event = parse_legal_date(base.event_date)
        if event is None:
            return decision("EVENT_UNCONFIRMED", "EVENT_DATE_INVALID")
        rows = list(self.session.scalars(select(LawArticleVersion).where(
            LawArticleVersion.law_id == law_id,
            LawArticleVersion.mst == base.mst,
            LawArticleVersion.article_id.in_(base.article_ids),
        )).all())
        by_article = {}
        for row in rows:
            by_article.setdefault(row.article_id.replace(" ", ""), []).append(row)
        vectors = []
        for article in base.article_ids:
            matches = by_article.get(article, [])
            if not matches:
                return decision("ARTICLE_VERSION_MISSING", "ARTICLE_TEMPORAL_ROW_MISSING")
            if len(matches) != 1:
                return decision("ARTICLE_VERSION_AMBIGUOUS", "MULTIPLE_ARTICLE_TEXT_VERSIONS")
            row = matches[0]
            effective = parse_legal_date(row.effective_from)
            if effective is None or row.effective_date_status not in (
                "SOURCE_DERIVED", "SOURCE_GROUNDED_CANDIDATE",
            ):
                return decision("ARTICLE_DATE_UNCONFIRMED", "EFFECTIVE_DATE_NOT_VERIFIED")
            if effective > event:
                return decision("ARTICLE_NOT_YET_EFFECTIVE", "ARTICLE_EFFECTIVE_AFTER_EVENT")
            if row.effective_to is not None:
                end = parse_legal_date(row.effective_to)
                if end is None:
                    return decision("ARTICLE_DATE_UNCONFIRMED", "EFFECTIVE_END_INVALID")
                if event >= end:
                    return decision("ARTICLE_PERIOD_MISMATCH", "ARTICLE_PERIOD_ENDED")
            if not row.source_vector_id:
                return decision("ARTICLE_SOURCE_MISSING", "SOURCE_VECTOR_ID_MISSING")
            vectors.append(row.source_vector_id)
        addenda = list(self.session.scalars(select(LawTransitionRule).where(
            LawTransitionRule.law_id == law_id,
            LawTransitionRule.mst == base.mst,
        )).all())
        if not addenda:
            return decision("ADDENDA_UNCONFIRMED", "TRANSITION_RULES_NOT_STRUCTURED",
                            vectors=vectors)
        if any(not r.rule_text or not r.source_vector_id for r in addenda):
            return decision("ADDENDA_UNCONFIRMED", "TRANSITION_SOURCE_MISSING",
                            vectors=vectors)
        if branch_review:
            # Do not infer article validity from MST ordering or missing effective_to.
            # Identical text across MSTs is not a conflicting legal provision.
            return decision("ARTICLE_BRANCH_REVIEW_REQUIRED",
                            "MULTI_EFFECTIVE_DATE_PER_MST",
                            "ARTICLE_AND_ADDENDA_BRANCH_SELECTION_REQUIRED",
                            "TRANSITION_APPLICABILITY_REVIEW_REQUIRED",
                            vectors=vectors)
        # Even if all effective dates are source-grounded, event-type-specific
        # applicability may depend on old contracts and transitional provisions.
        return decision("TEMPORAL_REVIEW_REQUIRED",
                        "ARTICLE_DATES_MATCH_EVENT",
                        "TRANSITION_APPLICABILITY_REVIEW_REQUIRED",
                        vectors=vectors)
