"""상담 원질문의 자료 검토 의도와 실제 반환 진술을 구분한다.

의도 분류와 사건 변동 감지가 같은 기준을 사용하도록 외부 호출 없는 규칙을 제공한다.
내부 재작성 질의는 사용자가 하지 않은 거래 진술의 근거로 사용하지 않는다.
"""

import re


def has_repayment_assertion(question: str) -> bool:
    """사용자가 실제로 반환받았다는 긍정 진술을 했는지 보수적으로 검사한다.

    Args:
        question: 사용자가 입력한 원질문. LLM 재작성 문장을 전달하지 않는다.

    Returns:
        임대인 측 지급 또는 임차인 측 반환 수령이 과거 사실로 진술된 경우 True.
    """
    # 질문·부정·조건부 문장과 최초 보증금 지급은 새 반환 사실이 아니다.
    # 날짜의 마침표는 보존하여 '임대인이 2026.10.20 입금했다'의 행위자를 잃지 않는다.
    for sentence in re.split(r"(?<=[!?。\n])|(?<!\d)\.(?!\d)", question or ""):
        if re.search(r"(?:\?|나요|는지|을까|여부|않|못|없|라면|경우|안\s*(?:입금|송금|반환))", sentence):
            continue
        if re.search(r"임대인(?:에게|한테)|집주인(?:에게|한테)", sentence):
            continue
        if re.search(r"(?:돌려받|반환받|변제받)(?:았|은)", sentence):
            return True
        # 행위자가 임차인인 송금은 최초 지급이며 반환받은 거래로 해석하지 않는다.
        if re.search(r"(?:임차인|세입자)(?:이|은|가).*(?:입금|송금|지급)", sentence):
            continue
        has_return_direction = bool(re.search(r"임대인|집주인|반환|변제|돌려|갚|(?:제|내)\s*계좌", sentence))
        if has_return_direction and re.search(
            r"(?:입금|송금|변제|반환|지급)(?:했|하였|하셨|됐다|되었)|돌려(?:줬|주었)|갚(?:았|아줬)",
            sentence,
        ):
            return True
    return False


def is_evidence_review_request(question: str) -> bool:
    """새 반환 진술을 포함하지 않은 등록 자료 분석 요청인지 판별한다.

    Args:
        question: 사용자 원질문.

    Returns:
        문서·증거를 대상으로 분석·정리·확인을 요청한 경우 True.
    """
    return (
        bool(re.search(r"계약서|자료|증거|문서", question or ""))
        and bool(re.search(r"분석|정리|검토|확인", question or ""))
        and not has_repayment_assertion(question)
    )


def is_conditional_contract_statement(statement: str) -> bool:
    """일반 의무·조건·예정·부정 문장을 실제 종료 사건과 구분한다.

    Args:
        statement: 문서에서 추출한 사실 또는 조항의 문장.

    Returns:
        현재 실제 발생 사실로 사용하면 안 되는 문장인 경우 True.
    """
    return bool(re.search(
        r"(?:종료|만료|해지)\s*(?:시(?:에는|에|는)?\b|할\s*경우|되면|한다면)|"
        r"(?:종료|만료|해지).{0,12}(?:않|못|없|예정|미정)|"
        r"(?:하여야|해야|할 의무|따른다|의무가 있다)",
        statement or "",
    ))
