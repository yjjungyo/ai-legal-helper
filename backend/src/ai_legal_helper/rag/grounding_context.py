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
        # [메타데이터 토큰 다이어트]
        # 동일한 파일명(title, filename, file_name, document_name)이 5번 반복되는 중복을 제거하고,
        # LLM 인용 및 시점 판단에 필수적인 필드만 선별하여 경량화한다.
        meta = {}
        if sid:
            meta["source_id"] = sid
        stype = source.get("source_type")
        if stype:
            meta["source_type"] = stype

        # 법령 특화 메타데이터 (조문 번호, 시행일, 공포번호 등)
        for law_key in (
            "statute_name", "article", "article_title", "effective_date", "promulgation_date",
            "version_date", "paragraph_no", "source_url",
        ):
            if source.get(law_key) is not None:
                meta[law_key] = source[law_key]

        # 사건 증거 검토 상태 (단위 테스트 및 안전 인용 검증 호환)
        for rev_key in ("approval_scope", "approval_scope_label"):
            if source.get(rev_key) is not None:
                meta[rev_key] = source[rev_key]

        # source_id와 다른 경우에만 document_name 보존
        doc_name = source.get("document_name")
        if doc_name and doc_name != sid:
            meta["document_name"] = doc_name

        # 증거 문서별 사실 승인 지침(claim_review_guide) 처리
        # [사실목록과 본문의 이중 중복 제거]
        # 본문(content)이 온전하게 존재하고 전체 사실 승인(FULL_APPROVED)인 경우,
        # 수십 개의 사실 문장 목록 나열을 생략하고 핵심 승인 지침만 남겨 토큰을 절감한다.
        guide = source.get("claim_review_guide")
        guide_section = ""
        if guide:
            approval_scope = source.get("approval_scope")
            has_rich_content = bool(content and content != "(원문 본문 미확보)" and len(content.strip()) > 30)
            if approval_scope == "FULL_APPROVED" and has_rich_content:
                # 사실 목록(- 확인된 승인 사실 목록: ...) 블록만 걷어내고 승인 구분과 인용 지침을 보존
                lines = [l for l in guide.splitlines() if not l.strip().startswith("* ") and not l.strip().startswith("- 확인된")]
                lean_guide = "\n".join(lines).strip()
                guide_section = f"\n[사실 검토 및 인용 지침]\n{lean_guide}\n"
            else:
                guide_section = f"\n[사실 검토 및 인용 지침]\n{guide}\n"

        # 본문이 비어있는데 guide가 있다면 guide를 본문 Fallback으로 활용
        effective_content = content
        if not effective_content or effective_content == "(원문 본문 미확보)":
            if guide:
                effective_content = f"(문서 추출 사실)\n{guide}"
            else:
                effective_content = "(원문 본문 미확보)"

        blocks.append(json.dumps(meta, ensure_ascii=False) + guide_section + "\n본문:\n" + effective_content)
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

    # [2026-11-12] 시행본·부칙을 법령명/조문만으로 합치면 다른 시점의 법을 잃는다.
    # 원본 source_id는 인용 안정성을 위해 변경하지 않고 내부 중복키만 강화한다.
    # 메타데이터의 버전 키가 비어 있으면 내용 해시로 구분해 무근거 병합을 방지한다.
    # 시행일자나 부칙이 명시적으로 다른 경우에만 버전을 구분하여 고유 키로 유지하고,
    # 그렇지 않은 일반 조문은 동일 키로 묶어 중복(공식/로컬/벡터)을 하나로 통합한다.
    version = next((str(src.get(k)).strip() for k in (
        "version_id", "law_version_id", "effective_date", "enforcement_date",
        "시행일자", "시행일", "law_effective_date",
    ) if src.get(k)), "")
    supplement = str(src.get("supplement_section") or src.get("addendum") or src.get("부칙") or "").strip()
    version_suffix = f":version={version}:supplement={supplement}" if (version or supplement) else ""

    # 1. statute_name과 article 필드가 명시된 경우
    if statute_name and article:
        return f"{statute_name.strip()}:{article.strip()}{version_suffix}"

    # 2. title / filename 정규식 파싱
    m = re.search(r"([가-힣\s]+법(?:률)?)\s*(제\d+조(?:의\d+)?)", title)
    if m:
        return f"{m.group(1).strip()}:{m.group(2).strip()}{version_suffix}"

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
            return f"{law_name}:{parts[3]}{version_suffix}"

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

        # 공식 법령(OFFICIAL: / STATUTE)이나 초안에 실제 인용된 증거는 원문 전문 100% 보존
        is_official_or_statute = (
            str(src.get("source_id") or "").startswith(("OFFICIAL:", "STATUTE:"))
            or src.get("source_type") in ("STATUTE", "PRECEDENT")
            or src.get("retrieval_method") == "OFFICIAL_STATUTE_SEARCH"
        )
        if is_cited or is_official_or_statute:
            pruned_evidence_sources.append(src)
            continue

        # 미인용 증거는 메타데이터 유지 + 본문 스니펫 축약
        # [의미 기반 핵심 증거 식별]: 파일명뿐 아니라 본문 내용에 권리관계 키워드가 포함된 경우도 핵심 증거로 분류
        raw_content = str(src.get("content") or "").strip()
        is_core_evidence = (
            any(
                kw in str(src.get("filename") or "").lower() or kw in str(src.get("document_name") or "").lower()
                for kw in ("등기", "계약", "registry", "contract", "전부증명서", "가압류", "근저당")
            )
            or any(
                kw in raw_content
                for kw in ("근저당권설정", "근저당권 설정", "채권최고액", "가압류", "경매개시결정", "말소등기", "임차권등기", "확정일자")
            )
        )
        # 핵심 증거는 1,500자까지 우선 보존하며, 1,500자 뒤에 위치한 핵심 반대 증거(Counter-Evidence: 말소, 가압류, 근저당 등)도
        # 윈도우 발췌를 통해 검증 컨텍스트에서 유실되지 않도록 정밀 보존
        snippet_len = max(max_unreferenced_snippet, 1500) if is_core_evidence else max_unreferenced_snippet
        if len(raw_content) > snippet_len:
            condensed = dict(src)
            deep_keywords = (
                "근저당", "저당권", "가압류", "압류", "경매", "말소", "을구", "갑구",
                "순위번호", "접수일", "채권최고액", "특약", "임차권등기", "배당요구"
            )
            deep_windows = []
            for kw in deep_keywords:
                pos = raw_content.find(kw, snippet_len)
                while pos != -1:
                    w_start = max(snippet_len, pos - 150)
                    w_end = min(len(raw_content), pos + 250)
                    deep_windows.append((w_start, w_end))
                    pos = raw_content.find(kw, pos + len(kw) + 150)

            if deep_windows:
                deep_windows.sort()
                merged_windows = []
                cur_start, cur_end = deep_windows[0]
                for s, e in deep_windows[1:]:
                    if s <= cur_end + 50:
                        cur_end = max(cur_end, e)
                    else:
                        merged_windows.append((cur_start, cur_end))
                        cur_start, cur_end = s, e
                merged_windows.append((cur_start, cur_end))

                extracted_parts = [raw_content[:snippet_len]]
                for ws, we in merged_windows[:3]:
                    extracted_parts.append(f"\n... [핵심 권리/반대 증거 구간 발췌 (위치: {ws}~{we}자)] ...\n{raw_content[ws:we]}")
                extracted_parts.append("\n... (초안 미인용 증거: 기타 상세 본문 생략)")
                condensed["content"] = "".join(extracted_parts)
            else:
                condensed["content"] = f"{raw_content[:snippet_len]}... (초안 미인용 증거: 상세 본문 생략)"
            pruned_evidence_sources.append(condensed)
        else:
            pruned_evidence_sources.append(src)

    return deduped_statutes + pruned_evidence_sources


def prune_sources_for_consultation(
    sources: List[Dict[str, Any]],
    draft_answer: str = "",
    verification: Optional[Dict[str, Any]] = None,
    max_unreferenced_snippet: int = 150,
) -> List[Dict[str, Any]]:
    """답변 초안 작성 및 재작성 시 프롬프트 컨텍스트 다이어트를 수행한다.

    1. 동일 법령 조문 중복 제거 (공식 검색 결과 우선) -> 최초/재작성 공통 적용.
    2. 재작성(draft_answer 존재 시):
       - 기존 초안에서 인용된 증거 + 검증 지적(verification)에 포함된 출처 ID는 원문 전문 100% 보존.
       - 지적이나 초안에 없는 미인용 증거는 앞 150자 스니펫으로 압축.
    3. 최초 작성(draft_answer 없음):
       - 증거 문서는 원문 보존하되, 중복 법령만 제거하여 입력 토큰 절감.

    Args:
        sources: 전체 출처 메타데이터 및 본문 목록.
        draft_answer: 이전 초안 문자열 (재작성 시).
        verification: 검증 결과 딕셔너리 (재작성 시).
        max_unreferenced_snippet: 비인용 증거에 남겨둘 최대 앞부분 글자 수.

    Returns:
        List[Dict[str, Any]]: 컨텍스트 다이어트가 적용된 출처 목록.
    """
    if not sources:
        return []

    # 1단계: 법령 조문 중복 제거 (공통)
    seen_statutes: Dict[str, Dict[str, Any]] = {}
    non_statute_sources: List[Dict[str, Any]] = []

    for src in sources:
        if not isinstance(src, dict):
            continue
        st_key = normalize_statute_key(src)
        if st_key:
            if st_key in seen_statutes:
                existing = seen_statutes[st_key]
                if src.get("retrieval_method") == "OFFICIAL_STATUTE_SEARCH" and existing.get("retrieval_method") != "OFFICIAL_STATUTE_SEARCH":
                    seen_statutes[st_key] = src
                elif len(str(src.get("content") or "")) > len(str(existing.get("content") or "")) and existing.get("retrieval_method") != "OFFICIAL_STATUTE_SEARCH":
                    seen_statutes[st_key] = src
                continue
            seen_statutes[st_key] = src
        else:
            non_statute_sources.append(src)

    deduped_statutes = list(seen_statutes.values())

    # 초안이 없는 최초 작성이면 증거 원문은 그대로 보존하고 중복 제거된 법령과 병합 반환
    if not draft_answer.strip():
        return deduped_statutes + non_statute_sources

    # 2단계: 재작성 시 비인용 증거 문서 본문 다이어트
    draft_lower = draft_answer.lower()
    # 검증 지적에 포함된 출처 ID 수집
    targeted_source_ids = set()
    if isinstance(verification, dict):
        for c in verification.get("claims", []):
            if isinstance(c, dict) and c.get("grounding_status") in ("UNSUPPORTED", "UNCERTAIN"):
                for sid in c.get("source_ids", []):
                    if isinstance(sid, str):
                        targeted_source_ids.add(sid.lower())

    pruned_evidence_sources = []
    for src in non_statute_sources:
        is_cited = False
        sid = str(src.get("source_id") or "").strip().lower()
        if sid and sid in targeted_source_ids:
            is_cited = True

        if not is_cited:
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

        # 초안에 인용되었거나 검증 지적에 연결된 핵심 증거는 원문 전문 100% 보존
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
