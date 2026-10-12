# -*- coding: utf-8 -*-
"""
모듈명: logging_config.py

[모듈 개요]
구조화된 JSON 로그 포맷터 및 시스템 로깅 설정을 제공하는 모듈이다.
모든 로그 레코드에 한국 표준시(KST) 타임스탬프와 Context 추적 메타데이터(trace_id, request_id 등)를 부착한다.

[주요 기능]
1. CustomJsonFormatter: 한국 표준시(KST) ISO 타임스탬프 및 실행 컨텍스트 자동 주입
2. setup_logging: 콘솔(sys.stdout) 및 파일(app.log) 로그 핸들러 구성
3. get_logger: 모듈별 로거 인스턴스 반환
"""
import logging
import sys
import json
from datetime import datetime
from pythonjsonlogger import jsonlogger
from ai_legal_helper.observability.context import get_context_dict
from ai_legal_helper.utils.datetime_utils import KST


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """구조화된 JSON 로그 포맷터로, 한국 표준시(KST) 타임스탬프와 ContextVar 추적 정보를 삽입한다."""

    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)

        ctx = get_context_dict()
        for key, value in ctx.items():
            log_record[key] = value

        # 기본 로그 필드
        log_record['level'] = record.levelname
        # 한국 표준시(KST, UTC+9) ISO 포맷 타임스탬프 적용
        log_record['timestamp'] = datetime.fromtimestamp(record.created, tz=KST).isoformat()


def setup_logging(log_level: str = "INFO"):
    """전역 로깅 설정을 초기화한다.

    Args:
        log_level: 기본 로그 레벨 (기본값: "INFO")
    """
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # 기존 핸들러 제거
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    log_handler = logging.StreamHandler(sys.stdout)
    formatter = CustomJsonFormatter('%(timestamp)s %(level)s %(message)s')
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

    # 파일 핸들러 추가 (UTF-8 인코딩)
    file_handler = logging.FileHandler("app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 외부 라이브러리 노이즈 억제
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def get_logger(name: str):
    """지정된 이름의 로거 객체를 반환한다."""
    return logging.getLogger(name)
