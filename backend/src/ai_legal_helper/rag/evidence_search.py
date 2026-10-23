# -*- coding: utf-8 -*-
"""
모듈명: evidence_search.py

[모듈 개요]
사건 증거에 대한 ChromaDB Embedding/Vector 검색 의존성을 대체하는
PostgreSQL 기반 구조화·전문 증거 검색 엔진(Structured & Full-Text Evidence Search) 모듈이다.

[주요 기능]
1. 자연어 질문 조건 분석 (날짜·기간, 금액, 당사자, 법률행위, 문서명, Claim 유형, 핵심 키워드 추출)
2. 사건 ID(case_id) 및 사용자 권한 기반 엄격한 데이터 격리
3. SQLAlchemy 매개변수 바인딩 기반 구조화 조건 검색 (E2 전략)
4. PostgreSQL ILIKE 및 pg_trgm(유사 문자열) 기반 한국어 텍스트 검색 (E1 전략)
5. 구조화 검색 + 텍스트 검색 통합 하이브리드 검색 및 Span-Claim-Fact 원문 위치 역추적
6. 승인 상태(APPROVED/EDITED vs PENDING vs REJECTED) 필터링 및 상충(CONTRADICTS)/공백(Gaps) 조회

[설계 의도]
- LLM이 임의의 SQL을 직접 생성·실행하지 않도록 Pydantic 기반 검색 조건 모델(EvidenceSearchQueryPlan)을
  먼저 구성하고, 검증된 매개변수 바인딩 쿼리만 실행한다.
- 한국어 조사/어미 분리 및 금액(아라비아 숫자 ↔ 한글 수사)·날짜(YYYY-MM-DD ↔ YYYY년 M월 D일) 정규화를 통해
  Embedding 없이도 계약서·통지서 원문 Span과 Claim, Fact를 정밀하게 매칭한다.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from ai_legal_helper.database.models import (
    Case,
    Party,
    Fact,
    Event,
    LegalIssue,
    EvidenceDocument,
    EvidenceSpan,
    EvidenceClaim,
    EvidenceLink,
    EvidenceSpanClaimLink,
)
from ai_legal_helper.observability.decorators import trace

logger = logging.getLogger(__name__)

# 확정 사실 근거로 사용할 수 있는 승인 상태
APPROVED_REVIEW_STATUSES: Tuple[str, ...] = ("APPROVED", "EDITED")

# 한국어 불용어 및 조사 정규식
_STOPWORDS: Set[str] = {
    "그리고", "그런데", "하지만", "어떻게", "무엇", "있나요", "있습니까", "합니까", "해야",
    "하나요", "인가요", "되나요", "경우", "관련", "대해", "대한", "제가", "저는", "우리",
    "이번", "지금", "혹시", "정말", "가능", "방법", "문제", "사건", "질문", "누구", "언제",
    "얼마", "어디", "무슨", "어떤", "있을까요", "알려주세요", "궁금합니다",
}
_JOSA_RE = re.compile(
    r"(으로부터|에서부터|에게서|으로서|으로써|이라도|이라고|이라며|이라서|"
    r"으로|에서|에게|까지|부터|이나|이랑|하고|보다|처럼|만큼|조차|마저|"
    r"은|는|이|가|을|를|에|의|도|만|로|와|과|야|여)$"
)

# 당사자 역할 사전
_PARTY_ROLE_KEYWORDS: Set[str] = {
    "임대인", "임차인", "집주인", "세입자", "원고", "피고", "채권자", "채무자",
    "근로자", "사용자", "고용주", "매도인", "매수인", "양도인", "양수인",
    "보증인", "연대보증인", "대리인", "중개인", "공인중개사", "도급인", "수급인",
    "피해자", "가해자", "피의자", "고소인", "피고소인", "신청인", "피신청인",
}

# 주요 법률행위 키워드 사전
_ACTION_KEYWORDS: Set[str] = {
    "지급", "미지급", "반환", "미반환", "체결", "해지", "해제", "갱신", "거절",
    "통지", "내용증명", "인도", "명도", "퇴거", "수리", "보수", "이체", "송금",
    "입금", "출금", "차압", "가압류", "가처분", "경매", "등기", "전입신고",
    "확정일자", "해고", "권고사직", " 징계", "체불", "손해배상", "위약금", "특약",
}

# 문서 종류/명칭 키워드 사전
_DOCUMENT_KEYWORDS: Set[str] = {
    "계약서", "임대차계약서", "근로계약서", "매매계약서", "차용증", "영수증",
    "이체내역", "송금확인증", "통장", "내용증명", "통지서", "최고장", "녹취",
    "녹취록", "문자", "카톡", "카카오톡", "이메일", "메시지", "등기부등본",
    "등기사항전부증명서", "건축물대장", "진단서", "견적서", "세금계산서", "취업규칙",
}

# 질문 키워드 → 표준 Claim Type 매핑
_KEYWORD_TO_CLAIM_TYPES: Dict[str, List[str]] = {
    "언제": ["DATE"],
    "날짜": ["DATE"],
    "기한": ["DATE"],
    "만료": ["DATE"],
    "만기": ["DATE"],
    "계약일": ["DATE"],
    "지급일": ["DATE"],
    "얼마": ["AMOUNT"],
    "금액": ["AMOUNT"],
    "보증금": ["AMOUNT", "RIGHT_DUTY"],
    "전세금": ["AMOUNT", "RIGHT_DUTY"],
    "월세": ["AMOUNT"],
    "차임": ["AMOUNT"],
    "임금": ["AMOUNT", "RIGHT_DUTY"],
    "퇴직금": ["AMOUNT", "RIGHT_DUTY"],
    "대금": ["AMOUNT"],
    "위약금": ["AMOUNT", "CONDITION"],
    "손해배상": ["AMOUNT", "RIGHT_DUTY"],
    "비용": ["AMOUNT"],
    "누구": ["PARTY_INFO"],
    "당사자": ["PARTY_INFO"],
    "임대인": ["PARTY_INFO", "RIGHT_DUTY"],
    "임차인": ["PARTY_INFO", "RIGHT_DUTY"],
    "특약": ["CONDITION"],
    "조건": ["CONDITION"],
    "해지": ["ACTION", "CONDITION"],
    "해제": ["ACTION", "CONDITION"],
    "통지": ["ACTION"],
    "내용증명": ["ACTION", "DOC_INFO"],
    "지급": ["ACTION", "AMOUNT"],
    "반환": ["ACTION", "RIGHT_DUTY", "AMOUNT"],
    "수리": ["ACTION", "RIGHT_DUTY"],
    "목적물": ["PROPERTY"],
    "주소": ["PROPERTY"],
    "아파트": ["PROPERTY"],
    "건물": ["PROPERTY"],
    "주택": ["PROPERTY"],
    "계약서": ["DOC_INFO", "CONDITION"],
}

# 아라비아 금액 단위 ↔ 한글 금액 표현 변환 테이블
_KOR_NUM_MAP: Dict[int, str] = {
    1: "일", 2: "이", 3: "삼", 4: "사", 5: "오",
    6: "육", 7: "칠", 8: "팔", 9: "구",
}
_KOR_TO_DIGIT: Dict[str, int] = {v: k for k, v in _KOR_NUM_MAP.items()}


class EvidenceSearchQueryPlan(BaseModel):
    """질문에서 추출된 구조화 증거 검색 계획 모델.

    LLM이나 분석기가 생성한 검색 조건을 검증·정규화하여 보관하며,
    직접적인 SQL 문자열을 포함하지 않는다.
    """
    raw_query: str = Field(default="", description="원본 질문 문자열")
    keywords: List[str] = Field(default_factory=list, description="조사 제거 핵심 키워드 목록")
    date_terms: List[str] = Field(default_factory=list, description="추출 및 정규화된 날짜/연월 검색어")
    amount_terms: List[str] = Field(default_factory=list, description="추출 및 정규화된 금액 검색어")
    party_terms: List[str] = Field(default_factory=list, description="당사자 이름 또는 역할 검색어")
    action_terms: List[str] = Field(default_factory=list, description="법률행위 검색어")
    document_terms: List[str] = Field(default_factory=list, description="문서명 또는 문서 유형 검색어")
    claim_types: List[str] = Field(default_factory=list, description="추론된 표준 Claim 유형 코드 목록")
    include_pending: bool = Field(default=False, description="미승인(PENDING) Claim 포함 여부")
    only_contradictions: bool = Field(default=False, description="상충(CONTRADICTS) 관계 전용 검색 여부")

    @property
    def date_variants(self) -> List[str]:
        """date_terms의 호환 별칭 프로퍼티."""
        return self.date_terms

    @property
    def amount_variants(self) -> List[str]:
        """amount_terms의 호환 별칭 프로퍼티."""
        return self.amount_terms


class EvidenceSearchHit(BaseModel):
    """PostgreSQL 증거 검색 개별 결과 항목 모델 (지시서 제4절 표준 스키마).

    실제 DB 레코드에서 확인된 ID와 원문 발췌, 페이지 번호만 포함하며
    존재하지 않는 위치 정보를 임의 생성하지 않는다.
    """
    case_id: str
    evidence_id: Optional[str] = None
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    span_id: Optional[str] = None
    page_number: Optional[int] = None
    paragraph_index: Optional[int] = None
    claim_id: Optional[str] = None
    fact_id: Optional[str] = None
    statement: Optional[str] = None
    claim_statement: Optional[str] = None
    source_excerpt: Optional[str] = None
    review_status: Optional[str] = None
    assertion_status: Optional[str] = None
    verification_status: Optional[str] = None
    match_reason: str = ""
    score: float = 0.0
    node_type: str = "EvidenceClaim"
    node_id: Optional[str] = None


class EvidenceSearchResponse(BaseModel):
    """PostgreSQL 증거 검색 종합 응답 모델."""
    case_id: str
    strategy: str = "hybrid_pg"
    query_plan: EvidenceSearchQueryPlan
    hits: List[EvidenceSearchHit] = Field(default_factory=list)
    matched_claim_ids: List[str] = Field(default_factory=list)
    matched_fact_ids: List[str] = Field(default_factory=list)
    matched_span_ids: List[str] = Field(default_factory=list)
    matched_document_ids: List[str] = Field(default_factory=list)
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_gaps: List[Dict[str, Any]] = Field(default_factory=list)


def extract_search_keywords(query: str, max_keywords: int = 10) -> List[str]:
    """자연어 질문에서 한국어 조사와 불용어를 제거한 핵심 키워드 목록을 추출한다.

    Args:
        query: 사용자 질문 문자열.
        max_keywords: 반환할 최대 키워드 개수.

    Returns:
        List[str]: 정규화된 키워드 목록.
    """
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", query or "")
    out: List[str] = []
    for raw_t in tokens:
        t = _JOSA_RE.sub("", raw_t).strip()
        if len(t) < 2 or t in _STOPWORDS:
            continue
        t_low = t.lower()
        if t_low not in out:
            out.append(t_low)
        if len(out) >= max_keywords:
            break
    return out


def _expand_date_variants(query: str) -> List[str]:
    """질문 내 날짜 표현을 추출하고 다양한 표기 변형(YYYY-MM-DD, YYYY년 M월 D일, YYYY.M.D)으로 확장한다."""
    variants: List[str] = []

    def _add(v: str) -> None:
        if v and v not in variants:
            variants.append(v)

    # 1. YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD, YYYY년 M월 D일
    full_date_re = re.compile(
        r"((?:19|20)\d{2})\s*(?:[-./년]\s*)(\d{1,2})\s*(?:[-./월]\s*)(\d{1,2})\s*일?"
    )
    for m in full_date_re.finditer(query or ""):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        _add(f"{y:04d}-{mo:02d}-{d:02d}")
        _add(f"{y}년 {mo}월 {d}일")
        _add(f"{y}. {mo}. {d}.")
        _add(f"{y}.{mo:02d}.{d:02d}")

    # 2. YYYY년 M월 (일 없는 연월)
    ym_re = re.compile(r"((?:19|20)\d{2})\s*(?:[-./년]\s*)(\d{1,2})\s*월?")
    for m in ym_re.finditer(query or ""):
        y, mo = int(m.group(1)), int(m.group(2))
        _add(f"{y:04d}-{mo:02d}")
        _add(f"{y}년 {mo}월")

    # 3. M월 D일 (연도 생략)
    md_re = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")
    for m in md_re.finditer(query or ""):
        mo, d = int(m.group(1)), int(m.group(2))
        _add(f"{mo}월 {d}일")
        _add(f"-{mo:02d}-{d:02d}")

    return variants


def _expand_amount_variants(query: str) -> List[str]:
    """질문 내 금액 표현을 추출하고 아라비아 숫자(콤마 유무) 및 한글 금액 표기로 상호 확장한다.

    예: '5000만원' <-> '5,000만원' <-> '오천만원'
        '3억원' <-> '3억' <-> '삼억'
    """
    variants: List[str] = []

    def _add(v: str) -> None:
        if v and v not in variants:
            variants.append(v)

    # 1. 아라비아 숫자 금액: 예) 5000만원, 5,000만 원, 3억, 3000만
    num_amt_re = re.compile(r"(\d[\d,]*)\s*(억|천만|백만|십만|만)?\s*(원)?")
    for m in num_amt_re.finditer(query or ""):
        raw_num, unit, won = m.group(1), m.group(2) or "", m.group(3) or ""
        if not unit and not won:
            continue
        clean_num_str = raw_num.replace(",", "")
        if not clean_num_str.isdigit():
            continue
        num_val = int(clean_num_str)
        formatted_comma = f"{num_val:,}"

        _add(f"{clean_num_str}{unit}{won}")
        _add(f"{formatted_comma}{unit}{won}")
        if unit:
            _add(f"{clean_num_str}{unit}")
            _add(f"{formatted_comma}{unit}")

        # 만 단위에서 천만 단위 한글 변환 (예: 5000만 -> 오천만, 3000만 -> 삼천만)
        if unit == "만" and num_val in (1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000):
            k_digit = _KOR_NUM_MAP.get(num_val // 1000)
            if k_digit:
                _add(f"{k_digit}천만")
                _add(f"{k_digit}천만원")
        elif unit == "만" and num_val in (100, 200, 300, 400, 500, 600, 700, 800, 900):
            k_digit = _KOR_NUM_MAP.get(num_val // 100)
            if k_digit:
                _add(f"{k_digit}백만")
                _add(f"{k_digit}백만원")
        elif unit == "억" and 1 <= num_val <= 9:
            k_digit = _KOR_NUM_MAP.get(num_val)
            if k_digit:
                _add(f"{k_digit}억")
                _add(f"{k_digit}억원")

    # 2. 한글 숫자 금액: 예) 오천만원, 삼천만원, 삼억원
    kor_amt_re = re.compile(r"([일이삼사오육칠팔구])(천|백|십)?(억|만)\s*원?")
    for m in kor_amt_re.finditer(query or ""):
        d_kor, sub_unit, big_unit = m.group(1), m.group(2) or "", m.group(3)
        digit = _KOR_TO_DIGIT.get(d_kor, 0)
        if not digit:
            continue
        _add(f"{d_kor}{sub_unit}{big_unit}")
        _add(f"{d_kor}{sub_unit}{big_unit}원")
        mult = {"천": 1000, "백": 100, "십": 10, "": 1}.get(sub_unit, 1)
        numeric = digit * mult
        _add(f"{numeric}{big_unit}")
        _add(f"{numeric:,}{big_unit}")
        _add(f"{numeric}{big_unit}원")
        _add(f"{numeric:,}{big_unit}원")

    return variants


def analyze_evidence_query(
    query: str,
    known_party_names: Optional[List[str]] = None,
    include_pending: bool = False,
) -> EvidenceSearchQueryPlan:
    """자연어 질문을 분석하여 구조화된 증거 검색 계획(EvidenceSearchQueryPlan)을 생성한다.

    Args:
        query: 사용자 질문 문자열.
        known_party_names: 사건에 등록된 당사자 실명 목록(선택).
        include_pending: 미승인(PENDING) Claim 포함 여부.

    Returns:
        EvidenceSearchQueryPlan: 정규화된 구조화 검색 조건.
    """
    q = (query or "").strip()
    keywords = extract_search_keywords(q)
    date_terms = _expand_date_variants(q)
    amount_terms = _expand_amount_variants(q)

    party_terms: List[str] = []
    for role in _PARTY_ROLE_KEYWORDS:
        if role in q and role not in party_terms:
            party_terms.append(role)
    for name in (known_party_names or []):
        if name and len(name.strip()) >= 2 and name.strip() in q:
            if name.strip() not in party_terms:
                party_terms.append(name.strip())

    action_terms = [act for act in _ACTION_KEYWORDS if act in q]
    document_terms = [doc_kw for doc_kw in _DOCUMENT_KEYWORDS if doc_kw in q]

    claim_types: List[str] = []
    if date_terms:
        claim_types.append("DATE")
    if amount_terms:
        claim_types.append("AMOUNT")
    if party_terms:
        claim_types.append("PARTY_INFO")
    for kw, c_types in _KEYWORD_TO_CLAIM_TYPES.items():
        if kw in q:
            for ct in c_types:
                if ct not in claim_types:
                    claim_types.append(ct)

    only_contradictions = any(w in q for w in ("모순", "상충", "충돌", "다른데", "불일치", "반박"))

    return EvidenceSearchQueryPlan(
        raw_query=q,
        keywords=keywords,
        date_terms=date_terms,
        amount_terms=amount_terms,
        party_terms=party_terms,
        action_terms=action_terms,
        document_terms=document_terms,
        claim_types=claim_types,
        include_pending=include_pending,
        only_contradictions=only_contradictions,
    )


def _check_pg_trgm_available(db: Session) -> bool:
    """현재 PostgreSQL 세션에서 pg_trgm 확장(similarity 함수)이 사용 가능한지 확인한다."""
    try:
        bind = db.get_bind()
        if bind.dialect.name != "postgresql":
            return False
        res = db.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
        ).scalar()
        return bool(res)
    except Exception:
        return False


def _compute_trigram_similarity(a: str, b: str) -> float:
    """애플리케이션 레벨 문자 2/3-gram 유사도를 계산한다 (pg_trgm 미설치 환경 호환용)."""
    s1 = re.sub(r"\s+", "", (a or "").lower())
    s2 = re.sub(r"\s+", "", (b or "").lower())
    if not s1 or not s2:
        return 0.0
    n = 2 if min(len(s1), len(s2)) < 4 else 3
    grams1 = {s1[i:i + n] for i in range(max(1, len(s1) - n + 1))}
    grams2 = {s2[i:i + n] for i in range(max(1, len(s2) - n + 1))}
    if not grams1 or not grams2:
        return 0.0
    inter = len(grams1 & grams2)
    return inter / float(len(grams1 | grams2))


@trace
def search_evidence_in_postgres(
    db: Session,
    case_id: str,
    query: str,
    strategy: str = "hybrid_pg",
    include_pending: bool = False,
    limit: int = 15,
    user_id: Optional[str] = None,
    top_k: Optional[int] = None,
) -> EvidenceSearchResponse:
    """PostgreSQL에 저장된 사건 증거·주장·사실·원문 Span을 구조화 조건 및 텍스트로 검색한다.

    지원 전략(strategy):
      - 'text' (E1): 키워드 ILIKE 및 문자열 유사도(pg_trgm/n-gram) 중심 원문·문장 검색
      - 'structured' (E2): 날짜·금액·당사자·Claim유형·문서명·승인상태·Fact/Link 조건 중심 구조화 검색
      - 'hybrid_pg' (기본): E1(텍스트) + E2(구조화) 결합 및 Span-Claim-Fact 양방향 출처 역추적

    Args:
        db: SQLAlchemy 세션.
        case_id: 검색 대상 사건 ID (필수 격리 키).
        query: 사용자 질문 문자열.
        strategy: 검색 전략 ('text' | 'structured' | 'hybrid_pg').
        include_pending: True이면 PENDING 상태의 Claim 후보도 포함 (확정 근거 외 후보 조회용).
        limit: 반환할 최대 Hit 수.
        user_id: 요청 사용자 ID (제공 시 사건 소유권 추가 검증).

    Returns:
        EvidenceSearchResponse: 구조화 검색 결과, 매칭된 ID 집합, 상충 및 증거 공백 정보.
    """
    if top_k is not None:
        limit = top_k
    empty_plan = EvidenceSearchQueryPlan(raw_query=query or "", include_pending=include_pending)
    if not case_id:
        return EvidenceSearchResponse(case_id="", strategy=strategy, query_plan=empty_plan)

    # 1. 사건 실존 및 소유권 격리 검증
    case_q = db.query(Case).filter(Case.id == case_id)
    if user_id:
        case_q = case_q.filter(or_(Case.user_id == user_id, Case.user_id.is_(None)))
    case_obj = case_q.first()
    if case_obj is None:
        return EvidenceSearchResponse(case_id=case_id, strategy=strategy, query_plan=empty_plan)

    # 2. 사건 소속 데이터 로드 (단일 사건 내 엔티티를 매개변수 바인딩으로 안전하게 조회)
    parties = db.query(Party).filter(Party.case_id == case_id).all()
    known_party_names = [p.name for p in parties if p.name]

    plan = analyze_evidence_query(
        query=query,
        known_party_names=known_party_names,
        include_pending=include_pending,
    )

    docs = db.query(EvidenceDocument).filter(EvidenceDocument.case_id == case_id).all()
    docs_by_id: Dict[str, EvidenceDocument] = {d.id: d for d in docs}
    doc_ids = list(docs_by_id.keys())

    spans: List[EvidenceSpan] = []
    if doc_ids:
        spans = (
            db.query(EvidenceSpan)
            .filter(EvidenceSpan.evidence_id.in_(doc_ids))
            .order_by(EvidenceSpan.page_number.asc(), EvidenceSpan.paragraph_index.asc())
            .all()
        )
    spans_by_id: Dict[str, EvidenceSpan] = {s.id: s for s in spans}

    # 승인 상태 정책 적용: REJECTED는 언제나 제외, 기본은 APPROVED/EDITED만 허용
    allowed_statuses = list(APPROVED_REVIEW_STATUSES)
    if include_pending:
        allowed_statuses.append("PENDING")

    claims = (
        db.query(EvidenceClaim)
        .filter(
            EvidenceClaim.case_id == case_id,
            EvidenceClaim.review_status.in_(allowed_statuses),
        )
        .all()
    )
    claims_by_id: Dict[str, EvidenceClaim] = {c.id: c for c in claims}

    # Span <-> Claim 다대다 연결 매핑
    claim_to_span_ids: Dict[str, List[str]] = {}
    span_to_claim_ids: Dict[str, List[str]] = {}
    if claims_by_id and spans_by_id:
        scl_rows = (
            db.query(EvidenceSpanClaimLink)
            .filter(EvidenceSpanClaimLink.claim_id.in_(list(claims_by_id.keys())))
            .all()
        )
        for row in scl_rows:
            if row.span_id in spans_by_id:
                claim_to_span_ids.setdefault(row.claim_id, []).append(row.span_id)
                span_to_claim_ids.setdefault(row.span_id, []).append(row.claim_id)

    facts = db.query(Fact).filter(Fact.case_id == case_id).all()
    facts_by_id: Dict[str, Fact] = {f.id: f for f in facts}

    events = db.query(Event).filter(Event.case_id == case_id).all()
    issues = db.query(LegalIssue).filter(LegalIssue.case_id == case_id).all()

    links: List[EvidenceLink] = []
    if doc_ids:
        links = db.query(EvidenceLink).filter(EvidenceLink.evidence_id.in_(doc_ids)).all()

    # Claim -> 지지/상충하는 Fact 매핑
    claim_to_fact_ids: Dict[str, List[str]] = {}
    fact_to_claim_ids: Dict[str, List[str]] = {}
    contradiction_records: List[Dict[str, Any]] = []

    for lnk in links:
        # 미승인/반려 Claim의 링크는 확정 근거 매핑에서 제외
        if lnk.claim_id and lnk.claim_id not in claims_by_id:
            continue
        if lnk.target_type == "FACT" and lnk.target_id in facts_by_id:
            if lnk.link_type == "SUPPORTS" and lnk.claim_id:
                claim_to_fact_ids.setdefault(lnk.claim_id, []).append(lnk.target_id)
                fact_to_claim_ids.setdefault(lnk.target_id, []).append(lnk.claim_id)
            elif lnk.link_type == "CONTRADICTS":
                c_obj = claims_by_id.get(lnk.claim_id) if lnk.claim_id else None
                f_obj = facts_by_id.get(lnk.target_id)
                sup_ids = fact_to_claim_ids.get(lnk.target_id, [])
                contradiction_records.append({
                    "target_type": "Fact",
                    "target_id": lnk.target_id,
                    "target_content": f_obj.statement if f_obj else "",
                    "contradicting_id": lnk.claim_id or lnk.span_id,
                    "contradicting_type": "EvidenceClaim" if lnk.claim_id else "EvidenceSpan",
                    "contradicting_statement": c_obj.statement if c_obj else "",
                    "evidence_id": lnk.evidence_id,
                    "supporting_claim_ids": sup_ids,
                })

    # 증거 공백(승인된 증거 SUPPORTS가 없는 Fact / LegalIssue) 계산
    evidence_gaps: List[Dict[str, Any]] = []
    for f in facts:
        if not fact_to_claim_ids.get(f.id):
            evidence_gaps.append({
                "node_type": "Fact",
                "node_id": f.id,
                "content": f.statement,
            })
    for iss in issues:
        rel_fids = iss.related_fact_ids or []
        if not any(fact_to_claim_ids.get(fid) for fid in rel_fids):
            evidence_gaps.append({
                "node_type": "LegalIssue",
                "node_id": iss.id,
                "content": iss.title,
            })

    use_text = strategy in ("text", "hybrid_pg")
    use_structured = strategy in ("structured", "hybrid_pg")
    trgm_available = _check_pg_trgm_available(db) if use_text else False

    hits: List[EvidenceSearchHit] = []

    # ------------------------------------------------------------------
    # A. EvidenceClaim 검색 (구조화 조건 + 텍스트 + 연결된 원문 Span/Fact 결합)
    # ------------------------------------------------------------------
    for claim in claims:
        doc = docs_by_id.get(claim.evidence_id)
        doc_name = doc.original_filename if doc else None
        linked_span_ids = claim_to_span_ids.get(claim.id, [])
        primary_span = spans_by_id.get(linked_span_ids[0]) if linked_span_ids else None
        span_texts = " ".join(
            spans_by_id[sid].text_excerpt for sid in linked_span_ids if sid in spans_by_id
        )
        linked_fact_ids = claim_to_fact_ids.get(claim.id, [])
        primary_fact = facts_by_id.get(linked_fact_ids[0]) if linked_fact_ids else None

        combined_text = f"{claim.statement or ''} {span_texts} {doc_name or ''}".lower()
        score = 0.0
        reasons: List[str] = []

        if use_structured:
            # 1) 날짜 조건 매칭
            matched_dates = [dt for dt in plan.date_terms if dt.lower() in combined_text]
            if matched_dates:
                score += 3.5 * len(matched_dates)
                reasons.append(f"DATE_MATCH:{','.join(matched_dates[:2])}")

            # 2) 금액 조건 매칭
            matched_amts = [amt for amt in plan.amount_terms if amt.lower() in combined_text]
            if matched_amts:
                score += 3.5 * len(matched_amts)
                reasons.append(f"AMOUNT_MATCH:{matched_amts[0]}")

            # 3) 당사자 조건 매칭
            matched_parties = [pt for pt in plan.party_terms if pt.lower() in combined_text]
            if matched_parties:
                score += 2.5 * len(matched_parties)
                reasons.append(f"PARTY_MATCH:{','.join(matched_parties[:2])}")

            # 4) 법률행위 조건 매칭
            matched_actions = [act for act in plan.action_terms if act.lower() in combined_text]
            if matched_actions:
                score += 2.0 * len(matched_actions)
                reasons.append(f"ACTION_MATCH:{','.join(matched_actions[:2])}")

            # 5) 문서명 조건 매칭
            matched_docs = [dk for dk in plan.document_terms if dk.lower() in (doc_name or "").lower()]
            if matched_docs:
                score += 2.5
                reasons.append(f"DOCUMENT_MATCH:{matched_docs[0]}")

            # 6) Claim 유형 코드 일치
            if claim.claim_type and claim.claim_type in plan.claim_types:
                score += 1.5
                reasons.append(f"CLAIM_TYPE:{claim.claim_type}")

            # 7) 상충 후보 우선 검색
            if plan.only_contradictions and claim.assertion_status == "CONTRADICTION_CANDIDATE":
                score += 4.0
                reasons.append("CONTRADICTION_CANDIDATE")

        if use_text:
            # 8) 핵심 키워드 ILIKE 매칭
            matched_kws = [kw for kw in plan.keywords if kw in combined_text]
            if matched_kws:
                score += 2.0 * len(matched_kws)
                reasons.append(f"KEYWORD_MATCH:{','.join(matched_kws[:4])}")

            # 9) 유사 문자열(Trigram) 보정 점수
            if plan.raw_query and score == 0.0:
                sim = _compute_trigram_similarity(plan.raw_query, claim.statement or "")
                if sim >= 0.18:
                    score += round(sim * 3.0, 2)
                    reasons.append(f"TRGM_SIMILARITY:{sim:.2f}" if trgm_available else f"NGRAM_SIMILARITY:{sim:.2f}")

        if score > 0.0:
            hits.append(
                EvidenceSearchHit(
                    case_id=case_id,
                    evidence_id=claim.evidence_id,
                    document_id=claim.evidence_id,
                    document_name=doc_name,
                    span_id=primary_span.id if primary_span else None,
                    page_number=primary_span.page_number if primary_span else None,
                    paragraph_index=primary_span.paragraph_index if primary_span else None,
                    claim_id=claim.id,
                    fact_id=primary_fact.id if primary_fact else None,
                    statement=claim.statement,
                    claim_statement=claim.statement,
                    source_excerpt=primary_span.text_excerpt if primary_span else None,
                    review_status=claim.review_status,
                    assertion_status=claim.assertion_status,
                    verification_status=primary_fact.verification_status if primary_fact else "CLAIM_ONLY",
                    match_reason=" | ".join(reasons),
                    score=score,
                    node_type="EvidenceClaim",
                    node_id=claim.id,
                )
            )

    # ------------------------------------------------------------------
    # B. 원문 EvidenceSpan 직접 검색 (Claim에 아직 포착되지 않은 세부 원문/조항 보완)
    # ------------------------------------------------------------------
    matched_span_set = {h.span_id for h in hits if h.span_id}
    for span in spans:
        if span.id in matched_span_set:
            continue
        doc = docs_by_id.get(span.evidence_id)
        doc_name = doc.original_filename if doc else None
        span_txt_low = f"{span.text_excerpt or ''} {doc_name or ''}".lower()

        # 반려(REJECTED)된 Claim에만 연결된 Span인지 확인
        linked_cids = span_to_claim_ids.get(span.id, [])
        primary_claim = claims_by_id.get(linked_cids[0]) if linked_cids else None

        score = 0.0
        reasons = []
        if use_structured:
            matched_dates = [dt for dt in plan.date_terms if dt.lower() in span_txt_low]
            if matched_dates:
                score += 3.0 * len(matched_dates)
                reasons.append(f"SPAN_DATE:{matched_dates[0]}")
            matched_amts = [amt for amt in plan.amount_terms if amt.lower() in span_txt_low]
            if matched_amts:
                score += 3.0 * len(matched_amts)
                reasons.append(f"SPAN_AMOUNT:{matched_amts[0]}")

        if use_text:
            matched_kws = [kw for kw in plan.keywords if kw in span_txt_low]
            if matched_kws:
                score += 1.8 * len(matched_kws)
                reasons.append(f"SPAN_KEYWORD:{','.join(matched_kws[:4])}")

        if score > 0.0:
            linked_fids = claim_to_fact_ids.get(primary_claim.id, []) if primary_claim else []
            primary_fact = facts_by_id.get(linked_fids[0]) if linked_fids else None
            hits.append(
                EvidenceSearchHit(
                    case_id=case_id,
                    evidence_id=span.evidence_id,
                    document_id=span.evidence_id,
                    document_name=doc_name,
                    span_id=span.id,
                    page_number=span.page_number,
                    paragraph_index=span.paragraph_index,
                    claim_id=primary_claim.id if primary_claim else None,
                    fact_id=primary_fact.id if primary_fact else None,
                    statement=primary_claim.statement if primary_claim else span.text_excerpt,
                    claim_statement=primary_claim.statement if primary_claim else None,
                    source_excerpt=span.text_excerpt,
                    review_status=primary_claim.review_status if primary_claim else "SPAN_RAW",
                    assertion_status=primary_claim.assertion_status if primary_claim else "DOCUMENT_EXCERPT",
                    verification_status=primary_fact.verification_status if primary_fact else "SPAN_ONLY",
                    match_reason=" | ".join(reasons),
                    score=score,
                    node_type="EvidenceSpan",
                    node_id=span.id,
                )
            )

    # ------------------------------------------------------------------
    # C. 사건 Fact / Event / LegalIssue 직접 검색 (Graph Traversal 시드 확보용)
    # ------------------------------------------------------------------
    matched_fact_set = {h.fact_id for h in hits if h.fact_id}
    for fact in facts:
        if fact.id in matched_fact_set:
            continue
        f_low = f"{fact.statement or ''} {fact.occurred_at or ''}".lower()
        score = 0.0
        reasons = []
        if use_structured:
            matched_dates = [dt for dt in plan.date_terms if dt.lower() in f_low]
            if matched_dates:
                score += 2.5
                reasons.append(f"FACT_DATE:{matched_dates[0]}")
            matched_amts = [amt for amt in plan.amount_terms if amt.lower() in f_low]
            if matched_amts:
                score += 2.5
                reasons.append(f"FACT_AMOUNT:{matched_amts[0]}")
        if use_text:
            matched_kws = [kw for kw in plan.keywords if kw in f_low]
            if matched_kws:
                score += 1.5 * len(matched_kws)
                reasons.append(f"FACT_KEYWORD:{','.join(matched_kws[:4])}")

        if score > 0.0:
            sup_cids = fact_to_claim_ids.get(fact.id, [])
            sup_claim = claims_by_id.get(sup_cids[0]) if sup_cids else None
            sup_sids = claim_to_span_ids.get(sup_claim.id, []) if sup_claim else []
            sup_span = spans_by_id.get(sup_sids[0]) if sup_sids else None
            ev_id = sup_claim.evidence_id if sup_claim else (
                fact.source_ref if fact.source_type == "DOCUMENT_SUPPORTED" else None
            )
            doc = docs_by_id.get(ev_id) if ev_id else None

            hits.append(
                EvidenceSearchHit(
                    case_id=case_id,
                    evidence_id=ev_id,
                    document_id=ev_id,
                    document_name=doc.original_filename if doc else None,
                    span_id=sup_span.id if sup_span else None,
                    page_number=sup_span.page_number if sup_span else None,
                    paragraph_index=sup_span.paragraph_index if sup_span else None,
                    claim_id=sup_claim.id if sup_claim else None,
                    fact_id=fact.id,
                    statement=fact.statement,
                    claim_statement=sup_claim.statement if sup_claim else None,
                    source_excerpt=sup_span.text_excerpt if sup_span else None,
                    review_status=sup_claim.review_status if sup_claim else None,
                    assertion_status=sup_claim.assertion_status if sup_claim else fact.source_type,
                    verification_status=fact.verification_status,
                    match_reason=" | ".join(reasons),
                    score=score,
                    node_type="Fact",
                    node_id=fact.id,
                )
            )

    # 점수 내림차순 정렬 및 상위 limit 절삭
    hits.sort(key=lambda h: h.score, reverse=True)
    top_hits = hits[:limit]

    matched_claim_ids: List[str] = []
    matched_fact_ids: List[str] = []
    matched_span_ids: List[str] = []
    matched_document_ids: List[str] = []

    for h in top_hits:
        if h.claim_id and h.claim_id not in matched_claim_ids:
            matched_claim_ids.append(h.claim_id)
        if h.fact_id and h.fact_id not in matched_fact_ids:
            matched_fact_ids.append(h.fact_id)
        if h.span_id and h.span_id not in matched_span_ids:
            matched_span_ids.append(h.span_id)
        if h.evidence_id and h.evidence_id not in matched_document_ids:
            matched_document_ids.append(h.evidence_id)

    return EvidenceSearchResponse(
        case_id=case_id,
        strategy=strategy,
        query_plan=plan,
        hits=top_hits,
        matched_claim_ids=matched_claim_ids,
        matched_fact_ids=matched_fact_ids,
        matched_span_ids=matched_span_ids,
        matched_document_ids=matched_document_ids,
        contradictions=contradiction_records,
        evidence_gaps=evidence_gaps,
    )
