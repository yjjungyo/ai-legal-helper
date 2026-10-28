"""
모듈명: main.py

[모듈 개요]
AI Legal Helper 백엔드 FastAPI 애플리케이션의 엔트리포인트 및 전역 라이프사이클을 관리한다.
CORS, 전역 에러 핸들러, 분산 추적(trace_id/request_id) 주입 미들웨어, 헬스체크 및 라우터를 등록한다.

[주요 기능]
1. lifespan: 백그라운드 Graph Sync Worker 루프의 안전한 시작 및 종료 관리
2. trace_context_middleware: 들어오는 모든 HTTP 요청에 고유 trace_id/request_id 발급 및 ContextVar 주입
3. 라우터 통합: consultation, cases, evidence, documents, graph, workflow, auth 모듈 등록
4. 헬스체크: /api/v1/health/live 및 /api/v1/health/ready (Postgres, Neo4j) 제공
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy.exc import SQLAlchemyError
import time
import asyncio
import uuid

from ai_legal_helper.api.routes import consultation, cases, evidence, graph, documents, workflow, auth
from ai_legal_helper.observability.logging_config import setup_logging, get_logger
from ai_legal_helper.observability.context import (
    set_trace_id,
    reset_trace_id,
    set_request_id,
    reset_request_id,
    set_case_id,
    reset_case_id,
)
from ai_legal_helper.database.graph_sync_worker import graph_sync_worker_loop
from ai_legal_helper.database.session import engine
from ai_legal_helper.database.neo4j import get_neo4j_driver
import sys

# Windows 환경에서 psycopg async 및 ProactorEventLoop 호환성을 위한 SelectorLoop 지정
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# Initialize logging and configuration
setup_logging("INFO")
logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 애플리케이션 시작 시 체크포인터 테이블 초기화 및 백그라운드 Graph Sync Worker를 기동하고,
    종료 시 워커 태스크 취소, Langfuse 버퍼 플러시, Neo4j 드라이버 정리를 수행한다.
    """
    # 0. PostgreSQL LangGraph Checkpointer 테이블 자동 초기화 (P0-03)
    try:
        from ai_legal_helper.workflows.legal_workflow import init_checkpointer
        await init_checkpointer()
    except Exception as e:
        logger.warning(f"[LIFESPAN] Checkpointer initialization warning: {e}")

    worker_task = asyncio.create_task(graph_sync_worker_loop())
    yield
    # 1. 백그라운드 Graph Sync Worker 안전 종료
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    # 2. Langfuse 관측성 버퍼 플러시
    try:
        from ai_legal_helper.observability.langfuse_client import flush_langfuse
        flush_langfuse()
    except Exception:
        pass
    # 3. Neo4j 드라이버 리소스 정리
    try:
        driver = get_neo4j_driver()
        if driver:
            driver.close()
    except Exception:
        pass

app = FastAPI(title="AI Legal Helper API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_context_middleware(request: Request, call_next):
    """모든 HTTP 요청에 대해 고유 trace_id와 request_id를 부여하고 컨텍스트에 주입한다.

    클라이언트 요청 헤더('X-Trace-Id', 'X-Request-Id')가 있으면 이를 승계하고,
    없을 경우 신규 UUID를 발급하여 Langfuse 분산 추적 및 애플리케이션 로그를 일치시킨다.

    Args:
        request (Request): 들어오는 FastAPI HTTP 요청 객체.
        call_next: 다음 미들웨어 또는 엔드포인트 핸들러 호출 함수.

    Returns:
        Response: 'X-Trace-Id'와 'X-Request-Id' 응답 헤더가 주입된 HTTP 응답 객체.
    """
    trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())

    t_token = set_trace_id(trace_id)
    r_token = set_request_id(request_id)

    # URL 경로에서 case_id 자동 추출 (/api/v1/cases/{case_id}/...)
    c_token = None
    candidate_case_id = None
    path_parts = request.url.path.strip("/").split("/")
    if "cases" in path_parts:
        c_idx = path_parts.index("cases")
        if len(path_parts) > c_idx + 1:
            candidate = path_parts[c_idx + 1]
            if len(candidate) >= 8 and candidate not in ("actions", "evidence", "statements"):
                candidate_case_id = candidate
                c_token = set_case_id(candidate)

    # Langfuse 최상위 Root Trace 시작
    from ai_legal_helper.observability.langfuse_client import start_trace, end_trace, get_system_name
    path = request.url.path

    # 헬스체크, CORS 사전 요청(OPTIONS), 프론트엔드 단주기 상담 상태 폴링(GET /consultations/{id})을 노이즈로 분류
    # -> 무의미한 빈 Langfuse Root Trace 누적 방지 및 터미널 반복 로그 스팸 차단
    is_health_or_options = (
        path.endswith("/health/live")
        or path.endswith("/health")
        or request.method == "OPTIONS"
    )
    is_consultation_polling = (
        request.method == "GET"
        and "/api/v1/consultations/" in path
    )
    is_noise = is_health_or_options or is_consultation_polling
    is_consultation_post = (
        request.method == "POST"
        and "/api/v1/consultations" in path
    )

    if not is_noise:
        sys_name = get_system_name()
        # 상담 파이프라인(POST)은 시작부터 'LegalConsultation'으로 명명하여 Langfuse 추적 명확성 확보 (P0-3)
        trace_name = "LegalConsultation" if is_consultation_post else f"HTTP:{request.method}_{path}"
        start_trace(
            trace_id=trace_id,
            name=trace_name,
            session_id=candidate_case_id,
            metadata={
                "method": request.method,
                "path": path,
                "request_id": request_id,
                "system_name": sys_name,
            },
            tags=[sys_name],
        )

    start_time = time.time()
    try:
        response = await call_next(request)
        elapsed_ms = (time.time() - start_time) * 1000
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Request-Id"] = request_id

        # 정상적인 단주기 폴링은 콘솔 노이즈 방지를 위해 DEBUG 레벨로 처리하고, 오류(4xx, 5xx) 발생 시에만 WARNING 로깅
        if not is_noise:
            client_ip = request.client.host if request.client else "-"
            logger.info(f'{client_ip} - "{request.method} {path}" {response.status_code} ({elapsed_ms:.1f}ms)')
        elif response.status_code >= 400:
            client_ip = request.client.host if request.client else "-"
            logger.warning(f'{client_ip} - "{request.method} {path}" {response.status_code} ({elapsed_ms:.1f}ms)')
        else:
            client_ip = request.client.host if request.client else "-"
            logger.debug(f'{client_ip} - "{request.method} {path}" {response.status_code} ({elapsed_ms:.1f}ms)')

        return response
    finally:
        if not is_noise and not is_consultation_post:
            end_trace(trace_id)
        reset_trace_id(t_token)
        reset_request_id(r_token)
        if c_token:
            reset_case_id(c_token)

app.include_router(consultation.router, prefix="/api/v1")
app.include_router(cases.router, prefix="/api/v1")
app.include_router(evidence.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(graph.router, prefix="/api/v1")
app.include_router(workflow.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")

# --- Exception Handlers ---

@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.error(f"Database error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "데이터베이스 오류가 발생했습니다.", "error_code": "DB_ERROR"},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "서버 내부 오류가 발생했습니다.", "error_code": "INTERNAL_SERVER_ERROR"},
    )

# --- Health Check Endpoints ---

@app.get("/api/v1/health/live")
async def health_live():
    """Liveness probe: 애플리케이션이 실행 중인지 확인"""
    return {"status": "ok", "timestamp": time.time()}

@app.get("/api/v1/health/ready")
async def health_ready():
    """Readiness probe: 외부 종속성(DB, Neo4j) 접근 가능 여부 확인"""
    health_status = {"status": "ok", "timestamp": time.time(), "dependencies": {}}
    
    # 1. Check PostgreSQL
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        health_status["dependencies"]["postgres"] = "up"
    except Exception as e:
        logger.error(f"Postgres check failed: {e}")
        health_status["dependencies"]["postgres"] = "down"
        health_status["status"] = "error"
        
    # 2. Check Neo4j
    driver = get_neo4j_driver()
    if driver:
        try:
            driver.verify_connectivity()
            health_status["dependencies"]["neo4j"] = "up"
        except Exception as e:
            logger.error(f"Neo4j check failed: {e}")
            health_status["dependencies"]["neo4j"] = "down"
            health_status["status"] = "error"
    else:
        health_status["dependencies"]["neo4j"] = "down"
        health_status["status"] = "error"
        
    status_code = 200 if health_status["status"] == "ok" else 503
    return JSONResponse(status_code=status_code, content=health_status)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ai_legal_helper.api.main:app", host="0.0.0.0", port=8000, reload=True)

