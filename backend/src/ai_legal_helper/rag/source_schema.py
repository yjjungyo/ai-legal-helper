# -*- coding: utf-8 -*-
"""
모듈명: source_schema.py

[모듈 개요]
법률 RAG 및 사건 증거 RAG에서 조회된 모든 근거 문서를 단일 표준 스키마(StandardSource)로
정규화하고 변환하는 모듈이다.

[주요 기능]
1. 공통 필드(source_id, source_type, document_id, title, content, retrieval_method, chunk_id,
   source_url, version_date, retrieved_at) 및 유형별 필드(법령, 판례, 사건 증거, 일반 문서) 정의
2. ChromaDB 법령 문서, Neo4j GraphRAG 경로, PostgreSQL 구조화 증거 검색 결과를 표준 Source 스키마로 변환
3. 실제 메타데이터·본문에서 확인된 값만 기록하고 확인되지 않은 필드는 모두 None(null)으로 처리
"""
from datetime import datetime, timezone
import os
import re
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict


# 법령 파일명 패턴: 예) 민법(법률)(제20432호)(20250131).pdf
_STATUTE_FILENAME_RE = re.compile(
    r"^([가-힣A-Za-z0-9·\s]+?)\((?:법률|대통령령|총리령|부령|대법원규칙|헌법재판소규칙)[^)]*\)"
    r"(?:\(제?\d+호\))?(?:\((\d{8})\))?\.pdf$",
    re.IGNORECASE,
)
# 본문 내 조문 번호 패턴: 예) 제3조, 제621조의2
_ARTICLE_RE = re.compile(r"(제\s*\d+\s*조(?:\s*의\s*\d+)?)")
# 판례 사건번호 패턴: 예) 2022다21580, 2020도12345
_CASE_NUMBER_RE = re.compile(r"((?:19|20)\d{2}\s*[가-힣]{1,3}\s*\d{2,7})")
# 법원명 패턴: 예) 대법원, 헌법재판소, 서울고등법원, 서울중앙지방법원
_COURT_RE = re.compile(r"(대법원|헌법재판소|[가-힣]{2,6}(?:고등|지방|가정|행정|특허|회생)법원)")
# 판례 선고일 패턴: 예) 2023. 5. 11. 선고 또는 2023-05-11
_DECISION_DATE_RE = re.compile(r"((?:19|20)\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.)\s*선고")


class StandardSource(BaseModel):
    """법률 RAG 및 사건 증거 RAG 통합 표준 출처 스키마.

    실제 검색 결과에서 확인된 메타데이터만 기록하며, 확인되지 않은 값은 모두 None(JSON null)으로 유지한다.
    기존 프런트엔드/백엔드 하위 호환을 위해 `file` 및 `file_name` 필드를 함께 제공한다.
    """
    model_config = ConfigDict(from_attributes=True)

    # 1. 공통 필수·표준 필드
    source_id: str
    source_type: str  # "STATUTE" | "PRECEDENT" | "CASE_EVIDENCE" | "DOCUMENT"
    document_id: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    retrieval_method: Optional[str] = None
    chunk_id: Optional[str] = None
    source_url: Optional[str] = None
    version_date: Optional[str] = None
    retrieved_at: Optional[str] = None

    # 2. 법령(STATUTE) 전용 필드 (P1-02)
    law_id: Optional[str] = None
    statute_name: Optional[str] = None
    article: Optional[str] = None
    promulgation_date: Optional[str] = None
    promulgation_number: Optional[str] = None
    effective_date: Optional[str] = None
    version_id: Optional[str] = None

    # 3. 판례(PRECEDENT) 전용 필드
    court: Optional[str] = None
    case_number: Optional[str] = None
    decision_date: Optional[str] = None

    # 4. 사건 증거(CASE_EVIDENCE) 및 일반 문서(DOCUMENT) 전용 필드
    evidence_id: Optional[str] = None
    evidence_label: Optional[str] = None
    label: Optional[str] = None
    span_id: Optional[str] = None
    claim_id: Optional[str] = None
    paragraph_index: Optional[int] = None
    filename: Optional[str] = None
    page: Optional[str] = None
    text_excerpt: Optional[str] = None

    # 5. 기존 API/UI 하위 호환용 필드
    file: str = "?"
    file_name: Optional[str] = None
    category: Optional[str] = None


def _utc_now_iso() -> str:
    """현재 UTC 시각을 ISO-8601 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _format_yyyymmdd(raw: Optional[str]) -> Optional[str]:
    """8자리 날짜 문자열(YYYYMMDD)을 YYYY-MM-DD 형식으로 변환한다."""
    if not raw:
        return None
    s = str(raw).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def build_source_from_chroma_doc(
    doc: Any,
    category: Optional[str] = None,
    retrieval_method: str = "CHROMA_VECTOR",
) -> Dict[str, Any]:
    """ChromaDB에서 검색된 LangChain Document 객체를 표준 Source 딕셔너리로 변환한다.

    Args:
        doc: 검색된 LangChain Document 또는 유사 객체 (page_content, metadata 보유).
        category: 검색된 법률 도메인 카테고리.
        retrieval_method: 검색 방식 식별자 (기본값: "CHROMA_VECTOR").

    Returns:
        Dict[str, Any]: StandardSource 스키마를 준수하는 딕셔너리.
    """
    meta: Dict[str, Any] = getattr(doc, "metadata", None) or {}
    content: str = (getattr(doc, "page_content", None) or "").strip()

    raw_fn = meta.get("file_name") or meta.get("filename") or meta.get("source") or meta.get("file_path")
    filename = os.path.basename(str(raw_fn)).strip() if raw_fn and str(raw_fn).strip() != "?" else None

    p1 = meta.get("page")
    p2 = meta.get("page_end", p1)
    if p1 is not None and str(p1).strip() not in ("", "?"):
        page_disp = str(p1) if p1 == p2 or p2 in (None, "?", "") else f"{p1}-{p2}"
    else:
        page_disp = None

    chunk_id = (
        str(meta.get("chunk_id") or meta.get("id") or getattr(doc, "id", "")).strip() or None
    )
    document_id = str(meta.get("document_id") or meta.get("doc_id") or "").strip() or filename
    source_url = str(meta.get("source_url") or meta.get("url") or "").strip() or None
    version_date = _format_yyyymmdd(meta.get("version_date"))

    # 유형(source_type) 및 법령/판례 메타데이터 추출 (실제 확인된 값만 기록)
    explicit_type = str(meta.get("source_type") or meta.get("doc_type") or "").strip().upper()
    statute_name = meta.get("statute_name") or meta.get("law_name")
    article = meta.get("article") or meta.get("article_number")
    effective_date = _format_yyyymmdd(meta.get("effective_date"))

    court = meta.get("court")
    case_number = meta.get("case_number")
    decision_date = meta.get("decision_date")

    # 파일명에서 표준 법령명 및 시행일 추출 (예: 민법(법률)(제20432호)(20250131).pdf)
    if filename:
        m_stat = _STATUTE_FILENAME_RE.match(filename)
        if m_stat:
            if not statute_name:
                statute_name = m_stat.group(1).strip()
            if m_stat.group(2):
                parsed_date = _format_yyyymmdd(m_stat.group(2))
                if not version_date:
                    version_date = parsed_date
                if not effective_date:
                    effective_date = parsed_date

    # 본문에서 확인되는 조문 또는 판례 번호 추출 (임의 추론 금지, 정규식 완전 매칭만 허용)
    if not article and content:
        m_art = _ARTICLE_RE.search(content)
        if m_art:
            article = re.sub(r"\s+", "", m_art.group(1))

    if not case_number and content:
        m_cn = _CASE_NUMBER_RE.search(content)
        if m_cn:
            case_number = re.sub(r"\s+", "", m_cn.group(1))

    if not court and content and case_number:
        m_ct = _COURT_RE.search(content)
        if m_ct:
            court = m_ct.group(1)

    if not decision_date and content and case_number:
        m_dd = _DECISION_DATE_RE.search(content)
        if m_dd:
            decision_date = re.sub(r"\s+", " ", m_dd.group(1)).strip()

    # source_type 결정
    if explicit_type in ("STATUTE", "PRECEDENT", "CASE_EVIDENCE", "DOCUMENT"):
        source_type = explicit_type
    elif case_number or court or (filename and ("판례" in filename or "판결" in filename)):
        source_type = "PRECEDENT"
    elif statute_name or (filename and any(k in filename for k in ("법률", "시행령", "시행규칙", "보호법", "민법", "형법", "상법", "근로기준법"))):
        source_type = "STATUTE"
    elif meta.get("evidence_id") or category in ("EVIDENCE_POSTGRES", "EVIDENCE_GRAPH", "EVIDENCE_VECTOR"):
        source_type = "CASE_EVIDENCE"
    else:
        source_type = "DOCUMENT"

    # source_type에 맞지 않는 타 유형 필드는 None으로 초기화
    if source_type != "STATUTE":
        statute_name = None
        article = article if source_type == "DOCUMENT" else None
        effective_date = None
    if source_type != "PRECEDENT":
        court = None
        case_number = None
        decision_date = None

    title = (
        meta.get("title")
        or statute_name
        or (f"{court or ''} {case_number}".strip() if case_number else None)
        or filename
    )

    fn_Part = filename or document_id or "unknown_doc"
    pg_Part = page_disp or "1"
    source_id = str(meta.get("source_id") or f"{fn_Part}_{pg_Part}")
    if not chunk_id:
        chunk_id = f"{source_id}#chunk"

    std = StandardSource(
        source_id=source_id,
        source_type=source_type,
        document_id=document_id,
        title=title,
        content=content or None,
        retrieval_method=retrieval_method,
        chunk_id=chunk_id,
        source_url=source_url,
        version_date=version_date,
        retrieved_at=_utc_now_iso(),
        statute_name=statute_name,
        article=article,
        effective_date=effective_date,
        court=court,
        case_number=case_number,
        decision_date=decision_date,
        evidence_id=str(meta.get("evidence_id")).strip() if meta.get("evidence_id") else None,
        filename=filename,
        page=page_disp,
        file=filename or source_id,
        file_name=filename,
        category=category,
    )
    return std.model_dump()


def build_source_from_graph_path(path: Dict[str, Any]) -> Dict[str, Any]:
    """Neo4j GraphRAG 검증 경로(valid_path)를 표준 CASE_EVIDENCE Source 딕셔너리로 변환한다."""
    span_or_claim_id = path.get("span_id") or path.get("claim_id") or "unknown"
    evidence_id = path.get("evidence_id")
    raw_fn = path.get("filename")
    filename = os.path.basename(str(raw_fn)).strip() if raw_fn else None
    raw_page = path.get("page_or_section") if path.get("page_or_section") is not None else path.get("page_number")
    page = str(raw_page).strip() if raw_page is not None and str(raw_page).strip() != "" else None
    source_id = f"GRAPH:{span_or_claim_id}"
    content = (
        f"{path.get('claim_statement') or path.get('evidence_text') or ''} "
        f"-{path.get('relation') or 'SUPPORTS'}-> {path.get('target_content') or ''}"
    ).strip()

    std = StandardSource(
        source_id=source_id,
        source_type="CASE_EVIDENCE",
        document_id=str(evidence_id) if evidence_id else None,
        title=filename or (f"사건 증거 ({evidence_id})" if evidence_id else "사건 증거 그래프"),
        content=content or None,
        retrieval_method="NEO4J_GRAPH",
        chunk_id=str(span_or_claim_id),
        source_url=None,
        version_date=None,
        retrieved_at=_utc_now_iso(),
        evidence_id=str(evidence_id) if evidence_id else None,
        span_id=str(path.get("span_id")).strip() if path.get("span_id") else None,
        claim_id=str(path.get("claim_id")).strip() if path.get("claim_id") else None,
        paragraph_index=int(path["paragraph_index"]) if path.get("paragraph_index") is not None else None,
        filename=filename,
        page=page,
        file=filename or source_id,
        file_name=filename,
        category="EVIDENCE_GRAPH",
    )
    return std.model_dump()


def build_source_from_evidence_search_result(hit: Any) -> Dict[str, Any]:
    """PostgreSQL Evidence Search 결과(EvidenceSearchHit 또는 dict)를 표준 CASE_EVIDENCE Source로 변환한다.

    출처 식별자(source_id)는 실제 Evidence ID와 Span/Claim ID를 기반으로 생성하여
    법령 Source ID와 혼동되지 않도록 보장한다.
    """
    d: Dict[str, Any] = hit.model_dump() if hasattr(hit, "model_dump") else dict(hit or {})
    evidence_id = str(d.get("evidence_id") or d.get("document_id") or "").strip() or None
    span_id = str(d.get("span_id") or "").strip() or None
    claim_id = str(d.get("claim_id") or "").strip() or None
    fact_id = str(d.get("fact_id") or "").strip() or None
    node_id = span_id or claim_id or fact_id or str(d.get("node_id") or "unknown").strip()

    if evidence_id and span_id:
        source_id = f"EVIDENCE:{evidence_id}:SPAN:{span_id}"
    elif evidence_id and claim_id:
        source_id = f"EVIDENCE:{evidence_id}:CLAIM:{claim_id}"
    elif span_id:
        source_id = f"EVIDENCE:SPAN:{span_id}"
    elif claim_id:
        source_id = f"EVIDENCE:CLAIM:{claim_id}"
    else:
        source_id = f"EVIDENCE:{node_id}"

    raw_fn = d.get("document_name") or d.get("filename") or d.get("file_name")
    filename = os.path.basename(str(raw_fn)).strip() if raw_fn else None
    raw_page = d.get("page_number") if d.get("page_number") is not None else d.get("page")
    page = str(raw_page).strip() if raw_page is not None and str(raw_page).strip() != "" else None

    stmt = (d.get("claim_statement") or d.get("statement") or "").strip()
    excerpt = (d.get("source_excerpt") or d.get("content") or "").strip()
    if stmt and excerpt and stmt != excerpt:
        content = f"{stmt} [원문 발췌: {excerpt}]"
    else:
        content = stmt or excerpt or None

    std = StandardSource(
        source_id=source_id,
        source_type="CASE_EVIDENCE",
        document_id=evidence_id or node_id,
        title=filename or (f"사건 증거 ({evidence_id})" if evidence_id else "사건 증거 (PostgreSQL)"),
        content=content,
        retrieval_method="POSTGRES_EVIDENCE_SEARCH",
        chunk_id=span_id or claim_id or node_id,
        source_url=None,
        version_date=None,
        retrieved_at=_utc_now_iso(),
        evidence_id=evidence_id,
        span_id=span_id,
        claim_id=claim_id,
        paragraph_index=int(d["paragraph_index"]) if d.get("paragraph_index") is not None else None,
        filename=filename,
        page=page,
        file=filename or source_id,
        file_name=filename,
        category="EVIDENCE_POSTGRES",
    )
    return std.model_dump()


def build_source_from_vector_match(v: Dict[str, Any]) -> Dict[str, Any]:
    """[Deprecated] 기존 벡터 매치 하위 호환용 변환 함수.

    운영 경로에서는 build_source_from_evidence_search_result()를 사용한다.
    """
    node_id = str(v.get("node_id") or "unknown")
    node_type = str(v.get("node_type") or "Evidence")
    raw_fn = v.get("filename") or v.get("file_name") or v.get("document_name")
    filename = os.path.basename(str(raw_fn)).strip() if raw_fn else None
    evidence_id = str(v.get("evidence_id")).strip() if v.get("evidence_id") else None
    page = str(v.get("page") or v.get("page_number") or "").strip() or None
    source_id = f"VECTOR:{node_id}"
    content = f"{node_type}: {v.get('content') or v.get('statement') or ''}".strip()

    std = StandardSource(
        source_id=source_id,
        source_type="CASE_EVIDENCE",
        document_id=evidence_id or node_id,
        title=filename or f"사건 증거 ({node_type})",
        content=content or None,
        retrieval_method="HYBRID_VECTOR_FALLBACK",
        chunk_id=node_id,
        source_url=None,
        version_date=None,
        retrieved_at=_utc_now_iso(),
        evidence_id=evidence_id,
        filename=filename,
        page=page,
        file=filename or source_id,
        file_name=filename,
        category="EVIDENCE_VECTOR",
    )
    return std.model_dump()


def normalize_source_dict(raw: Any) -> Dict[str, Any]:
    """임의의 출처 딕셔너리(레거시 `{file, page}` 또는 표준 딕셔너리)를 StandardSource 딕셔너리로 정규화한다."""
    if isinstance(raw, StandardSource):
        return raw.model_dump()
    if not isinstance(raw, dict):
        fn = os.path.basename(str(raw))
        return StandardSource(
            source_id=fn,
            source_type="DOCUMENT",
            document_id=fn,
            title=fn,
            filename=fn,
            file=fn,
            file_name=fn,
        ).model_dump()

    raw_fn = raw.get("filename") or raw.get("file_name") or raw.get("file") or raw.get("document_name")
    filename = os.path.basename(str(raw_fn)).strip() if raw_fn and str(raw_fn).strip() not in ("", "?") else None
    raw_page = raw.get("page") if raw.get("page") is not None else raw.get("page_number")
    page = str(raw_page).strip() if raw_page not in (None, "", "?") else None
    source_id = str(raw.get("source_id") or (f"{filename}_{page}" if filename and page else (filename or "UNKNOWN")))

    # 이미 source_type과 retrieval_method가 있으면 그대로 보존하되 누락 필드를 StandardSource로 보완
    source_type = raw.get("source_type")
    if not source_type:
        cat = str(raw.get("category") or "")
        if (
            cat in ("EVIDENCE_GRAPH", "EVIDENCE_POSTGRES", "EVIDENCE_VECTOR")
            or raw.get("evidence_id")
            or source_id.startswith(("GRAPH:", "EVIDENCE:", "VECTOR:"))
        ):
            source_type = "CASE_EVIDENCE"
        elif raw.get("case_number") or raw.get("court") or (filename and ("판례" in filename or "판결" in filename)):
            source_type = "PRECEDENT"
        elif raw.get("statute_name") or (filename and any(k in filename for k in ("법률", "시행령", "시행규칙", "보호법", "민법", "형법", "상법", "근로기준법"))):
            source_type = "STATUTE"
        else:
            source_type = "DOCUMENT"

    statute_name = raw.get("statute_name")
    version_date = _format_yyyymmdd(raw.get("version_date"))
    effective_date = _format_yyyymmdd(raw.get("effective_date"))
    if filename and source_type == "STATUTE":
        m_stat = _STATUTE_FILENAME_RE.match(filename)
        if m_stat:
            statute_name = statute_name or m_stat.group(1).strip()
            if m_stat.group(2):
                parsed_dt = _format_yyyymmdd(m_stat.group(2))
                version_date = version_date or parsed_dt
                effective_date = effective_date or parsed_dt

    content = raw.get("content")
    article = raw.get("article")
    if not article and content and source_type == "STATUTE":
        m_art = _ARTICLE_RE.search(str(content))
        if m_art:
            article = re.sub(r"\s+", "", m_art.group(1))

    std = StandardSource(
        source_id=source_id,
        source_type=source_type,
        document_id=raw.get("document_id") or raw.get("evidence_id") or filename,
        title=raw.get("title") or statute_name or filename or source_id,
        content=content,
        retrieval_method=raw.get("retrieval_method") or (
            "NEO4J_GRAPH" if source_id.startswith("GRAPH:")
            else "POSTGRES_EVIDENCE_SEARCH" if source_id.startswith("EVIDENCE:")
            else "HYBRID_VECTOR_FALLBACK" if source_id.startswith("VECTOR:")
            else "CHROMA_VECTOR"
        ),
        chunk_id=raw.get("chunk_id") or (f"{source_id}#chunk" if source_id != "UNKNOWN" else None),
        source_url=raw.get("source_url"),
        version_date=version_date,
        retrieved_at=raw.get("retrieved_at") or _utc_now_iso(),
        law_id=str(raw.get("law_id")).strip() if raw.get("law_id") else None,
        statute_name=statute_name if source_type == "STATUTE" else None,
        article=article if source_type in ("STATUTE", "DOCUMENT") else None,
        promulgation_date=_format_yyyymmdd(raw.get("promulgation_date")) if source_type == "STATUTE" else None,
        promulgation_number=str(raw.get("promulgation_number")).strip() if raw.get("promulgation_number") else None,
        effective_date=effective_date if source_type == "STATUTE" else None,
        version_id=str(raw.get("version_id")).strip() if raw.get("version_id") else None,
        court=raw.get("court") if source_type == "PRECEDENT" else None,
        case_number=raw.get("case_number") if source_type == "PRECEDENT" else None,
        decision_date=raw.get("decision_date") if source_type == "PRECEDENT" else None,
        evidence_id=raw.get("evidence_id"),
        evidence_label=raw.get("evidence_label") or raw.get("label"),
        label=raw.get("label") or raw.get("evidence_label"),
        span_id=raw.get("span_id"),
        claim_id=raw.get("claim_id"),
        text_excerpt=raw.get("text_excerpt"),
        filename=filename,
        page=page,
        file=filename or raw.get("file") or source_id,
        file_name=filename,
        category=raw.get("category"),
    )
    return std.model_dump()


def is_statute_applicable_to_date(source_dict: Dict[str, Any], target_date_str: str) -> bool:
    """주어진 법령 출처가 사건 발생일(또는 계약/해지 기준일)에 시행 중이었는지 검증한다.

    Args:
        source_dict: 법령 출처 정보 딕셔너리 (effective_date, promulgation_date, version_date 등 포함).
        target_date_str: 사건 발생일 또는 계약/해지 기준일자 (예: '2026-10-17' 또는 '20261017').

    Returns:
        bool: 사건 발생일 기준 시행 중인 법령이면 True, 미시행 법령이면 False.
              날짜 정보가 없거나 파싱 불가능한 경우 안전하게 True를 반환한다.
    """
    if not source_dict or not target_date_str:
        return True

    def _parse_clean_date(d: Any) -> Optional[datetime]:
        if not d:
            return None
        s = str(d).strip().replace(".", "-").replace("/", "-")
        if len(s) == 8 and s.isdigit():
            s = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except Exception:
            return None

    target_dt = _parse_clean_date(target_date_str)
    if not target_dt:
        return True

    eff_str = source_dict.get("effective_date") or source_dict.get("version_date")
    eff_dt = _parse_clean_date(eff_str)
    if eff_dt:
        return target_dt >= eff_dt

    prom_str = source_dict.get("promulgation_date")
    prom_dt = _parse_clean_date(prom_str)
    if prom_dt:
        return target_dt >= prom_dt

    return True
