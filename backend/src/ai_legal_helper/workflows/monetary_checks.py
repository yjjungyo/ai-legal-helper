"""상담 답변에 명시된 원화 덧셈·뺄셈의 계산 오류를 검출한다.

청구권이나 실제 지급 여부는 판단하지 않는다. 명시적인 산식만 Decimal로 검산하며,
지원하지 않는 표기는 추측하지 않고 기존 근거 검증기에 맡긴다.
"""

import re
from decimal import Decimal

_AMOUNT = r"\d[\d,]*(?:\.\d+)?\s*(?:억|만)?\s*원"
_EQUATION = re.compile(rf"(?<![\d,.])({_AMOUNT}(?:\s*[+−-]\s*{_AMOUNT})+)\s*=\s*({_AMOUNT})")


def _won(value: str) -> Decimal:
    """원·만원·억원으로 명시된 단일 숫자를 원 단위로 변환한다."""
    number = Decimal(re.search(r"\d[\d,]*(?:\.\d+)?", value)[0].replace(",", ""))
    return number * (100_000_000 if "억" in value else 10_000 if "만" in value else 1)


def invalid_monetary_equations(answer: str) -> list[str]:
    """명시된 원화 산식 중 계산이 맞지 않는 원문 구간을 반환한다.

    Args:
        answer: 작성된 답변 원문. 마크다운 강조 기호는 계산 구문에서만 무시한다.

    Returns:
        불일치 산식 목록. 미지원 표기나 산식 부재는 금액의 정확성을 보증하지 않는다.
    """
    invalid = []
    for match in _EQUATION.finditer((answer or "").replace("**", "")):
        parts = re.split(r"\s*([+−-])\s*", match[1])
        total = _won(parts[0])
        for operator, amount in zip(parts[1::2], parts[2::2]):
            total += _won(amount) if operator == "+" else -_won(amount)
        if total != _won(match[2]):
            invalid.append(match[0])
    return invalid
