# -*- coding: utf-8 -*-
"""P0-LAW-01: 공식 법령명 색인을 이용한 검색 대상 식별기 (1차 독립 모듈).

목적:
    LLM이 생성한 법령명이 정답이라고 가정하지 않고 질문의 핵심 명사로 법제처
    법령명 목록을 역검색한다. 현재 단계는 법령 *이름* 탐색/검증만 수행하며,
    조문·부칙 또는 특정 시점의 적용 여부를 판정하지 않는다.
설계:
    추가 LLM을 호출하지 않는다. 공식 목록에서 확인된 법령만 결과에 포함한다.
    HTTP 호출은 기존 공식 검색기의 재시도/마스킹 함수를 재사용한다.
    실행 흐름 변경 전 회귀 테스트할 수 있도록 기존 LangGraph에는 연결하지 않는다.
"""
from __future__ import annotations

import logging
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_LAW_SUFFIX = ("시행령", "시행규칙", "법률", "특별법", "법", "령", "규칙", "규정")
_GRAMMAR_SUFFIX = ("을", "를", "은", "는", "이", "가", "의", "에", "와", "과", "로", "도")
_SENTENCE_SUFFIX = ("입니다", "습니다", "합니다", "하려고", "인가요", "하나요", "주세요")
_GENERIC_TERMS = {"시행령", "시행규칙", "법령", "계약", "신고", "개정", "확인", "반드시", "새로운", "최신"}


@dataclass(frozen=True)
class VerifiedStatuteCandidate:
    """공식 법령 목록에서 이름을 확인한 검색 후보 (조문 검증 결과가 아님)."""

    law_name: str
    law_id: str
    law_type: str
    score: int
    reasons: tuple[str, ...] = ()


@dataclass
class StatuteResolution:
    """후보 선정 결과와 감사를 위한 시도 내역."""

    status: str
    candidates: list[VerifiedStatuteCandidate] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    skipped_llm_candidates: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    """공백·구두점이 달라도 내용어를 비교할 수 있도록 정규화한다."""
    return re.sub(r"[^가-힣A-Za-z0-9]", "", text or "").lower()


def _core_terms(law_name: str) -> list[str]:
    """법령의 문법적 접미 표현을 제외한 법률 분야 식별어를 추출한다."""
    core = re.sub(r"등에\s*관한|에\s*관한|관한|등의|및", " ", law_name)
    for suffix in _LAW_SUFFIX:
        core = re.sub(rf"{suffix}(?=\s|$)", " ", core)
    return [word for word in re.findall(r"[가-힣]{2,}", core) if word not in _GENERIC_TERMS]


def _search_terms(question: str, llm_candidates: list[str], max_queries: int) -> list[str]:
    """질문에서 법령명에 포함될 가능성이 높은 긴 내용어를 우선 선택한다.

    도메인별 법령명/단어 매핑은 두지 않는다. 사람·날짜·서술어를 제외하고
    길고 구체적인 단어를 먼저 공식 목록에 질의한다.
    """
    terms: list[tuple[int, str]] = []
    for idx, raw in enumerate(re.findall(r"[가-힣]{4,}", question or "")):
        if raw.endswith(_SENTENCE_SUFFIX):
            continue
        word = raw
        if word.endswith(_GRAMMAR_SUFFIX):
            word = word[:-1]
        if len(word) < 4 or word in _GENERIC_TERMS or word.endswith(_SENTENCE_SUFFIX):
            continue
        # 검색 순서는 고유어 길이 우선, 같은 길이면 질문에 먼저 등장한 단어 우선.
        terms.append((idx, word))
    terms.sort(key=lambda item: (-len(item[1]), item[0]))
    ordered = list(dict.fromkeys(term for _, term in terms))
    # 질문이 '민법 제6조'처럼 짧은 경우 LLM 법령명을 폴백 검색어로만 사용한다.
    for law in llm_candidates:
        name = str(law or "").strip(" 「」")
        if name and any(name.endswith(s) for s in _LAW_SUFFIX) and name not in ordered:
            ordered.append(name)
    return ordered[:max_queries]


def _score(question: str, name: str, proposed: set[str]) -> tuple[int, tuple[str, ...]]:
    """법령명과 원문 질문의 실질 내용어 일치도 및 명시 유형을 점수화한다."""
    normalized_question = _normalize(question)
    matching = [t for t in _core_terms(name) if _normalize(t) in normalized_question]
    exact_reference = bool(_normalize(name) and _normalize(name) in normalized_question)
    if not matching and not exact_reference:
        return 0, ("질문에 법령의 고유 식별어가 확인되지 않음",)
    score = sum(len(t) * 10 for t in matching)
    reasons = [f"질문-법령명 식별어 일치: {', '.join(matching)}"] if matching else []
    if exact_reference:
        score = max(score, 50)
        reasons.append("질문에 정식 법령명 명시")
    for law_type in ("시행령", "시행규칙"):
        if law_type in question and name.endswith(law_type):
            score += 25
            reasons.append(f"질문에 명시된 법령 유형 일치: {law_type}")
            break
    if name in proposed:
        score += 5
        reasons.append("LLM 후보와 공식 법령명 일치")
    return score, tuple(reasons)


def resolve_statute_candidates(
    question: str,
    llm_candidates: list[str],
    *,
    fetch_xml: Optional[Callable[[str], Optional[bytes]]] = None,
    max_queries: int = 3,
    max_candidates: int = 5,
) -> StatuteResolution:
    """공식 법령 *목록*을 검색해 후보를 순위화한다.

    Args:
        question: 사용자 원본 질문 (개인정보는 외부 쿼리로 보내지 않음).
        llm_candidates: 검증 단계가 제안한 법령명 (확정 사실로 취급하지 않음).
        fetch_xml: 테스트에서 외부 네트워크를 대체할 주입 함수.
        max_queries: 대기시간 제어를 위한 법령명 검색 최대 횟수.
        max_candidates: 반환할 공식 확인 후보 상한.

    Returns:
        공식 법령명 확인 후보, 조회에 사용한 단어, 근거 부족 LLM 후보.
        조회 실패 시 후보를 만들어내거나 LLM 후보를 검증 완료로 승격하지 않음.
    """
    api_key = os.getenv("LAW_OPENAPI_KEY", "")
    if not api_key and fetch_xml is None:
        logger.warning("[STATUTE_RESOLVER] LAW_OPENAPI_KEY 부재: 공식 법령명 확인 생략")
        return StatuteResolution(status="NO_API_KEY", skipped_llm_candidates=list(llm_candidates))
    if not question.strip() or max_queries <= 0:
        return StatuteResolution(status="NO_QUERY", skipped_llm_candidates=list(llm_candidates))

    # 기존 검색 도구에서 구현된 재시도와 민감정보 마스킹을 그대로 사용한다.
    if fetch_xml is None:
        from ai_legal_helper.tools.official_statute_search import _fetch_xml_with_retry

        def fetch_xml(url: str) -> Optional[bytes]:
            return _fetch_xml_with_retry(url, api_key=api_key)

    proposed = {str(x).strip(" 「」") for x in llm_candidates}
    terms = _search_terms(question, llm_candidates, max_queries)
    by_name: dict[str, VerifiedStatuteCandidate] = {}
    queried: list[str] = []
    for term in terms:
        queried.append(term)
        url = ("https://www.law.go.kr/DRF/lawSearch.do?"
               + urllib.parse.urlencode({"OC": api_key, "target": "law", "type": "XML", "query": term}))
        try:
            raw = fetch_xml(url)
            if not raw:
                logger.warning("[STATUTE_RESOLVER] 법령명 조회 응답 없음 | 검색어=%s", term)
                continue
            root = ET.fromstring(raw)
        except (ET.ParseError, OSError, ValueError) as exc:
            logger.warning("[STATUTE_RESOLVER] 조회 실패 | 검색어=%s | 오류종류=%s", term, type(exc).__name__)
            continue
        for elem in root.findall(".//law"):
            name = (elem.findtext("법령명한글") or "").strip()
            if not name:
                continue
            score, reasons = _score(question, name, proposed)
            if score <= 0:
                logger.info("[STATUTE_RESOLVER] 후보 제외 | 법령=%s | 근거=%s", name, "; ".join(reasons))
                continue
            candidate = VerifiedStatuteCandidate(
                law_name=name,
                law_id=(elem.findtext("법령ID") or "").strip(),
                law_type=(elem.findtext("법령구분명") or "").strip(),
                score=score,
                reasons=reasons,
            )
            if name not in by_name or by_name[name].score < score:
                by_name[name] = candidate
        logger.info("[STATUTE_RESOLVER] 공식 법령명 검색 | 검색어=%s | 누적적합후보=%d", term, len(by_name))
        # 명시된 시행령 등 유형까지 일치하는 높은 신뢰도 후보라면 불필요한 재조회 방지.
        if any(c.score >= 75 for c in by_name.values()):
            break

    candidates = sorted(by_name.values(), key=lambda c: (-c.score, c.law_name))[:max_candidates]
    accepted = {c.law_name for c in candidates}
    rejected = [name for name in llm_candidates if str(name).strip(" 「」") not in accepted]
    for c in candidates:
        logger.info("[STATUTE_RESOLVER] 공식 확인 후보 | 법령=%s | 점수=%d | 이유=%s",
                    c.law_name, c.score, "; ".join(c.reasons))
    logger.info("[STATUTE_RESOLVER] 후보 탐색 종료 | 검색어=%s | 공식후보=%s | 미선정LLM후보=%s",
                queried, [c.law_name for c in candidates], rejected)
    return StatuteResolution(status="FOUND" if candidates else "NO_MATCH",
                             candidates=candidates, search_terms=queried,
                             skipped_llm_candidates=rejected)
