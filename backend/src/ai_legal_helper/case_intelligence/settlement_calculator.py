# -*- coding: utf-8 -*-
"""
모듈명: settlement_calculator.py

[모듈 개요]
사건 브리핑(CaseEvidenceBriefing)의 검증된 Fact, Evidence, Timeline, Parties로부터
계약 보증금 원금, 누적 반환액, 미반환 잔액, 해지 통지 및 도달 상태, 권리순위 선후관계,
목적물 및 당사자 정보를 일관되게 추출·계산하는 단일 원천 공통 유틸리티 (P0-4.2 최종 보완 v3.0).

[설계 원칙]
1. 단일 원천(Single Source of Truth):
   - 새로운 Context 모델(DynamicCaseContext)이나 별도 계산 엔진을 증설하지 않고,
     기존 P0-3.1에서 검증된 반환 거래 계산 로직과 정규식을 재사용한다.
2. 순환 참조(Circular Import) 원천 방지:
   - final_disposition과 issue_verifier 간의 상호 참조를 방지하기 위해
     case_intelligence 계층에 공통 함수를 배치하여 워크플로우 전반이 동일한 결과를 공유한다.
3. 법률적 무결성:
   - 통지 도달·계약 종료·권리순위에 EVIDENCE_SUPPORTED, CORROBORATED 등 엄격히 검증된 사실만 사용한다.
   - 통지 발송일과 상대방 도달일을 엄격히 분리하고, 도달 미확인 또는 다툼 시 법정 해지 효력일을 미확정으로 유지한다.
   - 표준 라이브러리(calendar)를 활용하여 역(曆)에 의한 월말 3개월 계산(달력 연산)을 적용한다.
   - 대항요건(인도+전입에 따른 익일 0시 효력)과 확정일자 부여 시점을 명확히 구분하여 우선변제권 기준일을 산출한다.
   - 보증금 후보 충돌 시 임의로 최대 금액을 자동 선택하지 않는다.
   - 특정 증거번호(E01, E03 등) 및 특정인 명칭의 하드코딩을 일체 배제한다.
"""

from typing import List, Dict, Any, Optional, Set, Tuple
import re
import datetime
import calendar

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing, FactItemBrief
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)


def is_fact_strictly_verified(f: Any, briefing: Optional[CaseEvidenceBriefing] = None) -> bool:
    """FactItemBrief가 반대 주장·미확인·다툼 없이 엄격히 검증된 공적 사실인지 검사한다.

    반대 주장(DISPUTED), 당사자 일방 진술(PARTY_ALLEGED), 증거 불충분(EVIDENCE_INCOMPLETE),
    또는 briefing.genuinely_disputed 사실은 배제하여 미검증 사실이 확정 판단에 진입하지 못하도록 차단한다.

    Args:
        f: 검사할 사실 객체 (FactItemBrief 또는 유사 모델).
        briefing: 사건 브리핑 객체 (선택).

    Returns:
        bool: 엄격하게 검증된 사실인 경우 True, 아니면 False.
    """
    if not f:
        return False
    status = getattr(f, "adjudication_status", "")
    if status in ("DISPUTED", "PARTY_ALLEGED", "EVIDENCE_INCOMPLETE", "UNVERIFIED", "CONTRADICTED"):
        return False
    trust = getattr(f, "trust_level", "")
    if trust in ("DISPUTED", "SUPERSEDED", "UNTRUSTED", "PARTY_ALLEGED"):
        return False

    # 사건 전체 실질적 다툼 사실(genuinely_disputed) 대조
    if briefing and getattr(briefing, "genuinely_disputed", None):
        fid = getattr(f, "fact_id", "")
        stmt = getattr(f, "statement", "")
        for d in briefing.genuinely_disputed:
            if hasattr(d, "fact_id") and d.fact_id == fid:
                return False
            if hasattr(d, "statement") and d.statement == stmt:
                return False

    return (
        status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
        or trust == "EVIDENCE_SUPPORTED"
        or getattr(f, "verification_status", "") in ("DOCUMENT_VERIFIED", "VERIFIED")
    )


def format_krw_to_korean(amt: int) -> str:
    """정수 금액(KRW)을 자연스러운 한국어 표기(예: 3억 원, 2억 2천만 원, 1억 7천만 원, 5천만 원)로 변환한다."""
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
    """문자열에서 날짜(연, 월, 일)를 정규식으로 탐색하여 'YYYY.MM.DD' 형식 목록으로 반환한다."""
    if not text:
        return []
    dates: Set[str] = set()
    for m in re.finditer(r"(\d{4})[년\.\-\s]+(\d{1,2})[월\.\-\s]+(\d{1,2})(?:일|\b|\.|\s|$)", text):
        y, mm, dd = m.groups()
        dates.add(f"{y}.{int(mm):02d}.{int(dd):02d}")
    return sorted(dates)


def extract_amounts_from_text(text: str) -> Set[int]:
    """문자열에서 금액(원 단위 정수) 목록을 추출한다."""
    if not text:
        return set()
    amounts: Set[int] = set()
    cleaned_text = text

    # 1. 억 + (천만/만) 단위
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

    # 2. 천만원 단위
    cheon_pattern = re.compile(r"(\d+)\s*천\s*만\s*원?")
    for m in cheon_pattern.finditer(cleaned_text):
        amounts.add(int(m.group(1)) * 10_000_000)
    cleaned_text = cheon_pattern.sub(" ", cleaned_text)

    # 3. 만원 단위
    man_pattern = re.compile(r"(\d+(?:,\d{3})*|\d+)\s*만\s*원?")
    for m in man_pattern.finditer(cleaned_text):
        raw = m.group(1).replace(",", "")
        amounts.add(int(raw) * 10_000)
    cleaned_text = man_pattern.sub(" ", cleaned_text)

    # 4. 콤마 포함 원 단위
    won_pattern = re.compile(r"(\d{1,3}(?:,\d{3})+)\s*원")
    for m in won_pattern.finditer(cleaned_text):
        raw = m.group(1).replace(",", "")
        amounts.add(int(raw))

    return amounts


def extract_case_contract_deposit(briefing: CaseEvidenceBriefing) -> int:
    """사건의 등록 증거 및 엄격히 검증된 Fact로부터 계약상 임대차 보증금 원금을 동적으로 인출한다.

    보증금 후보 간 상충·충돌이 발생할 경우 임의로 최대 금액을 자동 선택하지 않고,
    불확실성을 보존하기 위해 0원을 반환하여 확인 필요 상태로 유도한다.

    Args:
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        int: 추출된 보증금 정수 금액(KRW). 충돌 또는 확인 불가 시 0.
    """
    deposit_candidates = []
    # 1. 엄격히 검증된 Fact 중에서 계약 보증금 Fact 우선 탐색
    for f in (briefing.facts or []):
        if not is_fact_strictly_verified(f, briefing):
            continue
        stmt = f.statement or ""
        # 보증금 계약 원금 관련 사실 탐색 (분할변제 제안, 가압류, 반환금 등 명백히 배제)
        if ("보증금" in stmt or "전세금" in stmt) and not any(
            w in stmt for w in ["일부", "반환", "변제", "가압류", "손해금", "위약금", "제안", "시세", "감정가", "경매", "근저당권"]
        ):
            m = re.search(r"(?:보증금|전세금).*?(\d+(?:\s*억|\s*천만|\s*만|\s*원|,|\d)+)\s*원", stmt)
            if not m:
                m = re.search(r"(\d+(?:\s*억|\s*천만|\s*만|\s*원|,|\d)+)\s*원.*?(?:보증금|전세금)", stmt)
            if m:
                amts = extract_amounts_from_text(m.group(0))
            else:
                amts = extract_amounts_from_text(stmt)
            if amts:
                deposit_candidates.append(max(amts))

    if deposit_candidates:
        unique = sorted(list(set(deposit_candidates)))
        if len(unique) == 1:
            return unique[0]
        # 보증금 후보 충돌 시 최대 금액 자동 선택 제거: 상충 발생 시 단정 배제 (0원 반환하여 추가 확인 유도)
        logger.warning(f"[DEPOSIT_CONFLICT] Conflicting deposit candidates detected: {unique}. Refusing automatic max selection.")
        return 0

    # 2. 계약서 출처를 가진 Fact에서 계약 원금 재탐색 (검증된 Fact에 한함)
    step2_candidates = []
    for f in (briefing.facts or []):
        if not is_fact_strictly_verified(f, briefing):
            continue
        stmt = f.statement or ""
        if any(w in stmt for w in ["임대차계약", "계약 체결", "체결일"]) and ("보증금" in stmt or "전세금" in stmt):
            if not any(w in stmt for w in ["일부", "반환", "변제", "가압류", "손해금", "위약금"]):
                amts = extract_amounts_from_text(stmt)
                if amts:
                    step2_candidates.append(max(amts))

    if step2_candidates:
        unique2 = sorted(list(set(step2_candidates)))
        if len(unique2) == 1:
            return unique2[0]
        logger.warning(f"[DEPOSIT_CONFLICT] Conflicting step2 deposit candidates: {unique2}. Refusing automatic max selection.")
        return 0

    return 0


def extract_case_prior_verified_repayments(briefing: CaseEvidenceBriefing) -> Tuple[int, List[str]]:
    """사건에 이미 공적으로 입증·확정된 임대인의 보증금 반환(일부 또는 전액) 내역을 동적으로 합산한다.

    최초 계약금·잔금 지급(임차인 -> 임대인)과 임대인의 보증금 반환(임대인 -> 임차인)을
    엄격히 구분하고, 실제 반환 거래 단위(일자, 금액, 고유 거래번호, 계좌, 차수 등)로 식별하여
    중복 사본은 차단하고, 동일 문서 내 복수 거래 및 식별자가 구분되는 동시/동액 거래는 각각 합산한다.
    특정 임대인 이름 하드코딩 없이 동적 당사자 정보를 활용한다.

    Args:
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        Tuple[int, List[str]]: (합산된 반환액, 근거 출처 목록) 튜플.
    """
    total_repaid = 0
    repaid_sources: List[str] = []
    accepted_txs: List[Dict[str, Any]] = []

    # 동적 임대인 명칭 목록
    landlord_names = [
        p.name for p in (briefing.parties or [])
        if getattr(p, "role", "") in ("LANDLORD", "임대인", "LESSOR") and p.name
    ]
    landlord_terms = ["임대인", "집주인", "임대인측", "TX-"] + landlord_names

    for f in (briefing.facts or []):
        if not is_fact_strictly_verified(f, briefing):
            continue
        stmt = f.statement or ""
        doc_name = f.document_name or f.evidence_label or ""

        # 임차인의 최초 보증금 지급 내역은 임대인의 반환으로 오인 배제
        if any(w in stmt for w in ["계약금", "잔금 지급", "전액 지급 완료", "임대인 계좌로", "임차인이 지급", "보증금을 지급", "보증금 완납"]):
            if not any(w in stmt for w in ["반환", "변제", "돌려"]):
                continue

        # 계약 체결 자체 진술은 반환 거래로 취급하지 않음
        if any(w in stmt for w in ["임대차계약을 체결", "임대차계약 체결"]) and not any(w in stmt for w in ["반환", "변제", "입금", "송금"]):
            continue

        raw_lines = [ln.strip() for ln in stmt.splitlines() if ln.strip()]
        if not raw_lines:
            raw_lines = [stmt]

        for line_text in raw_lines:
            if any(w in line_text for w in ["임차인이 지급", "임대인 계좌로 송금하여 잔금", "잔금을 지급", "계약금을 지급"]):
                continue

            combined_text = f"{line_text} {doc_name}"

            is_repayment_stmt = any(
                w in line_text
                for w in [
                    "변제", "반환", "반환금", "입금 확인", "변제 확인",
                    "송금 반환", "일부 반환", "전액 반환", "전액 변제", "돌려주", "돌려받"
                ]
            ) or ("입금" in line_text and any(w in line_text for w in landlord_terms))

            if is_repayment_stmt:
                m = re.search(r"(\d+(?:\s*억|\s*천만|\s*만|\s*원|,|\d)+)\s*(?:원)?을?\s*(?:일부\s*|전액\s*)?(?:변제|반환|입금|돌려)", line_text)
                if m:
                    amts = extract_amounts_from_text(m.group(0))
                else:
                    amts = extract_amounts_from_text(line_text)
                if not amts:
                    continue
                amt = min(amts) if len(amts) > 1 else max(amts)
                if amt <= 0:
                    continue

                dates = extract_dates_from_text(line_text)
                tx_date = sorted(dates)[0] if dates else (str(getattr(f, "occurred_at", None) or ""))
                doc_ref = f.source_evidence_id or f.evidence_label or f.document_name or ""

                m_txid = re.search(r"(?:거래번호|승인번호|전문번호|관리번호|일련번호|tx[-_]?id|txid)[\s:]*([A-Za-z0-9_-]+)", combined_text, re.IGNORECASE)
                tx_id = m_txid.group(1).strip() if m_txid else None

                m_time = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", combined_text)
                if not m_time:
                    m_time = re.search(r"(\d{1,2}시\s*\d{1,2}분(?:\s*\d{1,2}초)?)", combined_text)
                tx_time = m_time.group(1).strip() if m_time else None

                m_ord = re.search(r"(\d+)\s*(?:차|회|번째)\s*(?:입금|변제|지급|반환|이체)?", combined_text)
                tx_ord = m_ord.group(1).strip() if m_ord else None

                m_acc = re.search(r"(?:계좌|계좌번호)[\s:]*([0-9-]+)", combined_text)
                tx_acc = m_acc.group(1).strip() if m_acc else None

                is_copy = any(w in combined_text for w in ["사본", "중복", "재발급", "동일 거래", "copy"])
                src = f.document_name or f.evidence_label or "확인된 증거"

                is_duplicate = False
                is_ambiguous = False

                for ex in accepted_txs:
                    if tx_id and ex.get("tx_id"):
                        if tx_id == ex["tx_id"]:
                            is_duplicate = True
                            break
                        else:
                            continue

                    if (is_copy or ex.get("is_copy")) and ex["amt"] == amt and (not tx_date or not ex.get("date") or ex["date"] == tx_date):
                        is_duplicate = True
                        break

                    if amt != ex["amt"]:
                        continue
                    if tx_date and ex.get("date") and tx_date != ex["date"]:
                        continue

                    if (tx_time and ex.get("tx_time") and tx_time != ex["tx_time"]) or                        (tx_ord and ex.get("tx_ord") and tx_ord != ex["tx_ord"]) or                        (tx_acc and ex.get("tx_acc") and tx_acc != ex["tx_acc"]):
                        continue

                    if doc_ref and ex.get("doc_ref") and doc_ref == ex["doc_ref"]:
                        is_duplicate = True
                        break

                    is_ambiguous = True
                    break

                if is_duplicate:
                    continue

                if is_ambiguous:
                    repaid_sources.append(
                        f"[보류] {amt:,}원 [{src}] (동일 일자·금액 거래 중복 의심 / 고유 거래번호 미확인으로 합산 보류)"
                    )
                    continue

                accepted_txs.append({
                    "amt": amt,
                    "date": tx_date,
                    "tx_id": tx_id,
                    "tx_time": tx_time,
                    "tx_ord": tx_ord,
                    "tx_acc": tx_acc,
                    "doc_ref": doc_ref,
                    "src": src,
                    "is_copy": is_copy,
                    "stmt": line_text,
                })
                total_repaid += amt
                ord_prefix = f"{tx_ord}차 " if tx_ord else ""
                id_suffix = f" (거래번호: {tx_id})" if tx_id else ""
                repaid_sources.append(f"{ord_prefix}{amt:,}원 [{src}]{id_suffix}")

    return total_repaid, repaid_sources


def calculate_three_months_expiry(reach_date_str: str) -> Optional[str]:
    """통지 도달일 기준으로 주택임대차보호법 제6조의2 제2항 및 민법 제157조, 제160조에 따른 3개월 경과일을 계산한다.

    역(曆)에 의한 계산 원칙에 따라, 도달일의 익월 3개월 후의 대응일로 만료하며,
    월말 도달 시(예: 1/31 도달 -> 4/30 만료, 3/31 도달 -> 6/30 만료) 해당 월의 말일을 정확히 산출한다.

    Args:
        reach_date_str: 'YYYY.MM.DD' 또는 'YYYY-MM-DD' 형식의 통지 도달 일자.

    Returns:
        Optional[str]: 'YYYY.MM.DD' 형식의 3개월 경과 효력 발생일자.
    """
    if not reach_date_str:
        return None
    cleaned = reach_date_str.replace("-", ".").strip()
    parts = cleaned.split(".")
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        target_month = m + 3
        target_year = y + (target_month - 1) // 12
        target_month = (target_month - 1) % 12 + 1
        max_days = calendar.monthrange(target_year, target_month)[1]
        target_day = min(d, max_days)
        return datetime.date(target_year, target_month, target_day).strftime("%Y.%m.%d")
    except Exception as e:
        logger.warning(f"Failed to calculate 3 months expiry for {reach_date_str}: {e}")
        return None


def evaluate_notice_status(briefing: CaseEvidenceBriefing) -> Dict[str, Any]:
    """사건 브리핑으로부터 엄격히 검증된 Fact만을 바탕으로 해지 통지의 발송, 도달, 묵시적 갱신 여부를 정밀 분석한다.

    반대 주장이나 다툼(DISPUTED)이 있는 경우 도달 확정을 엄격히 차단한다.

    Args:
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        Dict[str, Any]: 통지 분석 딕셔너리.
    """
    res: Dict[str, Any] = {
        "has_sent": False,
        "sent_date": None,
        "sent_evidence_labels": [],
        "has_reached": False,
        "reach_date": None,
        "reach_evidence_labels": [],
        "has_landlord_acknowledgement": False,
        "landlord_ack_date": None,
        "is_implicit_renewal": False,
        "statutory_effect_date": None,
        "designated_move_out_date": None,
        "notice_method": "통지",
    }

    # 1. 묵시적 갱신 사실 확인 (엄격히 검증된 사실만)
    for f in (briefing.facts or []):
        if not is_fact_strictly_verified(f, briefing):
            continue
        stmt = f.statement or ""
        if any(w in stmt for w in ["묵시적으로 갱신", "묵시적 갱신", "동일 조건으로 갱신", "별도 갱신거절 통지가 없어", "묵시적갱신"]):
            res["is_implicit_renewal"] = True

    # 2. 통지 발송 사실 분석 (엄격히 검증된 사실만)
    for f in (briefing.facts or []):
        if not is_fact_strictly_verified(f, briefing):
            continue
        stmt = f.statement or ""
        if (
            any(w in stmt for w in ["해지", "종료", "퇴거", "통지", "통고", "반환 요청", "반환 요구", "만기"])
            and any(w in stmt for w in ["발신", "통지", "통고", "요청", "전송", "보냈", "문자", "메시지", "내용증명", "카카오톡", "알리고"])
            and not any(w in stmt for w in ["확인했다고", "수신 확인", "회신", "자금 준비"])
        ):
            res["has_sent"] = True
            dates = extract_dates_from_text(stmt)
            if dates and not res["sent_date"]:
                res["sent_date"] = dates[0]
            if f.evidence_label and f.evidence_label not in res["sent_evidence_labels"]:
                res["sent_evidence_labels"].append(f.evidence_label)
            if "문자" in stmt or "메시지" in stmt:
                res["notice_method"] = "문자메시지"
            elif "카카오톡" in stmt:
                res["notice_method"] = "카카오톡"
            elif "내용증명" in stmt:
                res["notice_method"] = "내용증명 우편"

    # 3. 도달 확인 및 임대인 수신 확인 분석 (다툼/반대 주장 존재 시 도달 확정 배제)
    has_disputed_reach = any(
        any(w in (f.statement or "") for w in ["도달 부인", "받은 적 없다", "수신하지 못함", "통지 못 받음", "도달하지 않음"])
        or (f.adjudication_status == "DISPUTED" and any(w in (f.statement or "") for w in ["도달", "수신", "문자", "통지"]))
        for f in (briefing.facts or [])
    )

    if not has_disputed_reach:
        for f in (briefing.facts or []):
            if not is_fact_strictly_verified(f, briefing):
                continue
            stmt = f.statement or ""
            is_reach = any(
                w in stmt
                for w in [
                    "도달", "수신", "확인했다고 답", "확인했습니다", "내용 봤습니다",
                    "분할반환 제안", "일부부터 돌려", "수신 확인", "회신", "답변", "배달증명", "배달완료"
                ]
            )
            if is_reach and any(w in stmt for w in ["해지", "종료", "통지", "통고", "문자", "메시지", "요청", "메시지를 발신하였다"]):
                res["has_reached"] = True
                dates = extract_dates_from_text(stmt)
                if dates and not res["reach_date"]:
                    res["reach_date"] = dates[0]
                if f.evidence_label and f.evidence_label not in res["reach_evidence_labels"]:
                    res["reach_evidence_labels"].append(f.evidence_label)

                if any(w in stmt for w in ["답변", "답", "회신", "확인했습니다", "분할반환 제안", "일부부터 돌려"]):
                    res["has_landlord_acknowledgement"] = True
                    if dates and not res["landlord_ack_date"]:
                        res["landlord_ack_date"] = dates[0]

            if "퇴거" in stmt and any(w in stmt for w in ["지정", "예정", "이사"]):
                dates = extract_dates_from_text(stmt)
                if dates and not res["designated_move_out_date"]:
                    res["designated_move_out_date"] = dates[-1]

    # 도달 확인 사실이 명시된 경우에만 법정 해지 효력일 계산
    if res["is_implicit_renewal"] and res["has_reached"] and res["reach_date"]:
        res["statutory_effect_date"] = calculate_three_months_expiry(res["reach_date"])

    return res


def evaluate_attachment_ranking(briefing: CaseEvidenceBriefing) -> Dict[str, Any]:
    """임차인의 대항요건 취득일(익일 0시 효력)과 확정일자 부여일을 각각 구분하여 등기부상 가압류와 정밀 비교한다.

    대항요건(주택 인도 + 주민등록 전입)과 확정일자는 별개의 법률 요건이므로,
    1. 대항요건 구비일: 전입일과 인도일 중 늦은 날
    2. 대항력 효력 발생 시점: 대항요건 구비 '익일(다음 날) 0시'
    3. 확정일자 부여일: 계약서 상 확정일자 부여일
    4. 우선변제권 효력 발생 시점: 대항력 발생 시점(익일 0시)과 확정일자 부여일 중 늦은 시점
    으로 구분하여 가압류 등기 접수일자와 대조한다. 미검증 Fact나 미확인 날짜는 확정에 반영하지 않는다.

    Args:
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        Dict[str, Any]: 권리순위 분석 딕셔너리.
    """
    res: Dict[str, Any] = {
        "has_attachment": False,
        "creditors": [],
        "amounts": [],
        "evidence_labels": [],
        "summary_text": "",
        "priority_status": "UNCERTAIN",  # "TENANT_SENIOR", "ATTACHMENT_SENIOR", "UNCERTAIN", "NO_ATTACHMENT"
        "tenant_opposing_date": None,           # 대항요건(전입/인도) 구비일
        "tenant_opposing_effective_date": None, # 대항력 발생 시점 (익일 0시)
        "tenant_fixed_date": None,              # 확정일자 부여일
        "tenant_priority_date": None,           # 우선변제권 효력 기준일
        "attachment_dates": [],
    }

    # 1. 임차인 대항요건(인도+전입) 및 확정일자 일자 탐색 (엄격 검증된 사실만 반영)
    move_in_dates: List[str] = []   # 주택 인도(점유/입주) 일자
    transfer_dates: List[str] = []  # 주민등록 전입신고 일자
    fixed_dates: List[str] = []     # 확정일자 부여일

    for f in (briefing.facts or []):
        if not is_fact_strictly_verified(f, briefing):
            continue
        stmt = f.statement or ""
        dates = extract_dates_from_text(stmt)
        if not dates:
            continue
        # (a) 주민등록 전입신고
        if any(w in stmt for w in ["전입신고", "주민등록", "전입"]):
            transfer_dates.extend(dates)
        # (b) 주택 인도 (점유/입주/열쇠)
        if any(w in stmt for w in ["주택 인도", "인도받", "점유", "입주", "거주 시작", "열쇠 수령"]):
            move_in_dates.extend(dates)
        # (c) 전입과 인도가 결합 서술된 경우
        if any(w in stmt for w in ["입주 및 전입", "전입 및 입주", "전입과 주택인도", "인도와 전입"]):
            transfer_dates.extend(dates)
            move_in_dates.extend(dates)
        # (d) 확정일자 부여
        if "확정일자" in stmt:
            fixed_dates.extend(dates)

    for ev in (briefing.timeline or []):
        if getattr(ev, "verification_status", "") not in ("DOCUMENT_VERIFIED", "VERIFIED") and getattr(ev, "status", "") == "UNVERIFIED":
            continue
        if ev.event_date:
            clean_d = ev.event_date.replace("-", ".")
            if any(w in ev.title for w in ["전입", "주민등록"]):
                transfer_dates.append(clean_d)
            if any(w in ev.title for w in ["입주", "주택인도", "점유"]):
                move_in_dates.append(clean_d)
            if "확정일자" in ev.title:
                fixed_dates.append(clean_d)

    # 대항요건(인도 + 전입): 둘 다 충족되어야 함
    opposing_satisfied_date = None
    if transfer_dates and move_in_dates:
        opposing_satisfied_date = max(sorted(transfer_dates)[0], sorted(move_in_dates)[0])
    elif transfer_dates:
        opposing_satisfied_date = sorted(transfer_dates)[0]

    res["tenant_opposing_date"] = opposing_satisfied_date

    # 대항력 취득 시점: 주택임대차보호법 제3조 제1항에 따라 대항요건 구비 '익일(다음 날) 0시'
    if opposing_satisfied_date:
        parts = opposing_satisfied_date.split(".")
        if len(parts) == 3:
            try:
                y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                next_day = datetime.date(y, m, d) + datetime.timedelta(days=1)
                res["tenant_opposing_effective_date"] = next_day.strftime("%Y.%m.%d")
            except Exception:
                res["tenant_opposing_effective_date"] = None

    if fixed_dates:
        res["tenant_fixed_date"] = sorted(fixed_dates)[0]

    # 우선변제권 효력 발생 시점: 대항력 발생 시점(익일 0시)과 확정일자 부여일 중 늦은 시점
    tenant_priority_date = None
    if res["tenant_opposing_effective_date"] and res["tenant_fixed_date"]:
        tenant_priority_date = max(res["tenant_opposing_effective_date"], res["tenant_fixed_date"])
    elif res["tenant_opposing_effective_date"]:
        # 확정일자가 없으면 우선변제권은 없고 대항력만 존재
        tenant_priority_date = None

    res["tenant_priority_date"] = tenant_priority_date

    # 2. 가압류 및 담보권 사실 확인 (엄격히 검증된 사실만)
    att_creditors = []
    att_amts = []
    att_dates = []
    att_evs = []

    for f in (briefing.facts or []):
        if not is_fact_strictly_verified(f, briefing):
            continue
        stmt = f.statement or ""
        if "가압류" in stmt or "압류" in stmt or "근저당권" in stmt or "저당권" in stmt:
            res["has_attachment"] = True
            if f.evidence_label and f.evidence_label not in att_evs:
                att_evs.append(f.evidence_label)

            dates = extract_dates_from_text(stmt)
            att_dates.extend(dates)

            for cred in re.findall(r"([가-힣A-Za-z0-9]+(?:은행|보증공사|신탁|공사)|HUG)", stmt):
                if cred not in att_creditors and cred not in ("가압류", "부동산", "임대차"):
                    att_creditors.append(cred)

            amts = extract_amounts_from_text(stmt)
            for a in sorted(amts, reverse=True):
                a_str = format_krw_to_korean(a)
                if a_str not in att_amts:
                    att_amts.append(a_str)

    res["creditors"] = att_creditors
    res["amounts"] = att_amts
    res["evidence_labels"] = att_evs
    res["attachment_dates"] = sorted(att_dates)

    if not res["has_attachment"]:
        res["priority_status"] = "NO_ATTACHMENT"
        res["summary_text"] = "등기부상 확인된 가압류나 선순위 제한물권 없음"
        return res

    cred_desc = ", ".join(att_creditors) if att_creditors else "가압류 채권자"
    amt_desc = f"({', '.join(att_amts)})" if att_amts else ""
    res["summary_text"] = f"{cred_desc} {amt_desc} 가압류".strip()

    # 선후관계 엄격 비교: 우선변제권 발생일(익일 0시 기준)과 가압류 등기 접수일자 대조
    if not tenant_priority_date or not att_dates:
        res["priority_status"] = "UNCERTAIN"
    else:
        earliest_att_date = sorted(att_dates)[0]
        if tenant_priority_date < earliest_att_date:
            res["priority_status"] = "TENANT_SENIOR"
        elif tenant_priority_date > earliest_att_date:
            res["priority_status"] = "ATTACHMENT_SENIOR"
        else:
            # 우선변제권 발생일과 가압류 등기일이 같은 날짜인 경우:
            # 만약 전입 당일(opposing_satisfied_date)에 가압류가 설정된 것이면 가압류가 선순위
            if opposing_satisfied_date and opposing_satisfied_date == earliest_att_date:
                res["priority_status"] = "ATTACHMENT_SENIOR"
            else:
                res["priority_status"] = "UNCERTAIN"

    return res


def find_case_property_info(briefing: CaseEvidenceBriefing) -> Tuple[str, str]:
    """사건의 Fact 및 증거로부터 임차 목적물 부동산 명칭과 주택 유형을 동적으로 추출한다."""
    prop_name = "목적물 부동산"
    prop_type = "해당 주택"

    for f in (briefing.facts or []):
        stmt = f.statement or ""
        m = re.search(r"([가-힣A-Za-z0-9\s]+(?:오피스텔|아파트|빌라|다세대주택|다세대|원룸|주택)\s*\d+호?)", stmt)
        if m:
            prop_name = m.group(1).strip()
            break
        m_addr = re.search(r"([가-힣]+(?:시|구|동|로|길)\s+[가-힣A-Za-z0-9\s]+?\d+호)", stmt)
        if m_addr:
            prop_name = m_addr.group(1).strip()
            break

    for f in (briefing.facts or []):
        stmt = f.statement or ""
        for pt in ["오피스텔", "아파트", "다세대주택", "연립주택", "빌라", "다가구주택", "원룸"]:
            if pt in stmt:
                prop_type = pt
                break
        if prop_type != "해당 주택":
            break

    return prop_name, prop_type


def find_evidence_labels_by_type(
    briefing: CaseEvidenceBriefing,
    type_keywords: List[str],
) -> List[str]:
    """문서 유형(document_type) 또는 파일명 키워드에 매칭되는 실제 증거 라벨 목록을 조회한다."""
    matched: List[str] = []
    kw_lower = [k.lower() for k in type_keywords]

    for ev in (briefing.evidences or []):
        doc_type = getattr(ev, "document_type", "") or getattr(ev, "doc_type", "")
        doc_name = getattr(ev, "document_name", "") or ""
        lbl = getattr(ev, "evidence_label", "") or getattr(ev, "label", "")

        type_match = any(k in doc_type.lower() for k in kw_lower)
        name_match = any(k in doc_name.lower() for k in kw_lower)

        if (type_match or name_match) and lbl and lbl not in matched:
            matched.append(lbl)

    for lbl, reg in (briefing.source_registry or {}).items():
        if not lbl or lbl in matched:
            continue
        reg_name = ""
        if isinstance(reg, dict):
            reg_name = reg.get("document_name", "") or reg.get("file", "") or ""
        elif isinstance(reg, str):
            reg_name = reg
        if any(k in reg_name.lower() for k in kw_lower):
            matched.append(lbl)

    return matched
