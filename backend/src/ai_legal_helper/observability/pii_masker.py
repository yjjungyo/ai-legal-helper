# -*- coding: utf-8 -*-
"""
모듈명: pii_masker.py

[모듈 개요]
로그, 모니터링(Langfuse), 진단 아티팩트 등에 기록되는 텍스트에서
주민등록번호, 전화번호, 계좌번호, 이메일, API Key/인증 토큰 등
개인정보(PII) 및 시스템 보안 비밀정보를 안전하게 식별하고 마스킹하는 중앙 유틸리티 모듈.

[주요 기능]
1. `mask_pii(text)`:
   - 주민등록번호: 앞 6자리(생년월일) 유지, 뒷자리 7자리 `*******` 마스킹
   - 전화번호/휴대전화: 010, 02, 지역번호 등 중간 국번 마스킹 (`010-****-1234`)
   - 은행 계좌번호: 숫자-숫자-숫자 패턴 마스킹 (`***-**-******`)
   - 이메일: 아이디 및 도메인 마스킹 (`***@***.***`)
   - API Key/Bearer Token/OpenLaw 인증키: sk-, OC=, Bearer 등 식별자 마스킹
2. `sanitize_diagnostic_text(text, max_len)`:
   - PII 마스킹을 선행한 후, 진단용 텍스트의 길이를 제한하여 로그 과부하 방지
"""

from typing import Optional
import re

# 주민등록번호 패턴 (생년월일 6자리 - 뒷자리 7자리, 구분자 하이픈 또는 공백)
_RRN_PATTERN = re.compile(r"\b(\d{6})[- ]?([1-4]\d{6})\b")

# 일반 전화번호 및 휴대전화 패턴 (010, 02, 031 등)
_PHONE_PATTERN = re.compile(r"\b(01[016789]|02|0[3-6]\d)[- ]?(\d{3,4})[- ]?(\d{4})\b")

# 은행 계좌번호 패턴 (3~6자리 - 2~6자리 - 3~6자리)
_ACCOUNT_PATTERN = re.compile(r"\b(\d{3,6})[- ](\d{2,6})[- ](\d{3,6})\b")

# 이메일 패턴
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# API 키, Bearer 토큰 및 공공 API 인증키 패턴
_API_KEY_PATTERN = re.compile(
    r"\b(sk-[A-Za-z0-9_\-]{20,}|OC=[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9_\-\.]{20,}|api[_-]?key=[\w-]+)\b",
    re.IGNORECASE,
)


def mask_pii(text: Optional[str]) -> str:
    """텍스트 내 주민등록번호, 전화번호, 계좌번호, 이메일, API 키 등 민감정보(PII)를 자동으로 마스킹한다.

    Args:
        text (Optional[str]): 원본 입력 문자열.

    Returns:
        str: 민감정보가 마스킹된 안전한 문자열. None 또는 빈 문자열인 경우 "" 반환.
    """
    if not text:
        return ""

    if not isinstance(text, str):
        text = str(text)

    # 1. 주민등록번호 (생년월일 6자리는 보존하고 뒷자리 7자리를 마스킹)
    cleaned = _RRN_PATTERN.sub(r"\1-*******", text)

    # 2. 전화번호 및 휴대전화 (가운데 번호 마스킹)
    cleaned = _PHONE_PATTERN.sub(r"\1-****-\3", cleaned)

    # 3. 은행 계좌번호 마스킹
    cleaned = _ACCOUNT_PATTERN.sub("***-**-******", cleaned)

    # 4. 이메일 주소 마스킹
    cleaned = _EMAIL_PATTERN.sub("***@***.***", cleaned)

    # 5. API 키 및 인증 토큰 마스킹
    cleaned = _API_KEY_PATTERN.sub("[MASKED_API_KEY]", cleaned)

    return cleaned


def sanitize_diagnostic_text(text: Optional[str], max_len: int = 1500) -> str:
    """진단 로그 및 아티팩트용 텍스트의 PII를 마스킹하고 최대 길이를 안전하게 제한한다.

    Args:
        text (Optional[str]): 로깅할 진단 텍스트.
        max_len (int): 허용할 최대 문자 수 (기본값: 1500자).

    Returns:
        str: 마스킹 및 축약 처리된 문자열.
    """
    if not text:
        return "(없음)"

    masked = mask_pii(text)
    if len(masked) > max_len:
        return masked[:max_len] + f"\n... (총 {len(masked)}자 중 {max_len}자만 표시됨)"
    return masked

