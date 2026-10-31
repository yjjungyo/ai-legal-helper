"""
모듈명: logging_config.py

[모듈 개요]
사람이 직관적으로 디버깅할 수 있는 고가독성 텍스트 로그 포맷터 및 시스템 로깅 설정을 제공한다.
불필요한 null 메타데이터와 중복 출력을 제거하고, 유효한 컨텍스트(trace_id, case_id 등)만 선별 표기한다.
환경변수 LOG_FORMAT에 따라 텍스트 포맷(기본값) 또는 기계 분석용 JSON 포맷을 선택할 수 있다.

[주요 기능]
1. LoguruStyleFormatter: Loguru/Rich 스타일 고가독성 포맷터 (파이프 구분, 한국어 단계 [에이전트 >> 단계명], 저수준 네트워크 트레이스 한국어 변환, 콘솔 ANSI 컬러 vs 파일 클린 텍스트)
2. CustomJsonFormatter: 기계 및 로그 수집기(ELK/CloudWatch)용 구조화 JSON 포맷터 (파일명, 라인, 모듈 포함)
3. HttpNoiseFilter: CORS OPTIONS 프리플라이트 및 헬스체크 등 디버깅 방해 노이즈 필터링
4. setup_logging: 콘솔(sys.stdout, colorize=True) 및 일자별 롤링 파일(TimedRotatingFileHandler, colorize=False) 구성
"""
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import re
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

# LangGraph 노드 및 에이전트 한국어 단계 매핑 (콘솔 및 파일 로그 가독성 향상)
_NODE_KR_LABELS = {
    "supervisor_initialize": "1단계: 사건·맥락 확인(init)",
    "intent_analysis": "1단계: 질문 의도 분석(intent)",
    "general_conversation": "1단계: 일반 대화 안내(general)",
    "followup_action": "후속턴: 실무 행동 가이드(followup_action)",
    "route": "2단계: 법률 분야 판별(route)",
    "routing_exit": "2단계: 추가 정보 안내(routing_exit)",
    "plan": "2단계: 쟁점·도구 계획(plan)",
    "run_agents": "3단계: 법령·판례 검색(run_agents)",
    "synthesize": "4단계: 쟁점별 분석·초안 작성(synthesize)",
    "verification": "5단계: 법령·증거 근거 검증(verification)",
    "revise": "5단계: 답변 보강·재작성(revise)",
    "statute_search_approval": "5단계: 외부 법령 조회 승인 대기(hilt)",
    "execute_statute_search": "5단계: 국가법령정보센터 조회(statute_search)",
    "re_analyze": "5단계: 확보 법령 기반 재분석(re_analyze)",
    "finalize": "6단계: 최종 답변 확정(finalize)",
    "insufficient": "6단계: 판단 유보·보완 안내(insufficient)",
}

_AGENT_KR_LABELS = {
    "IntentAnalyzer": "의도분석 에이전트",
    "RouterAgent": "분야분류 에이전트",
    "PlannerAgent": "쟁점계획 에이전트",
    "SynthesizerAgent": "종합분석 에이전트",
    "VerificationAgent": "근거검증 에이전트",
    "DocumentAnswerAgent": "문서상담 에이전트",
    "DocumentVerifier": "문서검증 에이전트",
    "ActionPlanner": "대응전략 에이전트",
}


def _translate_log_message(msg: str) -> str:
    """httpcore/httpcore2(_trace.py), httpx, asyncio 등 저수준 영문 네트워크·시스템 로그를
    사람이 직관적으로 이해할 수 있는 한국어 메시지로 변환한다.

    비즈니스 로직에는 영향을 주지 않으며, 포맷팅 출력 시점에만 동작한다.

    Args:
        msg (str): 원본 로그 메시지 문자열.

    Returns:
        str: 한국어로 변환된 로그 메시지 (변환 대상이 아닌 경우 원문 그대로 반환).
    """
    if not msg or not isinstance(msg, str):
        return msg

    stripped = msg.strip()

    # 1. httpcore / httpcore2 (_trace.py) 저수준 통신 트레이스 변환
    if stripped.startswith("connect_tcp.started"):
        host_m = re.search(r"host='([^']+)'", stripped)
        port_m = re.search(r"port=(\d+)", stripped)
        host_str = host_m.group(1) if host_m else "AI 서버"
        port_str = f":{port_m.group(1)}" if port_m else ""
        return f"[AI 서버 연결] TCP 네트워크 연결 시작 (대상: {host_str}{port_str})"

    if stripped.startswith("connect_tcp.complete"):
        return "[AI 서버 연결] TCP 네트워크 스트림 연결 완료"

    if stripped.startswith("connect_tcp.failed"):
        return f"[AI 서버 연결] TCP 네트워크 연결 실패 ({stripped})"

    if stripped.startswith("start_tls.started"):
        srv_m = re.search(r"server_hostname='([^']+)'", stripped)
        srv_str = f" (서버: {srv_m.group(1)})" if srv_m else ""
        return f"[보안 채널 수립] TLS/SSL 암호화 핸드셰이크 시작{srv_str}"

    if stripped.startswith("start_tls.complete"):
        return "[보안 채널 수립] TLS/SSL 암호화 보안 연결 완료"

    if stripped.startswith("start_tls.failed"):
        return f"[보안 채널 수립] TLS/SSL 암호화 연결 실패 ({stripped})"

    if stripped.startswith("send_request_headers.started"):
        meth_m = re.search(r"\[b'([A-Z]+)'\]", stripped)
        meth_str = f" (메서드: {meth_m.group(1)})" if meth_m else ""
        return f"[AI 요청 전송] HTTP 요청 헤더 전송 시작{meth_str}"

    if stripped.startswith("send_request_headers.complete"):
        return "[AI 요청 전송] HTTP 요청 헤더 전송 완료"

    if stripped.startswith("send_request_body.started"):
        return "[AI 데이터 전송] LLM 프롬프트·컨텍스트 본문 데이터 전송 시작"

    if stripped.startswith("send_request_body.complete"):
        return "[AI 데이터 전송] LLM 프롬프트·컨텍스트 본문 데이터 전송 완료"

    if stripped.startswith("receive_response_headers.started"):
        return "[AI 응답 대기] LLM 서버 추론 및 응답 헤더 수신 대기 중..."

    if stripped.startswith("receive_response_headers.complete"):
        code_m = re.search(r"\(\s*b'[^']+'\s*,\s*(\d+)", stripped)
        code_str = f" (상태코드: {code_m.group(1)})" if code_m else ""
        return f"[AI 응답 수신] LLM 서버 응답 헤더 수신 완료{code_str}"

    if stripped.startswith("receive_response_body.started"):
        return "[AI 응답 수신] LLM 생성 답변 본문 데이터 수신 시작"

    if stripped.startswith("receive_response_body.complete"):
        return "[AI 응답 완료] LLM 생성 답변 본문 데이터 수신 완료"

    if stripped.startswith("response_closed.started"):
        return "[통신 세션 정리] HTTP 응답 스트림 종료 시작"

    if stripped.startswith("response_closed.complete"):
        return "[통신 세션 정리] HTTP 응답 스트림 종료 완료"

    if stripped.startswith("close.started"):
        return "[통신 세션 정리] 네트워크 소켓 연결 닫기 시작"

    if stripped.startswith("close.complete"):
        return "[통신 세션 정리] 네트워크 소켓 연결 닫기 완료"

    # 2. httpx 요약 로그 변환
    if stripped.startswith("HTTP Request:"):
        req_m = re.match(r'HTTP Request:\s+([A-Z]+)\s+(\S+)\s+"([^"]+)"', stripped)
        if req_m:
            return f"[외부 API 통신 완료] {req_m.group(1)} {req_m.group(2)} -> 응답: {req_m.group(3)}"

    # 3. asyncio 이벤트 루프 로그 변환
    if stripped.startswith("Using selector:") or stripped.startswith("Using proactor:"):
        parts = stripped.split(":", 1)
        detail = parts[1].strip() if len(parts) > 1 else stripped
        return f"[비동기 이벤트 루프] 입출력 제어기 초기화 완료 ({detail})"

    return msg


class LoguruStyleFormatter(logging.Formatter):
    """Loguru/Rich 스타일의 고가독성 포맷터 (스타일 1, 3, 4 통합).

    1. 대괄호 남발을 줄이고 파이프(|) 구분자를 사용하여 시각적 피로도를 최소화한다.
    2. Multi-Agent(LangGraph) 컨텍스트가 활성화되어 있으면 [에이전트 >> 한국어 단계명] 흐름을 강조 표기한다.
    3. colorize 플래그에 따라 콘솔에는 ANSI 컬러를, 파일(app.log)에는 순수 텍스트(Clean text)를 출력한다.
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

        # 5. Multi-Agent / LangGraph 실행 컨텍스트 ([에이전트 >> 한국어 단계명])
        raw_agent = ctx.get("agent_name") or getattr(record, "agent_name", None)
        raw_node = ctx.get("node_name") or getattr(record, "node_name", None)
        agent_disp = _AGENT_KR_LABELS.get(raw_agent, raw_agent) if raw_agent else None
        node_disp = _NODE_KR_LABELS.get(raw_node, raw_node) if raw_node else None

        if agent_disp and node_disp and raw_agent != raw_node:
            agent_str = f"[{agent_disp} >> {node_disp}] "
        elif node_disp:
            agent_str = f"[{node_disp}] "
        elif agent_disp:
            agent_str = f"[{agent_disp}] "
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

        # 7. 본문 메시지 (저수준 영문 네트워크 트레이스 등을 한국어로 자동 변환)
        msg = _translate_log_message(record.getMessage())

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
    for noisy_lib in ("httpx", "httpcore", "httpcore2", "openai", "neo4j", "langfuse"):
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """지정된 이름의 로거 객체를 반환한다.

    Args:
        name (str): 로거 이름 (통상 __name__).

    Returns:
        logging.Logger: 설정된 로거 인스턴스.
    """
    return logging.getLogger(name)
