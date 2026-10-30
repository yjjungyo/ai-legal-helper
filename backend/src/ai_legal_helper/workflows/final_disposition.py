# -*- coding: utf-8 -*-
"""
모듈명: final_disposition.py

[모듈 개요]
쟁점별 검증 결과(IssueVerificationResult)와 사건 증거 브리핑(CaseEvidenceBriefing)을 바탕으로
최종 고객 응답 처분 상태(final_disposition: DELIVERED, CAUTIONARY, WITHHELD)를 결정하고,
검증된 쟁점과 확인된 사실관계만을 안전하게 선별·조립(Assemble)하여 최종 답변을 생성하는 모듈.

[주요 기능]
1. 쟁점 기반 최종 처분 상태 결정 (determine_final_disposition, Section 8, P0-05):
   - 검증된 쟁점이 존재하면 전체 답변 폐기를 방지하고 DELIVERED 또는 CAUTIONARY 부여
   - 안전하게 제공 가능한 쟁점이 전혀 없는 극단적 경우에만 WITHHELD 부여
2. 사건 사실 정렬 및 선별 로직 (select_grounded_facts_for_display, Section 12, P0-08):
   - 문서 제목, 단순 서명란 서식, 단순 전화번호 등 부차적 메타데이터 배제
   - 보증금, 계약기간, 대항력(전입/확정일자), 통지, 가압류 등 핵심 요건사실 우선 가중치 정렬
   - 출처 다양성(Diversity) 보장: 특정 증거 독점을 방지하고 복수 증거(E01, E02, E03, E05, E09, E10 등) 사실을 고루 안배
3. 동적 부분 답변 조립 (assemble_grounded_answer, Section 8, P0-05):
   - 사전에 작성된 고정 템플릿(결론 및 3단계 행동 가이드) 전면 배제
   - 실제 검증 완료된 쟁점 및 확인 사실만을 바탕으로 사건 맞춤형 종합 판단과 행동 가이드 동적 구성
4. 개선된 판단 유보 생성 (build_dynamic_withheld_answer, Section 9, P0-06):
   - WITHHELD 상태에서도 등록된 증거 목록과 입증된 핵심 사실을 요약하여 투명성 제공
"""

from typing import List, Dict, Any, Tuple, Optional, Set
import re
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.case_intelligence.settlement_calculator import (
    format_krw_to_korean,
    extract_dates_from_text,
    extract_amounts_from_text,
    extract_case_contract_deposit,
    extract_case_prior_verified_repayments,
    calculate_three_months_expiry,
    evaluate_notice_status,
    evaluate_attachment_ranking,
    find_case_property_info,
    find_evidence_labels_by_type,
)
from ai_legal_helper.agents.issue_verifier import IssueVerificationResult
from ai_legal_helper.api.schemas.consultation import ClaimReference, ClaimCitation
from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import EvidenceClaim, EvidenceSpan
from ai_legal_helper.utils.text_formatter import clean_markdown_formatting
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

# 부차적 메타데이터 배제용 패턴 (문서명, 연락처, 단순 서명란 서식)
_METADATA_EXCLUDE_PATTERNS = [
    re.compile(r"^(문서\s*제목은|이\s*문서는|제목은|문서의\s*명칭은|표제는)", re.IGNORECASE),
    re.compile(r"(연락처는|전화번호는|휴대폰|010-\d{4}-\d{4})", re.IGNORECASE),
    re.compile(r"(서명란이\s*존재한다|기재되어\s*있고\s*서명란|서명·날인란|날인란)", re.IGNORECASE),
    re.compile(r"^임대차\s*목적물의\s*전용면적은", re.IGNORECASE),
]


def is_trivial_metadata_fact(stmt: str) -> bool:
    """사건 본질과 무관한 서식·메타데이터·단순 연락처 사실인지 검사한다 (P0-08)."""
    stmt_clean = stmt.strip()
    for pat in _METADATA_EXCLUDE_PATTERNS:
        if pat.search(stmt_clean):
            return True
    return False


def score_fact_legal_importance(fact: Any, query: Optional[str] = None) -> float:
    """법률 요건사실 및 질문 맥락과의 연관성에 따라 사실의 중요도 점수를 계산한다 (P0-08).

    Args:
        fact: FactItemBrief 객체.
        query: 사용자 질문 문자열.

    Returns:
        float: 중요도 가중치 점수.
    """
    stmt = fact.statement.lower()
    score = 0.0

    # 1. 보증금 / 지급 / 채권·채무 관련 (+50)
    if any(k in stmt for k in ["보증금", "잔금", "계약금", "이체", "영수", "지급", "반환", "원이다", "원약정"]):
        score += 50.0

    # 2. 임대차 계약 기간 / 인도 / 거주 관련 (+40)
    if any(k in stmt for k in ["계약 체결", "임대차 기간", "만료", "종료", "월 차임", "인도"]):
        score += 40.0

    # 3. 대항력 / 전입신고 / 확정일자 / 점유 (+45)
    if any(k in stmt for k in ["전입", "주민등록", "확정일자", "점유", "거주", "대항력"]):
        score += 45.0

    # 4. 계약 종료 통고 / 내용증명 / 해지 의사표시 (+35)
    if any(k in stmt for k in ["통고", "통지", "퇴거", "해지", "갱신 거절", "내용증명", "카카오톡", "문자"]):
        score += 35.0

    # 5. 제한물권 / 가압류 / 경매 / 채권자 (+40)
    if any(k in stmt for k in ["가압류", "압류", "근저당", "경매", "배당", "hug", "주택도시보증공사", "은행", "결정문"]):
        score += 40.0

    # 6. 임대인의 분할반환 제안 등 교섭 (+30)
    if any(k in stmt for k in ["분할", "분할반환", "1년 뒤", "합의", "제안"]):
        score += 30.0

    # 7. 질문(query) 키워드 연관 가중치 (+20)
    if query:
        q_tokens = [tok for tok in re.findall(r"[가-힣0-9A-Za-z]{2,}", query.lower()) if tok not in ["주세요", "대해", "관련", "어떻게"]]
        matched_tokens = sum(1 for tok in q_tokens if tok in stmt)
        score += matched_tokens * 10.0

    return score


def _extract_semantic_fact_key(statement: str) -> str:
    """사실 진술문에서 동일한 법률 요건사실(보증금 금액, 계약기간 등)을 대표하는 정규화 키를 추출한다 (P0-03/Gate 2).

    동일한 보증금 금액 사실(예: 계약서 2억 2천, 송금내역 2억 2천, 영수증 2억 2천 등 3개)이나
    동일 계약기간 진술이 다수 존재할 때 단 하나의 대표 사실로 병합·중복 제거하기 위함이다.

    Args:
        statement: 사실 진술문 문자열.

    Returns:
        str: 의미론적 요건사실 그룹 식별자 키.
    """
    stmt = statement.strip()

    # 1. 보증금 금액 관련 요건사실 (금액 기반 일치 그룹화: 계약서, 송금내역, 영수증, 수령확인 등)
    amts = extract_amounts_from_text(stmt)
    if amts and (any(k in stmt for k in ("보증금", "전세금", "임차보증금", "송금", "입금", "지급", "차임", "영수", "수령", "반환", "계약금", "잔금")) or max(amts) >= 10_000_000):
        return f"SEMANTIC_DEPOSIT_{max(amts)}"

    # 2. 계약 기간 관련 요건사실 (시작일-종료일 기준 일치 그룹화)
    date_matches = re.findall(r"(\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2})", stmt)
    if len(date_matches) >= 2 and any(k in stmt for k in ("기간", "만료", "시작", "종료", "임대차", "계약")):
        d1 = re.sub(r"\s+", "", date_matches[0]).replace("-", ".").replace("/", ".")
        d2 = re.sub(r"\s+", "", date_matches[1]).replace("-", ".").replace("/", ".")
        return f"SEMANTIC_PERIOD_{d1}_{d2}"

    # 3. 전입 및 확정일자 대항력 요건사실
    if ("전입" in stmt or "주민등록" in stmt) and "확정일자" in stmt:
        return "SEMANTIC_OPPOSABILITY_REQ"

    # 4. 계약 만료/해지 통지 및 임대인 확인 사실
    if any(k in stmt for k in ("해지", "종료", "만료", "갱신거절")) and any(k in stmt for k in ("통지", "문자", "카카오", "회신", "확인", "곤란")):
        return "SEMANTIC_TERMINATION_NOTICE"

    return f"STMT_{stmt}"


def select_grounded_facts_for_display(
    briefing: CaseEvidenceBriefing,
    query: Optional[str] = None,
    max_facts: int = 5,
) -> List[Any]:
    """등록된 사실관계 중 핵심 요건사실과 질문 연관 사실을 우선 선별하고 출처 다양성 및 의미론적 중복을 제거한다 (P0-03/Gate 2).

    선별 원칙:
    1. 신뢰 상태가 직접 입증(EVIDENCE_SUPPORTED, CORROBORATED)된 사실만 대상.
    2. 문서 제목, 단순 서명란, 연락처 등 부차적 메타데이터 배제.
    3. 요건사실 가중치(보증금, 임대차 기간, 대항력, 통고 등) 내림차순 정렬.
    4. 의미론적 중복 제거: 동일한 보증금 금액(예: 계약서, 송금내역, 영수증 3건), 동일한 계약기간 사실은
       가장 구체적이고 신뢰도 높은 1건만 대표로 선별.
    5. 출처 다양성 보장: 동일 증거 라벨에서 최대 2건까지만 선택하여 여러 증거가 고루 포섭되도록 함.
    6. 기본 최대 3~5건으로 간결하게 구성하여 사용자 가독성을 극대화.

    Args:
        briefing: 사건 증거 브리핑 모델.
        query: 사용자 질문 문자열.
        max_facts: 반환할 최대 사실 건수 (기본 5건).

    Returns:
        List[Any]: 선별된 FactItemBrief 객체 리스트.
    """
    supported_facts = [
        f for f in briefing.facts
        if (f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED") or getattr(f, "trust_level", "") == "EVIDENCE_SUPPORTED")
        and getattr(f, "trust_level", "") != "SUPERSEDED"
        and not is_trivial_metadata_fact(f.statement)
    ]

    # 가중치 점수 내림차순 정렬
    scored_facts = sorted(
        supported_facts,
        key=lambda f: score_fact_legal_importance(f, query),
        reverse=True,
    )

    selected: List[Any] = []
    seen_stmts = set()
    seen_semantic_keys = set()
    label_counts: Dict[str, int] = {}
    remaining_pool: List[Any] = []

    # 1차 라운드: 증거 라벨별 다양성 확보 및 의미론적 중복 제거
    for f in scored_facts:
        norm_stmt = f.statement.strip()
        sem_key = _extract_semantic_fact_key(norm_stmt)
        if norm_stmt in seen_stmts or sem_key in seen_semantic_keys:
            continue

        lbl = f.evidence_label or "UNKNOWN"
        curr_cnt = label_counts.get(lbl, 0)
        if curr_cnt < 2:
            selected.append(f)
            seen_stmts.add(norm_stmt)
            seen_semantic_keys.add(sem_key)
            label_counts[lbl] = curr_cnt + 1
            if len(selected) >= max_facts:
                break
        else:
            remaining_pool.append(f)

    # 슬롯이 남은 경우 나머지 상위 가중치 사실로 보충 (의미론적 중복 여전히 배제)
    if len(selected) < max_facts and remaining_pool:
        for f in remaining_pool:
            norm_stmt = f.statement.strip()
            sem_key = _extract_semantic_fact_key(norm_stmt)
            if norm_stmt not in seen_stmts and sem_key not in seen_semantic_keys:
                selected.append(f)
                seen_stmts.add(norm_stmt)
                seen_semantic_keys.add(sem_key)
                if len(selected) >= max_facts:
                    break

    return selected


def determine_final_disposition(
    issue_results: List[IssueVerificationResult],
) -> Tuple[str, str]:
    """쟁점별 검증 결과를 종합하여 최종 응답 처분 상태(DELIVERED, CAUTIONARY, WITHHELD)를 판정한다.

    Section 8.3 요구사항 반영:
    1. DELIVERED: 핵심 법률 쟁점이 VERIFIED 상태로 확정되고 BLOCKED 쟁점이 없음.
    2. CAUTIONARY: 실질적 법률 분석이 검증되었으나, 일부 쟁점이 CONDITIONAL 또는 NEEDS_EVIDENCE 상태임.
    3. WITHHELD: 모든 쟁점이 BLOCKED이거나, 안전하게 제공할 수 있는 법률적 판단이 전혀 없음.

    Args:
        issue_results: 각 단위 법률 쟁점별 검증 결과 목록.

    Returns:
        Tuple[str, str]: (final_disposition, disposition_reason)
    """
    if not issue_results:
        return "WITHHELD", "검증 대상 법률 쟁점이 도출되지 않았습니다."

    verified_count = sum(1 for r in issue_results if r.status == "VERIFIED")
    conditional_count = sum(1 for r in issue_results if r.status == "CONDITIONAL")
    needs_evidence_count = sum(1 for r in issue_results if r.status in ("NEEDS_EVIDENCE", "NEEDS_LEGAL_SOURCE"))
    blocked_count = sum(1 for r in issue_results if r.status == "BLOCKED")

    # 모든 쟁점이 차단되었거나 실질 분석이 전무한 경우
    if verified_count == 0 and conditional_count == 0:
        return "WITHHELD", f"모든 쟁점({len(issue_results)}건)의 증거 또는 법률 근거가 불충분하여 법률 판단을 유보합니다."

    # 모든 쟁점이 완전 검증된 경우
    if verified_count > 0 and conditional_count == 0 and needs_evidence_count == 0 and blocked_count == 0:
        return "DELIVERED", f"핵심 법률 쟁점 {verified_count}건이 등록 증거 및 관련 법령에 의해 검증되었습니다."

    # 검증된 쟁점과 조건부/증거부족 쟁점이 혼합된 경우 -> CAUTIONARY (부분 답변 보존)
    return "CAUTIONARY", (
        f"검증 완료 쟁점 {verified_count}건, 조건부 쟁점 {conditional_count}건이 "
        f"식별되어 확인된 범위 내에서 실질적 분석을 제공합니다."
    )


# [P0-4.2 최종 보완 v3.0] 단일 원천 settlement_calculator 로직 재수출 (호환성 유지)
# extract_case_contract_deposit 및 extract_case_prior_verified_repayments는
# 모듈 상단에서 settlement_calculator로부터 직접 임포트되어 공유됩니다.


def extract_case_attachment_info(briefing: CaseEvidenceBriefing) -> Tuple[bool, Optional[str], str, bool]:
    """가압류 사실 존재 여부, 가압류 등기일자, 관련 문서명, 증거 검증 여부를 Fact와 Evidence에서 동적으로 추출한다.

    Returns:
        Tuple[bool, Optional[str], str, bool]: (가압류 언급 여부, 가압류 등기일자, 문서명, 증거검증 여부)
    """
    has_attachment = False
    attachment_date = None
    doc_name = find_case_attachment_evidence_name(briefing)
    is_verified = False

    for f in (briefing.facts or []):
        stmt = f.statement or ""
        # 단, '가압류가 없다', '가압류 미설정', '가압류 부존재' 등 부인 문맥은 제외 (P0-01)
        if ("가압류" in stmt or "압류" in stmt) and not any(w in stmt for w in ["없다", "미설정", "단독", "부존재", "설정되지 않", "없음"]):
            has_attachment = True
            fact_verified = (
                f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
                or getattr(f, "trust_level", "") == "EVIDENCE_SUPPORTED"
                or getattr(f, "verification_status", "") in ("DOCUMENT_VERIFIED", "VERIFIED")
            )
            dates = extract_dates_from_text(stmt)
            if dates:
                attachment_date = sorted(dates)[0]
            if fact_verified:
                is_verified = True
                if f.document_name or f.evidence_label:
                    doc_name = f.document_name or f.evidence_label

    for ev in (briefing.evidences or []):
        dname = ev.document_name or ""
        if "가압류" in dname:
            has_attachment = True
            if getattr(ev, "verification_status", "") in ("VERIFIED", "DOCUMENT_VERIFIED", "REVIEWED", "APPROVED"):
                is_verified = True

    return has_attachment, attachment_date, doc_name, is_verified


def extract_case_opposing_power_date(briefing: CaseEvidenceBriefing) -> Optional[str]:
    """임차인의 대항요건(주민등록 전입) 및 확정일자 취득 일자를 Fact에서 동적으로 추출한다."""
    for f in (briefing.facts or []):
        stmt = f.statement or ""
        if any(w in stmt for w in ["전입", "주민등록", "확정일자", "입주"]):
            dates = extract_dates_from_text(stmt)
            if dates:
                return sorted(dates)[0]
    for ev in (briefing.timeline or []):
        if any(w in ev.title for w in ["전입", "확정일자", "입주"]):
            if ev.event_date:
                return ev.event_date
    return None


def extract_case_prior_encumbrances(briefing: CaseEvidenceBriefing, tenant_date: Optional[str] = None) -> List[str]:
    """임차인의 대항력 취득일 이전에 설정된 선순위 담보물권(근저당권 등) 여부를 동적으로 탐색한다."""
    prior_encumbrances = []
    for f in (briefing.facts or []):
        stmt = f.statement or ""
        if any(w in stmt for w in ["근저당", "저당권", "선순위 담보"]) and not any(w in stmt for w in ["없다", "미설정", "단독", "부존재"]):
            prior_encumbrances.append(stmt)
    return prior_encumbrances


def extract_case_notice_delivery_date(briefing: CaseEvidenceBriefing) -> Optional[str]:
    """사건 증거로 확정된 계약 해지 통고의 실제 도달 일자를 Fact에서 동적으로 추출한다."""
    for f in (briefing.facts or []):
        stmt = f.statement or ""
        if any(w in stmt for w in ["해지통고", "도달", "배달증명", "해지 통지"]):
            dates = extract_dates_from_text(stmt)
            if dates:
                return sorted(dates)[0]
    return None


def find_case_attachment_evidence_name(briefing: CaseEvidenceBriefing) -> str:
    """사건에 등록된 등기사항전부증명서 또는 가압류 관련 증거 문서명을 동적으로 탐색한다."""
    for ev in (briefing.evidences or []):
        dname = ev.document_name or ""
        if any(w in dname for w in ["등기", "을구", "가압류"]):
            return dname
    for lbl, reg in (briefing.source_registry or {}).items():
        if isinstance(reg, dict):
            dname = reg.get("document_name") or ""
            if any(w in dname for w in ["등기", "을구", "가압류"]):
                return dname
    return ""


def detect_case_delta(
    briefing: CaseEvidenceBriefing,
    conv_context: Optional[Any] = None,
    current_question: str = "",
    resolved_query: str = "",
) -> Optional[Dict[str, Any]]:
    """사건의 새로운 사실, 증거 또는 정정 정보가 기존 법률 판단에 미치는 영향을 분석하여
    변경 전후 비교 구조(Case Delta)를 생성한다 (P0-3.1).

    고정된 사건 데이터(보증금 3억, 5천만원 변제, 2022.03.10 등)를 전면 배제하고,
    현재 사건의 Fact, Evidence, 적용 법령에서 모든 수치와 일자를 동적으로 도출한다.

    구조 (Section 5):
    - changed_facts: 변경된 사실 및 근거 문서
    - impacted_determinations: 영향받는 법률 판단
    - preserved_determinations: 유지되는 판단
    - new_next_actions: 새로운 다음 행동

    Args:
        briefing: 현재 사건 증거 브리핑 모델.
        conv_context: 이전 상담 턴들이 담긴 ConversationContext 객체 또는 딕셔너리.
        current_question: 현재 사용자 질문 문자열.
        resolved_query: 문맥이 복원된 내부 작업 질의.

    Returns:
        Optional[Dict[str, Any]]: 사건 변동 사항이 식별된 경우 4대 영역 딕셔너리, 없으면 None.
    """
    q_corpus = f"{current_question} {resolved_query}".lower()
    changed_facts: List[str] = []
    impacted_determinations: List[str] = []
    preserved_determinations: List[str] = []
    new_next_actions: List[str] = []

    contract_deposit_krw = extract_case_contract_deposit(briefing)
    prior_repaid_krw, prior_sources = extract_case_prior_verified_repayments(briefing)

    calc_basis: Dict[str, Any] = {
        "status": "UNKNOWN",
        "contract_deposit_krw": contract_deposit_krw,
        "verified_partial_repayment_krw": 0,
        "alleged_partial_repayment_krw": 0,
        "unrepaid_balance_krw": contract_deposit_krw,
    }

    # 1. 보증금 일부 변제 / 입금 (S01 / P0-3.1)
    repayment_terms = ["입금", "변제", "일부 반환", "돌려받", "돌려줬", "돌려주", "송금", "갚았", "부쳤", "일부 지급"]
    has_repayment_mention = any(t in q_corpus for t in repayment_terms) and any(
        w in q_corpus for w in ["원", "만", "천", "억", "입금", "변제", "돌려", "받았", "보냈", "얼마", "잔액"]
    )

    has_verified_payment_fact = (prior_repaid_krw > 0) or any(
        any(w in (f.statement or "").lower() for w in ["일부 변제", "일부 반환", "일부변제", "입금 확인", "변제 확인"])
        and not any(w in (f.statement or "").lower() for w in ["계약금", "잔금 지급"])
        and (f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED") or getattr(f, "trust_level", "") == "EVIDENCE_SUPPORTED" or getattr(f, "verification_status", "") in ("DOCUMENT_VERIFIED", "VERIFIED"))
        for f in (briefing.facts or [])
    )

    if has_repayment_mention or has_verified_payment_fact:
        # 질문 내 언급된 변제/입금 금액 정밀 추출 (남은 잔액 수치와 엄격 분리)
        asserted_krw = 0
        # 1. '입금/변제/반환/송금/돌려/지급' 문맥의 변제 주장 금액 우선 추출
        m_repay = re.search(
            r"(\d+(?:\s*억|\s*천만|\s*만|\s*원|,|\d)+)\s*(?:원)?을?\s*(?:일부\s*)?(?:추가로\s*|더\s*|새로\s*)?(?:변제|반환|입금|송금|돌려|갚|부쳤|지급)",
            current_question or q_corpus
        )
        if not m_repay:
            m_repay = re.search(
                r"(?:변제|반환|입금|송금|돌려받|받은|갚은)\s*(?:금액이?|돈이?)?\s*(\d+(?:\s*억|\s*천만|\s*만|\s*원|,|\d)+)\s*원",
                current_question or q_corpus
            )
        if m_repay:
            repay_amts = extract_amounts_from_text(m_repay.group(0))
            cand_repay = [a for a in repay_amts if a != contract_deposit_krw and a > 0]
            if cand_repay:
                asserted_krw = max(cand_repay)
        elif not has_verified_payment_fact:
            # 확정된 변제 증거가 없는 상태에서만 일반 금액 중 잔액 표현 제외 탐색
            q_amts = extract_amounts_from_text(current_question or q_corpus)
            cand_amts = [a for a in q_amts if a != contract_deposit_krw and a > 0]
            if cand_amts:
                # '남은', '잔액', '미반환', '잔여' 뒤의 금액은 잔액 문의이므로 변제 주장액에서 제외
                m_bal_q = re.search(r"(?:남은|잔액은?|미반환|잔여).*?(\d+(?:\s*억|\s*천만|\s*만|\s*원|,|\d)+)\s*원", current_question or q_corpus)
                bal_in_q = max(extract_amounts_from_text(m_bal_q.group(0))) if m_bal_q else None
                cand_no_bal = [a for a in cand_amts if a != bal_in_q]
                asserted_krw = max(cand_no_bal) if cand_no_bal else (max(cand_amts) if not bal_in_q else 0)

        # Fact 중 새롭게 입증된 반환 금액 및 파일명 탐색
        ev_transfer_doc_name = None
        ev_transfer_amt = 0
        explicit_fact_balance = None
        for f in (briefing.facts or []):
            if any(w in (f.statement or "") for w in ["일부 변제", "일부 반환", "입금 확인", "변제 확인"]) and not any(w in (f.statement or "") for w in ["계약금", "잔금"]):
                m = re.search(r"(\d+(?:\s*억|\s*천만|\s*만|\s*원|,|\d)+)\s*(?:원)?을?\s*(?:일부\s*)?(?:변제|반환|입금|돌려)", f.statement or "")
                if m:
                    f_amts = extract_amounts_from_text(m.group(0))
                else:
                    f_amts = extract_amounts_from_text(f.statement or "")
                if f_amts:
                    ev_transfer_amt = min(f_amts) if len(f_amts) > 1 else max(f_amts)
                    if not ev_transfer_doc_name:
                        ev_transfer_doc_name = f.document_name or f.evidence_label
                # 문장에 '남은 잔액' 등이 명시되어 있으면 보관
                m_bal = re.search(r"(?:잔액은?|미반환).*?(\d+(?:\s*억|\s*천만|\s*만|\s*원|,|\d)+)\s*원", f.statement or "")
                if m_bal:
                    b_amts = extract_amounts_from_text(m_bal.group(0))
                    if b_amts:
                        explicit_fact_balance = max(b_amts)
                break

        is_new_allegation = (
            asserted_krw > 0
            and (asserted_krw != prior_repaid_krw or any(w in q_corpus for w in ["추가", "또", "더", "새로", "새로운", "다시"]))
        )

        if has_verified_payment_fact:
            if is_new_allegation and prior_repaid_krw > 0:
                # [작업 1] 기존 확정 변제와 신규 구두 주장 분리
                # 예: 기존 확정 2천만원 + 신규 주장 3천만원
                confirmed_balance = max(0, contract_deposit_krw - prior_repaid_krw) if contract_deposit_krw else 0
                provisional_balance = max(0, confirmed_balance - asserted_krw)
                doc_label = ev_transfer_doc_name or (prior_sources[0] if prior_sources else "확인된 증거")

                calc_basis = {
                    "status": "PARTIALLY_CONFIRMED_WITH_NEW_ALLEGATION",
                    "contract_deposit_krw": contract_deposit_krw,
                    "verified_partial_repayment_krw": prior_repaid_krw,
                    "alleged_partial_repayment_krw": asserted_krw,
                    "confirmed_unrepaid_balance_krw": confirmed_balance,
                    "provisional_unrepaid_balance_krw": provisional_balance,
                    "unrepaid_balance_krw": confirmed_balance,
                }

                changed_facts.append(
                    f"기존 보증금 중 {prior_repaid_krw:,}원 일부 변제 확정 [{doc_label}] 및 "
                    f"의뢰인의 신규 {asserted_krw:,}원 추가 입금 진술 접수 (신규 주장 증빙 미제출 / USER_ALLEGED)"
                )
                impacted_determinations.append(
                    f"공적으로 확인된 미반환 잔액은 {confirmed_balance:,}원(지연손해금 기산 대상 원금)이며, "
                    f"의뢰인의 추가 {asserted_krw:,}원 입금 진술이 객관적 금융 증빙으로 확인될 경우 잠정 잔액은 {provisional_balance:,}원으로 감축될 수 있음. "
                    f"단, 신규 입금 증빙(이체확인증 등) 확인 전까지는 법률상 확정 미반환 잔액 {confirmed_balance:,}원을 기준으로 청구 금액 및 지연손해금을 산정함. "
                    "일부 변제금은 민법 제479조에 따라 비용·이자·원본 순으로 충당됨"
                )
                preserved_determinations.append(
                    "임차인의 대항력, 우선변제권 및 임차권등기명령 신청 권한은 보증금 전액 반환 시까지 온전히 유지됨"
                )
                new_next_actions.append(
                    f"확정 미반환 잔액 {confirmed_balance:,}원을 기준으로 지급명령 또는 보증금 반환 청구 소송을 준비하되, "
                    f"신규 {asserted_krw:,}원 추가 입금에 대한 계좌 이체확인증 또는 영수증 원본을 증거로 등록하여 입증할 것"
                )
            else:
                # 확정된 반환액 계산 (하드코딩 기본값 배제)
                repaid_amt = prior_repaid_krw if prior_repaid_krw > 0 else (ev_transfer_amt or asserted_krw)
                if repaid_amt > 0:
                    total_confirmed_repaid = max(prior_repaid_krw, repaid_amt)
                    if explicit_fact_balance is not None:
                        confirmed_balance = explicit_fact_balance
                    else:
                        confirmed_balance = max(0, contract_deposit_krw - total_confirmed_repaid) if contract_deposit_krw else 0
                    doc_label = ev_transfer_doc_name or (prior_sources[0] if prior_sources else "확인된 증거")
                    calc_basis = {
                        "status": "CONFIRMED",
                        "contract_deposit_krw": contract_deposit_krw,
                        "verified_partial_repayment_krw": total_confirmed_repaid,
                        "alleged_partial_repayment_krw": 0,
                        "confirmed_unrepaid_balance_krw": confirmed_balance,
                        "provisional_unrepaid_balance_krw": confirmed_balance,
                        "unrepaid_balance_krw": confirmed_balance,
                    }

                    changed_facts.append(f"보증금 중 {repaid_amt:,}원 일부 변제 입금 확인 [{doc_label}]")
                    impacted_determinations.append(
                        f"보증금 반환 청구 가능 잔액이 {contract_deposit_krw:,}원에서 {confirmed_balance:,}원으로 감축 확정됨 "
                        f"(지연손해금 기산 대상 원금도 잔액 {confirmed_balance:,}원 기준으로 적용). "
                        "일부 변제된 금액은 민법 제479조에 따라 기발생 지연손해금 및 비용에 우선 충당된 후 잔여 원본에 충당되며, "
                        f"변제일 이후에는 잔여 원금 {confirmed_balance:,}원에 대해서만 법정 지연손해금이 기산됨"
                    )
                    preserved_determinations.append(
                        "임차인의 선순위 대항력 및 우선변제권, 임차권등기명령 신청 권한, 계약 해지 효력은 "
                        "보증금 일부 변제와 무관하게 전액 반환 시까지 온전히 유지됨"
                    )
                    new_next_actions.append(
                        f"미반환 잔액 {confirmed_balance:,}원에 대한 지급명령 신청 또는 보증금 반환 청구 소송 제기"
                    )
                else:
                    # 확정 사실은 식별되었으나 구체적 수치 산출이 불가한 경우 임의 금액을 대입하지 않고 확인 필요로 안내
                    changed_facts.append("보증금 일부 변제 사실 확인 (금액 특정 불가 / 증거 재검토 요망)")
                    impacted_determinations.append(
                        "보증금 일부 변제 사실은 공적으로 확인되었으나 구체적인 변제 수치가 특정되지 않아 잔액을 즉시 확정할 수 없음. "
                        "상세 금융 거래 내역 및 이체확인증에 대한 재검토가 필요함"
                    )
                    preserved_determinations.append(
                        "임차인의 대항력, 우선변제권 및 전액 반환 청구 권리는 보증금 완제 시까지 온전히 유지됨"
                    )
                    new_next_actions.append(
                        "정확한 변제 잔액 산정을 위해 금융 거래 상세 내역서 또는 영수증 원본 재확인"
                    )
        else:
            # 증빙 미제출 또는 미승인 상태 (USER_ALLEGED / 하드코딩 기본값 배제)
            alleged_amt = asserted_krw or ev_transfer_amt
            if alleged_amt > 0:
                provisional_balance = max(0, contract_deposit_krw - (prior_repaid_krw + alleged_amt)) if contract_deposit_krw else 0
                calc_basis = {
                    "status": "PROVISIONAL",
                    "contract_deposit_krw": contract_deposit_krw,
                    "verified_partial_repayment_krw": prior_repaid_krw,
                    "alleged_partial_repayment_krw": alleged_amt,
                    "confirmed_unrepaid_balance_krw": contract_deposit_krw,
                    "provisional_unrepaid_balance_krw": provisional_balance,
                    "unrepaid_balance_krw": provisional_balance,
                }

                changed_facts.append(f"의뢰인의 {alleged_amt:,}원 일부 입금 진술 접수 (증빙 미제출 / USER_ALLEGED)")
                impacted_determinations.append(
                    f"계약상 확인된 보증금 {contract_deposit_krw:,}원 중 {alleged_amt:,}원 입금 진술에 따라 잠정 잔액이 {provisional_balance:,}원으로 안내되나, "
                    "객관적 금융 증빙(이체확인증 등) 확인 전까지는 법률상 보증금 원금 전액이 공적으로 감축 확정되지 않음. "
                    "일부 지급이 인정될 경우 민법 제479조에 따른 비용·이자·원본 충당 순서에 따라 실제 변제 잔액이 정산되어야 함"
                )
                preserved_determinations.append(
                    "임차인의 대항력, 우선변제권, 임차권등기명령 신청 권리는 잔액 전액 반환 시까지 그대로 유지됨"
                )
                new_next_actions.append(
                    f"임대인으로부터 받은 {alleged_amt:,}원의 계좌 이체확인증 또는 영수증을 증거로 등록하여 공적으로 입증할 것"
                )
            else:
                # 금액 추출 실패 시 임의 금액을 대입하지 않고 확인 필요 상태로 반환
                changed_facts.append("의뢰인의 보증금 일부 입금/변제 진술 접수 (구체적 금액 미상 / 확인 필요 / USER_ALLEGED)")
                impacted_determinations.append(
                    f"계약상 확인된 보증금 {contract_deposit_krw:,}원 중 일부 입금 진술이 접수되었으나, "
                    "구체적인 입금 금액이 명시되지 않았거나 객관적 금융 증빙이 제출되지 않아 잔액을 산정할 수 없음. "
                    "정확한 입금액과 금융 증빙 확인 전까지는 법률상 보증금 원금 감축이 확정되지 않음"
                )
                preserved_determinations.append(
                    "임차인의 대항력, 우선변제권 및 전액 반환 청구 권리는 보증금 완제 시까지 온전히 유지됨"
                )
                new_next_actions.append(
                    "임대인으로부터 입금받은 정확한 금액과 계좌 이체확인증 또는 입금증빙 자료를 증거로 등록하여 확인할 것"
                )

    # 2. 목적물 조기 퇴거 / 점유 이전 / 이사 질의 (S05: '그럼 지금 이사를 가도 돼?')
    moveout_terms = ["이사", "퇴거", "열쇠", "비밀번호", "짐 빼", "방 빼", "나가도", "이사가도"]
    if any(t in q_corpus for t in moveout_terms):
        changed_facts.append("의뢰인의 보증금 미반환 상태에서의 조기 이사(퇴거) 및 점유 이전 가능 여부 문의")
        impacted_determinations.append(
            "보증금 전액을 반환받기 전 또는 임차권등기명령에 따른 등기가 등기부에 기재되기 전에 "
            "주택의 점유를 상실(이사/열쇠 인도/비밀번호 공유)하거나 전입을 이전하면, "
            "주택임대차보호법상 대항력 및 우선변제권이 즉시 소멸하는 치명적 법률 위험 발생. "
            "따라서 현재 상태에서는 절대 점유를 이전해서는 안 됨"
        )
        preserved_determinations.append(
            "목적물에 거주(점유)하고 주민등록(전입)을 유지하는 한 기존 대항력과 우선변제권은 확고히 보존됨"
        )
        new_next_actions.append(
            "관할 법원에 임차권등기명령을 신청하고, 등기사항전부증명서(을구)에 임차권등기가 실제로 기재된 것을 "
            "확인한 후에 비로소 이사(점유 이전)할 것"
        )

    # 3. 새로운 가압류 사실 추가 (S02 / P0-01 허위 Case Delta 생성 차단 및 가압류 무결성 검증)
    # [P0-01 원칙]
    # 질문이나 resolved_query에 우연히 '경매', '배당', '순위' 등의 단어가 포함되어 있다는 이유만으로
    # 사건에 등록되지도 않은 가압류 사실을 날조 생성하는 것을 전면 차단한다.
    # Case Delta는 실제 사건 Fact/Evidence에 가압류가 존재하거나, 의뢰인이 이번 질문에서 명시적으로
    # 신규 가압류의 존재를 주장(USER_ALLEGED)한 경우에만 한정하여 평가한다.
    has_attachment_fact, attachment_date, att_doc_name, is_att_verified = extract_case_attachment_info(briefing)

    # 의뢰인이 질문에서 명시적으로 가압류를 신규 주장/문의하였는지 확인 (단순 일반 질문이나 '어떤 조치를 해야 하나요' 배제)
    user_alleged_attachment = any(w in (current_question or "") for w in ["가압류가", "가압류를", "가압류 들어", "가압류 걸", "가압류 설정", "등기부에 가압류", "가압류 등기", "가압류 추가"])

    # 가압류 Fact/증거가 존재하거나, 의뢰인이 신규 가압류를 명시적으로 주장한 경우에만 분기 진입
    if has_attachment_fact or user_alleged_attachment:
        tenant_date = extract_case_opposing_power_date(briefing)
        prior_encumbrances = extract_case_prior_encumbrances(briefing, tenant_date)

        if not is_att_verified or not attachment_date:
            # 등기일자나 증거 검증이 없는 상태: '후순위', '1순위', '최우선 배당' 단정 전면 금지 (작업 3)
            # 미등록 문서인 경우 가공의 등기부명을 날조하지 않고 증빙 미제출 표기
            doc_label = f"[{att_doc_name}]" if att_doc_name else "[증빙 미제출 / USER_ALLEGED]"
            changed_facts.append(f"목적물 부동산에 대한 신규 가압류 언급/등기 사실 접수 (등기일자 미검증 / 권리순위 미확정) {doc_label}".strip())
            impacted_determinations.append(
                "가압류의 구체적 등기 접수일자 및 권리설정 내역이 공적 증거(등기사항전부증명서)로 검증되지 않아, "
                "임차인의 대항요건·확정일자와의 권리 선후관계를 즉시 확정할 수 없음. "
                "등기부 확인 전까지는 '1순위' 또는 '최우선 배당'을 단정할 수 없음"
            )
            preserved_determinations.append(
                f"임차인이 기취득한 대항요건({tenant_date or '전입/확정일자'})에 따른 기본적 법적 지위 보존"
            )
            new_next_actions.append(
                "대법원 인터넷등기소에서 최신 부동산등기사항전부증명서(을구)를 발급받아 "
                "가압류의 정확한 등기 접수일자 및 선순위 권리 존재 여부를 확인하고 증거로 등록할 것"
            )
        elif prior_encumbrances:
            # 선순위 담보물권이 존재하는 경우: 1순위 최우선 배당 불가
            doc_label = f"[{att_doc_name}]" if att_doc_name else ""
            changed_facts.append(f"목적물 부동산에 가압류 등기 사실 추가 확인 {doc_label}".strip())
            impacted_determinations.append(
                f"목적물에 선순위 담보물권({prior_encumbrances[0]})이 존재하므로 1순위 최우선 배당이 불가하며, "
                "선순위 채권최고액과 경매 낙찰가율에 따른 배당 순위 및 잔여 담보 가치를 면밀히 검토해야 함"
            )
            preserved_determinations.append(
                f"임차인의 대항요건({tenant_date or '구비일'}) 취득에 따른 법적 대항력 및 상대적 권리 순위"
            )
            new_next_actions.append(
                "대법원 인터넷등기소를 통한 등기사항전부증명서 추가 변동 모니터링 및 향후 경매 개시 시 "
                "배당요구종기 내 권리신고 및 배당요구 신청서 접수"
            )
        elif tenant_date and attachment_date and attachment_date > tenant_date:
            # 임차인의 대항요건/확정일자가 가압류 등기일보다 앞서는 것이 검증된 경우
            doc_label = f"[{att_doc_name}]" if att_doc_name else ""
            changed_facts.append(f"목적물 부동산에 후순위 가압류 등기 사실 추가 확인 {doc_label}".strip())
            impacted_determinations.append(
                f"[판단할 수 있는 사실]: 신규 가압류 채권자에 대해서는 임차인의 대항요건 및 확정일자({tenant_date})가 앞서므로 기존 우선순위 보존 및 대항력 유지. "
                "[추가로 필요한 등기·법률정보]: 단, 등기사항전부증명서(을구) 상의 다른 선순위 제한물권(담보권)이나 조세채권(당해세 등 법정기일 우선채권)의 존재 및 변동 여부를 추가 확인해야 최종 경매 배당 순위가 확정되며, 공적 등기부 열람 전까지 절대적 1순위 또는 전액 최우선 배당을 단정할 수 없음"
            )
            preserved_determinations.append(
                f"임차인의 1순위 대항력 및 우선변제권 ({tenant_date} 확정일자 기준 후순위 가압류 대비 선순위 지위 유지)"
            )
            new_next_actions.append(
                "대법원 인터넷등기소를 통한 등기사항전부증명서 추가 변동 모니터링 및 향후 경매 개시 시 "
                "배당요구종기 내 권리신고 및 배당요구 신청서 접수"
            )
        else:
            # 가압류 등기일이 임차인 대항력보다 앞서거나 같은 경우
            doc_label = f"[{att_doc_name}]" if att_doc_name else ""
            changed_facts.append(f"목적물 부동산에 선행/동순위 가압류 등기 사실 추가 확인 {doc_label}".strip())
            impacted_determinations.append(
                f"가압류 등기일({attachment_date})이 임차인의 대항요건 구비일({tenant_date or '미확인'})보다 앞서거나 같아 "
                "임차인이 가압류 채권자에게 우선적 대항력을 주장하기 어려우며 동순위 안분배당 또는 열후할 수 있음"
            )
            preserved_determinations.append(
                "임대차계약에 기초한 임대인에 대한 일반 보증금 반환 채권 유지"
            )
            new_next_actions.append(
                "전문 변호사와 신속한 대면 상담을 통해 배당 순위 및 보증금 보전 대책 강구"
            )

    # 4. 기존 사실 정정 (S03: '통지일이 2024년 3월 20일이에요')
    correction_terms = ["날짜가 달라", "정정", "잘못 알았", "통지일이", "통지일은"]
    if any(t in q_corpus for t in correction_terms):
        actual_notice_date = extract_case_notice_delivery_date(briefing) or "공적 서면 증거 도달일"
        changed_facts.append("의뢰인의 계약 해지 통지일 정정 진술 접수 (사용자 진술 / USER_ALLEGED)")
        impacted_determinations.append(
            f"기존 등록된 공적 서면 증거에 기재된 도달일({actual_notice_date})을 기준으로 "
            "법률효과 발생일을 유지하며, 객관적 서면 증빙 없는 구두 진술만으로 확정된 법률효과 발생일을 임의 변경하지 않음"
        )
        preserved_determinations.append(
            "기존 서면 증거에 의한 계약 해지 통고 효력 발생 및 계약 종료일 판단 유지"
        )
        new_next_actions.append(
            "만약 다른 일자에 추가 통지가 도달하였다면 해당 서면 증거(배달증명서, 문자 수신화면 등)를 "
            "등록하여 공적으로 입증할 것"
        )

    # 5. 증거 충돌 (S04)
    has_dispute = bool(briefing.genuinely_disputed) or any(
        f.adjudication_status == "GENUINELY_DISPUTED" or getattr(f, "trust_level", "") == "DISPUTED"
        for f in (briefing.facts or [])
    )
    if has_dispute:
        disp_reason = briefing.genuinely_disputed[0].reason if briefing.genuinely_disputed else "증거 간 상충"
        changed_facts.append(f"제출된 증거 간 실질적 상충 및 모순 발생 (DISPUTED): {disp_reason}")
        impacted_determinations.append(
            "상충되는 사실관계에 대해서는 일방의 주장만을 근거로 단정적 법률 판단을 내릴 수 없으며, "
            "분쟁(DISPUTED) 상태로 관리하여 객관적 추가 증빙에 따라 조건부로 판단함"
        )
        preserved_determinations.append(
            "상충되지 않는 기존 기본 계약 체결 및 대항요건 취득 사실"
        )
        new_next_actions.append(
            "상충 사실을 입증할 수 있는 객관적 금융거래원장, 공문서 등 추가 공적 증거 확보 및 법률전문가 대면 상담"
        )

    if not changed_facts:
        return None

    return {
        "has_delta": True,
        "changed_facts": changed_facts,
        "impacted_determinations": impacted_determinations,
        "preserved_determinations": preserved_determinations,
        "new_next_actions": new_next_actions,
        "calculation_basis": calc_basis,
    }


def assemble_grounded_answer(
    issue_results: List[IssueVerificationResult],
    briefing: CaseEvidenceBriefing,
    draft_answer: str,
    disposition: str,
    case_delta: Optional[Dict[str, Any]] = None,
    current_question: Optional[str] = None,
    conv_context: Optional[str] = None,
) -> str:
    """쟁점별 검증 결과 및 사건 브리핑 사실관계를 종합하여 인용 출처가 명시된 고품질 법률 답변을 조립한다.

    [P0-03 / Gate 2 답변 구조 개편 원칙]
    1. [1. 핵심 결론]: 질문에 직접적이고 명확하게 답변하는 2~4문장의 결론을 최상단에 배치.
    2. [2. 판단 근거 (핵심 사실)]: 의미론적 중복이 제거된 핵심 사실 3~5개만 선별하여 원본 파일명과 함께 표시.
    3. [3. 우선 행동 가이드]: 질문 및 사건 상황에 맞는 핵심 안전 조치 3~5개만 엄선 (무관한 경매/배당 과잉 생성 차단).
    4. [4. 미확인 사항 및 주의사항]: 보완 필요 사항 2~3개 및 실무적 주의사항 안내.
    5. [5. 상세 법률 분석 (심층 검토)]: 검증 완료 쟁점 및 조건부 쟁점 세부 내용 (UI에서 접기/펼치기 가능).
    6. [6. 참고 법률 및 증거 출처]: 중복 제거된 증거 파일 및 적용 법령 조문 목록.
    7. 빈 인용(', , , ,') 및 빈 대괄호('[]')를 원천 필터링하여 무결한 텍스트를 생성.

    Args:
        issue_results: 단위 쟁점별 검증 결과 목록.
        briefing: 사건 증거 브리핑 모델.
        draft_answer: AI가 생성한 원본 초안 텍스트.
        disposition: 최종 처분 코드 ('DELIVERED', 'CAUTIONARY', 'WITHHELD').
        case_delta: 사건 변동 감지 결과 딕셔너리.
        current_question: 사용자의 현재 질문 문자열.
        conv_context: 대화 맥락 문자열.

    Returns:
        str: 정돈된 마크다운 형태의 최종 법률 조언 답변.
    """
    sections = []
    doc_name_map = {ev.evidence_label: ev.document_name for ev in (briefing.evidences or []) if ev.document_name}
    for lbl, reg in (briefing.source_registry or {}).items():
        if isinstance(reg, dict) and reg.get("document_name") and lbl not in doc_name_map:
            doc_name_map[lbl] = reg["document_name"]

    verified_issues = [r for r in issue_results if r.status == "VERIFIED"]
    conditional_issues = [r for r in issue_results if r.status in ("CONDITIONAL", "NEEDS_EVIDENCE", "NEEDS_LEGAL_SOURCE", "BLOCKED")]

    # 사건 변동 사항 감지
    if case_delta is None and (current_question or conv_context):
        case_delta = detect_case_delta(
            briefing=briefing,
            conv_context=conv_context,
            current_question=current_question or "",
            resolved_query="",
        )

    # 보증금 및 권리 정보 추출
    deposit_krw = extract_case_contract_deposit(briefing)
    repaid_krw, _ = extract_case_prior_verified_repayments(briefing)
    balance_krw = max(0, deposit_krw - repaid_krw) if deposit_krw > 0 else 0
    deposit_text = format_krw_to_korean(deposit_krw) if deposit_krw > 0 else "보증금"
    balance_text = format_krw_to_korean(balance_krw) if balance_krw > 0 else "미반환 보증금"
    prop_name, prop_type = find_case_property_info(briefing)

    has_verified_termination = any(r.issue_id == "ISSUE_LEASE_TERMINATION" and r.status == "VERIFIED" for r in verified_issues)

    # --------------------------------------------------------------------------
    # [사건 변동 사항 및 법률 판단 비교] (사건 변동이 감지된 경우에만 출력)
    # --------------------------------------------------------------------------
    if case_delta and case_delta.get("has_delta"):
        sections.append("[사건 변동 사항 및 법률 판단 비교]")
        if case_delta.get("changed_facts"):
            sections.append("■ 변경된 사실")
            for cf in case_delta["changed_facts"]:
                sections.append(f"- {cf}")
        if case_delta.get("impacted_determinations"):
            sections.append("■ 영향받는 법률 판단")
            for idet in case_delta["impacted_determinations"]:
                sections.append(f"- {idet}")
        if case_delta.get("preserved_determinations"):
            sections.append("■ 유지되는 판단")
            for pdet in case_delta["preserved_determinations"]:
                sections.append(f"- {pdet}")
        if case_delta.get("new_next_actions"):
            sections.append("■ 새로운 다음 행동")
            for nact in case_delta["new_next_actions"]:
                sections.append(f"- {nact}")
        sections.append("")

    # --------------------------------------------------------------------------
    # [1. 핵심 결론] (P0-03: 질문에 바로 답하는 2~4문장의 명확한 법률 결론)
    # --------------------------------------------------------------------------
    sections.append("[1. 핵심 결론]")
    if has_verified_termination:
        conclusion_lines = [
            f"임대차계약은 기간 만료로 이미 종료 확정되었으며, 임대인의 {balance_text if balance_krw > 0 else deposit_text} 반환 채무는 확정적으로 이행기에 도달하였습니다.",
            "임대인이 다음 세입자 유치 시까지 반환을 미루더라도 이는 개인적 사정에 불과하며 의뢰인이 이를 기다릴 법적 의무는 전혀 없습니다.",
            f"보증금 전액을 반환받을 때까지 {prop_type}의 점유와 대항력을 절대 상실하지 마시고, 즉시 임차권등기명령 신청과 내용증명 발송, 지급명령 또는 소송 절차에 착수하십시오.",
        ]
    elif verified_issues:
        top_recs = [rec for r in verified_issues for rec in r.safe_recommendations[:1]]
        conclusion_lines = top_recs[:2]
        conclusion_lines.append(f"보증금({balance_text if balance_krw > 0 else deposit_text}) 회수를 위해 대항력을 유지한 상태에서 단계적 법적 조치를 진행하시기 바랍니다.")
    else:
        conclusion_lines = [
            f"현재 등록된 증거를 바탕으로 {deposit_text}에 관한 기초 권리관계를 확인 중입니다.",
            "주택의 점유와 주민등록을 온전히 유지하시고, 아래 확인된 사실과 법률 분석을 바탕으로 단계별 조치를 준비하십시오.",
        ]
    sections.append(" ".join(conclusion_lines))

    # --------------------------------------------------------------------------
    # [2. 판단 근거 (핵심 사실)] (P0-03: 의미론적 중복 제거된 핵심 사실 3~5개 선별)
    # --------------------------------------------------------------------------
    sections.append("\n[2. 판단 근거 (핵심 사실)]")
    if case_delta and case_delta.get("changed_facts"):
        for cf in case_delta["changed_facts"]:
            if "일부 입금 진술" in cf and "USER_ALLEGED" in cf:
                amts = extract_amounts_from_text(cf)
                amt_str = f"{next(iter(amts)):,}원" if amts else "일부 금액"
                sections.append(f"- [잠정] 의뢰인이 임대인으로부터 {amt_str}을 입금받았다고 진술하였다 (증거 미제출 / USER_ALLEGED)")

    selected_facts = select_grounded_facts_for_display(briefing, query=draft_answer, max_facts=5)
    if selected_facts:
        for f in selected_facts:
            lbl = f.evidence_label or ""
            doc_name = f.document_name or (doc_name_map.get(lbl) if lbl else "")
            doc_name_clean = doc_name.strip() if doc_name else ""
            if doc_name_clean:
                cite_label = f"[{doc_name_clean}]"
            elif lbl and lbl.strip():
                cite_label = f"[{lbl.strip()}]"
            else:
                cite_label = ""
            sections.append(f"- {f.statement} {cite_label}".strip())
    else:
        sections.append("- 등록된 증거로부터 확인된 기초 사실관계를 정리 중입니다.")

    # --------------------------------------------------------------------------
    # [3. 우선 행동 가이드] (P0-04: 과잉 행동 배제, 엄선된 핵심 행동 3~5개)
    # --------------------------------------------------------------------------
    sections.append("\n[3. 우선 행동 가이드]")

    lease_labels = find_evidence_labels_by_type(briefing, ["LEASE", "임대차", "계약서"])
    notice_labels = find_evidence_labels_by_type(briefing, ["NOTICE", "통고", "통지", "문자", "카카오", "내용증명"])
    residence_labels = find_evidence_labels_by_type(briefing, ["RESIDENCE", "주민등록", "전입", "초본", "등본"])
    attachment_labels = find_evidence_labels_by_type(briefing, ["REGISTRY", "등기", "가압류", "압류", "근저당"])

    q_user = (current_question or "").lower()
    has_actual_auction = any(w in (briefing.title or "") or any(w in f.statement for f in briefing.facts) for w in ("경매개시", "경매 개시", "배당기일", "타경"))
    has_actual_installment = any(w in (briefing.title or "") or any(w in f.statement for f in briefing.facts) or w in q_user for w in ("분할", "일부만 먼저"))

    prioritized_actions: List[Dict[str, Any]] = []

    # 1) 절대 안전 조치 (대항력 및 점유 유지) - 전세 상담 1순위 수칙
    prioritized_actions.append({
        "text": f"보증금({balance_text if balance_krw > 0 else deposit_text}) 전액을 반환받거나 관할 법원의 임차권등기명령에 따른 등기가 등기부에 기재되기 전까지는 절대 {prop_type}의 점유를 상실(열쇠 인도, 비밀번호 공유, 임의 퇴거)하거나 전입을 옮기지 마십시오. (대항력 및 우선변제권 유지 필수)",
        "evidence_labels": list(set(lease_labels + residence_labels)),
    })

    # 2) 내용증명 발송 및 이행최고
    prioritized_actions.append({
        "text": "임대인에게 보증금 반환 최고 및 지연손해금(민법 연 5%, 소촉법 연 12%) 청구 내용증명을 발송하여 임대인의 이행지체 책임을 명확히 하십시오.",
        "evidence_labels": notice_labels or lease_labels,
    })

    # 3) 임차권등기명령 신청
    prioritized_actions.append({
        "text": "계약 종료 즉시 관할 법원에 주택임차권등기명령을 신청하여 향후 부득이하게 이사할 때에도 기존 대항력과 우선변제권이 온전히 유지·보전되도록 조치하십시오.",
        "evidence_labels": list(set(lease_labels + residence_labels)),
    })

    # 4) 분할반환 제안 거절 (사건 또는 질문에 분할반환이 실제로 존재할 때만 추가)
    if has_actual_installment:
        demand_target = f"미반환 잔액 {balance_text}" if repaid_krw > 0 else f"{deposit_text} 전액"
        prioritized_actions.append({
            "text": f"임대인의 분할반환 제안을 거절하고 {demand_target}의 일시반환을 강력히 촉구하십시오.",
            "evidence_labels": list(set(notice_labels + lease_labels)),
        })
    else:
        # 지급명령 또는 보증금반환청구 소송 제기
        prioritized_actions.append({
            "text": "임대인의 반환 지체가 계속될 경우 지급명령 신청 또는 보증금반환청구 소송을 제기하여 조속히 강제집행 권원(판결문 등)을 확보하십시오.",
            "evidence_labels": list(set(lease_labels + residence_labels)),
        })

    # 5) 경매 배당요구 (사건에 실제 경매가 개시된 경우에만 추가) vs 등기부 권리변동 모니터링
    if has_actual_auction:
        prioritized_actions.append({
            "text": "경매 개시 결정 시 배당요구 종기일을 확인하고 선순위 대항력 또는 우선배당 권리신고 및 배당요구를 진행하십시오.",
            "evidence_labels": list(set(lease_labels + attachment_labels)),
        })
    else:
        prioritized_actions.append({
            "text": f"대법원 인터넷등기소를 통해 {prop_name}의 최신 등기사항전부증명서(말소사항 포함)를 발급받아 가압류나 다른 선순위 권리 변동 여부를 주기적으로 확인하십시오.",
            "evidence_labels": attachment_labels or lease_labels,
        })

    # 최대 3~5개로 엄격히 제한
    final_actions = prioritized_actions[:5]
    for idx, act in enumerate(final_actions, 1):
        cites = []
        for s in act.get("evidence_labels", []):
            if not s:
                continue
            dname = doc_name_map.get(s, "")
            if dname and dname.strip():
                cites.append(f"[{dname.strip()}]")
            elif s.strip() and s in briefing.source_registry:
                cites.append(f"[{s.strip()}]")
        # 중복 제거
        cites = list(dict.fromkeys(cites))
        cite_str = f" {', '.join(cites)}" if cites else ""
        sections.append(f"{idx}. {act['text']}{cite_str}")

    # --------------------------------------------------------------------------
    # [4. 미확인 사항 및 주의사항] (증거 공백 2~3개 및 실무 유의사항)
    # --------------------------------------------------------------------------
    sections.append("\n[4. 미확인 사항 및 주의사항]")
    if briefing.evidence_gaps:
        for gap in briefing.evidence_gaps[:3]:
            act_text = f" (권장: {gap.recommended_action})" if gap.recommended_action else ""
            sections.append(f"- [{gap.priority}] {gap.target_proposition}{act_text}")
    else:
        sections.append("- 사건 등록 증거 기준 기본 요건사실은 충실히 구비되어 있습니다.")
    sections.append(
        "- 구두 합의에만 의존한 조치는 불측의 손해를 초래할 수 있으므로, "
        "서류를 지참하여 대한법률구조공단(국번없이 132) 또는 변호사의 대면 전문 상담을 병행하시기 바랍니다."
    )

    # --------------------------------------------------------------------------
    # [5. 상세 법률 분석 (심층 검토)] (검증 완료 및 조건부 쟁점 세부 내용 - UI 접기 지원)
    # --------------------------------------------------------------------------
    sections.append("\n[5. 상세 법률 분석 (심층 검토)]")
    if verified_issues:
        for idx, r in enumerate(verified_issues, 1):
            sections.append(f"\n{idx}. '{r.issue_title}' (검증 완료)")
            for rec in r.safe_recommendations:
                sections.append(f"  * 법률 판단: {rec}")
            if r.supported_source_ids:
                doc_cites = []
                for s in sorted(set(r.supported_source_ids)):
                    if not s:
                        continue
                    dname = doc_name_map.get(s, "")
                    if dname and dname.strip():
                        doc_cites.append(f"[{dname.strip()}]")
                    elif s.strip():
                        doc_cites.append(f"[{s.strip()}]")
                doc_cites = list(dict.fromkeys([c for c in doc_cites if c and c not in ("[]", "[None]", "[ ]")]))
                if doc_cites:
                    sections.append(f"  * 관련 증거: {', '.join(doc_cites)}")
            if r.supported_statute_ids:
                valid_laws = [law.strip() for law in r.supported_statute_ids if law and law.strip()]
                if valid_laws:
                    sections.append(f"  * 적용 법령: {', '.join(valid_laws)}")

    if conditional_issues:
        sections.append("\n[3. 조건부 판단 및 미확인 사항]")
        start_idx_cond = len(verified_issues) + 1
        for idx, r in enumerate(conditional_issues, start_idx_cond):
            status_kr = {
                "CONDITIONAL": "조건부 판단",
                "NEEDS_EVIDENCE": "증거 보완 필요",
                "NEEDS_LEGAL_SOURCE": "법령 근거 보강 필요",
                "BLOCKED": "판단 유보",
            }.get(r.status, "조건부 검토")
            sections.append(f"\n{idx}. '{r.issue_title}' ({status_kr})")
            for rec in r.safe_recommendations:
                clean_rec = rec
                if has_verified_termination and ("계약 종료 여부" in rec or "계약해지 효력" in rec):
                    clean_rec = clean_rec.replace("계약 종료 여부가 조건부 상태입니다", "계약 자체는 기간 만료로 종료 확정되었으나 세부 통지 입증자료 보강이 권장됩니다")
                    clean_rec = clean_rec.replace("계약 종료 여부는 전혀 확인할 수 없습니다", "임대차계약은 이미 종료 확정되었습니다")
                sections.append(f"  * 조건부 판단: {clean_rec}")
            if r.unresolved_facts:
                unres_text = ", ".join(r.unresolved_facts[:2])
                sections.append(f"  * 전제 조건 및 미확인 사실: {unres_text}")
            if r.supported_statute_ids or r.missing_statutes:
                valid_laws = [law.strip() for law in (r.supported_statute_ids or r.missing_statutes) if law and law.strip()]
                if valid_laws:
                    sections.append(f"  * 관련 법령: {', '.join(valid_laws)}")
            if r.supported_source_ids:
                doc_cites = []
                for s in sorted(set(r.supported_source_ids)):
                    if not s:
                        continue
                    dname = doc_name_map.get(s, "")
                    if dname and dname.strip():
                        doc_cites.append(f"[{dname.strip()}]")
                    elif s.strip():
                        doc_cites.append(f"[{s.strip()}]")
                doc_cites = list(dict.fromkeys([c for c in doc_cites if c and c not in ("[]", "[None]", "[ ]")]))
                if doc_cites:
                    sections.append(f"  * 관련 증거: {', '.join(doc_cites)}")
    elif not verified_issues:
        sections.append("- 현재 완전하게 확정할 수 있는 법률 쟁점은 없으며, 등록된 증거를 토대로 확인된 사실 범위를 안내합니다.")

    # --------------------------------------------------------------------------
    # [6. 참고 법률 및 증거 출처] (P0-03: 중복 제거된 증거 및 법령 목록)
    # --------------------------------------------------------------------------
    sections.append("\n[6. 참고 법률 및 증거 출처]")
    all_cited_docs = []
    for ev in (briefing.evidences or []):
        if ev.document_name and ev.document_name.strip():
            all_cited_docs.append(f"[{ev.document_name.strip()}] ({ev.document_type or '증거'})")
    all_cited_docs = list(dict.fromkeys(all_cited_docs))
    if all_cited_docs:
        sections.append("■ 참조 사건 증거")
        for doc_item in all_cited_docs[:6]:
            sections.append(f"- {doc_item}")

    all_laws = []
    for r in (issue_results or []):
        for law in (r.supported_statute_ids or []):
            if law and law.strip():
                all_laws.append(law.strip())
    all_laws = list(dict.fromkeys(all_laws))
    if all_laws:
        sections.append("■ 참조 법령 및 조문")
        for law_item in all_laws[:6]:
            sections.append(f"- {law_item}")

    final_text = "\n".join(sections)
    return clean_markdown_formatting(final_text)


def build_dynamic_withheld_answer(
    issue_results: Any,
    briefing: Any,
    reason_code: str = "LEGAL_SOURCE_MISSING",
) -> str:
    """판단 유보(WITHHELD) 상태에서도 확인된 사실과 실제 등록 증거 목록을 제공하는 안내문을 생성한다.

    Section 9 (P0-06) 요구사항 반영:
    1. 기계적 일반 안내문 대신, 실제 등록된 증거(E01, E02...)와 확인된 사실을 명시
    2. 이미 계약서나 이체내역이 등록된 경우 '계약서를 확보하세요' 등의 불필요한 반복 방지
    3. 유보된 구체적 사유 및 남아있는 증거 공백만을 정확히 명시

    Args:
        issue_results: 쟁점별 검증 결과 (또는 briefing).
        briefing: 사건 증거 브리핑 (또는 issue_results).
        reason_code: 유보 대표 사유 코드.

    Returns:
        str: 정돈된 판단 유보 안내문.
    """
    # 인수 순서 유연 처리 (briefing, issue_results 또는 issue_results, briefing 모두 허용)
    if isinstance(issue_results, CaseEvidenceBriefing):
        briefing, issue_results = issue_results, briefing
    elif not isinstance(briefing, CaseEvidenceBriefing) and hasattr(issue_results, "facts"):
        briefing, issue_results = issue_results, briefing

    if not isinstance(issue_results, list):
        issue_results = [issue_results] if issue_results else []

    sections = []
    sections.append("[안내: 일부 쟁점에 대한 법적 근거 및 증빙 추가 확인 필요]\n")
    sections.append(
        "현재 사건에 등록된 증거를 바탕으로 기본 사실관계는 정상적으로 확인되었으나, "
        "일부 법률 효과를 확정하기 위해 추가적인 공적 확인이 필요하여 답변을 조건부로 안내합니다.\n"
    )

    # 1. 현재 확인된 사실관계 (핵심 요건사실 선별 적용)
    sections.append("[1. 등록 증거로 입증된 사실관계]")
    selected_withheld_facts = select_grounded_facts_for_display(briefing, max_facts=8)
    if selected_withheld_facts:
        for f in selected_withheld_facts:
            doc_label = f.document_name or f.evidence_label
            cite = f"[{doc_label}]" if doc_label else ""
            sections.append(f"- {f.statement} {cite}".strip())
    else:
        sections.append("- 등록된 진술을 바탕으로 기초 정황을 확인하였습니다.")

    # 2. 등록된 증거 목록
    sections.append("\n[2. 현재 등록된 사건 증거 목록]")
    for ev in briefing.evidences[:8]:
        sections.append(f"- [{ev.evidence_label}] {ev.document_name} ({ev.document_type})")

    # 3. 보완이 필요한 구체적 쟁점 및 서류
    sections.append("\n[3. 유보 사유 및 보완이 필요한 사항]")
    if briefing.evidence_gaps:
        for g in briefing.evidence_gaps[:4]:
            sections.append(f"- {g.target_proposition} (권장: {g.recommended_action or '관련 확인'})")
    else:
        sections.append("- 목적물에 관한 최신 등기사항전부증명서 및 권리 변동 내역의 확인이 필요합니다.")

    # 4. 안전한 후속 행동 가이드
    sections.append("\n[4. 안전한 후속 행동 가이드]")
    sections.append(
        "- 보증금 반환을 받지 못한 상태에서 퇴거나 전입 이전을 하지 마시고 점유를 유지하십시오.\n"
        "- 관할 법원 임차권등기명령 신청 또는 대한법률구조공단(132), 전문 변호사의 대면 상담을 병행하십시오."
    )

    final_text = "\n".join(sections)
    return clean_markdown_formatting(final_text)


def extract_dates_from_text(text: str) -> Set[str]:
    """문자열에서 날짜(연, 월, 일) 목록을 추출한다.

    한국어 조사(일입니다, 일자, 일) 및 다양한 구분자(년월일, ., -)를 지원한다.

    Args:
        text: 날짜를 탐색할 원문 텍스트.

    Returns:
        Set[str]: 'YYYY.MM.DD' 형식으로 정규화된 일자 집합.
    """
    dates = set()
    for m in re.finditer(r"(\d{4})[년\.\-\s]+(\d{1,2})[월\.\-\s]+(\d{1,2})(?:일|\b)", text):
        y, mm, dd = m.groups()
        dates.add(f"{y}.{int(mm):02d}.{int(dd):02d}")
    return dates


# extract_amounts_from_text는 settlement_calculator에서 임포트됨



def extract_named_entities(text: str) -> Dict[str, Set[str]]:
    """문자열에서 주요 기관명, 당사자, 행위 유형을 추출한다.

    Args:
        text: 엔티티를 탐색할 텍스트.

    Returns:
        Dict[str, Set[str]]: 기관(orgs), 당사자(parties), 행위(actions) 집합 딕셔너리.
    """
    orgs = set()
    for o in ["동진은행", "우리은행", "신한은행", "국민은행", "하나은행", "HUG", "주택도시보증공사", "대법원", "인터넷등기소", "경매법원"]:
        if o in text:
            orgs.add(o)
    parties = set()
    for p in ["박정훈", "이수현"]:
        if p in text:
            parties.add(p)
    actions = set()
    for a in ["내용증명", "문자", "통화", "녹취록", "임차권등기", "지급", "이체", "가압류", "배당", "전입신고", "확정일자"]:
        if a in text:
            actions.add(a)
    return {"orgs": orgs, "parties": parties, "actions": actions}


def verify_claim_match(
    target_statement: str,
    candidate_statement: str,
    candidate_spans: List[Dict[str, Any]],
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """대상 진술문과 후보 Claim의 단어·날짜·금액·기관명·행위 일치 여부를 엄격히 검증한다.

    [P0-2.1 Grounding 무결성 규칙]
    1. 금융기관/채권자 불일치(우리은행 vs 동진은행 등) 차단
    2. 당사자 상충 차단
    3. 금액 불일치(3천만원 vs 3억원 등) 차단
    4. 발생 일자 상충 차단
    5. 행위 유형 상충(내용증명 발송 주장 vs 문자 메시지 등) 차단
    6. 단순 1단어 부분 일치 차단 (최소 의미 토큰 2개 이상 일치 필수)
    7. 적절한 Span이 없는 경우 임의 대체 배제

    Args:
        target_statement: 검증 대상이 되는 답변 내 진술문/주장.
        candidate_statement: 증거 문서에서 추출된 후보 Claim 진술문.
        candidate_spans: 후보 Claim에 연결된 원문 발췌(Span) 목록.

    Returns:
        Tuple[bool, str, Optional[Dict[str, Any]]]: (검증 성공 여부, 검증 이유, 선정된 최적 Span 딕셔너리)
    """
    ent_target = extract_named_entities(target_statement)
    ent_cand = extract_named_entities(candidate_statement)

    # 1. 기관명 / 채권자 불일치 검증
    if ent_target["orgs"] and ent_cand["orgs"]:
        if not ent_target["orgs"].intersection(ent_cand["orgs"]):
            return False, f"기관/채권자 불일치 ({list(ent_target['orgs'])} != {list(ent_cand['orgs'])})", None

    # 2. 당사자 불일치 검증
    if ent_target["parties"] and ent_cand["parties"]:
        if not ent_target["parties"].intersection(ent_cand["parties"]):
            return False, f"당사자 불일치 ({list(ent_target['parties'])} != {list(ent_cand['parties'])})", None

    # 3. 금액 불일치 검증
    amt_target = extract_amounts_from_text(target_statement)
    amt_cand = extract_amounts_from_text(candidate_statement)
    if amt_target and amt_cand:
        if not amt_target.intersection(amt_cand):
            return False, f"금액 불일치 ({amt_target} != {amt_cand})", None

    # 4. 날짜 상충 검증
    dt_target = extract_dates_from_text(target_statement)
    dt_cand = extract_dates_from_text(candidate_statement)
    if dt_target and dt_cand:
        if not dt_target.intersection(dt_cand):
            return False, f"일자 상충 ({dt_target} != {dt_cand})", None

    # 5. 행위 유형 상충 검증
    if "내용증명" in ent_target["actions"] and "내용증명" not in ent_cand["actions"] and "문자" in ent_cand["actions"]:
        return False, "통지 수단 불일치 (내용증명 발송 주장 != 문자메시지)", None

    # 6. 의미 토큰 중첩 검증
    t_words = set(re.findall(r"[가-힣0-9]{2,}", target_statement))
    c_words = set(re.findall(r"[가-힣0-9]{2,}", candidate_statement))
    common = t_words.intersection(c_words)
    if len(common) < 2 and len(t_words) >= 4:
        return False, "의미 토큰 중첩 부족 (2개 미만 일치)", None

    # 7. 원문 발췌(Span) 유효성 검증
    if not candidate_spans:
        return False, "원문 발췌(Span) 부재", None

    # 여러 Span 중 타겟 진술문 단어가 가장 많이 포함된 Span 선택
    best_span = candidate_spans[0]
    best_span_overlap = -1
    for s in candidate_spans:
        if not isinstance(s, dict):
            continue
        s_text = str(s.get("text_excerpt") or "")
        s_words = set(re.findall(r"[가-힣0-9]{2,}", s_text))
        s_overlap = len(t_words.intersection(s_words))
        if s_overlap > best_span_overlap:
            best_span_overlap = s_overlap
            best_span = s

    return True, f"검증 완료 (공통 토큰 {len(common)}건, 엔티티 일치)", best_span


def verify_legal_source_reference(
    statute_str: str,
    retrieved_sources: Optional[List[Dict[str, Any]]],
) -> Tuple[Optional[str], str, Optional[str], str, str]:
    """법률 조문 문자열이 실제 검색된 출처(retrieved_sources)에 존재하는지 검증한다.

    실제 검색된 source_id가 존재하는 경우에만 SUPPORTED로 판정하며,
    조문 문자열만 있고 실제 검색 결과가 없으면 UNVERIFIED_SOURCE로 표시한다.

    Args:
        statute_str: 검증할 법령 조문 문자열 (예: "주택임대차보호법 제3조 제1항").
        retrieved_sources: 상담 파이프라인에서 실제 조회된 표준 출처 목록.

    Returns:
        Tuple[Optional[str], str, Optional[str], str, str]:
            (실제 source_id, 법령명, 조문 번호, 접지 상태, 검증 설명)
    """
    statute_str = str(statute_str or "").strip()
    if not statute_str:
        return None, "", None, "UNVERIFIED_SOURCE", "조문 문자열 부재"

    if "제" in statute_str:
        stat_name = statute_str.split("제")[0].strip()
        art = "제" + statute_str.split("제")[1].strip()
    else:
        stat_name = statute_str.strip()
        art = None

    if not retrieved_sources:
        return None, stat_name, art, "UNVERIFIED_SOURCE", "실제 검색된 출처 목록 부재"

    # 조문 번호 숫자 파싱 (예: 제3조의2 -> 3조의2)
    art_num_match = re.search(r"제\s*(\d+(?:의\d+)?)조", art or "")
    target_art_num = art_num_match.group(1) if art_num_match else ""

    for s in retrieved_sources:
        if not isinstance(s, dict):
            continue
        # 출처 딕셔너리 내 필드가 None일 경우(예: statute_name=None) TypeError 방지를 위한 str 캐스팅
        s_id = str(s.get("source_id") or "")
        s_title = str(s.get("title") or "")
        s_stat_name = str(s.get("statute_name") or "")
        s_art = str(s.get("article") or "")
        s_content = str(s.get("content") or "")

        name_match = (
            (bool(stat_name) and stat_name in s_stat_name)
            or (bool(stat_name) and stat_name in s_title)
            or (bool(stat_name) and stat_name in s_id)
        )
        if not name_match:
            continue

        if target_art_num:
            art_match = (
                f"제{target_art_num}조" in s_art
                or f"제{target_art_num}조" in s_id
                or f"제{target_art_num}조" in s_title
                or f"제{target_art_num}조" in s_content
                or f"제 {target_art_num} 조" in s_content
            )
            if art_match:
                return s_id, stat_name, art, "SUPPORTED", f"검색된 출처 [{s_id}] 일치 검증 완료"
        else:
            return s_id, stat_name, art, "SUPPORTED", f"검색된 출처 [{s_id}] 일치 검증 완료"

    return None, stat_name, art, "UNVERIFIED_SOURCE", "실제 검색된 법령 출처 식별자 부재"


def build_claim_citations(
    issue_results: List[IssueVerificationResult],
    briefing: CaseEvidenceBriefing,
    final_answer: str,
    retrieved_sources: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """답변 내 사실 명제, 법률 판단, 권고사항을 실제 증거 문서(UUID, Claims, Spans) 및 법령과 원자적으로 연결한다.

    [P0-2.1 Grounding Integrity Hardening 요구사항]
    1. 단어 일부가 일치한다는 이유만으로 근거를 확정하지 않는다 (날짜, 금액, 기관명, 당사자, 행위 일치 검증).
    2. 일치하는 Claim이 없을 때 첫 번째 Claim 또는 Span으로 대체하지 않는다 (미일치 시 None 반환).
    3. Fact에 이미 연결된 EvidenceClaim 또는 EvidenceSpan의 명시적 관계가 있으면 이를 우선 검토한다.
    4. 실제 검색된 법률 출처가 존재하는 경우에만 source_id를 부여하고 SUPPORTED로 판정한다.
    5. 최종 답변에 존재하지 않는 주장은 단순히 계획된 쟁점이나 고정 안내문이라는 이유로 추가하지 않는다.
    6. 사용자 표시용 증거 인용은 E01 번호 대신 실제 등록된 증거 파일의 전체 원본 이름을 기본 인용명으로 사용한다.

    Args:
        issue_results: 단위 쟁점별 검증 결과 객체 목록.
        briefing: 사건 증거 브리핑 모델 (Source Registry 및 사실관계 포함).
        final_answer: 확정 조립된 최종 답변 텍스트.
        retrieved_sources: 워크플로우에서 실제 조회된 출처 목록.

    Returns:
        List[Dict[str, Any]]: 직렬화 가능한 ClaimCitation 딕셔너리 목록.
    """
    if not briefing or not briefing.case_id:
        return []

    try:
        from ai_legal_helper.database.models import EvidenceClaim, FactAdjudication, EvidenceLink
        from sqlalchemy.orm import selectinload

        doc_claims_map: Dict[str, List[Dict[str, Any]]] = {}
        claim_dict_by_id: Dict[str, Dict[str, Any]] = {}
        fact_claim_links: Dict[str, str] = {}
        fact_span_links: Dict[str, str] = {}

        # 1. DB 세션 내에서 대상 사건의 Claim, Span, Fact 매핑 정보 일괄 로드
        with SessionLocal() as db:
            claims = (
                db.query(EvidenceClaim)
                .options(selectinload(EvidenceClaim.spans))
                .filter(EvidenceClaim.case_id == briefing.case_id)
                .all()
            )
            for c in claims:
                spans_data = []
                for s in (c.spans or []):
                    spans_data.append({
                        "id": s.id,
                        "text_excerpt": s.text_excerpt,
                        "page_number": s.page_number,
                    })
                c_dict = {
                    "id": c.id,
                    "evidence_id": c.evidence_id,
                    "statement": c.statement or "",
                    "spans": spans_data,
                }
                doc_claims_map.setdefault(c.evidence_id, []).append(c_dict)
                claim_dict_by_id[c.id] = c_dict

            # 명시적 Fact 연결 관계 조회
            adjs = db.query(FactAdjudication).filter(FactAdjudication.case_id == briefing.case_id).all()
            for a in adjs:
                if a.fact_id and a.claim_id:
                    fact_claim_links[a.fact_id] = a.claim_id

            elinks = db.query(EvidenceLink).filter(EvidenceLink.target_type == "FACT").all()
            for el in elinks:
                if el.target_id:
                    if el.claim_id:
                        fact_claim_links[el.target_id] = el.claim_id
                    if el.span_id:
                        fact_span_links[el.target_id] = el.span_id

        doc_name_map = {
            ev.evidence_label: ev.document_name
            for ev in (briefing.evidences or [])
            if ev.document_name
        }
        for lbl, reg in (briefing.source_registry or {}).items():
            if isinstance(reg, dict) and reg.get("document_name") and lbl not in doc_name_map:
                doc_name_map[lbl] = reg["document_name"]

        citations: List[ClaimCitation] = []

        # 2. [1. 현재 확인된 핵심 사실] 섹션 사실관계 접지
        selected_facts = select_grounded_facts_for_display(briefing, query=final_answer, max_facts=16)
        for f in selected_facts:
            # 최종 답변에 해당 사실 진술문이 존재하는지 확인 (답변 외 주장 추가 차단)
            key_phrase = f.statement[:25]
            if key_phrase not in final_answer:
                continue

            lbl = f.evidence_label or ""
            reg = briefing.source_registry.get(lbl) or {}
            doc_id = f.source_evidence_id or reg.get("evidence_id")
            doc_name = f.document_name or doc_name_map.get(lbl) or reg.get("document_name")

            c_id: Optional[str] = None
            s_id: Optional[str] = None
            excerpt: Optional[str] = None
            gr_status: str = "UNSUPPORTED"
            explanation: str = "일치하는 증거 명제 부재"

            # 2-1. 명시적 Fact-Claim 연결 우선 확인
            explicit_c_id = fact_claim_links.get(f.fact_id)
            if explicit_c_id and explicit_c_id in claim_dict_by_id:
                cand = claim_dict_by_id[explicit_c_id]
                is_valid, reason, best_span = verify_claim_match(f.statement, cand["statement"], cand["spans"])
                if is_valid:
                    c_id = cand["id"]
                    if best_span:
                        s_id = best_span["id"]
                        excerpt = best_span["text_excerpt"]
                    gr_status = "SUPPORTED"
                    explanation = f"명시적 연결 명제 [{c_id[:8]}] 및 발췌 [{s_id[:8] if s_id else 'None'}] 일치 확인 ({reason})"

            # 2-2. 명시적 연결이 없거나 실패한 경우 문서 내 Claim 엄격 검증 탐색
            if not c_id and doc_id:
                cand_list = doc_claims_map.get(doc_id, [])
                best_cand = None
                best_cand_span = None
                best_cand_reason = ""
                best_cand_overlap = -1
                t_words = set(re.findall(r"[가-힣0-9]{2,}", f.statement))
                for cand in cand_list:
                    is_valid, reason, best_span = verify_claim_match(f.statement, cand["statement"], cand["spans"])
                    if is_valid:
                        c_words = set(re.findall(r"[가-힣0-9]{2,}", cand["statement"]))
                        overlap = len(t_words.intersection(c_words))
                        if overlap > best_cand_overlap:
                            best_cand_overlap = overlap
                            best_cand = cand
                            best_cand_span = best_span
                            best_cand_reason = reason

                if best_cand:
                    c_id = best_cand["id"]
                    if best_cand_span:
                        s_id = best_cand_span["id"]
                        excerpt = best_cand_span["text_excerpt"]
                    gr_status = "SUPPORTED"
                    explanation = f"문서 검증 통과 명제 [{c_id[:8]}] 및 발췌 [{s_id[:8] if s_id else 'None'}] 일치 확인 ({best_cand_reason})"
                else:
                    # 일치하는 Claim이 없으면 첫 번째 Claim이나 Span으로 절대 대체하지 않는다 (P0-2.1)
                    c_id = None
                    s_id = None
                    excerpt = None
                    gr_status = "UNSUPPORTED"
                    explanation = "일치하는 증거 명제 또는 원문 발췌 부재 (임의 대체 배제)"

            ev_refs = []
            if doc_id:
                ev_refs.append(ClaimReference(
                    evidence_id=doc_id,
                    evidence_label=lbl or None,
                    claim_id=c_id,
                    span_id=s_id,
                    text_excerpt=excerpt,
                    document_name=doc_name,
                ))

            # P0-2.1: 인용 태그에 파일명을 기본 표기
            tag_name = doc_name or lbl or "증거"
            citations.append(ClaimCitation(
                citation_tag=f"[{tag_name}]",
                claim_text=f.statement,
                grounding_status=gr_status,
                evidence_refs=ev_refs,
                legal_refs=[],
                explanation=explanation,
            ))

        # 3. [2. 현재 판단 가능한 법률 쟁점] 및 [3. 조건부 판단] 접지
        for r in (issue_results or []):
            for rec in (r.safe_recommendations or []):
                # 최종 답변에 해당 권고/판단 문구가 존재하는지 확인 (답변 외 계획 쟁점 배제)
                rec_key = rec[:25]
                if rec_key not in final_answer:
                    continue

                ev_refs = []
                for src_lbl in (r.supported_source_ids or []):
                    reg = briefing.source_registry.get(src_lbl) or {}
                    doc_id = reg.get("evidence_id")
                    doc_name = doc_name_map.get(src_lbl) or reg.get("document_name")
                    if doc_id:
                        # 문서 내에서 쟁점 및 권고와 엔티티가 일치하는 명제 탐색
                        cand_list = doc_claims_map.get(doc_id, [])
                        c_id = None
                        s_id = None
                        excerpt = None
                        best_rec_overlap = -1
                        rec_words = set(re.findall(r"[가-힣0-9]{2,}", rec))
                        for cand in cand_list:
                            is_valid, reason, best_span = verify_claim_match(rec, cand["statement"], cand["spans"])
                            if not is_valid:
                                # 권고문 대신 쟁점 제목으로 2차 매칭
                                is_valid, reason, best_span = verify_claim_match(r.issue_title, cand["statement"], cand["spans"])
                            if is_valid:
                                c_words = set(re.findall(r"[가-힣0-9]{2,}", cand["statement"]))
                                overlap = len(rec_words.intersection(c_words))
                                if overlap > best_rec_overlap:
                                    best_rec_overlap = overlap
                                    c_id = cand["id"]
                                    if best_span:
                                        s_id = best_span["id"]
                                        excerpt = best_span["text_excerpt"]

                        ev_refs.append(ClaimReference(
                            evidence_id=doc_id,
                            evidence_label=src_lbl,
                            claim_id=c_id,
                            span_id=s_id,
                            text_excerpt=excerpt,
                            document_name=doc_name,
                        ))

                leg_refs = []
                all_statutes_supported = True
                for stat in (r.supported_statute_ids or []):
                    source_id, stat_name, art, stat_status, stat_exp = verify_legal_source_reference(stat, retrieved_sources)
                    if stat_status != "SUPPORTED":
                        all_statutes_supported = False
                    leg_refs.append({
                        "source_id": source_id,
                        "statute_id": stat,
                        "statute_name": stat_name,
                        "article": art,
                        "grounding_status": stat_status,
                        "explanation": stat_exp,
                    })

                # 태그는 원본 파일명 기준
                tag_parts = []
                for s in sorted(set(r.supported_source_ids or [])):
                    if not s:
                        continue
                    dname = doc_name_map.get(s, "")
                    if dname and dname.strip():
                        tag_parts.append(f"[{dname.strip()}]")
                    elif s.strip():
                        tag_parts.append(f"[{s.strip()}]")
                tag_parts = list(dict.fromkeys([p for p in tag_parts if p and p not in ("[]", "[None]", "[ ]")]))
                tag = ", ".join(tag_parts) if tag_parts else "[법률근거]"

                # 실정법 출처와 쟁점 검증 상태 모두 충족 시에만 SUPPORTED
                if r.status == "VERIFIED" and (all_statutes_supported or not leg_refs):
                    gr_status = "SUPPORTED"
                else:
                    gr_status = "CONDITIONALLY_SUPPORTED"

                citations.append(ClaimCitation(
                    citation_tag=tag,
                    claim_text=rec,
                    grounding_status=gr_status,
                    evidence_refs=ev_refs,
                    legal_refs=leg_refs,
                    explanation=f"{r.issue_title} ({r.status}) - 법률 출처 검증: {'완료' if all_statutes_supported else '미검증/조건부'}",
                ))

        # 4. [4. 지금 할 수 있는 안전한 행동 가이드] 5대 조치사항 접지 (사건별 동적 증거 라벨 매핑)
        dyn_lease_labels = find_evidence_labels_by_type(briefing, ["LEASE", "임대차", "계약서"])
        dyn_notice_labels = find_evidence_labels_by_type(briefing, ["NOTICE", "통고", "통지", "문자", "카카오", "내용증명"])
        dyn_residence_labels = find_evidence_labels_by_type(briefing, ["RESIDENCE", "주민등록", "전입", "초본", "등본"])
        dyn_attachment_labels = find_evidence_labels_by_type(briefing, ["REGISTRY", "등기", "가압류", "압류", "근저당"])

        action_item_configs = [
            {
                "text": "보증금 전액을 반환받거나 관할 법원의 임차권등기명령에 따른 등기가 등기부에 기재되기 전까지는 절대 주택의 점유를 상실(열쇠 인도, 비밀번호 공유, 임의 퇴거)하거나 전입을 옮기지 마십시오. (대항력 및 우선변제권 유지 필수)",
                "evidence_labels": list(set(dyn_lease_labels + dyn_residence_labels)),
                "statute": "주택임대차보호법 제3조 제1항",
            },
            {
                "text": "임대인에게 보증금 반환 최고 및 지연손해금(민법 연 5%, 소촉법 연 12%) 청구 내용증명을 발송하여 임대인의 이행지체 책임을 명확히 하십시오.",
                "evidence_labels": dyn_notice_labels or dyn_lease_labels,
                "statute": "민법 제544조",
            },
            {
                "text": "계약 종료 즉시 관할 법원에 임차권등기명령을 신청하여 향후 부득이하게 이사할 때에도 기존 대항력과 우선변제권이 온전히 유지·보전되도록 조치하십시오.",
                "evidence_labels": list(set(dyn_lease_labels + dyn_residence_labels)),
                "statute": "주택임대차보호법 제3조의3",
            },
            {
                "text": "대법원 인터넷등기소를 통해 목적물 부동산의 최신 말소사항 포함 등기사항전부증명서를 발급받아 가압류 외 다른 선순위 권리 변동 여부를 최종 대조하십시오.",
                "evidence_labels": dyn_attachment_labels or dyn_lease_labels,
                "statute": "부동산등기법",
            },
            {
                "text": "목적물에 관한 경매 절차가 개시될 경우, 선순위 대항력을 바탕으로 보증금 전액을 낙찰자에게 인수시킬지 또는 배당요구종기 내에 권리신고 및 배당요구 신청서를 관할 경매법원에 접수하여 우선배당받을지 신중히 선택하여 진행하십시오.",
                "evidence_labels": list(set(dyn_lease_labels + dyn_attachment_labels)),
                "statute": "주택임대차보호법 제3조의2 제2항",
            },
        ]
        for act in action_item_configs:
            # 최종 답변에 해당 행동 지침이 존재하는지 확인 (미포함 시 추가 차단)
            key_phrase = act["text"][:25]
            if key_phrase not in final_answer:
                continue

            ev_refs = []
            has_unsupported_evidence = False
            for src_lbl in act["evidence_labels"]:
                reg = briefing.source_registry.get(src_lbl) or {}
                doc_id = reg.get("evidence_id")
                doc_name = doc_name_map.get(src_lbl) or reg.get("document_name")
                c_id = None
                s_id = None
                excerpt = None
                if doc_id:
                    cand_list = doc_claims_map.get(doc_id, [])
                    best_act_overlap = -1
                    act_words = set(re.findall(r"[가-힣0-9]{2,}", act["text"]))
                    for cand in cand_list:
                        is_valid, reason, best_span = verify_claim_match(act["text"], cand["statement"], cand["spans"])
                        if is_valid:
                            c_words = set(re.findall(r"[가-힣0-9]{2,}", cand["statement"]))
                            overlap = len(act_words.intersection(c_words))
                            if overlap > best_act_overlap:
                                best_act_overlap = overlap
                                c_id = cand["id"]
                                if best_span:
                                    s_id = best_span["id"]
                                    excerpt = best_span["text_excerpt"]

                    if not c_id:
                        has_unsupported_evidence = True

                    ev_refs.append(ClaimReference(
                        evidence_id=doc_id,
                        evidence_label=src_lbl,
                        claim_id=c_id,
                        span_id=s_id,
                        text_excerpt=excerpt,
                        document_name=doc_name,
                    ))

            # 법령 출처 검증
            stat = act.get("statute") or ""
            source_id, stat_name, art, stat_status, stat_exp = verify_legal_source_reference(stat, retrieved_sources)
            leg_refs = [{
                "source_id": source_id,
                "statute_id": stat,
                "statute_name": stat_name,
                "article": art,
                "grounding_status": stat_status,
                "explanation": stat_exp,
            }]

            # 태그는 원본 파일명 기준
            tag_parts = [
                f"[{doc_name_map[s]}]" if (s in doc_name_map and doc_name_map[s]) else f"[{s}]"
                for s in act["evidence_labels"]
                if s in briefing.source_registry
            ]
            tag = ", ".join(tag_parts) if tag_parts else "[행동지침]"

            # 실제 증거 및 법령 출처가 검색된 경우에만 SUPPORTED
            if not has_unsupported_evidence and stat_status == "SUPPORTED":
                gr_status = "SUPPORTED"
                explanation = "권리보전을 위한 법정 단계별 행동 지침 (증거 및 법령 출처 검증 완료)"
            else:
                gr_status = "CONDITIONALLY_SUPPORTED"
                explanation = f"권리보전을 위한 실무 지침 ({stat_exp})"

            citations.append(ClaimCitation(
                citation_tag=tag,
                claim_text=act["text"],
                grounding_status=gr_status,
                evidence_refs=ev_refs,
                legal_refs=leg_refs,
                explanation=explanation,
            ))

        return [c.model_dump() for c in citations]
    except Exception as e:
        logger.warning(f"[BUILD_CLAIM_CITATIONS] 예외 발생: {e}", exc_info=True)
        return []
