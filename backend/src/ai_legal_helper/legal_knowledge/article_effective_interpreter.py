# -*- coding: utf-8 -*-
"""P12-10: grounded LLM interpretation of article effective dates.

Only pre-fetched official addenda are accepted. This module makes no official
network requests and never treats LLM output as legal applicability.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Sequence

from ai_legal_helper.tools.statute_temporal import iso_date

_ARTICLE = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?")
_ALLOWED = {"ARTICLE_EXCEPTION", "GENERAL_EFFECTIVE_DATE", "TRANSITION_REVIEW"}


def _normalize_article(value: str) -> str:
    match = _ARTICLE.fullmatch(str(value).strip())
    return re.sub(r"\s+", "", match.group()) if match else ""


@dataclass(frozen=True)
class EffectiveInterpretation:
    article_id: str
    effective_from: str | None
    status: str
    basis: str
    evidence_quote: str | None
    reason_code: str

    def as_dict(self) -> dict:
        return dict(article_id=self.article_id, effective_from=self.effective_from,
                    status=self.status, basis=self.basis,
                    evidence_quote=self.evidence_quote, reason_code=self.reason_code)


def interpret_article_dates(
    *,
    article_ids: Sequence[str],
    official_addenda: Sequence[str],
    promulgation_date: str | None,
    llm_invoke: Callable[[str], str] | None = None,
) -> list[EffectiveInterpretation]:
    """Require exact source quote, valid date and explicit article linkage.

    Caller must supply official, already-authorized XML addenda. In particular,
    an LLM cannot verify relative-date arithmetic or transitional applicability.
    """
    articles = tuple(dict.fromkeys(filter(None, (_normalize_article(a) for a in article_ids))))
    sources = [str(s).strip() for s in official_addenda if str(s).strip()]
    def unknown(article: str, reason: str) -> EffectiveInterpretation:
        return EffectiveInterpretation(article, None, "UNCONFIRMED", "NONE", None, reason)
    if not sources:
        return [unknown(a, "OFFICIAL_ADDENDUM_MISSING") for a in articles]
    if llm_invoke is None:
        return [unknown(a, "LLM_NOT_CONFIGURED") for a in articles]
    prompt = (
        "You extract Korean statutory effective dates from official addenda. "
        "Never infer or calculate dates. Return ONLY JSON array of objects with "
        "article_id, effective_from (YYYY-MM-DD or null), basis "
        "(ARTICLE_EXCEPTION, GENERAL_EFFECTIVE_DATE, TRANSITION_REVIEW), "
        "evidence_quote (exact contiguous substring of one source), and "
        "reason_code. An exception for an article overrides general dates. "
        "If exceptions, transitional provisions or relative dates need legal "
        "interpretation, set effective_from null and basis TRANSITION_REVIEW. "
        "Do not decide applicability.\n"
        + json.dumps({"articles": articles, "promulgation_date": promulgation_date,
                      "official_addenda": sources}, ensure_ascii=False)
    )
    try:
        response = llm_invoke(prompt)
        if not isinstance(response, str):
            response = str(getattr(response, "content", ""))
        parsed = json.loads(response)
        if not isinstance(parsed, list):
            raise ValueError("INVALID_LLM_FORMAT")
    except Exception:
        return [unknown(a, "LLM_RESPONSE_INVALID") for a in articles]
    candidates: dict[str, list[EffectiveInterpretation]] = {a: [] for a in articles}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        article = _normalize_article(item.get("article_id") or "")
        if article not in candidates:
            continue
        quote = item.get("evidence_quote")
        basis = item.get("basis")
        raw_date = item.get("effective_from")
        date = iso_date(raw_date)
        if (not isinstance(quote, str) or not quote.strip()
                or not any(quote in source for source in sources)
                or basis not in _ALLOWED):
            candidates[article].append(unknown(article, "SOURCE_QUOTE_UNVERIFIED"))
            continue
        if basis == "TRANSITION_REVIEW" or not date:
            candidates[article].append(EffectiveInterpretation(
                article, None, "REVIEW_REQUIRED", basis, quote,
                "TRANSITION_OR_DATE_REVIEW_REQUIRED"))
            continue
        # A date written in the quote is required; calculated relative dates
        # are never accepted solely on the model's assertion.
        literal_dates = re.findall(
            r"(?<!\\d)\\d{4}\\s*(?:년|[-./])\\s*\\d{1,2}\\s*(?:월|[-./])\\s*\\d{1,2}\\s*일?",
            quote,
        )
        if date not in {iso_date(raw) for raw in literal_dates}:
            candidates[article].append(unknown(article, "DATE_NOT_EXPLICIT_IN_QUOTE"))
            continue
        if basis == "ARTICLE_EXCEPTION" and article not in re.sub(r"\s+", "", quote):
            candidates[article].append(unknown(article, "ARTICLE_NOT_IN_EXCEPTION_QUOTE"))
            continue
        candidates[article].append(EffectiveInterpretation(
            article, date, "SOURCE_GROUNDED_CANDIDATE", basis, quote,
            "APPLICABILITY_REVIEW_REQUIRED"))
    results = []
    for article in articles:
        found = candidates[article]
        if not found:
            results.append(unknown(article, "ARTICLE_NOT_EXTRACTED"))
        elif any(x.status != "SOURCE_GROUNDED_CANDIDATE" for x in found):
            results.append(unknown(article, "UNRESOLVED_EXCEPTION_OR_SOURCE"))
        else:
            exceptions = [x for x in found if x.basis == "ARTICLE_EXCEPTION"]
            chosen = exceptions or found
            results.append(chosen[0] if len({x.effective_from for x in chosen}) == 1
                           else unknown(article, "CONFLICTING_EFFECTIVE_DATES"))
    return results


def interpret_with_company_llm(*, article_ids: Sequence[str],
                               official_addenda: Sequence[str],
                               promulgation_date: str | None) -> list[EffectiveInterpretation]:
    """Explicit opt-in entry point using the existing observable LLM gateway.

    Not invoked by the background indexing worker automatically: the caller
    controls cost and whether the official source is HILT-authorized.
    """
    from ai_legal_helper.llm.gateway import get_llm
    llm = get_llm(temperature=0.0)
    return interpret_article_dates(
        article_ids=article_ids, official_addenda=official_addenda,
        promulgation_date=promulgation_date,
        llm_invoke=lambda prompt: llm.invoke(prompt).content,
    )
