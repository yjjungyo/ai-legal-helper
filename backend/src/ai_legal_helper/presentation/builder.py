"""검증된 상담 원문을 의미 변경 없이 UI 표현 블록으로 변환한다 (P2).

- 추가 LLM 호출 없음, 법률 판단/문장 재작성 없음
- SHA가 제공된 상담은 반드시 검증 당시의 SHA와 최종 answer의 일치를 확인
- Supported 주장 중 답변에서 '정확히 한 곳'에 나타나는 것만 출처 연결
- UI 구조화 불가능/미검증 상태이면 None (legacy answer 그대로 사용)
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Optional, Sequence

from ai_legal_helper.api.schemas.consultation import (
    ConsultationPresentation,
    PresentationBlock,
    PresentationClaim,
    PresentationSource,
)

_MARKDOWN_HEADING = re.compile(r"^#{1,4}[ \t]+\S")
_BRACKET_HEADING = re.compile(r"^\[([^\[\]\r\n]+)\]$")
_EVIDENCE_LABEL = re.compile(r"^E\d{1,3}(?:$|[_.\s-])", re.IGNORECASE)
_EVIDENCE_EXT = re.compile(r"\.(?:pdf|docx|txt|png|jpg|jpeg)$", re.IGNORECASE)


def _is_heading(line: str) -> bool:
    text = line.rstrip("\r\n").strip()
    if _MARKDOWN_HEADING.match(text):
        return True
    match = _BRACKET_HEADING.fullmatch(text)
    if not match:
        return False
    name = match.group(1).strip()
    # 출처 인용을 섹션 제목으로 오인하지 않는다.
    if _EVIDENCE_LABEL.match(name) or _EVIDENCE_EXT.search(name):
        return False
    return True


def _split_original(answer: str) -> list[PresentationBlock]:
    """원본 한 글자도 없애지 않고 [start,end) 구간으로 분할한다."""
    boundaries = [0]
    offset = 0
    for line in answer.splitlines(keepends=True):
        if offset and _is_heading(line):
            boundaries.append(offset)
        offset += len(line)
    boundaries.append(len(answer))
    blocks = []
    for i, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        if start >= end:
            continue
        markdown = answer[start:end]
        first_line = markdown.splitlines()[0] if markdown.splitlines() else ""
        is_section = _is_heading(first_line)
        kind = "SECTION" if is_section else ("LEAD" if not blocks else "BODY")
        title = None
        if is_section:
            stripped = first_line.strip()
            title = re.sub(r"^#{1,4}[ \t]+", "", stripped).strip() if stripped.startswith("#") else stripped[1:-1].strip()
        blocks.append(PresentationBlock(
            block_id=f"B{i:03d}", kind=kind, start=start, end=end,
            markdown=markdown, title=title,
        ))
    # 이 불변식이 깨지면 결과를 화면에 전달하지 않는다.
    if "".join(block.markdown for block in blocks) != answer:
        raise ValueError("PRESENTATION_TEXT_MISMATCH")
    return blocks


def _source_record(raw: Any) -> Optional[dict]:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    return None


def build_consultation_presentation(
    *, answer: Optional[str], verification_result: Optional[dict],
    verification_status: Optional[str], answer_status: Optional[str],
    sources: Sequence[Any],
) -> Optional[ConsultationPresentation]:
    """최종 답변의 문장/순서를 보존하는 읽기 전용 표현 모델을 생성한다."""
    if not isinstance(answer, str) or not answer.strip():
        return None
    if verification_status != "PASS" or answer_status not in ("DELIVERED", "CAUTIONARY", "REVISED"):
        return None
    verification = verification_result if isinstance(verification_result, dict) else {}
    if verification.get("status") != "PASS":
        return None
    digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()
    verified_hash = verification.get("verified_answer_sha256")
    if verified_hash and verified_hash != digest:
        return None
    binding = "HASH_MATCHED" if verified_hash else "STATUS_MATCHED"

    blocks = _split_original(answer)
    refs: list[PresentationSource] = []
    allowed: set[str] = set()
    for raw in sources or []:
        src = _source_record(raw)
        if not src:
            continue
        sid = src.get("source_id")
        if not isinstance(sid, str) or not sid.strip() or sid in allowed or sid == "UNKNOWN":
            continue
        name = (src.get("original_filename") or src.get("document_name") or src.get("filename")
                or src.get("statute_name") or src.get("title") or "").strip()
        allowed.add(sid)
        refs.append(PresentationSource(
            source_id=sid, source_type=src.get("source_type"),
            display_name=name or "출처명 확인 필요",
            document_name=(src.get("original_filename") or src.get("document_name") or src.get("filename")),
            evidence_id=src.get("evidence_id"), claim_id=src.get("claim_id"),
            span_id=src.get("span_id"), statute_name=src.get("statute_name"),
            article=src.get("article"), source_url=src.get("source_url"),
        ))

    claims: list[PresentationClaim] = []
    verified_claims = verification.get("claims")
    if not isinstance(verified_claims, list):
        verified_claims = []
    for item in verified_claims:
        if not isinstance(item, dict) or item.get("grounding_status") != "SUPPORTED":
            continue
        txt = item.get("claim")
        # 유사도 추론 금지: 원문 내 정확한 1회 일치만 연동한다.
        if not isinstance(txt, str) or not txt or answer.count(txt) != 1:
            continue
        start = answer.index(txt)
        end = start + len(txt)
        ids = item.get("source_ids") or []
        if not isinstance(ids, list):
            ids = []
        matched = list(dict.fromkeys(sid for sid in ids if isinstance(sid, str) and sid in allowed))
        claim_id = f"C{len(claims) + 1:03d}"
        claims.append(PresentationClaim(
            claim_id=claim_id, text=txt, start=start, end=end,
            claim_type=item.get("claim_type"), fact_status=item.get("fact_status"),
            source_refs=matched,
        ))
        for block in blocks:
            if block.start <= start and end <= block.end:
                block.claim_refs.append(claim_id)
                block.source_refs = list(dict.fromkeys(block.source_refs + matched))
                break

    lead_id = blocks[0].block_id if blocks and blocks[0].kind == "LEAD" else None
    return ConsultationPresentation(
        source_answer_sha256=digest,
        verification_binding=binding,
        direct_answer_block_id=lead_id,
        blocks=blocks, claims=claims, sources=refs,
    )
