"""
모듈명: logging_config.py

[모듈 개요]
사람이 직관적으로 디버깅할 수 있는 고가독성 텍스트 로그 포맷터 및 시스템 로깅 설정을 제공한다.
불필요한 null 메타데이터와 중복 출력을 제거하고, 유효한 컨텍스트(trace_id, case_id 등)만 선별 표기한다.
환경변수 LOG_FORMAT에 따라 텍스트 포맷(기본값) 또는 기계 분석용 JSON 포맷을 선택할 수 있다.

[주요 기능]
1. LoguruStyleFormatter: Loguru/Rich 스타일 고가독성 포맷터 (파이프 구분, Multi-Agent 흐름 [Agent >> Node], 콘솔 ANSI 컬러 vs 파일 클린 텍스트)
2. CustomJsonFormatter: 기계 및 로그 수집기(ELK/CloudWatch)용 구조화 JSON 포맷터 (파일명, 라인, 모듈 포함)
3. HttpNoiseFilter: CORS OPTIONS 프리플라이트 및 헬스체크 등 디버깅 방해 노이즈 필터링
4. setup_logging: 콘솔(sys.stdout, colorize=True) 및 일자별 롤링 파일(TimedRotatingFileHandler, colorize=False) 구성
"""
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import sys
from datetime import datetime
from typing import Optional
from pythonjsonlogger import jsonlogger

from ai_legal_helper.observability.context import get_context_dict
from ai_legal_helper.utils.datetime_utils import KST


try:
    import colorama
    colorama.init(autoreset=True)
except Exception:
    pass

# ANSI 컬러 상수 정의 (터미널 가독성 향상)
_RESET = "\033[0m"
_GRAY = "\033[90m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_BOLD_MAGENTA = "\033[1;35m"
_CYAN = "\033[36m"
_BOLD_RED = "\033[1;31m"
_RED = "\033[31m"


class LoguruStyleFormatter(logging.Formatter):
    """Loguru/Rich 스타일의 고가독성 포맷터 (스타일 1, 3, 4 통합).

    1. 대괄호 남발을 줄이고 파이프(|) 구분자를 사용하여 시각적 피로도를 최소화한다.
    2. Multi-Agent(LangGraph) 컨텍스트가 활성화되어 있으면 [Agent >> Node] 흐름을 강조 표기한다.
    3. colorize 플래그에 따라 콘솔에는 ANSI 컬러를, 파일(app.log)에는 순수 텍스트(Clean text)를 출력한다.

    출력 예시:
        2026-10-14 23:26:42.124 | INFO  | 770fee01 | cases.py:61:list_cases     - 사건 목록 조회 완료 (총 3건) [req:7a09d1bd]
        2026-10-14 23:26:43.500 | INFO  | 770fee01 | planner.py:84:plan         - [Planner >> extract_facts] 사실 관계 5건 추출 완료 [case:d54ebb0d]
        2026-10-14 23:26:44.200 | WARN  | 770fee01 | evidence.py:120:extract    - 증거 파일 텍스트 추출 중 [case:d54ebb0d]
        2026-10-14 23:26:45.000 | ERROR | 88b9e683 | manager.py:215:sync        - 데이터베이스 연결 시간 초과 오류 [case:d54ebb0d]
    """

    def __init__(self, colorize: bool = False):
        """포맷터를 초기화한다.

        Args:
            colorize (bool): True일 경우 터미널 콘솔용 ANSI 색상 코드를 적용하고,
                False일 경우 파일 저장용 클린 텍스트를 출력한다.
        """
        super().__init__()
        self.colorize = colorize

    def format(self, record: logging.LogRecord) -> str:
        """로그 레코드를 Loguru 스타일 문자열로 변환한다.

        Args:
            record (logging.LogRecord): 로깅 대상 레코드 객체.

        Returns:
            str: 사람이 직관적으로 읽을 수 있도록 포맷팅된 로그 문자열.
        """
        # 1. 한국 표준시(KST) 밀리초 타임스탬프 (YYYY-MM-DD HH:MM:SS.mmm)
        dt = datetime.fromtimestamp(record.created, tz=KST)
        time_str = dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # 2. 로그 레벨 (5자리 고정폭)
        lvl_name = "WARN" if record.levelname == "WARNING" else record.levelname
        lvl_str = f"{lvl_name:<5}"

        # 3. trace_id 추출 (앞 8자리 단축형, 미발급 시 8자리 하이픈)
        ctx = get_context_dict()
        raw_trace_id = getattr(record, "trace_id", None) or ctx.get("trace_id")
        trace_disp = raw_trace_id[:8] if raw_trace_id else "--------"

        # 4. 소스 위치 및 함수명 (예: cases.py:61:list_cases, 고정폭 28자)
        func = record.funcName
        if func and func != "<module>":
            loc_str = f"{record.filename}:{record.lineno}:{func}"
        else:
            loc_str = f"{record.filename}:{record.lineno}"
        loc_formatted = f"{loc_str:<28}"

        # 5. Multi-Agent / LangGraph 실행 컨텍스트 ([Agent >> Node])
        agent_name = ctx.get("agent_name") or getattr(record, "agent_name", None)
        node_name = ctx.get("node_name") or getattr(record, "node_name", None)
        if agent_name and node_name:
            agent_str = f"[{agent_name} >> {node_name}] "
        elif agent_name:
            agent_str = f"[{agent_name}] "
        elif node_name:
            agent_str = f"[{node_name}] "
        else:
            agent_str = ""

        # 6. 추가 컨텍스트 (case:xxxx, req:xxxx)
        ctx_items = []
        for k in ("case_id", "request_id"):
            val = ctx.get(k) or getattr(record, k, None)
            if val:
                val_str = str(val)
                val_short = val_str[:8] if len(val_str) > 16 else val_str
                label = "case" if k == "case_id" else "req"
                ctx_items.append(f"{label}:{val_short}")
        ctx_suffix = f" [{', '.join(ctx_items)}]" if ctx_items else ""

        # 7. 본문 메시지
        msg = record.getMessage()

        # 8. 색상 적용 (콘솔 vs 파일 분기)
        if self.colorize:
            pipe = f"{_GRAY}|{_RESET}"
            hyphen = f"{_GRAY}-{_RESET}"
            # 레벨별 컬러 매핑
            if lvl_name == "INFO":
                lvl_colored = f"{_GREEN}{lvl_str}{_RESET}"
            elif lvl_name == "WARN":
                lvl_colored = f"{_YELLOW}{lvl_str}{_RESET}"
            elif lvl_name in ("ERROR", "CRITICAL"):
                lvl_colored = f"{_BOLD_RED}{lvl_str}{_RESET}"
            elif lvl_name == "DEBUG":
                lvl_colored = f"{_BLUE}{lvl_str}{_RESET}"
            else:
                lvl_colored = lvl_str

            time_colored = f"{_GRAY}{time_str}{_RESET}"
            trace_colored = f"{_MAGENTA}{trace_disp}{_RESET}"
            loc_colored = f"{_CYAN}{loc_formatted}{_RESET}"
            agent_colored = f"{_BOLD_MAGENTA}{agent_str}{_RESET}" if agent_str else ""
            ctx_colored = f"{_GRAY}{ctx_suffix}{_RESET}" if ctx_suffix else ""

            base_log = f"{time_colored} {pipe} {lvl_colored} {pipe} {trace_colored} {pipe} {loc_colored} {hyphen} {agent_colored}{msg}{ctx_colored}"
        else:
            base_log = f"{time_str} | {lvl_str} | {trace_disp} | {loc_formatted} - {agent_str}{msg}{ctx_suffix}"

        # 9. 예외 트레이스백이 있을 경우 일반 파이썬처럼 줄바꿈하여 가독성 보장
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                err_text = f"{_RED}{record.exc_text}{_RESET}" if self.colorize else record.exc_text
                base_log = f"{base_log}\n{err_text}"

        if record.stack_info:
            base_log = f"{base_log}\n{self.formatStack(record.stack_info)}"

        return base_log


# 기존 코드와의 하위 호환성을 위한 별칭
HumanReadableFormatter = LoguruStyleFormatter


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """구조화된 JSON 로그 포맷터로, 한국 표준시(KST) 타임스탬프와 소스 파일/모듈/라인 추적 정보를 삽입한다."""

    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)

        ctx = get_context_dict()
        for key, value in ctx.items():
            log_record[key] = value

        log_record['level'] = record.levelname
        log_record['timestamp'] = datetime.fromtimestamp(record.created, tz=KST).isoformat()
        log_record['filename'] = record.filename
        log_record['lineno'] = record.lineno
        log_record['module'] = record.module
        log_record['funcName'] = record.funcName


class HttpNoiseFilter(logging.Filter):
    """디버깅 시 시야를 가리는 무의미한 CORS OPTIONS 프리플라이트, 헬스체크 및 1.5초 단주기 상담 폴링 로그를 필터링한다."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # 브라우저의 자동 CORS OPTIONS 요청 필터링
        if '"OPTIONS ' in msg or "OPTIONS /api/v1/" in msg:
            return False
        # 주기적 헬스체크 폴링 필터링
        if "/api/v1/health/live" in msg or "/api/v1/health" in msg:
            return False
        # 정상적인 상담 상태 단주기 폴링(GET ... 200) 콘솔 스팸 필터링 (오류는 보존)
        if '"GET /api/v1/consultations/' in msg and " 200 " in msg:
            return False
        return True


def setup_logging(log_level: Optional[str] = None):
    """전역 로깅 설정을 초기화한다.

    콘솔(sys.stdout)에는 ANSI 컬러가 적용된 LoguruStyleFormatter를 부착하고,
    파일(app.log)에는 색상 코드가 제거된 순수 텍스트 포맷터를 일자별 롤링으로 부착한다.

    Args:
        log_level: 기본 로그 레벨 (환경변수 LOG_LEVEL이 있으면 우선 적용).
    """
    effective_level = os.getenv("LOG_LEVEL", log_level or "INFO").upper()
    logger = logging.getLogger()
    logger.setLevel(effective_level)

    # 기존 핸들러 제거 (중복 부착 방지)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 포맷터 선택 (기본값: text, 필요시 LOG_FORMAT=json 설정 가능)
    format_type = os.getenv("LOG_FORMAT", "text").lower()

    # 노이즈 필터 (LOG_NOISE_FILTER=false로 끌 수 있음)
    noise_filter_enabled = os.getenv("LOG_NOISE_FILTER", "true").lower() != "false"
    noise_filter = HttpNoiseFilter() if noise_filter_enabled else None

    # 1. 콘솔 핸들러 (ANSI 컬러 적용)
    console_handler = logging.StreamHandler(sys.stdout)
    if format_type == "json":
        console_handler.setFormatter(CustomJsonFormatter('%(timestamp)s %(level)s %(message)s'))
    else:
        console_handler.setFormatter(LoguruStyleFormatter(colorize=True))
    if noise_filter:
        console_handler.addFilter(noise_filter)
    logger.addHandler(console_handler)

    # 2. 파일 핸들러 (ANSI 컬러 제거 - Clean Text, 일자별 자정 롤링)
    log_file_path = os.getenv("LOG_PATH", "app.log")
    log_dir = os.path.dirname(log_file_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    backup_count = int(os.getenv("LOG_BACKUP_COUNT", "30"))
    file_handler = TimedRotatingFileHandler(
        filename=log_file_path,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"
    if format_type == "json":
        file_handler.setFormatter(CustomJsonFormatter('%(timestamp)s %(level)s %(message)s'))
    else:
        file_handler.setFormatter(LoguruStyleFormatter(colorize=False))
    if noise_filter:
        file_handler.addFilter(noise_filter)
    logger.addHandler(file_handler)

    # 3. Uvicorn 서버 및 액세스 로그 최적화
    # uvicorn.error/uvicorn은 루트로 전파하여 서버 시작/종료 메시지 유지
    for uvi_name in ("uvicorn", "uvicorn.error"):
        uvi_logger = logging.getLogger(uvi_name)
        uvi_logger.handlers.clear()
        uvi_logger.propagate = True

    # uvicorn.access는 미들웨어 바깥에서 trace_id 없이 찍히므로 전파를 차단하고 미들웨어 로그로 일원화
    uvi_access = logging.getLogger("uvicorn.access")
    uvi_access.handlers.clear()
    uvi_access.propagate = False

    # 4. 외부 고노이즈 라이브러리 억제 (네트워크 패킷 트레이스 등)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)
    logging.getLogger("langfuse").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """지정된 이름의 로거 객체를 반환한다.

    Args:
        name (str): 로거 이름 (통상 __name__).

    Returns:
        logging.Logger: 설정된 로거 인스턴스.
    """
    return logging.getLogger(name)
