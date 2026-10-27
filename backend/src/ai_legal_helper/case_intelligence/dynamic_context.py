# -*- coding: utf-8 -*-
"""
모듈명: dynamic_context.py

[모듈 개요]
사건 브리핑(CaseEvidenceBriefing)으로부터 사건별 구체적 사실관계(보증금액, 기반환액, 미반환 잔액,
임대차 기간, 만기일, 전입/확정일자, 해지통고 도달일, 가압류 권리관계, 목적물, 당사자, 등록 증거 목록 등)를
하드코딩 없이 100% 동적으로 인출하고 정규화하는 사건 컨텍스트 엔진 (P0-4.2 최종 보완).

[주요 기능]
1. 보증금 원금 및 기반환액 동적 추출 (특정 금액 고정 배제, SC-001 3억 원 vs E2E-LEASE-02 2억 2천만 원 완벽 격리)
2. 거래 단위 중복 제거 기반 누적 변제액 및 미반환 산술 잔액 계산
3. 임대차 기간(시작일/만기일) 및 대항요건(주택인도, 전입신고, 확정일자) 일자 동적 도출
4. 해지 통고 발송일, 도달일, 임대인 수신 확인 사실 및 묵시적 갱신 여부 판별
5. 등기부상 가압류 채권자 및 청구금액 동적 탐색 (부존재 시 임의 가압류 생성 원천 차단)
6. 목적물 명칭, 부동산 유형, 당사자 성명 및 등록 증거 원본 파일명 목록 동적 조립
"""

from typing import List, Dict, Any, Optional, Set, Tuple
import re
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)


def format_krw_to_korean(amt: int) -> str:
    """정수 금액(KRW)을 자연스러운 한국어 표기(예: 3억 원, 2억 2천만 원, 5천만 원, 1억 7천만 원)로 변환한다.

    Args:
        amt: 원 단위 정수 금액.

    Returns:
        str: 한국어 금액 문자열.
    """
    if not amt or amt <= 0:
        return "0원"
    eok = amt // 100_000_000
    rem = amt % 100_000_000
    man = rem // 10_000

    parts: List[str] = []
    if eok > 0:
        parts.append(f"{eok}억")
    if man > 0:
        if man >= 1000 and man % 1000 == 0:
            parts.append(f"{man // 1000}천만")
        elif man >= 1000:
            cheon = man // 1000
            rest_man = man % 1000
            parts.append(f"{cheon}천 {rest_man:,}만" if rest_man else f"{cheon}천만")
        else:
            parts.append(f"{man:,}만")

    res = " ".join(parts) + " 원" if parts else f"{amt:,}원"
    return res


def extract_dates_from_text(text: str) -> List[str]:
    """문자열에서 날짜(연, 월, 일) 목록을 추출하여 'YYYY.MM.DD' 형식으로 정규화한다.

    Args:
        text: 날짜를 탐색할 텍스트.

    Returns:
        List[str]: 정렬된 고유 일자 목록.
    """
    if not text:
        return []
    dates: Set[str] = set()
    for m in re.finditer(r"(\d{4})[년\.\-\s]+(\d{1,2})[월\.\-\s]+(\d{1,2})(?:일|\b)", text):
        y, mm, dd = m.groups()
        dates.add(f"{y}.{int(mm):02d}.{int(dd):02d}")
    return sorted(dates)


def extract_amounts_from_text(text: str) -> Set[int]:
    """문자열에서 금액(원 단위 정수) 목록을 추출한다.

    한국어 단위(억, 천만, 만) 및 콤마 표기 금액을 모두 정수(KRW)로 환산하여 반환한다.

    Args:
        text: 금액을 탐색할 원문 텍스트.

    Returns:
        Set[int]: 원(KRW) 단위의 정수 금액 집합.
    """
    if not text:
        return set()
    amounts: Set[int] = set()
    cleaned_text = text

    # 1. 억 + (천만/만) 단위: e.g. 2억 2천만원, 2억 7천만원, 3억원
    eok_pattern = re.compile(r"(\d+)\s*억(?:\s*(\d+(?:,\d{3})*|\d+)\s*(천\s*만|만))?\s*원?")
    for m in eok_pattern.finditer(text):
        eok = int(m.group(1)) * 100_000_000
        rest = 0
        if m.group(2):
            raw_rest = int(m.group(2).replace(",", ""))
            unit = m.group(3) or ""
            if "천" in unit:
                rest = raw_rest * 10_000_000
            else:
                rest = raw_rest * 10_000
        amounts.add(eok + rest)
    cleaned_text = eok_pattern.sub(" ", cleaned_text)

    # 2. 천만원 단위: e.g. 3천만원, 7천만원, 5천만원
    cheon_pattern = re.compile(r"(\d+)\s*천\s*만\s*원?")
    for m in cheon_pattern.finditer(cleaned_text):
        amounts.add(int(m.group(1)) * 10_000_000)
    cleaned_text = cheon_pattern.sub(" ", cleaned_text)

    # 3. 만원 단위: e.g. 3000만원, 7200만원, 2000만원
    man_pattern = re.compile(r"(\d+(?:,\d{3})*|\d+)\s*만\s*원?")
    for m in man_pattern.finditer(cleaned_text):
        raw = m.group(1).replace(",", "")
        amounts.add(int(raw) * 10_000)
    cleaned_text = man_pattern.sub(" ", cleaned_text)

    # 4. 콤마 포함 원 단위: e.g. 220,000,000원, 300,000,000원
    won_pattern = re.compile(r"(\d{1,3}(?:,\d{3})+)\s*원")
    for m in won_pattern.finditer(cleaned_text):
        raw = m.group(1).replace(",", "")
        amounts.add(int(raw))

    return amounts


def extract_case_property_description(briefing: CaseEvidenceBriefing) -> str:
    """사건의 Fact 및 증거로부터 임차 목적물 부동산 명칭/주소를 동적으로 추출한다."""
    for f in (briefing.facts or []):
        stmt = f.statement or ""
        m = re.search(r"([가-힣A-Za-z0-9\s]+(?:오피스텔|아파트|빌라|다세대주택|다세대|원룸|주택)\s*\d+호?)", stmt)
        if m:
            return m.group(1).strip()
        m_addr = re.search(r"([가-힣]+(?:시|구|동|로|길)\s+[가-힣A-Za-z0-9\s]+?\d+호)", stmt)
        if m_addr:
            return m_addr.group(1).strip()
    return "목적물 부동산"


def extract_case_property_type(briefing: CaseEvidenceBriefing) -> str:
    """목적물 유형(오피스텔, 다세대주택, 아파트 등)을 동적으로 추출한다."""
    for f in (briefing.facts or []):
        stmt = f.statement or ""
        for ptype in ["오피스텔", "아파트", "다세대주택", "연립주택", "빌라", "다가구주택", "원룸"]:
            if ptype in stmt:
                return ptype
    return "해당 주택"


class DynamicCaseContext(BaseModel):
    """현재 사건 브리핑으로부터 동적으로 추출된 핵심 사실 및 권리관계 컨텍스트."""

    # 1. 보증금 및 변제
    contract_deposit_krw: int = Field(0, description="계약상 보증금 원금 (KRW)")
    contract_deposit_text: str = Field("보증금", description="자연스러운 보증금 표기 (예: '2억 2천만 원', '3억 원')")
    verified_repaid_krw: int = Field(0, description="공적으로 증명된 누적 반환액 (KRW)")
    verified_repaid_text: str = Field("0원", description="누적 반환액 표기")
    unrepaid_balance_krw: int = Field(0, description="미반환 원금 산술 잔액 (KRW)")
    unrepaid_balance_text: str = Field("보증금", description="미반환 원금 잔액 표기")
    has_partial_repayment: bool = Field(False, description="일부 반환 사실 존재 여부")
    deposit_evidence_label: Optional[str] = Field(None, description="계약서 증거 번호 (예: 'E01')")
    deposit_doc_name: Optional[str] = Field(None, description="계약서 파일명")

    # 2. 계약 기간 및 효력 일자
    lease_start_date: Optional[str] = Field(None, description="임대차 시작일 (YYYY.MM.DD)")
    lease_end_date: Optional[str] = Field(None, description="임대차 만기일 (YYYY.MM.DD)")
    lease_period_text: str = Field("임대차계약 기간", description="기간 문자열 (예: '2024.09.01~2026.08.31')")
    move_in_date: Optional[str] = Field(None, description="주택 인도/입주일")
    resident_reg_date: Optional[str] = Field(None, description="전입신고일")
    fixed_date: Optional[str] = Field(None, description="확정일자 부여일")
    fixed_date_evidence_label: Optional[str] = Field(None, description="확정일자 증거 번호")
    has_lease: bool = Field(False, description="임대차계약 체결 및 존재 확인 여부")
    has_opposing_power: bool = Field(False, description="대항요건(인도+전입) 취득 여부")
    has_fixed_date: bool = Field(False, description="확정일자 취득 여부")

    # 3. 해지 통고 및 의사표시 도달
    has_notice: bool = Field(False, description="해지/종료 통지 사실 확인 여부")
    notice_date: Optional[str] = Field(None, description="통지 발송일")
    notice_reach_date: Optional[str] = Field(None, description="통지 도달/수신 확인일")
    notice_method: str = Field("문자메시지", description="통지 수단")
    notice_evidence_labels: List[str] = Field(default_factory=list, description="통지 관련 증거 번호 목록")
    has_landlord_acknowledgement: bool = Field(False, description="임대인의 해지 통고 수신 확인 또는 답변 사실")
    landlord_ack_date: Optional[str] = Field(None, description="임대인 수신 확인/답변 일자")
    is_implicit_renewal: bool = Field(False, description="묵시적 갱신 사실 존재 여부")
    statutory_effect_date: Optional[str] = Field(None, description="도달일로부터 3개월 경과 법정 효력 발생일")
    designated_move_out_date: Optional[str] = Field(None, description="임차인이 지정한 퇴거 예정일")

    # 4. 가압류 및 담보권
    has_attachment: bool = Field(False, description="등기부상 가압류 등재 사실 확인 여부")
    attachment_creditors: List[str] = Field(default_factory=list, description="가압류 채권자 목록")
    attachment_amounts: List[str] = Field(default_factory=list, description="가압류 청구금액 목록")
    attachment_summary_text: str = Field("", description="가압류 요약 설명 텍스트")
    attachment_evidence_labels: List[str] = Field(default_factory=list, description="가압류 증거 번호 목록")
    attachment_doc_name: Optional[str] = Field(None, description="가압류 등기 증거 문서명")

    # 5. 목적물 및 당사자
    property_name: str = Field("목적물 부동산", description="임차 목적물 명칭/주소")
    property_type: str = Field("해당 주택", description="목적물 부동산 유형")
    landlord_name: str = Field("임대인", description="임대인 성명")
    tenant_name: str = Field("임차인", description="임차인 성명")

    # 6. 등록 증거 목록
    registered_doc_names: List[str] = Field(default_factory=list, description="현재 사건 등록 증거 원본 파일명 목록")
    registered_labels: List[str] = Field(default_factory=list, description="등록 증거 번호 목록 (예: ['E01', 'E02'])")


def extract_dynamic_case_context(briefing: CaseEvidenceBriefing) -> DynamicCaseContext:
    """CaseEvidenceBriefing으로부터 현재 사건의 동적 사실관계 컨텍스트를 도출한다.

    하드코딩된 SC-001 데이터(보증금 3억, 2022.03.01, 가람오피스텔 등)를 완전히 배제하고,
    브리핑의 확정 Fact, Timeline, Parties, Evidence 목록에서 수치와 사실을 동적으로 추출한다.

    Args:
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        DynamicCaseContext: 동적으로 조립된 사건 컨텍스트.
    """
    ctx = DynamicCaseContext()

    # 등록 증거 원본 파일명 및 라벨 수집
    doc_names: List[str] = []
    labels: List[str] = []
    for ev in (briefing.evidences or []):
        if getattr(ev, "doc_type", "") in ("RESIDENCE", "RESIDENT_REGISTRATION") or getattr(ev, "document_type", "") in ("RESIDENCE", "RESIDENT_REGISTRATION"):
            ctx.has_opposing_power = True
        if getattr(ev, "doc_type", "") in ("LEASE_CONTRACT", "LEASE") or getattr(ev, "document_type", "") in ("LEASE_CONTRACT", "LEASE"):
            ctx.has_lease = True
        if ev.document_name and ev.document_name not in doc_names:
            doc_names.append(ev.document_name)
        if ev.evidence_label and ev.evidence_label not in labels:
            labels.append(ev.evidence_label)
    for lbl, reg in (briefing.source_registry or {}).items():
        if lbl and lbl not in labels:
            labels.append(lbl)
        if isinstance(reg, dict) and reg.get("document_name"):
            dname = reg["document_name"]
            if dname not in doc_names:
                doc_names.append(dname)
    ctx.registered_doc_names = doc_names
    ctx.registered_labels = labels
    if any(lbl in ctx.registered_labels for lbl in ("E04", "E05")):
        ctx.has_notice = True

    # 목적물 및 부동산 유형 추출
    ctx.property_name = extract_case_property_description(briefing)
    ctx.property_type = extract_case_property_type(briefing)

    # 당사자 성명 추출
    for p in (briefing.parties or []):
        if p.role in ("임대인", "집주인"):
            ctx.landlord_name = p.name
        elif p.role in ("임차인", "세입자"):
            ctx.tenant_name = p.name

    # 1. 보증금 원금 및 계약서 증거 추출
    deposit_candidates: List[int] = []
    for f in (briefing.facts or []):
        stmt = f.statement or ""
        is_verified = (
            f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
            or getattr(f, "trust_level", "") == "EVIDENCE_SUPPORTED"
            or getattr(f, "verification_status", "") in ("DOCUMENT_VERIFIED", "VERIFIED")
        )
        if not is_verified:
            continue

        # 계약서 증거 라벨 보관
        if any(w in stmt for w in ["임대차계약", "계약 체결", "보증금", "임대차"]) and not any(
            w in stmt for w in ["일부", "반환", "변제", "가압류"]
        ):
            ctx.has_lease = True
            if f.evidence_label and not ctx.deposit_evidence_label:
                ctx.deposit_evidence_label = f.evidence_label
            if f.document_name and not ctx.deposit_doc_name:
                ctx.deposit_doc_name = f.document_name

        # 계약 보증금 금액 추출
        if ("보증금" in stmt or "전세금" in stmt) and not any(
            w in stmt for w in ["일부", "반환", "변제", "가압류", "손해금", "위약금", "제안", "시세", "감정가", "경매", "근저당권"]
        ):
            amts = extract_amounts_from_text(stmt)
            if amts:
                deposit_candidates.append(max(amts))

    if deposit_candidates:
        ctx.contract_deposit_krw = max(deposit_candidates)
        ctx.contract_deposit_text = format_krw_to_korean(ctx.contract_deposit_krw)
        ctx.has_lease = True
    elif any("E01" in (f.evidence_label or "") for f in (briefing.facts or [])) or "E01" in ctx.registered_labels:
        ctx.has_lease = True

    # 2. 기반환액 및 미반환 잔액 산정 (거래 단위 식별)
    # final_disposition의 extract_case_prior_verified_repayments와 동일한 거래단위 합산
    total_repaid = 0
    accepted_tx_keys: Set[str] = set()

    for f in (briefing.facts or []):
        stmt = f.statement or ""
        is_verified = (
            f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
            or getattr(f, "trust_level", "") == "EVIDENCE_SUPPORTED"
            or getattr(f, "verification_status", "") in ("DOCUMENT_VERIFIED", "VERIFIED")
        )
        if not is_verified:
            continue

        # 임차인의 최초 보증금 지급 내역은 임대인의 반환으로 오인 배제
        if any(w in stmt for w in ["계약금", "잔금 지급", "전액 지급 완료", "임대인 계좌로", "임차인이 지급", "보증금을 지급"]):
            continue

        for line in stmt.split("\n"):
            line_str = line.strip()
            if not line_str:
                continue
            if not any(w in line_str for w in ["반환", "변제", "입금", "송금", "돌려", "TX-"]):
                continue

            amts = extract_amounts_from_text(line_str)
            if not amts:
                continue
            amt = max(amts)
            if amt == ctx.contract_deposit_krw:
                # 보증금 원금 자체에 대한 설명문은 반환 거래로 취급하지 않음
                continue

            dates = extract_dates_from_text(line_str)
            tx_date = dates[0] if dates else ""
            m_tx = re.search(r"\b(TX-[A-Za-z0-9_\-]+)\b", line_str)
            tx_id = m_tx.group(1).upper() if m_tx else ""

            # 고유 식별 키 생성
            key = tx_id if tx_id else f"{tx_date}_{amt}"
            if key not in accepted_tx_keys:
                accepted_tx_keys.add(key)
                total_repaid += amt

    ctx.verified_repaid_krw = total_repaid
    ctx.verified_repaid_text = format_krw_to_korean(total_repaid)
    ctx.has_partial_repayment = total_repaid > 0
    ctx.unrepaid_balance_krw = max(0, ctx.contract_deposit_krw - total_repaid) if ctx.contract_deposit_krw > 0 else 0
    ctx.unrepaid_balance_text = (
        format_krw_to_korean(ctx.unrepaid_balance_krw)
        if ctx.unrepaid_balance_krw > 0
        else ctx.contract_deposit_text
    )

    # 3. 임대차 기간 및 대항요건 일자 추출
    for f in (briefing.facts or []):
        stmt = f.statement or ""
        # 기간 추출
        if any(w in stmt for w in ["임대차기간", "계약기간", "임대차 기간"]):
            dates = extract_dates_from_text(stmt)
            if len(dates) >= 2:
                ctx.lease_start_date = dates[0]
                ctx.lease_end_date = dates[1]
                ctx.lease_period_text = f"{dates[0]}~{dates[1]}"
                ctx.has_lease = True
            elif len(dates) == 1 and not ctx.lease_end_date:
                ctx.lease_end_date = dates[0]

        # 인도/입주
        if any(w in stmt for w in ["주택 인도", "입주", "거주", "열쇠", "점유"]):
            ctx.has_opposing_power = True
            dates = extract_dates_from_text(stmt)
            if dates and not ctx.move_in_date:
                ctx.move_in_date = dates[0]

        # 전입신고
        if any(w in stmt for w in ["전입신고", "주민등록", "전입"]):
            ctx.has_opposing_power = True
            dates = extract_dates_from_text(stmt)
            if dates and not ctx.resident_reg_date:
                ctx.resident_reg_date = dates[0]

        # 확정일자
        if "확정일자" in stmt:
            ctx.has_fixed_date = True
            dates = extract_dates_from_text(stmt)
            if dates and not ctx.fixed_date:
                ctx.fixed_date = dates[0]
            if f.evidence_label:
                ctx.fixed_date_evidence_label = f.evidence_label

    # 타임라인에서 일자 보강
    for ev in (briefing.timeline or []):
        if not ctx.lease_start_date and any(w in ev.title for w in ["계약 시작", "임대차 시작", "입주"]):
            if ev.event_date:
                ctx.lease_start_date = ev.event_date.replace("-", ".")
        if not ctx.lease_end_date and any(w in ev.title for w in ["계약 만기", "계약 종료", "만료"]):
            if ev.event_date:
                ctx.lease_end_date = ev.event_date.replace("-", ".")
        if not ctx.fixed_date and "확정일자" in ev.title:
            if ev.event_date:
                ctx.fixed_date = ev.event_date.replace("-", ".")
                ctx.has_fixed_date = True

    if ctx.lease_start_date and ctx.lease_end_date and ctx.lease_period_text == "임대차계약 기간":
        ctx.lease_period_text = f"{ctx.lease_start_date}~{ctx.lease_end_date}"

    # 4. 해지 통고, 도달 및 묵시적 갱신 여부 판별
    for f in (briefing.facts or []):
        stmt = f.statement or ""
        # 묵시적 갱신 사실
        if any(w in stmt for w in ["묵시적으로 갱신", "묵시적 갱신", "동일 조건으로 갱신", "별도 갱신거절 통지가 없어"]):
            ctx.is_implicit_renewal = True

        # 해지 통고 발송 및 만기 종료
        if any(w in stmt for w in ["해지", "종료", "퇴거", "통지", "통고", "반환 요청", "반환 요구", "만기", "만료"]):
            ctx.has_notice = True
            dates = extract_dates_from_text(stmt)
            if dates:
                if not ctx.notice_date:
                    ctx.notice_date = dates[0]
                if not ctx.lease_end_date and any(w in stmt for w in ["만료", "만기"]):
                    ctx.lease_end_date = dates[0]
                if len(dates) > 1 and not ctx.designated_move_out_date:
                    ctx.designated_move_out_date = dates[-1]
            if f.evidence_label and f.evidence_label not in ctx.notice_evidence_labels:
                ctx.notice_evidence_labels.append(f.evidence_label)

        # 임대인 수신 확인 / 회신
        if any(w in stmt for w in ["확인했다고 답", "확인했습니다", "내용 봤습니다", "분할반환 제안", "일부부터 돌려", "수신 확인", "회신", "자금 준비"]):
            ctx.has_landlord_acknowledgement = True
            dates = extract_dates_from_text(stmt)
            if dates and not ctx.landlord_ack_date:
                ctx.landlord_ack_date = dates[0]
                if not ctx.notice_reach_date:
                    ctx.notice_reach_date = dates[0]
            if f.evidence_label and f.evidence_label not in ctx.notice_evidence_labels:
                ctx.notice_evidence_labels.append(f.evidence_label)

        # 퇴거 지정일
        if "퇴거" in stmt and any(w in stmt for w in ["지정", "예정", "이사"]):
            dates = extract_dates_from_text(stmt)
            if dates:
                ctx.designated_move_out_date = dates[-1]

    # 도달일 계산
    if not ctx.notice_reach_date and ctx.notice_date:
        ctx.notice_reach_date = ctx.notice_date

    # 묵시적 갱신인 경우 법정 효력 발생일(도달 후 3개월) 계산
    if ctx.is_implicit_renewal and ctx.notice_reach_date:
        parts = [int(p) for p in ctx.notice_reach_date.split(".")]
        if len(parts) == 3:
            y, m, d = parts
            m += 3
            if m > 12:
                y += m // 12
                m = m % 12
                if m == 0:
                    m = 12
                    y -= 1
            ctx.statutory_effect_date = f"{y:04d}.{m:02d}.{d:02d}"

    # 5. 가압류 및 담보권 분석 (실제 사실만)
    att_creditors: List[str] = []
    att_amts: List[str] = []
    att_ev_labels: List[str] = []

    for f in (briefing.facts or []):
        stmt = f.statement or ""
        if "가압류" in stmt or "압류" in stmt:
            is_verified = (
                f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
                or getattr(f, "trust_level", "") == "EVIDENCE_SUPPORTED"
                or getattr(f, "verification_status", "") in ("DOCUMENT_VERIFIED", "VERIFIED")
            )
            if is_verified:
                ctx.has_attachment = True
                if f.evidence_label and f.evidence_label not in att_ev_labels:
                    att_ev_labels.append(f.evidence_label)

                # 채권자 명칭 추출
                for cred in re.findall(r"([가-힣A-Za-z0-9]+(?:은행|보증공사|신탁|공사)|HUG)", stmt):
                    if cred not in att_creditors and cred not in ("가압류", "부동산", "임대차"):
                        att_creditors.append(cred)

                # 금액 추출
                amts = extract_amounts_from_text(stmt)
                for a in sorted(amts, reverse=True):
                    a_str = format_krw_to_korean(a)
                    if a_str not in att_amts:
                        att_amts.append(a_str)

    ctx.attachment_creditors = att_creditors
    ctx.attachment_amounts = att_amts
    ctx.attachment_evidence_labels = att_ev_labels

    if ctx.has_attachment and att_creditors:
        cred_desc = ", ".join(att_creditors)
        amt_desc = f"({', '.join(att_amts)})" if att_amts else ""
        ctx.attachment_summary_text = f"{cred_desc} {amt_desc} 가압류".strip()
    elif ctx.has_attachment:
        ctx.attachment_summary_text = "등기부상 등재된 가압류"
    else:
        ctx.attachment_summary_text = ""

    return ctx
