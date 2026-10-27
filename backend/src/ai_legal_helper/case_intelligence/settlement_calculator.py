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
   - 통지 발송일과 상대방 도달일을 엄격히 분리하고, 도달 미확인 시 법정 해지 효력일을 미확정으로 유지한다.
   - 월말 도달 시 민법 제157조 및 제160조에 따른 역(曆)에 의한 3개월 계산(달력 연산)을 적용한다.
   - 대항요건·확정일자와 가압류 등기일의 실제 선후관계를 비교하여 불명확 시 선순위 단정을 배제한다.
   - 특정 증거번호(E01, E03 등)의 역할을 고정하지 않고 실제 document_type 및 Fact 근거를 대조한다.
"""

from typing import List, Dict, Any, Optional, Set, Tuple
import re
import datetime
import calendar

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)


def format_krw_to_korean(amt: int) -> str:
    """정수 금액(KRW)을 자연스러운 한국어 표기(예: 3억 원, 2억 2천만 원, 1억 7천만 원, 5천만 원)로 변환한다.

    단순 천 단위 콤마 표기 대신 법률 상담에 적합한 한글 단위(억, 만)로 조합하여 반환한다.

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
    """문자열에서 날짜(연, 월, 일)를 정규식으로 탐색하여 'YYYY.MM.DD' 형식 목록으로 반환한다.

    한국어 연월일 구문(예: '2026년 6월 30일', '2026.06.30', '2026-06-30')을 모두 지원한다.

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


def extract_case_contract_deposit(briefing: CaseEvidenceBriefing) -> int:
    """사건의 등록 증거 및 확정 Fact로부터 계약상 임대차 보증금 원금을 동적으로 인출한다.

    특정 금액(예: 300,000,000원)을 고정하지 않고, 임대차계약서 및 요건사실 진술문에서
    보증금 관련 금액을 분석하여 반환한다 (P0-3.1).
    단순히 가장 큰 금액을 선택하지 않고, 증거로 검증된 계약 원금 Fact에서 결정한다.

    Args:
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        int: 추출된 보증금 정수 금액(KRW). 확인 불가 시 0.
    """
    deposit_candidates = []
    # 1. 증거로 검증된 Fact 중에서 계약 보증금 Fact 우선 탐색
    for f in (briefing.facts or []):
        is_verified = (
            f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
            or getattr(f, "trust_level", "") == "EVIDENCE_SUPPORTED"
            or getattr(f, "verification_status", "") in ("DOCUMENT_VERIFIED", "VERIFIED")
        )
        if not is_verified:
            continue
        stmt = f.statement or ""
        # 보증금 계약 원금 관련 사실 탐색 (분할변제 제안, 가압류, 반환금 등 명백히 배제)
        if ("보증금" in stmt or "전세금" in stmt) and not any(
            w in stmt for w in ["일부", "반환", "변제", "가압류", "손해금", "위약금", "제안", "시세", "감정가", "경매", "근저당권"]
        ):
            # 계약 보증금 관련 명시 문구("보증금은 OOO원", "보증금 OOO원에 계약")
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
        return deposit_candidates[0] if len(set(deposit_candidates)) == 1 else max(deposit_candidates)

    # 2. 계약서 출처를 가진 Fact에서 계약 원금 재탐색 (검증된 Fact에 한함)
    for f in (briefing.facts or []):
        is_verified = (
            f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
            or getattr(f, "trust_level", "") == "EVIDENCE_SUPPORTED"
            or getattr(f, "verification_status", "") in ("DOCUMENT_VERIFIED", "VERIFIED")
        )
        if not is_verified:
            continue
        stmt = f.statement or ""
        if any(w in stmt for w in ["임대차계약", "계약 체결", "체결일"]) and ("보증금" in stmt or "전세금" in stmt):
            if not any(w in stmt for w in ["일부", "반환", "변제", "가압류", "손해금", "위약금"]):
                amts = extract_amounts_from_text(stmt)
                if amts:
                    return max(amts)

    return 0


def extract_case_prior_verified_repayments(briefing: CaseEvidenceBriefing) -> Tuple[int, List[str]]:
    """사건에 이미 공적으로 입증·확정된 임대인의 보증금 반환(일부 또는 전액) 내역을 동적으로 합산한다.

    최초 계약금·잔금 지급(임차인 -> 임대인)과 임대인의 보증금 반환(임대인 -> 임차인)을
    엄격히 구분하고, 실제 반환 거래 단위(일자, 금액, 고유 거래번호, 계좌, 차수 등)로 식별하여
    중복 사본은 차단하고, 동일 문서 내 복수 거래 및 식별자가 구분되는 동시/동액 거래는 각각 합산한다.
    고유 거래 식별자가 없어 동일성이 불확실한 거래는 확정 집계를 보류하여 이중 차감을 방지한다 (P0-3.1).
    보증금 전액 반환 거래 또한 정상 인정한다 (P0-4.2 최종 보완 v3.0).

    Args:
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        Tuple[int, List[str]]: (합산된 반환액, 근거 출처 목록) 튜플.
    """
    total_repaid = 0
    repaid_sources: List[str] = []
    accepted_txs: List[Dict[str, Any]] = []

    for f in (briefing.facts or []):
        is_verified = (
            f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
            or getattr(f, "trust_level", "") == "EVIDENCE_SUPPORTED"
            or getattr(f, "verification_status", "") in ("DOCUMENT_VERIFIED", "VERIFIED")
        )
        if not is_verified:
            continue
        stmt = f.statement or ""
        doc_name = f.document_name or f.evidence_label or ""

        # 임차인의 최초 보증금 지급 내역은 임대인의 반환으로 오인 배제
        if any(w in stmt for w in ["계약금", "잔금 지급", "전액 지급 완료", "임대인 계좌로", "임차인이 지급", "보증금을 지급", "보증금 완납"]):
            # 단, 문장 내에 반환/변제/환급 키워드가 명시된 경우는 아래 행 분할 단계에서 검토
            if not any(w in stmt for w in ["반환", "변제", "돌려"]):
                continue

        # 계약 체결 자체 진술은 반환 거래로 취급하지 않음
        if any(w in stmt for w in ["임대차계약을 체결", "임대차계약 체결"]) and not any(w in stmt for w in ["반환", "변제", "입금", "송금"]):
            continue

        # 단일 진술문 내 복수 거래 행 분할 지원 (예: 은행거래내역서 복수 라인 추출)
        raw_lines = [ln.strip() for ln in stmt.splitlines() if ln.strip()]
        if not raw_lines:
            raw_lines = [stmt]

        for line_text in raw_lines:
            # 임차인이 임대인에게 지급한 최초 계약금/잔금 행 배제
            if any(w in line_text for w in ["임차인이 지급", "임대인 계좌로 송금하여 잔금", "잔금을 지급", "계약금을 지급"]):
                continue

            combined_text = f"{line_text} {doc_name}"

            # 임대인의 반환/입금/변제 진술 식별 (일부 변제뿐 아니라 전액 반환도 포섭)
            is_repayment_stmt = any(
                w in line_text
                for w in [
                    "변제", "반환", "반환금", "입금 확인", "변제 확인",
                    "송금 반환", "일부 반환", "전액 반환", "전액 변제", "돌려주", "돌려받"
                ]
            ) or ("입금" in line_text and any(w in line_text for w in ["임대인", "최성호", "집주인", "TX-"]))

            if is_repayment_stmt:
                # 변제/반환/입금된 금액 정밀 추출
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

                # 거래 단위 식별자 추출
                dates = extract_dates_from_text(line_text)
                tx_date = sorted(dates)[0] if dates else (str(getattr(f, "occurred_at", None) or ""))
                doc_ref = f.source_evidence_id or f.evidence_label or f.document_name or ""

                # 1. 거래번호 / 승인번호 / 일련번호 / 전문번호
                m_txid = re.search(r"(?:거래번호|승인번호|전문번호|관리번호|일련번호|tx[-_]?id|txid)[\s:]*([A-Za-z0-9_-]+)", combined_text, re.IGNORECASE)
                tx_id = m_txid.group(1).strip() if m_txid else None

                # 2. 거래 시각 (시분초 또는 시분)
                m_time = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", combined_text)
                if not m_time:
                    m_time = re.search(r"(\d{1,2}시\s*\d{1,2}분(?:\s*\d{1,2}초)?)", combined_text)
                tx_time = m_time.group(1).strip() if m_time else None

                # 3. 차수 / 회차 (1차, 2차 등)
                m_ord = re.search(r"(\d+)\s*(?:차|회|번째)\s*(?:입금|변제|지급|반환|이체)?", combined_text)
                tx_ord = m_ord.group(1).strip() if m_ord else None

                # 4. 계좌번호
                m_acc = re.search(r"(?:계좌|계좌번호)[\s:]*([0-9-]+)", combined_text)
                tx_acc = m_acc.group(1).strip() if m_acc else None

                # 5. 사본 / 중복 표기 여부
                is_copy = any(w in combined_text for w in ["사본", "중복", "재발급", "동일 거래", "copy"])

                src = f.document_name or f.evidence_label or "확인된 증거"

                # 기존 수락된 거래들과 비교하여 중복 / 별개 / 의심 식별
                is_duplicate = False
                is_ambiguous = False

                for ex in accepted_txs:
                    # 1. 고유 거래번호(TX-ID) 비교: 둘 다 거래번호가 존재하는 경우
                    if tx_id and ex.get("tx_id"):
                        if tx_id == ex["tx_id"]:
                            # 동일 거래번호 -> 명백한 중복 (사본 또는 중복 추출)
                            is_duplicate = True
                            break
                        else:
                            # 서로 다른 거래번호 -> 동일 문서·동일 일자·동일 금액이라도 별개의 거래로 판별
                            continue

                    # 2. 명시적 사본 판정: 문맥/파일명에 사본 표기가 있고 금액 및 일자가 일치하는 경우
                    if (is_copy or ex.get("is_copy")) and ex["amt"] == amt and (not tx_date or not ex.get("date") or ex["date"] == tx_date):
                        is_duplicate = True
                        break

                    # 3. 금액 또는 일자가 상이한 경우 -> 별개의 거래
                    if amt != ex["amt"]:
                        continue
                    if tx_date and ex.get("date") and tx_date != ex["date"]:
                        continue

                    # 4. 금액과 일자가 동일한 경우 (tx_id가 한쪽 또는 양쪽에 없는 상황)
                    # 4-1. 보조 식별자(시간, 차수, 계좌) 중 하나라도 명확히 다르면 별개의 분할 거래
                    if (tx_time and ex.get("tx_time") and tx_time != ex["tx_time"]) or \
                       (tx_ord and ex.get("tx_ord") and tx_ord != ex["tx_ord"]) or \
                       (tx_acc and ex.get("tx_acc") and tx_acc != ex["tx_acc"]):
                        continue

                    # 4-2. 보조 식별자조차 없는 동일 일자·동일 금액 거래:
                    # 동일 문서 출처(doc_ref 동일)인 경우 동일 항목의 중복 추출로 판정하여 중복 차단
                    if doc_ref and ex.get("doc_ref") and doc_ref == ex["doc_ref"]:
                        is_duplicate = True
                        break

                    # 4-3. 서로 다른 문서인데 고유 식별자가 없고 동일성이 불확실한 경우:
                    # 이중 차감을 방지하고 안전한 권리 행사를 위해 확정 합산을 보류하고 확인 필요 상태 유지
                    is_ambiguous = True
                    break

                if is_duplicate:
                    continue

                if is_ambiguous:
                    # 고유 거래 식별자가 없고 동일성이 불확실하면 확정 판단 보류
                    repaid_sources.append(
                        f"[보류] {amt:,}원 [{src}] (동일 일자·금액 거래 중복 의심 / 고유 거래번호 미확인으로 합산 보류)"
                    )
                    continue

                # 신규 거래로 확정 집계
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
        Optional[str]: 'YYYY.MM.DD' 형식의 3개월 경과 효력 발생일자. 날짜 파싱 불가 시 None.
    """
    if not reach_date_str:
        return None
    cleaned = reach_date_str.replace("-", ".").strip()
    parts = cleaned.split(".")
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        # 표준 라이브러리 calendar.monthrange를 활용한 역(曆)에 의한 정확한 3개월 만료 계산
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
    """사건 브리핑으로부터 해지 통지의 발송 사실, 도달 확인 사실, 묵시적 갱신 여부를 정밀 분석한다.

    발송 사실과 상대방 도달 확인 사실을 엄격히 분리한다 (지시서 작업 D).
    도달 확인이 없는 경우 도달일과 법정 해지 효력일을 미확정(None)으로 유지한다.

    Args:
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        Dict[str, Any]: 통지 발송일, 도달일, 묵시적 갱신 여부, 법정 효력 발생일 분석 딕셔너리.
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

    # 1. 묵시적 갱신 사실 확인
    for f in (briefing.facts or []):
        stmt = f.statement or ""
        if any(w in stmt for w in ["묵시적으로 갱신", "묵시적 갱신", "동일 조건으로 갱신", "별도 갱신거절 통지가 없어", "묵시적갱신"]):
            res["is_implicit_renewal"] = True

    # 2. 통지 발송 사실 분석
    for f in (briefing.facts or []):
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

    # 3. 도달 확인 및 임대인 수신 확인 분석 (객관적 입증된 사실만)
    for f in (briefing.facts or []):
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

        # 퇴거 지정일
        if "퇴거" in stmt and any(w in stmt for w in ["지정", "예정", "이사"]):
            dates = extract_dates_from_text(stmt)
            if dates and not res["designated_move_out_date"]:
                res["designated_move_out_date"] = dates[-1]

    # 도달 확인 사실이 명시된 경우에만 법정 해지 효력일 계산
    if res["is_implicit_renewal"] and res["has_reached"] and res["reach_date"]:
        res["statutory_effect_date"] = calculate_three_months_expiry(res["reach_date"])

    return res


def evaluate_attachment_ranking(briefing: CaseEvidenceBriefing) -> Dict[str, Any]:
    """임차인의 대항요건 취득일, 확정일자와 등기부상 가압류·저당권의 설정일자를 정밀 비교한다.

    날짜가 없거나 권리관계가 불명확한 경우 선순위를 단정하지 않는다 (지시서 작업 E).

    Args:
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        Dict[str, Any]: 권리순위 분석 딕셔너리 (has_attachment, priority_status, creditors, amounts 등).
    """
    res: Dict[str, Any] = {
        "has_attachment": False,
        "creditors": [],
        "amounts": [],
        "evidence_labels": [],
        "summary_text": "",
        "priority_status": "UNCERTAIN",  # "TENANT_SENIOR", "ATTACHMENT_SENIOR", "UNCERTAIN", "NO_ATTACHMENT"
        "tenant_opposing_date": None,
        "tenant_fixed_date": None,
        "attachment_dates": [],
    }

    # 1. 임차인 대항요건(인도+전입) 및 확정일자 일자 탐색
    opposing_dates = []
    fixed_dates = []

    for f in (briefing.facts or []):
        stmt = f.statement or ""
        dates = extract_dates_from_text(stmt)
        if any(w in stmt for w in ["전입신고", "주민등록", "전입", "입주", "주택 인도", "점유"]):
            opposing_dates.extend(dates)
        if "확정일자" in stmt:
            fixed_dates.extend(dates)

    for ev in (briefing.timeline or []):
        if any(w in ev.title for w in ["전입", "입주", "대항력"]):
            if ev.event_date:
                opposing_dates.append(ev.event_date.replace("-", "."))
        if "확정일자" in ev.title:
            if ev.event_date:
                fixed_dates.append(ev.event_date.replace("-", "."))

    if opposing_dates:
        res["tenant_opposing_date"] = sorted(opposing_dates)[0]
    if fixed_dates:
        res["tenant_fixed_date"] = sorted(fixed_dates)[0]

    # 2. 가압류 및 담보권 사실 확인
    att_creditors = []
    att_amts = []
    att_dates = []
    att_evs = []

    for f in (briefing.facts or []):
        stmt = f.statement or ""
        if "가압류" in stmt or "압류" in stmt or "근저당권" in stmt or "저당권" in stmt:
            is_verified = (
                f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
                or getattr(f, "trust_level", "") == "EVIDENCE_SUPPORTED"
                or getattr(f, "verification_status", "") in ("DOCUMENT_VERIFIED", "VERIFIED")
            )
            if is_verified:
                res["has_attachment"] = True
                if f.evidence_label and f.evidence_label not in att_evs:
                    att_evs.append(f.evidence_label)

                # 날짜 추출
                dates = extract_dates_from_text(stmt)
                att_dates.extend(dates)

                # 채권자명 추출
                for cred in re.findall(r"([가-힣A-Za-z0-9]+(?:은행|보증공사|신탁|공사)|HUG)", stmt):
                    if cred not in att_creditors and cred not in ("가압류", "부동산", "임대차"):
                        att_creditors.append(cred)

                # 금액 추출
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

    # 선후관계 엄격 비교
    # 임차인의 우선변제권 기준일: 대항요건 취득일과 확정일자 중 늦은 일자
    tenant_base_date = None
    if res["tenant_opposing_date"] and res["tenant_fixed_date"]:
        tenant_base_date = max(res["tenant_opposing_date"], res["tenant_fixed_date"])
    elif res["tenant_opposing_date"]:
        tenant_base_date = res["tenant_opposing_date"]

    if not tenant_base_date or not att_dates:
        # 날짜 정보가 결여된 경우 단정하지 않고 UNCERTAIN 유지
        res["priority_status"] = "UNCERTAIN"
    else:
        earliest_att_date = sorted(att_dates)[0]
        if tenant_base_date < earliest_att_date:
            res["priority_status"] = "TENANT_SENIOR"
        elif tenant_base_date > earliest_att_date:
            res["priority_status"] = "ATTACHMENT_SENIOR"
        else:
            res["priority_status"] = "UNCERTAIN"

    return res


def find_case_property_info(briefing: CaseEvidenceBriefing) -> Tuple[str, str]:
    """사건의 Fact 및 증거로부터 임차 목적물 부동산 명칭과 주택 유형을 동적으로 추출한다.

    특정 사건 명칭('가람오피스텔 503호')의 고정을 배제하고, 현재 사건 Fact에서 실제 목적물을 조회한다.

    Args:
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        Tuple[str, str]: (목적물 명칭/주소, 목적물 유형) 튜플.
    """
    prop_name = "목적물 부동산"
    prop_type = "해당 주택"

    for f in (briefing.facts or []):
        stmt = f.statement or ""
        # 1. 상세 주소 및 호수 매칭
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
    """문서 유형(document_type) 또는 파일명 키워드에 매칭되는 실제 증거 라벨 목록을 조회한다.

    증거번호(E01, E03 등)의 역할을 임의 가정하지 않고 실제 등록된 증거의 메타데이터와 대조한다 (지시서 작업 B/D).

    Args:
        briefing: 현재 사건 증거 브리핑 모델.
        type_keywords: 탐색할 문서 유형 또는 파일명 키워드 목록 (예: ['LEASE', '계약서']).

    Returns:
        List[str]: 일치하는 증거 라벨 목록 (예: ['E01']).
    """
    matched: List[str] = []
    kw_lower = [k.lower() for k in type_keywords]

    # 1. briefing.evidences 확인
    for ev in (briefing.evidences or []):
        doc_type = getattr(ev, "document_type", "") or getattr(ev, "doc_type", "")
        doc_name = getattr(ev, "document_name", "") or ""
        lbl = getattr(ev, "evidence_label", "") or getattr(ev, "label", "")

        type_match = any(k in doc_type.lower() for k in kw_lower)
        name_match = any(k in doc_name.lower() for k in kw_lower)

        if (type_match or name_match) and lbl and lbl not in matched:
            matched.append(lbl)

    # 2. briefing.source_registry 확인
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
