"""상담 답변 경량 Verification 및 부분 교정(Targeted Repair) 모듈.

[역할]
AI가 작성한 법률 답변 초안을 대상으로 불필요한 전체 재작성을 방지하고,
결정론적 Python 규칙 검사를 1차로 수행한 뒤 실제 결함이 있는 문제 문장만
핀포인트로 식별하여 부분 교정(Repair)한다.

[주요 기능]
1. 결정론적 경량 검사 (출처 존재, 날짜·금액 일치, 질문 요구 충족, 법률 위험 단정 여부).
2. 선택적 LLM 검증 필요성 판정 (단순 법령 질의는 LLM 호출 없이 즉시 PASS).
3. 4단계 결과 분류 (PASS, REPAIR, NEED_SOURCE, BLOCK).
4. 문제 문장 타겟 부분 교정 (정상 문장 100% 보존).
5. 지시서 5.8 표준 로깅 규격([ANSWER_QA], [ANSWER_REPAIR]) 준수.

[데이터 흐름]
draft_answer → check_deterministic_qa → [PASS: 즉시 전달]
                                     → [REPAIR: repair_draft_answer(문제 문장 치환) → 재검증]
                                     → [NEED_SOURCE: 법령 보강]
                                     → [BLOCK: 위험 주장 차단/보류]

[참고 규범]
CODING_COMMENT_STANDARD.md, AGENTS.md, 상담 답변 품질 및 사용자 UX 개선 개발지시서 v1.0 STEP 5.
"""

import re
import os
import time
import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.rag.source_schema import normalize_source_dict
from ai_legal_helper.agents.verification import audit_citations_and_claims

logger = get_logger(__name__)

# 위험한 법률 효과 단정 표현 패턴 (통지 도달 전 확정 종료, 무조건 승소 등)
UNCONFIRMED_TERMINATION_PATTERNS = [
    re.compile(
        r"(\d{4}[년\.\-]\s*\d{1,2}[월\.\-]\s*\d{1,2}일?)(?:에|자로)?\s*(?:[가-힣A-Za-z0-9_]+\s*)*(?:완전히|확정적으로)?\s*(?:종료됩니다|해지됩니다|소멸합니다|끝납니다)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:즉시|무조건|당연히|바로)\s*(?:[가-힣A-Za-z0-9_]+\s*)*(?:종료|해지|효력|반환받을\s*수\s*있|반환|승소)", re.IGNORECASE),
]

# 브래킷 출처 ID 패턴 (예: [E01], [E99], [STATUTE-001])
BRACKET_SOURCE_ID_PATTERN = re.compile(
    r"\[\s*([E|e]\d{1,3}|STATUTE-[A-Za-z0-9_\-]+)\s*\]"
)

# 통지 도달/수령 조건부 설명 표기 패턴
RECEIPT_CONDITIONAL_PATTERNS = [
    "도달한 날부터", "도달한 때부터", "받은 날부터", "통지가 도달해야", "송달되어야", "수령한 날"
]


class RepairTarget(BaseModel):
    """부분 교정이 필요한 특정 문장 및 수정 지침 스키마."""
    sentence_index: int = Field(description="초안 내 문장 인덱스 (0-based)")
    original_sentence: str = Field(description="문제가 발견된 원문 문장")
    repair_reason: str = Field(description="수정이 필요한 구체적 이유")
    recommended_fix: Optional[str] = Field(default=None, description="권장 대체 표현 또는 수정 지침")


class QACheckResult(BaseModel):
    """경량 QA 검사 종합 결과 스키마."""
    status: str = Field(default="PASS", description="PASS, REPAIR, NEED_SOURCE, BLOCK 중 하나")
    reason_code: str = Field(default="NONE", description="오류 또는 처분 사유 코드")
    source_check_passed: bool = Field(default=True, description="출처 존재 및 정합성 검사 통과 여부")
    date_amount_passed: bool = Field(default=True, description="날짜 및 금액 일치 검사 통과 여부")
    question_coverage_passed: bool = Field(default=True, description="사용자 질문 요청 항목 충족 여부")
    question_items_total: int = Field(default=1, description="질문 속 식별된 요청 항목 수")
    question_items_answered: int = Field(default=1, description="초안에서 답변된 요청 항목 수")
    legal_risk_passed: bool = Field(default=True, description="위험한 법률 단정 배제 여부")
    requires_llm_eval: bool = Field(default=False, description="선택적 심층 LLM 검증 필요 여부")
    llm_eval_reasons: List[str] = Field(default_factory=list, description="LLM 추가 검토 사유 목록")
    repair_targets: List[RepairTarget] = Field(default_factory=list, description="부분 교정 대상 문장 목록")
    preserved_points: List[str] = Field(default_factory=list, description="수정 시에도 반드시 보존할 정상 판단/문장")
    missing_statutes: List[str] = Field(default_factory=list, description="누락된 필수 법령 목록")
    candidate_laws: List[str] = Field(default_factory=list, description="추천 후보 법령 목록")
    citation_audit: Dict[str, Any] = Field(default_factory=dict, description="상세 출처 감사 결과")


def split_into_sentences(text: str) -> List[str]:
    """답변 본문을 문장 단위로 분할하되 번호 매김 및 불릿을 보존한다.

    Args:
        text: 분할할 본문 텍스트.

    Returns:
        List[str]: 분할된 문장/항목 문자열 리스트.
    """
    if not text:
        return []

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    sentences: List[str] = []

    for line in lines:
        # 번호 매김(1., 2.) 또는 불릿(-, *)으로 시작하는 항목은 통째로 하나의 단위로 취급
        if re.match(r"^(\d+[\.\)]|[-*•])\s+", line):
            # 항목 내부에서 마침표로 끝나는 여러 문장이 있을 수 있으므로 세부 분할
            sub_parts = re.split(r"(?<=[.!?])\s+", line)
            for sp in sub_parts:
                sp_clean = sp.strip()
                if sp_clean:
                    sentences.append(sp_clean)
        else:
            sub_parts = re.split(r"(?<=[.!?])\s+", line)
            for sp in sub_parts:
                sp_clean = sp.strip()
                if sp_clean:
                    sentences.append(sp_clean)

    return sentences


def extract_question_demands(question: str) -> List[str]:
    """사용자 질문에서 복합 요구 항목을 식별한다.

    예: '계약은 어떤 상태인가요? 그리고 종료하려면 어떻게 해야 하나요?' -> ['상태', '종료']

    Args:
        question: 사용자 원본 질문 문자열.

    Returns:
        List[str]: 식별된 세부 요청 항목 설명 리스트.
    """
    if not question:
        return ["질문 내용 답변"]

    clean_q = question.strip()
    demands: List[str] = []

    # 1. 명시적 물음표(?), 접속사(그리고, 또한, 및), 쉼표 분할
    clauses = re.split(r"[?!\n]|(?:\s*,\s*)|(?:\s+(?:그리고|또한|및)\s+)", clean_q)
    for c in clauses:
        c_str = c.strip()
        if len(c_str) >= 4:
            demands.append(c_str)

    if not demands:
        demands = [clean_q]

    return demands[:4]  # 최대 4개 요구사항


def check_deterministic_qa(
    question: str,
    draft_answer: str,
    retrieved_sources: List[Dict[str, Any]],
    case_context: str = "",
) -> QACheckResult:
    """초안 답변을 대상으로 결정론적 규칙 기반 경량 검사를 수행한다.

    [검사 항목]
    1. 출처 존재 여부 (Source Registry와 인용 ID/파일명 대조).
    2. 날짜·금액 일치 여부 (사건 맥락 수치와 초안 수치 충돌 검사).
    3. 질문 요구 항목 충족 여부 (다중 질문 항목 매핑).
    4. 법률 단정 및 위험 표현 검사 (통지 도달 미확인 상태의 종료 확정 등).
    5. 선택적 LLM 검증 필요성 판정.

    Args:
        question: 사용자 원문 질문.
        draft_answer: 작성된 답변 초안.
        retrieved_sources: 검색된 공식 출처 목록.
        case_context: 사건 정보, 사실관계, 증거 브리핑.

    Returns:
        QACheckResult: 상세 검사 결과 및 처분 분기 정보.
    """
    logger.info(f"[ANSWER_QA] 검사 시작 (초안길이: {len(draft_answer)}자 | 질문: '{question[:60]}...')")

    sentences = split_into_sentences(draft_answer)
    repair_targets: List[RepairTarget] = []
    preserved_points: List[str] = []
    llm_eval_reasons: List[str] = []

    # 1. 출처 존재 검사 (audit_citations_and_claims + BRACKET_SOURCE_ID_PATTERN 검사)
    audit = audit_citations_and_claims(draft_answer, retrieved_sources, case_context=case_context)
    unverified_cits = list(audit.get("unverified_citations", []))
    unsupported_cits = list(audit.get("unsupported_citations", []))
    rejected_ids = set(audit.get("rejected_citation_ids", []))

    # 직접 인용된 [E01], [E99], [STATUTE-001] 등의 브래킷 ID가 실제 출처에 존재하는지 검사
    known_source_ids = {
        str(s.get("source_id") or "").lower() for s in (retrieved_sources or []) if s.get("source_id")
    }
    for m in BRACKET_SOURCE_ID_PATTERN.finditer(draft_answer):
        raw_id = m.group(1).strip()
        if raw_id.lower() not in known_source_ids:
            bracket_repr = f"[{raw_id}]"
            if bracket_repr not in unverified_cits:
                unverified_cits.append(bracket_repr)
            rejected_ids.add(raw_id)

    source_check_passed = len(unverified_cits) == 0 and len(rejected_ids) == 0

    if source_check_passed:
        logger.info(f"[ANSWER_QA] 출처 존재 검사: PASS (인용출처: {len(audit.get('retrieval_source_ids', []))}건 정상)")
    else:
        logger.warning(
            f"[ANSWER_QA] 출처 존재 검사: FAILED (미검증: {unverified_cits}, 거절ID: {list(rejected_ids)})"
        )
        # 미검증 인용이 포함된 문장 식별
        for idx, sent in enumerate(sentences):
            found_bad_cits = [c for c in unverified_cits if c in sent]
            found_rej_ids = [rid for rid in rejected_ids if rid in sent]
            if found_bad_cits or found_rej_ids:
                repair_targets.append(
                    RepairTarget(
                        sentence_index=idx,
                        original_sentence=sent,
                        repair_reason=f"출처 목록에 등록되지 않은 허위/미검증 인용({found_bad_cits or found_rej_ids}) 포함",
                        recommended_fix="허위 인용 표기를 제거하거나 실제 검색된 출처로 대체하세요.",
                    )
                )

    # 2. 날짜·금액 일치 검사
    date_amount_passed = True
    # 사건 맥락에서 보증금 금액 추출 (예: 3억 원, 2억 2천만 원)
    deposit_matches = re.findall(r"(\d+(?:억|\s*억)?(?:\s*\d+천)?만?\s*원)", case_context)
    if deposit_matches:
        known_deposit = deposit_matches[0].replace(" ", "")
        # 초안에서 언급된 보증금 표현 확인
        draft_deposits = re.findall(r"보증금\s*(?:은|이|으로)?\s*(\d+(?:억|\s*억)?(?:\s*\d+천)?만?\s*원)", draft_answer)
        for dd in draft_deposits:
            dd_clean = dd.replace(" ", "")
            if dd_clean != known_deposit and ("억" in known_deposit and "억" in dd_clean):
                date_amount_passed = False
                logger.warning(f"[ANSWER_QA] 금액 모순 감지: 사건금액({known_deposit}) != 답변금액({dd_clean})")
                for idx, sent in enumerate(sentences):
                    if dd in sent:
                        repair_targets.append(
                            RepairTarget(
                                sentence_index=idx,
                                original_sentence=sent,
                                repair_reason=f"사건의 실제 보증금({known_deposit})과 불일치하는 금액({dd_clean}) 기재",
                                recommended_fix=f"금액을 실제 사건 정보인 {known_deposit}으로 정정하세요.",
                            )
                        )

    if date_amount_passed:
        logger.info("[ANSWER_QA] 날짜·금액 검사: PASS")
    else:
        logger.warning("[ANSWER_QA] 날짜·금액 검사: FAILED")

    # 3. 질문 요청 항목 충족 검사
    demands = extract_question_demands(question)
    demands_total = len(demands)
    demands_answered = 0
    missing_demands: List[str] = []

    for d in demands:
        # 요구 구문의 주요 명사/동사 토큰 추출
        tokens = [t for t in re.findall(r"[가-힣a-zA-Z0-9]{2,}", d) if t not in ("어떻게", "언제", "무엇", "있나요", "인가요", "경우")]
        if not tokens:
            demands_answered += 1
            continue
        # 초안에 토큰이 하나 이상 언급되었는지 확인
        matched = any(tok in draft_answer for tok in tokens)
        if matched:
            demands_answered += 1
        else:
            missing_demands.append(d)

    question_coverage_passed = (demands_answered >= demands_total) or (demands_answered >= 1 and demands_total <= 2)
    logger.info(f"[ANSWER_QA] 질문 충족: {demands_answered}/{demands_total} (누락항목: {missing_demands or '없음'})")

    if not question_coverage_passed and missing_demands:
        llm_eval_reasons.append(f"질문 속 요청 항목('{missing_demands[0]}') 미답변")

    # 4. 법률 적용 위험 검사 (통지 도달 전 확정 종료 단정 등)
    legal_risk_passed = True
    has_receipt_evidence = any(kw in case_context for kw in ("도달 완료", "배달증명", "수령 완료", "확정 도달"))

    for idx, sent in enumerate(sentences):
        # 해당 문장에 자체 조건부 설명(도달한 때부터 등)이 포함되어 있다면 안전함
        sent_is_conditional = any(kw in sent for kw in RECEIPT_CONDITIONAL_PATTERNS)
        if not has_receipt_evidence and not sent_is_conditional:
            for pat in UNCONFIRMED_TERMINATION_PATTERNS:
                m = pat.search(sent)
                if m:
                    legal_risk_passed = False
                    logger.warning(f"[ANSWER_QA] 법률 적용 위험 감지: 도달일 미확인 상태의 종료일 확정 단정 -> '{sent}'")
                    repair_targets.append(
                        RepairTarget(
                            sentence_index=idx,
                            original_sentence=sent,
                            repair_reason="해지 통지 도달일이 객관적으로 확인되지 않았는데 종료일을 확정하여 단정함",
                            recommended_fix="도달일을 기준으로 3개월 뒤 효력이 발생한다는 조건부 설명으로 수정하세요.",
                        )
                    )
                    llm_eval_reasons.append("해지 효력 발생일의 법률요건 적용 (통지 도달 확인 전제 필요)")
                    break

    if legal_risk_passed:
        logger.info("[ANSWER_QA] 법률 적용 위험 검사: PASS")
    else:
        logger.warning("[ANSWER_QA] 법률 적용 위험 검사: REVIEW_REQUIRED")

    # 5. 정상 문장(보존할 판단) 식별
    problematic_indices = {rt.sentence_index for rt in repair_targets}
    for idx, sent in enumerate(sentences):
        if idx not in problematic_indices and len(sent) >= 10:
            preserved_points.append(sent)

    # 6. 선택적 LLM 검증 필요성 판정 (지시서 5.4)
    # 단순 법령 질의 여부 엄격 판정:
    # 1) 사건 맥락(case_context)이 없어야 함
    # 2) 검색 출처에 사건 증거(CASE_EVIDENCE 또는 txt/pdf/docx 파일)가 없어야 함 (오직 STATUTE만 존재)
    # 3) 질문 및 초안에 권리 변동/소멸/우선순위(가압류, 배당, 경매, 손해배상 등) 복합 법률 키워드가 없어야 함
    # 4) 초안에 실제 공식 법령 조문 인용이 적어도 1건 이상 존재해야 함
    has_case_evidence_source = any(
        s.get("source_type") == "CASE_EVIDENCE"
        or any(ext in str(s.get("source_id", "")).lower() for ext in (".txt", ".pdf", ".docx", ".png", ".jpg"))
        for s in (retrieved_sources or [])
    )
    has_statute_source = any(
        s.get("source_type") == "STATUTE" or "statute" in str(s.get("source_id", "")).lower()
        for s in (retrieved_sources or [])
    )
    complex_legal_kws = ("가압류", "압류", "경매", "배당", "우선순위", "우선변제", "소멸", "손해배상", "불법행위", "상계")
    has_complex_rights = any(kw in question or kw in draft_answer for kw in complex_legal_kws)

    is_pure_statute_query = (
        (not case_context or case_context.strip() in ("(사건 맥락 없음)", "(사건 정보 없음)"))
        and not has_case_evidence_source
        and has_statute_source
        and not has_complex_rights
        and len(audit.get("retrieval_source_ids", [])) > 0
        and source_check_passed
        and date_amount_passed
        and legal_risk_passed
    )

    requires_llm_eval = False
    if is_pure_statute_query and question_coverage_passed:
        # 단순 법령 질의이면서 조문이 완벽히 인용되고 검사 통과 시 LLM 재검증 생략!
        requires_llm_eval = False
        logger.info("[ANSWER_QA] 단순 법령 질의 및 결정론적 검사 통과: LLM 추가 검증 생략 (조기 PASS)")
    else:
        # 사건 상담, 복합 권리관계, 증거 대조 등은 반드시 선택적 심층 LLM 검증 수행
        requires_llm_eval = True
        if has_complex_rights:
            llm_eval_reasons.append("법적 권리의 발생·소멸·우선순위 복합 법률요건 적용 검토")
        if has_case_evidence_source or (case_context and len(case_context) > 20):
            llm_eval_reasons.append("사건 사실관계 및 증거 기반 법률요건 검증")
        if not legal_risk_passed:
            llm_eval_reasons.append("법률 적용 위험 단정 표현 정밀 심사")
        if not question_coverage_passed:
            llm_eval_reasons.append("질문 요청 항목 충족 여부 심층 검토")
        if len(repair_targets) > 0:
            llm_eval_reasons.append("부분 교정 대상 문장 식별 및 교체 지침 검토")

    if llm_eval_reasons:
        logger.info(f"[ANSWER_QA] LLM 추가 검토 사유:\n  - " + "\n  - ".join(llm_eval_reasons))

    if repair_targets:
        logger.info(f"[ANSWER_QA] 수정이 필요한 주장:\n  - " + "\n  - ".join([f"{rt.repair_reason} (문장 #{rt.sentence_index+1})" for rt in repair_targets]))

    # 상태 결정
    status = "PASS"
    reason_code = "NONE"

    if not source_check_passed and unverified_cits:
        status = "REPAIR"
        reason_code = "CITATION_INVALID"
    elif not date_amount_passed:
        status = "REPAIR"
        reason_code = "FACT_MISMATCH"
    elif not legal_risk_passed:
        status = "REPAIR"
        reason_code = "LEGAL_APPLICATION_ERROR"
    elif not question_coverage_passed:
        status = "REPAIR"
        reason_code = "QUESTION_UNANSWERED"

    return QACheckResult(
        status=status,
        reason_code=reason_code,
        source_check_passed=source_check_passed,
        date_amount_passed=date_amount_passed,
        question_coverage_passed=question_coverage_passed,
        question_items_total=demands_total,
        question_items_answered=demands_answered,
        legal_risk_passed=legal_risk_passed,
        requires_llm_eval=requires_llm_eval,
        llm_eval_reasons=llm_eval_reasons,
        repair_targets=repair_targets,
        preserved_points=preserved_points,
        citation_audit=audit,
    )


def repair_draft_answer(
    draft_answer: str,
    repair_targets: List[RepairTarget],
    preserved_points: List[str],
    case_context: str = "",
    retrieved_sources: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """문제가 지적된 문장만 핀포인트로 교체하고 정상 문장과 핵심 판단은 100% 보존한다.

    [부분 교정 원칙]
    1. 전체 답변을 처음부터 다시 작성하지 않는다.
    2. 문제가 된 문장(Target Sentences)만 LLM 또는 규칙으로 안전하게 치환한다.
    3. 보존 대상 문장(Preserved Points)은 원형 그대로 유지한다.
    4. 지시서 5.8 필수 로깅 규격을 출력한다.

    Args:
        draft_answer: 원본 초안 텍스트.
        repair_targets: 교정이 필요한 문장 목록.
        preserved_points: 유지할 정상 판단/문장 목록.
        case_context: 사건 정보 및 브리핑.
        retrieved_sources: 인용 가능한 공식 출처 목록.

    Returns:
        Tuple[str, Dict[str, Any]]: (부분 교정된 최종 답변, 교정 메타데이터).
    """
    start_time = time.time()
    logger.info("[ANSWER_REPAIR] 수정 시작")
    logger.info(f"[ANSWER_REPAIR] 수정 범위: 특정 문장 {len(repair_targets)}건")
    logger.info(f"[ANSWER_REPAIR] 유지할 판단: {len(preserved_points)}건")

    if not repair_targets:
        logger.info("[ANSWER_REPAIR] 교정 대상 문장이 없어 원본 초안 유지")
        return draft_answer, {"repaired": False, "target_count": 0}

    # 문장 교정 딕셔너리 구성 (original -> replaced)
    replacements: Dict[str, str] = {}

    from ai_legal_helper.llm.gateway import get_llm
    from langchain_core.prompts import PromptTemplate

    llm = get_llm(temperature=0.0)

    # 각 문제 문장에 대해 개별 교정 생성
    for rt in repair_targets:
        prompt = PromptTemplate.from_template(
            "당신은 법률 답변 부분 교정(Targeted Repair) 전문가입니다.\n"
            "기존 법률 답변 중 아래의 특정 한 문장에 결함이 지적되었습니다.\n"
            "다른 본문이나 양식은 일절 건드리지 말고, 지적된 [수정 이유]를 완벽히 반영하여 "
            "해당 한 문장을 대체할 정확하고 안전한 한 문장(또는 1~2문장의 정정 설명)만 작성하세요.\n\n"
            "[수정 대상 원문]\n{original_sentence}\n\n"
            "[수정 이유 및 지침]\n- {repair_reason}\n- 권장 조치: {recommended_fix}\n\n"
            "[사건 맥락]\n{case_context}\n\n"
            "[작성 규칙]\n"
            "1. 수정 대상 원문만을 교체할 대체 문장만 출력하세요.\n"
            "2. 부가적인 인사말이나 '수정된 문장:' 같은 설명 라벨은 절대 붙이지 마세요.\n"
            "3. 마크다운 특수문자(#, **, > 등)를 사용하지 마세요.\n"
            "4. 확인되지 않은 사실을 단정하지 말고 조건부(~할 경우, 도달 시)로 설명하세요."
        )
        try:
            formatted_prompt = prompt.format(
                original_sentence=rt.original_sentence,
                repair_reason=rt.repair_reason,
                recommended_fix=rt.recommended_fix or "사건 맥락에 부합하도록 교정",
                case_context=case_context[:500] or "(사건 맥락 없음)",
            )
            res = llm.invoke(formatted_prompt)
            raw_val = getattr(res, "content", res)
            replacement_text = str(raw_val).strip()
            # 앞뒤 따옴표 제거
            replacement_text = replacement_text.strip("\"'")
            replacements[rt.original_sentence] = str(replacement_text)
            logger.info(f"[ANSWER_REPAIR] 문장 교체 생성 완료: '{rt.original_sentence[:30]}...' -> '{replacement_text[:30]}...'")
        except Exception as e:
            logger.error(f"[ANSWER_REPAIR] LLM 문장 교체 생성 실패: {e}")
            # 폴백: 권장 조치가 있으면 권장 조치로 치환
            if rt.recommended_fix:
                replacements[rt.original_sentence] = f"(참고) {rt.recommended_fix}"

    # 초안 본문에서 문제 문장만 정확히 교체 (정상 문장 100% 보존)
    repaired_answer = draft_answer
    replaced_count = 0
    for orig, rep in replacements.items():
        if orig in repaired_answer:
            repaired_answer = repaired_answer.replace(orig, rep, 1)
            replaced_count += 1
        else:
            # 부분 문자열 일치 시도
            core_orig = orig[:30]
            for line in repaired_answer.split("\n"):
                if core_orig in line:
                    repaired_answer = repaired_answer.replace(line, rep, 1)
                    replaced_count += 1
                    break

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"[ANSWER_REPAIR] 수정 완료 (소요시간: {elapsed_ms:.1f}ms, 교체된 문장: {replaced_count}/{len(repair_targets)})")

    # 교정 후 안전성 재확인 (지시서 5.8: [ANSWER_QA] 수정 문장 재검증: PASS)
    recheck_audit = audit_citations_and_claims(repaired_answer, retrieved_sources or [], case_context=case_context)
    if not recheck_audit.get("unverified_citations"):
        logger.info("[ANSWER_QA] 수정 문장 재검증: PASS")
    else:
        logger.warning(f"[ANSWER_QA] 수정 문장 재검증: 주의 (미검증 인용 잔존: {recheck_audit.get('unverified_citations')})")

    meta = {
        "repaired": True,
        "target_count": len(repair_targets),
        "replaced_count": replaced_count,
        "elapsed_ms": elapsed_ms,
        "replacements": replacements,
    }
    return repaired_answer, meta
