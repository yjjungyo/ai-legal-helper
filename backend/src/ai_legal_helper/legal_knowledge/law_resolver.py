# -*- coding: utf-8 -*-
"""
P2 전체 법령명 기반 Law Resolver.

[역할]
기존 8개 Agent의 범주와 무관하게 PostgreSQL Law Catalog에서 공식 법령명·
법령약칭을 식별한다. 검색 결과는 법령 후보이며 조문·시행일·적용례에 대한
검증 결과가 아니다. Vector 적재 여부도 이 단계의 판정 대상이 아니다.

[보안/품질]
- 기본 동작은 오직 로컬 카탈로그 읽기. 외부 API/LLM 호출은 절대 하지 않는다.
- 법령명 경계 검사를 하므로 '민법'을 '난민법'의 부분 문자열로 오인하지 않는다.
- 동일한 공식 약칭이 서로 다른 법령에 속하면 AMBIGUOUS로 명시한다.
- 법률/시행령/시행규칙의 이름 유사성은 검토 후보만 제시하며 법적 위임
  관계나 적용 우선순위를 자동으로 확정하지 않는다.
- LLM이 제시한 후보는 공식 카탈로그에서 ID가 확인되기 전까지 채택하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ai_legal_helper.legal_knowledge.catalog_store import LawCatalogStore
from ai_legal_helper.legal_knowledge.law_catalog import normalize_law_name

_PARTICLES = (
    "으로부터", "에게서는", "에서는", "에서", "으로", "에게", "까지", "부터",
    "상의", "상", "에", "의", "은", "는", "이", "가", "을", "를", "와", "과", "도",
)
_HANGUL_OR_ALNUM = re.compile(r"[가-힣A-Za-z0-9]")
_ARTICLE_BEGIN = re.compile(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?")


@dataclass(frozen=True)
class ResolvedLaw:
    """공식 법령 ID가 확인된 검색 대상. 법적 적용 여부는 미검증이다."""

    law_id: str
    law_name: str
    law_type: str
    source: str
    matched_text: str
    score: int
    current_mst: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "law_id": self.law_id,
            "law_name": self.law_name,
            "law_type": self.law_type,
            "source": self.source,
            "matched_text": self.matched_text,
            "score": self.score,
            "current_mst": self.current_mst,
        }


@dataclass(frozen=True)
class LawFamilySuggestion:
    """이름 기반 관계 후보이며 법률의 위임/우선순위가 증명되지는 않았다."""

    law_id: str
    law_name: str
    relation_status: str = "NAME_FAMILY_CANDIDATE"


@dataclass
class LawResolution:
    """검색 결과와 미해결 상태. 동일 질문에 여러 법령이 필요할 수 있다."""

    status: str
    laws: list[ResolvedLaw] = field(default_factory=list)
    family_suggestions: list[LawFamilySuggestion] = field(default_factory=list)
    reason_code: str = ""
    official_search_required: bool = False


def _has_word_boundary(text: str, start: int, end: int) -> bool:
    """한국어 법령명 뒤 조사·조문 연결은 허용하고 긴 단어 속 포함은 제외한다."""
    if start > 0 and _HANGUL_OR_ALNUM.fullmatch(text[start - 1]):
        return False
    rest = text[end:]
    if not rest or not _HANGUL_OR_ALNUM.fullmatch(rest[0]):
        return True
    if _ARTICLE_BEGIN.match(rest):
        return True
    for particle in _PARTICLES:
        if not rest.startswith(particle):
            continue
        remain = rest[len(particle):]
        if not remain or not _HANGUL_OR_ALNUM.fullmatch(remain[0]) or _ARTICLE_BEGIN.match(remain):
            return True
    return False


def _explicit_spans(question: str, label: str) -> list[tuple[int, int]]:
    """공백 차이를 허용한 정확한 법령명/공식 약칭 매치만 반환."""
    if not label:
        return []
    pieces = label.split()
    pattern = r"\s*".join(re.escape(piece) for piece in pieces)
    return [
        (match.start(), match.end())
        for match in re.finditer(pattern, question, flags=re.IGNORECASE)
        if _has_word_boundary(question, match.start(), match.end())
    ]


def _family_base(name: str) -> str:
    """이름 끝의 시행령·시행규칙만 떼어내어 관련 법령 후보를 찾는다."""
    for suffix in ("시행규칙", "시행령"):
        if name.endswith(suffix):
            return normalize_law_name(name[:-len(suffix)])
    return normalize_law_name(name)


class LawResolver:
    """기존 Agent 라우팅과 분리된 공식 법령 후보 식별기."""

    def __init__(self, catalog: LawCatalogStore):
        self.catalog = catalog

    def resolve(
        self,
        question: str,
        *,
        suggested_laws: Optional[Iterable[str]] = None,
        max_candidates: int = 8,
    ) -> LawResolution:
        """질문에 명시된 공식 명칭/약칭을 우선하고 LLM 제안은 검증 후만 수용.

        Returns:
            FOUND: 질문에서 공식 명칭/약칭 직접 발견
            MULTIPLE: 질문에서 서로 다른 공식 법령명을 독립적으로 명시
            AMBIGUOUS: 동일 표현이 복수 공식 law_id에 연결
            SUGGESTED: 질문에는 법령명이 없지만 공식 이름과 일치한 제안
            NO_MATCH: 공식 법령 후보 없음 (추후 HILT 공식 검색 필요)
            CATALOG_EMPTY: 관리자 목록 동기화가 필요
        """
        if not question or not question.strip() or max_candidates <= 0:
            return LawResolution("NO_MATCH", reason_code="EMPTY_QUESTION",
                                 official_search_required=False)
        entries = self.catalog.all_entries()
        if not entries:
            return LawResolution("CATALOG_EMPTY", reason_code="CATALOG_NOT_SYNCED",
                                 official_search_required=True)
        matched: list[tuple[int, int, ResolvedLaw]] = []
        for row in entries:
            labels = [(row.official_name, "OFFICIAL_NAME", 1000)]
            labels.extend((alias.alias_name, "OFFICIAL_ALIAS" if alias.source == "OFFICIAL"
                           else "REVIEWED_ALIAS", 850)
                          for alias in row.aliases
                          if alias.source in ("OFFICIAL", "REVIEWED"))
            for label, source, base_score in labels:
                for start, end in _explicit_spans(question, label):
                    matched.append((start, end, ResolvedLaw(
                        law_id=row.law_id, law_name=row.official_name,
                        law_type=row.law_type or "", source=source,
                        matched_text=label,
                        score=base_score + len(normalize_law_name(label)),
                        current_mst=row.current_mst,
                    )))

        # 더 긴 명칭의 일부인 짧은 법령명(예: '...법' vs '...법 시행령')은
        # 독립된 질문 참조로 취급하지 않는다. 동일 길이 별칭 충돌은 모두 보존한다.
        direct: list[ResolvedLaw] = []
        for start, end, candidate in matched:
            if any(
                other_start <= start and end <= other_end
                and (other_start < start or other_end > end)
                for other_start, other_end, _ in matched
            ):
                continue
            direct.append(candidate)

        if direct:
            by_id: dict[str, ResolvedLaw] = {}
            for candidate in direct:
                if candidate.law_id not in by_id or candidate.score > by_id[candidate.law_id].score:
                    by_id[candidate.law_id] = candidate
            found = sorted(by_id.values(), key=lambda c: (-c.score, c.law_name))[:max_candidates]
            # 동일 span의 복수 law_id는 약칭 충돌일 수 있으므로 단정하지 않는다.
            ambiguous = any(
                len({c.law_id for s, e, c in matched if (s, e) == (start, end)}) > 1
                for start, end, _ in matched
            )
            return LawResolution(
                status="AMBIGUOUS" if ambiguous else ("MULTIPLE" if len(found) > 1 else "FOUND"),
                laws=found, family_suggestions=self._family_candidates(found, entries),
                reason_code="SHARED_ALIAS" if ambiguous else "DIRECT_OFFICIAL_NAME_MATCH",
                official_search_required=ambiguous,
            )

        # 질문에 실제 법령명이 없으면 LLM 제안은 정확한 공식 명칭/약칭일 때만
        # 검색 대상으로 수용한다. 법적 근거 또는 질문 관련성 검증 완료로 취급하지 않는다.
        suggested = list(suggested_laws or [])
        by_id: dict[str, ResolvedLaw] = {}
        for hint in suggested[:10]:
            label = re.split(r"제\s*\d+\s*조", str(hint), maxsplit=1)[0].strip(" 「」")
            key = normalize_law_name(label)
            if not key:
                continue
            for row in entries:
                labels = {row.name_key} | {
                    a.alias_key for a in row.aliases if a.source in ("OFFICIAL", "REVIEWED")
                }
                if key not in labels:
                    continue
                by_id[row.law_id] = ResolvedLaw(
                    law_id=row.law_id, law_name=row.official_name,
                    law_type=row.law_type or "", source="SUGGESTED_CATALOG_VERIFIED",
                    matched_text=label, score=500,
                    current_mst=row.current_mst,
                )
        proposed = sorted(by_id.values(), key=lambda c: c.law_name)[:max_candidates]
        return LawResolution(
            status=("AMBIGUOUS" if len(proposed) > 1 and len(suggested) == 1
                    else "SUGGESTED") if proposed else "NO_MATCH",
            laws=proposed,
            family_suggestions=self._family_candidates(proposed, entries),
            reason_code="LLM_CANDIDATE_ONLY" if proposed else "NO_OFFICIAL_NAME_MATCH",
            official_search_required=not bool(proposed) or (len(proposed) > 1 and len(suggested) == 1),
        )

    @staticmethod
    def _family_candidates(found: list[ResolvedLaw], entries: list) -> list[LawFamilySuggestion]:
        """동일 법명 기초 부분만 비교한다. 권한 위임 관계는 아직 미확정."""
        known = {x.law_id for x in found}
        bases = {_family_base(x.law_name) for x in found}
        suggestions = [
            LawFamilySuggestion(row.law_id, row.official_name)
            for row in entries
            if row.law_id not in known and _family_base(row.official_name) in bases
        ]
        return sorted(suggestions, key=lambda item: item.law_name)
