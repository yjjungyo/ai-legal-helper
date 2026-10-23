# -*- coding: utf-8 -*-
"""
모듈명: entity_sync.py

[모듈 개요]
사건의 확정 사실(Fact) 및 승인된 증거 주장(EvidenceClaim)을 기반으로
당사자(Party)와 타임라인 이벤트(Event)를 자동 생성·갱신·정리하는 공통 동기화 모듈이다.

[핵심 설계 원칙 (P0-01 ~ P0-04, P1)]
1. Evidence → Fact → Party 자동 생성 및 정규화:
   - `PARTY_INFO` 사실을 우선 처리하고, 타 유형 사실이라도 명확한 `(역할, 이름)` 표현이 있으면 보강 추출한다.
   - 어순(`임대인은 박정훈이다`, `임대인 박정훈`, `박정훈은 임대인이다`)에 무관하게 동일한 `(name, role)`로 정규화한다.
   - 특정 사건 인명·숫자를 하드코딩하지 않으며, 임대차·매매·민사·노동·형사 등 범용 법률 역할을 지원한다.
   - 유효한 인명/기관명이 확인되지 않는 일반 명사·서술어(`임대인은 보증금 반환을 지연했다` 등)에서는
     쓰레기 Party를 생성하지 않는다 (T04).
   - 동일 인물에 대해 본질적 법률 역할(`임대인`, `임차인`, `원고`, `피고` 등)이 확인된 경우,
     단순 통신/문서상 보조 역할(`발신자`, `수신자`, `작성자`) 및 연락처 정보는 별도 중복 Party로 만들지 않고
     해당 당사자의 `notes` 및 `related_fact_ids`로 병합한다 (T02, T03).
2. 수동 데이터(MANUAL) 보호 및 생명주기 정합성:
   - 사용자가 직접 등록한 `source_type == "MANUAL"` Party/Event는 삭제하거나 임의로 덮어쓰지 않는다 (T12).
   - EvidenceClaim이 수정(`EDIT`)되거나 반려(`REJECT`), 또는 증거 문서가 삭제될 때
     단독 근거만 있던 `EVIDENCE_DERIVED` Party/Event는 즉시 제거·갱신하고,
     다른 승인된 증거가 여전히 지지하는 Party/Event는 유지한다 (T09, T10, T11).
3. 멱등성(Idempotency) 및 기존 사건 복구(Backfill):
   - 동일 사건에 대해 `synchronize_case_entities` 또는 `rebuild_case_entities`를 반복 실행해도
     중복 Party/Event가 누적되지 않는다 (T13).
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from ai_legal_helper.case_intelligence.timeline import build_timeline_from_facts
from ai_legal_helper.database.models import (
    Case,
    Event,
    EvidenceClaim,
    EvidenceLink,
    Fact,
    Party,
)
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

# 1. 실체적 법률 지위(Substantive Legal Roles) 동의어 → 표준 역할 매핑
_SUBSTANTIVE_ROLE_MAP: Dict[str, str] = {
    # 임대차 / 부동산
    "임대인": "임대인",
    "공동임대인": "임대인",
    "집주인": "임대인",
    "건물주": "임대인",
    "임차인": "임차인",
    "공동임차인": "임차인",
    "세입자": "임차인",
    "입주자": "임차인",
    "전대인": "전대인",
    "전차인": "전차인",
    "매도인": "매도인",
    "매수인": "매수인",
    "분양자": "분양자",
    "수분양자": "수분양자",
    "소유자": "소유자",
    "점유자": "점유자",
    "공인중개사": "공인중개사",
    "중개인": "공인중개사",
    # 민사 / 채권·채무 / 계약
    "원고": "원고",
    "피고": "피고",
    "채권자": "채권자",
    "채무자": "채무자",
    "연대보증인": "연대보증인",
    "보증인": "보증인",
    "양도인": "양도인",
    "양수인": "양수인",
    "위임인": "위임인",
    "수임인": "수임인",
    "도급인": "도급인",
    "수급인": "수급인",
    "발주자": "발주자",
    "시공사": "시공사",
    "보험자": "보험자",
    "피보험자": "피보험자",
    # 노동 / 고용
    "사용자": "사용자",
    "고용주": "사용자",
    "사업주": "사용자",
    "근로자": "근로자",
    "피용자": "근로자",
    # 형사 / 가사 / 행정 / 대리
    "고소인": "고소인",
    "피고소인": "피고소인",
    "고발인": "고발인",
    "피고발인": "피고발인",
    "피해자": "피해자",
    "가해자": "가해자",
    "피의자": "피의자",
    "피고인": "피고인",
    "신청인": "신청인",
    "피신청인": "피신청인",
    "청구인": "청구인",
    "피청구인": "피청구인",
    "항소인": "항소인",
    "피항소인": "피항소인",
    "상속인": "상속인",
    "피상속인": "피상속인",
    "대리인": "대리인",
    "법정대리인": "법정대리인",
    "소송대리인": "소송대리인",
}

# 2. 문서·대화상 보조 역할(Auxiliary Roles) 매핑
_AUXILIARY_ROLE_MAP: Dict[str, str] = {
    "발신자": "발신자",
    "발신인": "발신자",
    "수신자": "수신자",
    "수신인": "수신자",
    "작성자": "작성자",
    "통지인": "통지인",
    "수령인": "수령인",
}

_ALL_ROLE_MAP: Dict[str, str] = {**_SUBSTANTIVE_ROLE_MAP, **_AUXILIARY_ROLE_MAP}
_SORTED_ROLE_TOKENS: List[str] = sorted(_ALL_ROLE_MAP.keys(), key=len, reverse=True)
_ROLE_ALTERNATION: str = "|".join(re.escape(r) for r in _SORTED_ROLE_TOKENS)

# 대립/쌍방 당사자 관계 추론 테이블
_COUNTERPARTY_RELATIONS: Dict[str, Tuple[str, str]] = {
    "임대인": ("임차인", "임대차계약 당사자"),
    "임차인": ("임대인", "임대차계약 당사자"),
    "전대인": ("전차인", "전대차계약 당사자"),
    "전차인": ("전대인", "전대차계약 당사자"),
    "매도인": ("매수인", "매매계약 당사자"),
    "매수인": ("매도인", "매매계약 당사자"),
    "원고": ("피고", "소송 당사자"),
    "피고": ("원고", "소송 당사자"),
    "채권자": ("채무자", "채권·채무 관계"),
    "채무자": ("채권자", "채권·채무 관계"),
    "사용자": ("근로자", "근로계약 당사자"),
    "근로자": ("사용자", "근로계약 당사자"),
    "도급인": ("수급인", "도급계약 당사자"),
    "수급인": ("도급인", "도급계약 당사자"),
    "고소인": ("피고소인", "형사고소 당사자"),
    "피고소인": ("고소인", "형사고소 당사자"),
    "신청인": ("피신청인", "신청사건 당사자"),
    "피신청인": ("신청인", "신청사건 당사자"),
}

# 인명/기관명으로 오인해서는 안 되는 일반 법률·계약·행위·상태 명사 사전 (T04 보호)
_NON_NAME_STOPWORDS: Set[str] = {
    *_ALL_ROLE_MAP.keys(),
    "계약", "계약서", "문서", "문자", "메시지", "대화", "내용증명", "통지서", "합의서", "확인서",
    "영수증", "특약", "조항", "서명", "서명란", "날인", "기재", "명시", "표시", "확인", "사실",
    "내용", "주장", "진술", "증거", "보증금", "전세금", "전세보증금", "임대차보증금", "계약금",
    "중도금", "잔금", "월세", "차임", "관리비", "이자", "지연손해금", "손해배상", "위약금", "금원",
    "금액", "계좌", "은행계좌", "주택", "아파트", "건물", "부동산", "목적물", "임차목적물", "호실",
    "주소", "소재지", "연락처", "전화번호", "휴대전화", "이메일", "성명", "이름", "성명미상", "불상",
    "미상", "미정", "없음", "있음", "동일", "본인", "상대방", "당사자", "제3자", "반환", "지급",
    "입금", "송금", "퇴거", "이사", "인도", "명도", "갱신", "해지", "종료", "만기", "만료", "연장",
    "지연", "거절", "거부", "동의", "합의", "승낙", "요청", "통보", "통지", "연락", "약속", "의무",
    "권리", "책임", "사정", "사유", "기한", "기간", "일정", "예정", "새로운", "신규", "기존",
    "다음", "해당", "위", "아래", "각", "양", "쌍방", "일방", "사이", "명의", "소유", "표시",
    "녹취", "녹취록", "통화", "형식", "원본", "사본", "문서에", "여부", "진술", "진술상", "유지", "거주",
}

_NON_NAME_SUBSTRINGS: Tuple[str, ...] = (
    "보증금", "전세금", "계약금", "중도금", "잔금", "차임", "월세", "연락처", "전화번호",
    "서명란", "계좌", "반환", "지급", "퇴거", "인도", "명도", "해지", "갱신", "지연",
    "거절", "요청", "통보", "통지", "기재", "명시", "하였다", "했다", "한다", "이다",
    "입니다", "있고", "있다", "없다", "않다", "미상", "불상", "예정", "기일", "문서", "진술", "여부",
)

_ORG_KEYWORDS: Tuple[str, ...] = (
    "주식회사", "(주)", "㈜", "유한회사", "합자회사", "법무법인", "재단법인", "사단법인",
    "은행", "공사", "공단", "조합", "협회", "보험", "증권", "건설", "산업", "물산", "코퍼레이션",
)

# 정규식 패턴들
# 패턴 1: "<역할>은/는/이/가 <이름>이다 / <이름>으로 기재되어 있다"
_PATTERN_ROLE_IS_NAME = re.compile(
    rf"(?P<role>{_ROLE_ALTERNATION})(?:은|는|이|가|:|\s*[:=]\s*)\s*"
    rf"(?P<name>(?:주식회사\s*[가-힣A-Za-z0-9]+?|\(주\)\s*[가-힣A-Za-z0-9]+?|㈜\s*[가-힣A-Za-z0-9]+?|[가-힣]{{2,10}}?))"
    rf"(?:\s*(?:씨|님))?"
    rf"(?=(?:이다|입니다|이고|이며|으로\s*기재|로\s*기재|으로\s*확인|로\s*확인|으로\s*명시|로\s*명시|으로\s*표시|로\s*표시|[.,;]|$))"
)

# 패턴 2: "<이름>은/는/이/가 <역할>이다 / <역할>로서"
_PATTERN_NAME_IS_ROLE = re.compile(
    rf"(?:^|[,;\s])(?P<name>(?:주식회사\s*[가-힣A-Za-z0-9]+?|\(주\)\s*[가-힣A-Za-z0-9]+?|㈜\s*[가-힣A-Za-z0-9]+?|[가-힣]{{2,4}}))"
    rf"(?:\s*(?:씨|님))?(?:은|는|이|가)\s+(?:이\s*사건\s*)?"
    rf"(?P<role>{_ROLE_ALTERNATION})"
    rf"(?=(?:이다|입니다|이고|이며|으로서|로서|[.,;]|$))"
)

# 패턴 3: "<역할>(<이름>)" 또는 "<이름>(<역할>)"
_PATTERN_ROLE_PAREN_NAME = re.compile(
    rf"(?P<role>{_ROLE_ALTERNATION})\s*\(\s*(?P<name>[가-힣]{{2,10}})\s*\)"
)
_PATTERN_NAME_PAREN_ROLE = re.compile(
    rf"(?P<name>[가-힣]{{2,10}})\s*\(\s*(?P<role>{_ROLE_ALTERNATION})\s*\)"
)

# 패턴 4: "<역할> <이름어절>" (예: "임대인 박정훈", "임대인 박정훈은", "임대인 박정훈의")
_PATTERN_ROLE_SPACE_NAME = re.compile(
    rf"(?<![가-힣])(?P<role>{_ROLE_ALTERNATION})\s+"
    rf"(?P<name>[가-힣]{{2,6}})"
    rf"(?=\s|[.,;)]|$)"
)

# 역할 귀속 연락처 추출 패턴: "임대인의 연락처는 010-4826-1357이다" 또는 "임대인은 박정훈이며 연락처는 010-4826-1357이다"
_PATTERN_ROLE_CONTACT = re.compile(
    rf"(?P<role>{_ROLE_ALTERNATION})(?:의|(?:은|는|이|가)\s+[가-힣]{{2,4}}(?:이고|이며|이고,|\s*,)?)?\s*"
    rf"(?:연락처|전화번호|휴대전화)(?:은|는|이|가|:)?\s*"
    rf"(?P<phone>0\d{{1,2}}[-.\s]?\d{{3,4}}[-.\s]?\d{{4}})"
)


@dataclass
class _ExtractedPartyCandidate:
    """Fact들로부터 병합된 단일 당사자 후보 데이터."""

    name: str
    role: str
    is_substantive: bool
    party_relationship: Optional[str] = None
    aux_roles: List[str] = field(default_factory=list)
    contacts: List[str] = field(default_factory=list)
    related_fact_ids: List[str] = field(default_factory=list)
    related_claim_ids: List[str] = field(default_factory=list)
    verification_status: str = "DOCUMENT_VERIFIED"


def _clean_and_validate_party_name(raw_name: str) -> Optional[str]:
    """추출된 이름 후보에서 불필요한 호칭·조사를 정리하고 유효한 인명/기관명인지 검증한다.

    Args:
        raw_name: 정규식에서 캡처된 원시 이름 문자열.

    Returns:
        Optional[str]: 유효한 인명/기관명이면 정규화된 이름, 아니면 None.
    """
    if not raw_name:
        return None
    name = raw_name.strip()
    name = re.sub(r"\s*(씨|님|귀하)$", "", name).strip()
    if not name:
        return None

    # 기관/법인명 여부 확인
    is_org = any(kw in name for kw in _ORG_KEYWORDS)
    compact = re.sub(r"\s+", "", name)

    if compact in _NON_NAME_STOPWORDS:
        return None
    if any(sub in compact for sub in _NON_NAME_SUBSTRINGS):
        return None

    if is_org:
        if 2 <= len(compact) <= 25:
            return re.sub(r"\s+", " ", name)
        return None

    # 개인 성명 검증: 어절 끝에 결합된 조사/호칭 정리 후 한글 2~4자 검증
    if len(compact) == 5 and compact.endswith(("에게", "으로", "부터", "께서", "님의", "씨의", "씨는", "씨가")):
        compact = compact[:-2]
    elif len(compact) == 4 and compact[-1] in ("의", "은", "는", "이", "가", "을", "를", "과", "와", "도", "로", "님", "씨"):
        compact = compact[:-1]
    elif len(compact) == 3 and compact[-1] in ("의", "은", "는", "이", "가", "을", "를", "과", "와", "도", "로"):
        # 2음절 일반명사 + 조사(예: "사이의", "본인의", "쌍방의")인 경우 배제
        if compact[:-1] in _NON_NAME_STOPWORDS:
            return None

    if compact in _NON_NAME_STOPWORDS:
        return None
    if any(sub in compact for sub in _NON_NAME_SUBSTRINGS):
        return None

    if re.fullmatch(r"[가-힣]{2,4}", compact):
        return compact

    return None


def _extract_role_name_pairs_from_statement(statement: str) -> List[Tuple[str, str, bool]]:
    """단일 Fact 진술문에서 `(정규화된_이름, 표준_역할, 실체적_역할_여부)` 목록을 추출한다."""
    if not statement:
        return []

    found: List[Tuple[str, str, bool]] = []
    seen: Set[Tuple[str, str]] = set()

    for pattern in (
        _PATTERN_ROLE_IS_NAME,
        _PATTERN_NAME_IS_ROLE,
        _PATTERN_ROLE_PAREN_NAME,
        _PATTERN_NAME_PAREN_ROLE,
        _PATTERN_ROLE_SPACE_NAME,
    ):
        for match in pattern.finditer(statement):
            raw_role = (match.group("role") or "").strip()
            raw_name = (match.group("name") or "").strip()
            clean_name = _clean_and_validate_party_name(raw_name)
            if not clean_name:
                continue
            canonical_role = _ALL_ROLE_MAP.get(raw_role)
            if not canonical_role:
                continue
            is_sub = raw_role in _SUBSTANTIVE_ROLE_MAP
            key = (clean_name, canonical_role)
            if key not in seen:
                seen.add(key)
                found.append((clean_name, canonical_role, is_sub))

    return found


def _merge_trust_status(current: str, candidate_fact: Fact) -> str:
    """복수의 Fact가 하나의 당사자를 지지할 때 가장 신뢰도가 높은 검증 상태를 결정한다."""
    priority = {
        "DOCUMENT_VERIFIED": 4,
        "VERIFIED": 3,
        "PARTY_ASSERTED": 2,
        "DISPUTED": 1,
        "UNVERIFIED": 0,
    }
    fact_status = (candidate_fact.verification_status or "UNVERIFIED").upper()
    if candidate_fact.source_type == "DOCUMENT_SUPPORTED" and fact_status == "UNVERIFIED":
        fact_status = "DOCUMENT_VERIFIED"
    elif candidate_fact.source_type == "USER_CLAIM" and fact_status == "UNVERIFIED":
        fact_status = "VERIFIED"

    return fact_status if priority.get(fact_status, 0) > priority.get(current, 0) else current


def extract_parties_from_facts(
    facts: List[Fact],
    claim_ids_by_fact_id: Optional[Dict[str, List[str]]] = None,
) -> List[_ExtractedPartyCandidate]:
    """사건의 Fact 목록으로부터 정규화·병합된 당사자 후보 목록을 추출한다.

    [추출 및 병합 규칙]
    1. `PARTY_INFO`(`당사자정보`) 유형 Fact를 최우선 스캔하고, 그 외 Fact에서도 명확한 `(역할, 이름)`을 추출한다.
    2. 동일 인물에 대해 실체적 법률 역할(`임대인`, `임차인`, `원고`, `피고` 등)이 존재하면,
       보조 역할(`발신자`, `수신자`, `작성자`)은 별도 Party 레코드로 생성하지 않고 해당 인물의
       실체적 역할 Party의 `aux_roles` 및 `related_fact_ids`로 병합한다 (T02, T03).
    3. 동일 인물이 서로 다른 두 개의 실체적 법률 역할(예: `임대인`과 `매도인`)을 갖는 경우에는
       `(name, role)` 단위로 각각 보존한다.
    4. `"임대인의 연락처는 010-..."`와 같이 역할 기준으로 서술된 연락처 Fact는 해당 역할의 Party에 병합한다.

    Args:
        facts: 사건의 전체 Fact 리스트.
        claim_ids_by_fact_id: Fact ID별 지지 EvidenceClaim ID 리스트 매핑.

    Returns:
        List[_ExtractedPartyCandidate]: 정규화된 당사자 후보 목록.
    """
    claim_map = claim_ids_by_fact_id or {}

    # PARTY_INFO 사실을 먼저 정렬하여 우선 처리
    sorted_facts = sorted(
        facts,
        key=lambda f: 0 if (f.fact_type or "").upper() in ("PARTY_INFO", "당사자정보") else 1,
    )

    substantive_by_key: Dict[Tuple[str, str], _ExtractedPartyCandidate] = {}
    auxiliary_by_name: Dict[str, List[Tuple[str, Fact]]] = {}
    role_contacts: Dict[str, List[Tuple[str, Fact]]] = {}

    for fact in sorted_facts:
        stmt = (fact.statement or "").strip()
        if not stmt:
            continue

        # 연락처 속성 추출 (예: "임대인의 연락처는 010-4826-1357이다.")
        for cm in _PATTERN_ROLE_CONTACT.finditer(stmt):
            c_role = _ALL_ROLE_MAP.get(cm.group("role"), cm.group("role"))
            phone = re.sub(r"[\s.]+", "-", cm.group("phone").strip())
            role_contacts.setdefault(c_role, []).append((phone, fact))

        pairs = _extract_role_name_pairs_from_statement(stmt)
        for name, role, is_sub in pairs:
            if is_sub:
                key = (name, role)
                if key not in substantive_by_key:
                    init_status = _merge_trust_status("UNVERIFIED", fact)
                    substantive_by_key[key] = _ExtractedPartyCandidate(
                        name=name,
                        role=role,
                        is_substantive=True,
                        verification_status=init_status,
                    )
                cand = substantive_by_key[key]
                cand.verification_status = _merge_trust_status(cand.verification_status, fact)
                if fact.id and fact.id not in cand.related_fact_ids:
                    cand.related_fact_ids.append(fact.id)
                for cid in claim_map.get(fact.id or "", []):
                    if cid not in cand.related_claim_ids:
                        cand.related_claim_ids.append(cid)
            else:
                auxiliary_by_name.setdefault(name, []).append((role, fact))

    # 보조 역할(발신자/수신자/작성자 등) 병합 처리
    for name, aux_items in auxiliary_by_name.items():
        matching_sub_candidates = [
            cand for (cand_name, _role), cand in substantive_by_key.items() if cand_name == name
        ]
        if matching_sub_candidates:
            # 이미 실체적 법률 역할이 확인된 인물이면 첫 번째 실체적 역할 후보에 보조 속성으로 병합
            target_cand = matching_sub_candidates[0]
            for aux_role, fact in aux_items:
                if aux_role not in target_cand.aux_roles:
                    target_cand.aux_roles.append(aux_role)
                if fact.id and fact.id not in target_cand.related_fact_ids:
                    target_cand.related_fact_ids.append(fact.id)
                for cid in claim_map.get(fact.id or "", []):
                    if cid not in target_cand.related_claim_ids:
                        target_cand.related_claim_ids.append(cid)
        else:
            # 실체적 역할이 전혀 없는 인물인 경우에만 보조 역할로 Party 후보 생성
            primary_aux_role = aux_items[0][0]
            key = (name, primary_aux_role)
            cand = _ExtractedPartyCandidate(
                name=name,
                role=primary_aux_role,
                is_substantive=False,
                verification_status=_merge_trust_status("UNVERIFIED", aux_items[0][1]),
            )
            for aux_role, fact in aux_items:
                if aux_role != primary_aux_role and aux_role not in cand.aux_roles:
                    cand.aux_roles.append(aux_role)
                if fact.id and fact.id not in cand.related_fact_ids:
                    cand.related_fact_ids.append(fact.id)
                for cid in claim_map.get(fact.id or "", []):
                    if cid not in cand.related_claim_ids:
                        cand.related_claim_ids.append(cid)
            substantive_by_key[key] = cand

    # 역할별 연락처 정보를 해당 역할의 당사자 후보에 연결
    for role, contact_items in role_contacts.items():
        role_cands = [c for (_n, r), c in substantive_by_key.items() if r == role]
        for target_cand in role_cands:
            for phone, fact in contact_items:
                if phone not in target_cand.contacts:
                    target_cand.contacts.append(phone)
                if fact.id and fact.id not in target_cand.related_fact_ids:
                    target_cand.related_fact_ids.append(fact.id)
                for cid in claim_map.get(fact.id or "", []):
                    if cid not in target_cand.related_claim_ids:
                        target_cand.related_claim_ids.append(cid)

    # 쌍방 당사자 관계(party_relationship) 자동 추론
    candidates = list(substantive_by_key.values())
    by_role: Dict[str, List[str]] = {}
    for c in candidates:
        by_role.setdefault(c.role, []).append(c.name)

    for c in candidates:
        rel_info = _COUNTERPARTY_RELATIONS.get(c.role)
        if rel_info:
            counter_role, rel_label = rel_info
            counter_names = by_role.get(counter_role, [])
            if counter_names:
                c.party_relationship = f"{rel_label} (상대방 {counter_role}: {', '.join(counter_names)})"
            else:
                c.party_relationship = rel_label

    return candidates


def _format_party_notes(cand: _ExtractedPartyCandidate) -> Optional[str]:
    """당사자의 연락처 및 보조 역할(발신자/수신자 등)을 요약 노트 문자열로 포맷한다."""
    parts: List[str] = []
    if cand.contacts:
        parts.append(f"연락처: {', '.join(cand.contacts)}")
    if cand.aux_roles:
        parts.append(f"문서/대화상 역할: {', '.join(cand.aux_roles)}")
    return " | ".join(parts) if parts else None


def _build_fact_to_claim_ids_map(db: Session, case_id: str, facts: List[Fact]) -> Dict[str, List[str]]:
    """사건 내 각 Fact를 지지하는 승인/수정된 EvidenceClaim ID 목록을 매핑한다."""
    result: Dict[str, List[str]] = {f.id: [] for f in facts if f.id}
    if not result:
        return result

    links = (
        db.query(EvidenceLink)
        .join(EvidenceClaim, EvidenceLink.claim_id == EvidenceClaim.id)
        .filter(
            EvidenceClaim.case_id == case_id,
            EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
            EvidenceLink.target_type == "FACT",
            EvidenceLink.link_type == "SUPPORTS",
        )
        .all()
    )
    for link in links:
        if link.target_id in result and link.claim_id:
            if link.claim_id not in result[link.target_id]:
                result[link.target_id].append(link.claim_id)

    # EvidenceLink가 누락된 경우 동일 진술문 기준으로 보강
    approved_claims = (
        db.query(EvidenceClaim)
        .filter(
            EvidenceClaim.case_id == case_id,
            EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
        )
        .all()
    )
    claims_by_norm: Dict[str, List[str]] = {}
    for c in approved_claims:
        norm_c = "".join((c.statement or "").split())
        if norm_c:
            claims_by_norm.setdefault(norm_c, []).append(c.id)

    for f in facts:
        if not f.id:
            continue
        norm_f = "".join((f.statement or "").split())
        for cid in claims_by_norm.get(norm_f, []):
            if cid not in result[f.id]:
                result[f.id].append(cid)

    return result


def synchronize_case_parties(
    db: Session,
    case_id: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """사건의 현재 확정 사실(Fact)을 기준으로 당사자(Party) 목록을 동기화한다.

    [수동 데이터 보호 및 정합성 원칙]
    - `source_type == "MANUAL"`인 수동 등록 Party는 삭제하거나 기존 필드를 덮어쓰지 않는다 (T12).
    - `source_type in ("EVIDENCE_DERIVED", "STATEMENT_EXTRACTED")`인 파생 Party는
      현재 유효한 Fact 집합에서 추출된 결과와 비교하여 추가·갱신·삭제한다 (T09, T10, T11).

    Args:
        db: 데이터베이스 세션.
        case_id: 사건 ID.
        dry_run: True이면 DB를 변경하지 않고 변경 예정 요약만 반환.

    Returns:
        Dict[str, Any]: 추가·갱신·유지·삭제된 Party 통계 및 미리보기.
    """
    facts = db.query(Fact).filter_by(case_id=case_id).all()
    claim_map = _build_fact_to_claim_ids_map(db, case_id, facts)
    candidates = extract_parties_from_facts(facts, claim_ids_by_fact_id=claim_map)
    candidate_map: Dict[Tuple[str, str], _ExtractedPartyCandidate] = {
        (c.name, c.role): c for c in candidates
    }

    existing_parties = db.query(Party).filter_by(case_id=case_id).all()
    existing_by_key: Dict[Tuple[str, str], Party] = {}
    duplicate_derived_to_remove: List[Party] = []

    for p in existing_parties:
        key = ((p.name or "").strip(), (p.role or "").strip())
        if key in existing_by_key:
            # 이미 동일 (name, role)이 있는 경우 수동(MANUAL) 레코드를 우선 보존하고 중복 파생 레코드 제거
            prev = existing_by_key[key]
            if (p.source_type or "MANUAL") == "MANUAL" and (prev.source_type or "MANUAL") != "MANUAL":
                duplicate_derived_to_remove.append(prev)
                existing_by_key[key] = p
            else:
                duplicate_derived_to_remove.append(p)
        else:
            existing_by_key[key] = p

    added: List[Dict[str, Any]] = []
    updated: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    preserved_manual: List[Dict[str, Any]] = []

    if not dry_run:
        for dup in duplicate_derived_to_remove:
            if (dup.source_type or "MANUAL") != "MANUAL":
                db.delete(dup)

    # 1. 기존 Party 점검: 더 이상 근거 Fact가 없는 파생 Party 제거 또는 수동 Party 보존
    for key, existing_p in list(existing_by_key.items()):
        is_manual = (existing_p.source_type or "MANUAL") == "MANUAL" and not existing_p.related_fact_ids
        if key not in candidate_map:
            if is_manual or (existing_p.source_type or "MANUAL") == "MANUAL":
                preserved_manual.append({"id": existing_p.id, "name": existing_p.name, "role": existing_p.role})
            else:
                removed.append({"id": existing_p.id, "name": existing_p.name, "role": existing_p.role})
                if not dry_run:
                    db.delete(existing_p)
                del existing_by_key[key]

    # 2. 추출된 후보 Party 추가 또는 기존 레코드 갱신
    for key, cand in candidate_map.items():
        notes_str = _format_party_notes(cand)
        if key in existing_by_key:
            existing_p = existing_by_key[key]
            is_manual = (existing_p.source_type or "MANUAL") == "MANUAL"
            if is_manual:
                # 수동 등록 Party는 삭제하거나 기존 값을 덮어쓰지 않고 비어 있는 관계/노트만 보완
                if not dry_run:
                    if not existing_p.party_relationship and cand.party_relationship:
                        existing_p.party_relationship = cand.party_relationship
                    if not existing_p.notes and notes_str:
                        existing_p.notes = notes_str
                    existing_p.related_fact_ids = cand.related_fact_ids
                    existing_p.related_claim_ids = cand.related_claim_ids
                preserved_manual.append({"id": existing_p.id, "name": existing_p.name, "role": existing_p.role})
            else:
                changed = (
                    existing_p.party_relationship != cand.party_relationship
                    or existing_p.notes != notes_str
                    or existing_p.verification_status != cand.verification_status
                    or (existing_p.related_fact_ids or []) != cand.related_fact_ids
                    or (existing_p.related_claim_ids or []) != cand.related_claim_ids
                )
                if changed:
                    updated.append({"id": existing_p.id, "name": cand.name, "role": cand.role})
                    if not dry_run:
                        existing_p.party_relationship = cand.party_relationship
                        existing_p.notes = notes_str
                        existing_p.verification_status = cand.verification_status
                        existing_p.related_fact_ids = cand.related_fact_ids
                        existing_p.related_claim_ids = cand.related_claim_ids
        else:
            added.append({
                "name": cand.name,
                "role": cand.role,
                "party_relationship": cand.party_relationship,
                "notes": notes_str,
                "verification_status": cand.verification_status,
                "related_fact_ids": cand.related_fact_ids,
            })
            if not dry_run:
                new_party = Party(
                    case_id=case_id,
                    name=cand.name,
                    role=cand.role,
                    party_relationship=cand.party_relationship,
                    notes=notes_str,
                    source_type="EVIDENCE_DERIVED",
                    verification_status=cand.verification_status,
                    related_fact_ids=cand.related_fact_ids,
                    related_claim_ids=cand.related_claim_ids,
                )
                db.add(new_party)

    if not dry_run:
        db.flush()

    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "preserved_manual": preserved_manual,
        "total_derived": len(candidates),
    }


def synchronize_case_timeline(
    db: Session,
    case_id: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """사건의 현재 확정 사실(Fact)을 기준으로 타임라인 이벤트(Event)를 동기화한다.

    [수동 이벤트 보호 및 Fact occurred_at 보강 원칙]
    - `source_type == "MANUAL"`이면서 `related_fact_ids`가 없는 수동 등록 Event는 절대 삭제하지 않는다 (T12).
    - `Fact.occurred_at`이 비어 있으나 `Fact.statement`에서 단일 정확 일자(`EXACT`)가 추출된 경우
      `Fact.occurred_at`을 함께 채워 데이터 일관성을 높인다.
    - 파생 Event(`EVIDENCE_DERIVED` / `STATEMENT_EXTRACTED`)는 최신 Fact 집합으로부터 재구축하여
      수정·반려된 Fact의 유령 일정이 남지 않도록 보장한다 (T09, T10, T11, T13).

    Args:
        db: 데이터베이스 세션.
        case_id: 사건 ID.
        dry_run: True이면 DB를 변경하지 않고 생성 예정 Event 요약만 반환.

    Returns:
        Dict[str, Any]: 생성·보존·삭제된 Event 통계 및 미리보기.
    """
    all_facts = db.query(Fact).filter_by(case_id=case_id).all()

    # Fact.occurred_at이 비어 있는 경우 본문에서 검증된 첫 번째 날짜로 보강
    if not dry_run:
        from ai_legal_helper.case_intelligence.conflict_detector import extract_dates_with_validation

        for f in all_facts:
            if not f.occurred_at and f.statement:
                v_dates, inv_dates, _roles = extract_dates_with_validation(f.statement)
                if v_dates and not inv_dates:
                    f.occurred_at = v_dates[0]

    derived_events = build_timeline_from_facts(all_facts)

    existing_events = db.query(Event).filter_by(case_id=case_id).all()
    manual_events: List[Event] = []
    derived_existing_events: List[Event] = []

    for ev in existing_events:
        has_fact_refs = bool(ev.related_fact_ids)
        if (ev.source_type or "MANUAL") == "MANUAL" and not has_fact_refs:
            manual_events.append(ev)
        else:
            derived_existing_events.append(ev)

    if not dry_run:
        for old_ev in derived_existing_events:
            db.delete(old_ev)
        db.flush()
        for new_ev in derived_events:
            new_ev.case_id = case_id
            db.add(new_ev)
        db.flush()

    return {
        "derived_events_count": len(derived_events),
        "preserved_manual_count": len(manual_events),
        "replaced_derived_count": len(derived_existing_events),
        "events_preview": [
            {
                "event_date": e.event_date,
                "event_type": e.event_type,
                "occurrence_status": e.occurrence_status,
                "title": e.title,
                "related_fact_ids": e.related_fact_ids,
            }
            for e in derived_events
        ],
    }


def synchronize_case_entities(
    db: Session,
    case_id: str,
    dry_run: bool = False,
    queue_graph_sync: bool = False,
) -> Dict[str, Any]:
    """사건의 Fact를 기반으로 Party와 Event(Timeline)를 단일 트랜잭션 흐름 안에서 일괄 동기화한다.

    Args:
        db: 데이터베이스 세션.
        case_id: 사건 ID.
        dry_run: True이면 DB 변경 없이 미리보기 결과만 반환.
        queue_graph_sync: True이면 동기화 후 Neo4j 그래프 동기화 태스크를 큐에 등록.

    Returns:
        Dict[str, Any]: 당사자 및 타임라인 동기화 결과 요약.
    """
    party_res = synchronize_case_parties(db, case_id, dry_run=dry_run)
    timeline_res = synchronize_case_timeline(db, case_id, dry_run=dry_run)

    if not dry_run and queue_graph_sync:
        from ai_legal_helper.database.graph_sync_worker import queue_sync_task

        queue_sync_task(db, case_id)

    return {
        "case_id": case_id,
        "dry_run": dry_run,
        "parties": party_res,
        "timeline": timeline_res,
    }


def rebuild_case_entities(
    db: Session,
    case_id: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """기존 사건의 Fact 및 승인된 EvidenceClaim을 재스캔하여 누락된 Parties와 Timeline을 복구(Backfill)한다.

    [복구 원칙 (P1)]
    - 원본 EvidenceDocument, EvidenceSpan, EvidenceClaim, EvidenceReview, 수동 입력 데이터는 절대 삭제하지 않는다.
    - 승인(`APPROVED`/`EDITED`)된 EvidenceClaim 중 아직 Fact로 생성되지 않은 항목이 있으면 먼저 Fact 및 SUPPORTS 링크를 보완한다.
    - 이후 `synchronize_case_entities`를 호출하여 Parties와 Timeline(Event)을 재구축하고 Neo4j 동기화 큐에 등록한다.
    - 기본적으로 `dry_run=True`로 미리보기를 제공하며, `dry_run=False`일 때 실제 커밋을 수행한다.

    Args:
        db: 데이터베이스 세션.
        case_id: 복구 대상 사건 ID.
        dry_run: True(기본값)이면 미리보기만 반환하고, False이면 실제 DB에 반영 후 커밋.

    Returns:
        Dict[str, Any]: 복구 전후 건수 및 상세 내역.
    """
    case = db.query(Case).filter_by(id=case_id).first()
    if not case:
        raise ValueError(f"Case {case_id} not found.")

    before_facts_count = db.query(Fact).filter_by(case_id=case_id).count()
    before_parties_count = db.query(Party).filter_by(case_id=case_id).count()
    before_events_count = db.query(Event).filter_by(case_id=case_id).count()

    # 승인된 EvidenceClaim 중 Fact가 누락된 경우 보완 확인
    approved_claims = (
        db.query(EvidenceClaim)
        .filter(
            EvidenceClaim.case_id == case_id,
            EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
        )
        .all()
    )
    existing_facts = db.query(Fact).filter_by(case_id=case_id).all()
    facts_by_norm = {
        "".join((f.statement or "").split()): f for f in existing_facts if f.statement
    }

    backfilled_facts: List[str] = []
    for claim in approved_claims:
        norm_stmt = "".join((claim.statement or "").split())
        if not norm_stmt:
            continue
        if norm_stmt not in facts_by_norm:
            backfilled_facts.append(claim.statement)
            if not dry_run:
                from ai_legal_helper.case_intelligence.evidence_manager import derive_fact_trust_status

                ver_status, src_type = derive_fact_trust_status(claim.assertion_status)
                new_fact = Fact(
                    case_id=case_id,
                    statement=claim.statement,
                    fact_type=claim.claim_type,
                    confidence=claim.confidence,
                    source_type=src_type,
                    source_ref=claim.evidence_id,
                    verification_status=ver_status,
                )
                db.add(new_fact)
                db.flush()
                facts_by_norm[norm_stmt] = new_fact
                db.add(
                    EvidenceLink(
                        evidence_id=claim.evidence_id,
                        claim_id=claim.id,
                        target_type="FACT",
                        target_id=new_fact.id,
                        link_type="SUPPORTS",
                    )
                )

    sync_res = synchronize_case_entities(
        db=db,
        case_id=case_id,
        dry_run=dry_run,
        queue_graph_sync=not dry_run,
    )

    if not dry_run:
        db.commit()

    after_facts_count = (
        db.query(Fact).filter_by(case_id=case_id).count()
        if not dry_run
        else before_facts_count + len(backfilled_facts)
    )
    after_parties_count = (
        db.query(Party).filter_by(case_id=case_id).count()
        if not dry_run
        else sync_res["parties"]["total_derived"] + len(sync_res["parties"]["preserved_manual"])
    )
    after_events_count = (
        db.query(Event).filter_by(case_id=case_id).count()
        if not dry_run
        else sync_res["timeline"]["derived_events_count"] + sync_res["timeline"]["preserved_manual_count"]
    )

    return {
        "case_id": case_id,
        "dry_run": dry_run,
        "before": {
            "facts": before_facts_count,
            "parties": before_parties_count,
            "events": before_events_count,
        },
        "after": {
            "facts": after_facts_count,
            "parties": after_parties_count,
            "events": after_events_count,
        },
        "backfilled_facts": backfilled_facts,
        "parties_sync": sync_res["parties"],
        "timeline_sync": sync_res["timeline"],
    }
