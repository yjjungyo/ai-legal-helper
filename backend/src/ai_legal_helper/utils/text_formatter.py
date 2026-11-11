# -*- coding: utf-8 -*-
"""
모듈명: text_formatter.py

[모듈 개요]
법률 상담 답변 및 검증 결과 텍스트에서 불필요한 원시 마크다운(Raw Markdown) 기호를 정제하고,
증거 인용 표기의 가독성을 높이며, 정형화된 공문서 및 법률의견서 표준 서식으로 변환하는 서식 정제 유틸리티 모듈이다.

[주요 기능]
1. `clean_markdown_formatting`:
   - `#`, `##`, `###` 마크다운 헤더를 대괄호 섹션 헤더(`[제목]`)로 안전하게 변환
   - `**볼드**`, `*이탤릭*` 기호를 일반 텍스트로 복원
   - `---` 수평선 및 `>` 인용 블록 기호 제거
   - 과도한 연속 빈 줄 축소
2. `expand_evidence_citations`:
   - 답변 본문 내 `[01]`, `[03]`, `[E01]`, `[01, 03]` 등 번호만 축약된 증거 표기를
     사건에 등록된 실제 전체 파일명(예: `[01_임대차_주요내용.txt]`, `[E01_주택임대차계약서.txt]`)으로 안전하게 자동 확장/복원
   - 의뢰인이 인용 증거의 실체를 명확히 인지할 수 있도록 가독성과 투명성 제고 (옵션 B 표준)
"""
import os
import re
from typing import Any, Dict, List, Union


def _extract_evidence_filename(item: Any) -> str:
    """등록 출처 항목(문자열 경로 또는 딕셔너리)에서 유효한 증거 파일명을 추출한다.

    Args:
        item (Any): 문자열 파일 경로 또는 출처 정보 딕셔너리.

    Returns:
        str: 추출된 증거 파일명 (예: '01_임대차_주요내용.txt'). 추출 실패 시 빈 문자열.
    """
    if isinstance(item, str):
        return os.path.basename(item.strip())
    if isinstance(item, dict):
        for k in ("document_name", "filename", "file_name", "file", "title", "source_id"):
            val = item.get(k)
            if val and isinstance(val, str):
                val_clean = val.strip()
                if any(ext in val_clean.lower() for ext in (".txt", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".hwp", ".hwpx")):
                    return os.path.basename(val_clean)
                if k in ("document_name", "filename", "file_name"):
                    return os.path.basename(val_clean)
        if item.get("source_type") == "CASE_EVIDENCE" and item.get("source_id"):
            return os.path.basename(str(item["source_id"]).strip())
    return ""


def extract_all_registered_evidence_sources(state: Any) -> List[Any]:
    """LangGraph State 또는 상담 컨텍스트에서 등록된 모든 사건 증거 파일 출처를 안전하게 수집한다.

    1. case_evidence_briefing (source_documents, evidence_files, source_registry)
    2. retrieved_sources
    3. DB EvidenceDocument (case_id 기준 - 인메모리 누락 시 안전한 Fallback)

    Args:
        state (Any): LangGraph 워크플로우 상태 객체(LegalState 또는 딕셔너리).

    Returns:
        List[Any]: 중복이 제거된 사건 증거 파일명 및 출처 객체 리스트.
    """
    sources: List[Any] = []
    seen_names = set()

    def _add(item: Any):
        if not item:
            return
        fn = _extract_evidence_filename(item)
        if fn and fn.lower() not in seen_names:
            seen_names.add(fn.lower())
            sources.append(item)

    if not isinstance(state, dict):
        if hasattr(state, "get"):
            pass
        else:
            return sources

    # 1. case_evidence_briefing
    briefing = state.get("case_evidence_briefing")
    briefing_dict = (
        briefing
        if isinstance(briefing, dict)
        else (briefing.model_dump() if hasattr(briefing, "model_dump") else {})
    ) if briefing else {}

    for doc in (briefing_dict.get("source_documents") or []):
        _add(doc)
    for doc in (briefing_dict.get("evidence_files") or []):
        _add(doc)

    s_reg = briefing_dict.get("source_registry") or {}
    if isinstance(s_reg, dict):
        for val in s_reg.values():
            _add(val)

    # 2. retrieved_sources
    for src in (state.get("retrieved_sources") or []):
        _add(src)

    # 3. DB EvidenceDocument Fallback
    case_id = (
        state.get("case_id")
        or briefing_dict.get("case_id")
        or (state.get("conversation_context") or {}).get("case_id")
        if isinstance(state.get("conversation_context"), dict)
        else getattr(state.get("conversation_context"), "case_id", None)
    )
    if case_id:
        try:
            from ai_legal_helper.database.session import SessionLocal
            from ai_legal_helper.database.models import EvidenceDocument
            with SessionLocal() as db:
                db_docs = db.query(EvidenceDocument).filter(EvidenceDocument.case_id == str(case_id)).all()
                for d in db_docs:
                    if d.original_filename:
                        _add(d.original_filename)
        except Exception:
            pass

    return sources


def expand_evidence_citations(
    text: str,
    registered_sources: List[Union[str, Dict[str, Any]]] | None = None,
) -> str:
    """답변 본문 내 축약된 증거 인용 표기([01], [03], [E01], [01, 03] 등)를 등록된 실제 전체 파일명으로 자동 확장 복원한다.

    의뢰인 및 법률 전문가가 답변을 읽을 때 단순 일련번호나 축약 부호만으로는 어떤 증거를 가리키는지
    인지하기 어려우므로, 사건에 등록된 실제 증거 파일명(예: `[01_임대차_주요내용.txt]`, `[E01_주택임대차계약서.txt]`)을
    온전히 복원하여 가독성과 출처 신뢰성을 극대화한다 (Option B: 전체 파일명 보존 표준).

    Args:
        text (str): 축약 인용 표기가 포함될 수 있는 답변 초안 또는 최종 텍스트.
        registered_sources (Optional[List[Union[str, Dict[str, Any]]]]):
            사건에 등록된 실제 증거 파일명 목록 또는 출처 딕셔너리 리스트.

    Returns:
        str: 축약 인용 부호가 실제 전체 파일명으로 복원된 텍스트.
    """
    if not text or not registered_sources:
        return text

    # 등록된 파일명 기반의 별칭-파일명 매핑 테이블 구성
    key_map: Dict[str, str] = {}
    for s in registered_sources:
        fn = _extract_evidence_filename(s)
        if not fn:
            continue
        # 1. 전체 파일명 자체 매핑
        key_map[fn.lower()] = fn
        # 2. 확장자 제거 파일명 매핑
        base = re.sub(r"\.[a-zA-Z0-9]+$", "", fn)
        key_map[base.lower()] = fn

        # 3. 파일명 시작 패턴에 따른 번호/별칭 매핑 (우선순위 고려)
        # 패턴 A: E01_... 또는 e01_...
        m_e = re.match(r"^[Ee]0*([1-9]\d*)", fn)
        if m_e:
            num = m_e.group(1)
            padded = f"{int(num):02d}"
            key_map[f"e{num}"] = fn
            key_map[f"e{padded}"] = fn
            key_map.setdefault(num, fn)
            key_map.setdefault(padded, fn)
            key_map.setdefault(f"증거{num}", fn)
            key_map.setdefault(f"증거{padded}", fn)
            key_map.setdefault(f"증거{num}호", fn)
            key_map.setdefault(f"증거{padded}호", fn)
            continue

        # 패턴 B: 01_... 또는 1_...
        m_num = re.match(r"^0*([1-9]\d*)", fn)
        if m_num:
            num = m_num.group(1)
            padded = f"{int(num):02d}"
            key_map[num] = fn
            key_map[padded] = fn
            key_map.setdefault(f"증거{num}", fn)
            key_map.setdefault(f"증거{padded}", fn)
            key_map.setdefault(f"증거{num}호", fn)
            key_map.setdefault(f"증거{padded}호", fn)
            key_map.setdefault(f"e{num}", fn)
            key_map.setdefault(f"e{padded}", fn)

    def _replace_match(match: re.Match) -> str:
        raw = match.group(1).strip()
        # 이미 유효한 확장자가 붙은 전체 파일명인 경우 보존
        if re.search(r"\.(txt|pdf|docx|png|jpe?g|hwp|hwpx)$", raw, re.IGNORECASE):
            return match.group(0)

        # 쉼표(,)로 구분된 다중 인용([01, 03]) 또는 단일 인용([01]) 분할 검사
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts:
            return match.group(0)

        expanded_parts = []
        all_matched = True
        for p in parts:
            p_clean = re.sub(r"\s+", "", p).lower()
            if p_clean in key_map:
                expanded_parts.append(f"[{key_map[p_clean]}]")
            else:
                all_matched = False
                break

        if all_matched and expanded_parts:
            return ", ".join(expanded_parts)

        return match.group(0)

    # 대괄호 패턴 검색 및 자동 확장 치환
    return re.sub(r"\[([^\]\n]+)\]", _replace_match, text)


def clean_markdown_formatting(text: str) -> str:
    """마크다운 원시 기호(헤더, 볼드, 이탤릭, 수평선, 인용구)를 정제하여 정형화된 플레인 텍스트로 변환한다.

    프론트엔드에 마크다운 렌더러가 부재하거나 화면에 #, ** 등의 기호가 원시 텍스트로
    그대로 노출되는 문제를 방지하고, 법률의견서에 걸맞은 깔끔한 서식을 보장한다.

    Args:
        text (str): 마크다운 기호가 포함된 원시 텍스트.

    Returns:
        str: 마크다운 기호가 제거되고 정돈된 플레인 텍스트.
    """
    if not text:
        return ""

    # 1. 수평선 (---, ***, ___ 등) 제거
    cleaned = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # 2. 마크다운 헤더 (#, ##, ### 등) -> [헤더명] 대괄호 제목으로 변환
    def _header_replacer(match: re.Match) -> str:
        title = match.group(1).strip()
        # 이미 대괄호로 감싸져 있는 경우 중복 대괄호 방지
        if title.startswith('[') and title.endswith(']'):
            return f"\n{title}\n"
        return f"\n[{title}]\n"

    cleaned = re.sub(r'^#{1,6}\s*(.+)$', _header_replacer, cleaned, flags=re.MULTILINE)

    # 3. 볼드 (**text**, __text__) -> text
    cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'__(.+?)__', r'\1', cleaned)

    # 4. 이탤릭 (*text*, _text_) -> text (인용구 괄호나 다른 표기에 지장 없도록 처리)
    cleaned = re.sub(r'(?<!\*)\*([^\*\n]+)\*(?!\*)', r'\1', cleaned)

    # 5. 인용 블록 (> text) 기호 제거
    cleaned = re.sub(r'^>\s*', '', cleaned, flags=re.MULTILINE)

    # 6. 인라인 백틱 (`code`) 제거
    cleaned = re.sub(r'`([^`\n]+)`', r'\1', cleaned)

    # 7. 연속 3개 이상의 개행을 2개로 압축 및 앞뒤 공백 제거
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

