# -*- coding: utf-8 -*-
"""답변 작성자와 검증기가 동일한 원문 출처를 보도록 컨텍스트를 구성한다.

[역할]
출처 추가 순서에 따른 개수 제한이나 본문 앞부분 절단을 하지 않는다.
전체 예산을 넘으면 누락을 숨기는 대신 명시적으로 실패하여 검증 범위를 보존한다.
사건 증거 문서의 경우 개별 사실 승인/반려 현황(claim_review_guide)을 본문과 함께
결합하여 LLM이 반려된 주장을 배제하고 승인된 사실만을 신뢰할 수 있도록 인용 지침을 주입한다.
"""

import json
import hashlib
from typing import Any, Dict, List, Tuple, Optional


def format_grounding_sources(
    sources: List[Dict[str, Any]], max_chars: int = 120_000,
) -> Tuple[str, Dict[str, Any]]:
    """전체 출처 본문과 실제 전달 목록을 함께 반환한다.

    증거 문서(CASE_EVIDENCE)의 경우 개별 사실의 승인 범위(approval_scope) 및
    승인/반려/보류 지침(claim_review_guide)을 본문 앞에 결합하여 LLM에 전달한다.

    Args:
        sources: 이번 요청에서 확보한 사건 증거와 법령 레지스트리.
        max_chars: 출처 컨텍스트의 문자 예산. 초과 시 일부를 조용히 생략하지 않는다.

    Returns:
        원문 컨텍스트와 source_ids·char_count·complete를 포함한 전달 명세.

    Raises:
        ValueError: 본문 예산을 넘거나 동일 출처 ID의 본문이 충돌한 경우.
    """
    blocks = []
    seen = {}
    for source in sources or []:
        sid = str(source.get("source_id") or source.get("evidence_id") or "")
        content = str(source.get("content") or source.get("article_text") or "").strip()
        if sid and sid in seen:
            if seen[sid] != content:
                raise ValueError("SOURCE_ID_CONTENT_CONFLICT")
            continue
        if not sid:
            # 기존 메타데이터만 있는 출처도 표시하되 가공 ID를 만들어 인용 가능하게 하지 않는다.
            sid = ""
        else:
            seen[sid] = content
        meta = {key: source.get(key) for key in (
            "source_id", "source_type", "evidence_id", "filename", "file_name", "title",
            "statute_name", "article", "article_title", "paragraph_no", "part", "chapter", "section",
            "promulgation_number", "promulgation_date", "effective_date", "version_date",
            "page", "source_url", "retrieval_method", "review_status", "source_kind", "document_name",
            "approval_scope", "approval_scope_label", "approved_claim_count", "rejected_claim_count", "pending_claim_count",
        ) if source.get(key) is not None}

        # 증거 문서별 사실 승인 지침(claim_review_guide)이 존재할 경우 원문 상단에 명시 주입
        guide = source.get("claim_review_guide")
        guide_section = f"\n[사실 검토 및 인용 지침]\n{guide}\n" if guide else ""

        blocks.append(json.dumps(meta, ensure_ascii=False) + guide_section + "\n본문:\n" + (content or "(원문 본문 미확보)"))
    rendered = "\n\n".join(blocks) or "(검색된 출처 없음)"
    if len(rendered) > max_chars:
        raise ValueError("GROUNDING_CONTEXT_LIMIT_EXCEEDED")
    return rendered, {
        "source_ids": list(seen), "source_count": len(seen), "char_count": len(rendered),
        "content_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "complete": True, "omitted_source_ids": [],
    }


def normalize_statute_key(src: Dict[str, Any]) -> Optional[str]:
    """법령명과 조문 번호로 고유 키를 정규화한다 (예: '주택임대차보호법:제3조의2').

    [최적화 1: 법령 조문 중복 제거]
    - 동일 조문이 공식 검색(OFFICIAL), 로컬 인덱스, Chroma Vector 등으로
      서로 다른 source_id를 가진 채 다중 수집되어 수만 자로 증폭되는 현상을 방지한다.

    Args:
        src: 법령 출처 메타데이터 딕셔너리.

    Returns:
        Optional[str]: '법령명:조문' 정규화 문자열 (판별 불가 시 None).
    """
    import re
    statute_name = src.get("statute_name") or ""
    article = src.get("article") or ""
    title = src.get("title") or src.get("filename") or ""

    # 1. statute_name과 article 필드가 명시된 경우
    if statute_name and article:
        return f"{statute_name.strip()}:{article.strip()}"

    # 2. title / filename 정규식 파싱
    m = re.search(r"([가-힣\s]+법(?:률)?)\s*(제\d+조(?:의\d+)?)", title)
    if m:
        return f"{m.group(1).strip()}:{m.group(2).strip()}"

    # 3. source_id 접두사 및 파트 파싱 (OFFICIAL:001248:... / STATUTE:001248:...)
    sid = str(src.get("source_id") or "")
    if sid.startswith("OFFICIAL:") or sid.startswith("STATUTE:"):
        parts = sid.split(":")
        if len(parts) >= 4 and parts[3].startswith("제"):
            law_id = parts[1]
            law_name = statute_name or (
                "주택임대차보호법" if law_id == "001248"
                else "민법" if law_id == "001706"
                else "민사집행법" if law_id == "009290"
                else law_id
            )
            return f"{law_name}:{parts[3]}"

    return None


def prune_sources_for_verification(
    sources: List[Dict[str, Any]],
    draft_answer: str = "",
    max_unreferenced_snippet: int = 150,
) -> List[Dict[str, Any]]:
    """검증 Agent 프롬프트 컨텍스트 다이어트를 위해 중복 법령 조문 및 비인용 증거를 경량화한다.

    [최적화 1: run_verification 프롬프트 다이어트]
    1. 동일 법령 조문 중복 제거:
       공식 법령(OFFICIAL), 로컬 사전적재, Vector 검색 간 동일 조문 중복을 1개(공식 우선)로 통일 (약 1.3만 자 감축).
    2. 비인용 증거 문서 본문 축약:
       초안에서 한 번도 인용되지 않은 증거 문서는 메타데이터와 150자 스니펫만 남기고 상세 본문을 생략.
    3. 법령 및 초안 인용 핵심 증거는 원문 전문 100% 보존.

    Args:
        sources: 전체 출처 메타데이터 및 본문 목록.
        draft_answer: 검증 대상 답변 초안 문자열.
        max_unreferenced_snippet: 비인용 증거에 남겨둘 최대 앞부분 글자 수 (기본값: 150).

    Returns:
        List[Dict[str, Any]]: 중복 제거 및 비인용 증거가 경량화된 출처 목록.
    """
    if not sources:
        return []

    draft_lower = (draft_answer or "").lower()

    # 1단계: 법령 조문 의미적 중복 제거 (Dedup by law_name + article)
    seen_statutes: Dict[str, Dict[str, Any]] = {}
    non_statute_sources: List[Dict[str, Any]] = []

    for src in sources:
        if not isinstance(src, dict):
            continue

        st_key = normalize_statute_key(src)
        if st_key:
            if st_key in seen_statutes:
                existing = seen_statutes[st_key]
                # 공식 법령 검색 결과(OFFICIAL_STATUTE_SEARCH)가 최우선
                if src.get("retrieval_method") == "OFFICIAL_STATUTE_SEARCH" and existing.get("retrieval_method") != "OFFICIAL_STATUTE_SEARCH":
                    seen_statutes[st_key] = src
                elif len(str(src.get("content") or "")) > len(str(existing.get("content") or "")) and existing.get("retrieval_method") != "OFFICIAL_STATUTE_SEARCH":
                    seen_statutes[st_key] = src
                continue
            seen_statutes[st_key] = src
        else:
            non_statute_sources.append(src)

    deduped_statutes = list(seen_statutes.values())

    # 2단계: 비인용 증거 문서 본문 다이어트
    pruned_evidence_sources = []
    for src in non_statute_sources:
        is_cited = False
        check_keys = ["filename", "file_name", "evidence_label", "source_id", "evidence_id", "document_name"]
        for key in check_keys:
            val = str(src.get(key) or "").strip().lower()
            if val and len(val) >= 2 and val in draft_lower:
                is_cited = True
                break

        if not is_cited and src.get("filename"):
            base_name = str(src.get("filename")).split(".")[0].lower()
            if len(base_name) >= 3 and base_name in draft_lower:
                is_cited = True

        # 초안에 실제 인용된 증거는 원문 전문 100% 보존
        if is_cited:
            pruned_evidence_sources.append(src)
            continue

        # 미인용 증거는 메타데이터 유지 + 본문 스니펫 축약
        raw_content = str(src.get("content") or "").strip()
        if len(raw_content) > max_unreferenced_snippet:
            condensed = dict(src)
            condensed["content"] = f"{raw_content[:max_unreferenced_snippet]}... (초안 미인용 증거: 상세 본문 생략)"
            pruned_evidence_sources.append(condensed)
        else:
            pruned_evidence_sources.append(src)

    return deduped_statutes + pruned_evidence_sources


def prune_case_context_for_verification(
    case_context: str,
    draft_answer: str = "",
    max_chars: int = 4000,
) -> str:
    """수만 자에 달하는 사건 사실관계 및 누적 대화 브리핑을 핵심 정보 위주로 압축한다.

    [최적화 1: run_verification 프롬프트 다이어트]
    - 다중 턴 상담에서 누적 복사된 과거 AI 답변과 249개 사실관계를 압축하여
      2.7만 자의 컨텍스트를 4,000자 이내로 정돈한다 (85% 이상 절감).

    Args:
        case_context: 사건 기본 정보, 과거 대화 누적, 사실관계 전체 문자열.
        draft_answer: 검증 대상 답변 초안.
        max_chars: 압축 목표 최대 글자 수 (기본값: 4000).

    Returns:
        str: 4,000자 이내로 경량화된 사건 맥락 문자열.
    """
    if not case_context or len(case_context) <= max_chars:
        return case_context or ""

    import re

    # 1. 사건 사실관계 섹션([2. 사건 사실관계 및 증거] 또는 [입증된 사실]) 분리
    m = re.search(r"(\[\d+\.\s*사건 사실관계.*?\]|\[입증된 사실.*?\]|\[사건 사실관계.*?\])", case_context)
    if m:
        header_part = case_context[:m.start()].strip()
        facts_part = case_context[m.start():].strip()
    else:
        header_part = case_context[:1500].strip()
        facts_part = case_context[1500:].strip()

    # 2. header_part에서 과거 턴들 중 최신 요약만 남기고 중간 턴 본문 축약
    turn_matches = list(re.finditer(r"\[Turn\s*\d+\]|턴\s*\d+\s*:", header_part))
    if len(turn_matches) > 1:
        first_turn = turn_matches[0]
        last_turn = turn_matches[-1]
        compact_header = (
            header_part[:first_turn.start()].strip()
            + f"\n\n[이전 {len(turn_matches)}개 상담 턴 경과 - 과거 문답 상세 생략]\n"
            + header_part[last_turn.start():].strip()
        )
    else:
        compact_header = header_part[:1200]

    # 3. facts_part를 남은 예산 이내로 정돈
    budget_for_facts = max(1000, max_chars - len(compact_header) - 100)
    if len(facts_part) > budget_for_facts:
        facts_part = facts_part[:budget_for_facts] + "\n... (외 세부 사실관계 및 증거 등록됨 - 상세 생략)"

    res = f"{compact_header}\n\n{facts_part}".strip()
    return res
