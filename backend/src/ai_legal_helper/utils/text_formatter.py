# -*- coding: utf-8 -*-
"""
모듈명: text_formatter.py

[모듈 개요]
법률 상담 답변 및 검증 결과 텍스트에서 불필요한 원시 마크다운(Raw Markdown) 기호를 정제하고,
정형화된 공문서 및 법률의견서 표준 플레인 텍스트 서식으로 변환하는 서식 정제 유틸리티 모듈이다.

[주요 기능]
1. `clean_markdown_formatting`:
   - `#`, `##`, `###` 마크다운 헤더를 대괄호 섹션 헤더(`[제목]`)로 안전하게 변환
   - `**볼드**`, `*이탤릭*` 기호를 일반 텍스트로 복원
   - `---` 수평선 및 `>` 인용 블록 기호 제거
   - 과도한 연속 빈 줄 축소
2. `format_plain_legal_section`:
   - 섹션명과 내용을 표준 법률 의견서 양식으로 조합
"""
import re


def clean_markdown_formatting(text: str) -> str:
    """마크다운 원시 기호(헤더, 볼드, 이탤릭, 수평선, 인용구)를 정제하여 정형화된 플레인 텍스트로 변환한다.

    프론트엔드에 마크다운 렌더러가 부재하거나 화면에 #, ** 등의 기호가 원시 텍스트로
    그대로 노출되는 문제를 방지하고, 법률의견서에 걸맞은 깔끔한 서식을 보장한다.

    Args:
        text (str): 마크다운 기호가 포함된 원시 텍스트.

    Returns:
        str: 마크다운 기호가 제거되고 정돈된 플레인 텍스트.
    """
    if not text:
        return ""

    # 1. 수평선 (---, ***, ___ 등) 제거
    cleaned = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # 2. 마크다운 헤더 (#, ##, ### 등) -> [헤더명] 대괄호 제목으로 변환
    def _header_replacer(match: re.Match) -> str:
        title = match.group(1).strip()
        # 이미 대괄호로 감싸져 있는 경우 중복 대괄호 방지
        if title.startswith('[') and title.endswith(']'):
            return f"\n{title}\n"
        return f"\n[{title}]\n"

    cleaned = re.sub(r'^#{1,6}\s*(.+)$', _header_replacer, cleaned, flags=re.MULTILINE)

    # 3. 볼드 (**text**, __text__) -> text
    cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'__(.+?)__', r'\1', cleaned)

    # 4. 이탤릭 (*text*, _text_) -> text (인용구 괄호나 다른 표기에 지장 없도록 처리)
    cleaned = re.sub(r'(?<!\*)\*([^\*\n]+)\*(?!\*)', r'\1', cleaned)

    # 5. 인용 블록 (> text) 기호 제거
    cleaned = re.sub(r'^>\s*', '', cleaned, flags=re.MULTILINE)

    # 6. 인라인 백틱 (`code`) 제거
    cleaned = re.sub(r'`([^`\n]+)`', r'\1', cleaned)

    # 7. 연속 3개 이상의 개행을 2개로 압축 및 앞뒤 공백 제거
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

