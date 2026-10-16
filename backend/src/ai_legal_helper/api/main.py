from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy.exc import SQLAlchemyError
import time
import asyncio

from ai_legal_helper.api.routes import consultation, cases, evidence, graph, documents, workflow, auth
from ai_legal_helper.observability.logging_config import setup_logging, get_logger
from ai_legal_helper.database.graph_sync_worker import graph_sync_worker_loop
from ai_legal_helper.database.session import engine
from ai_legal_helper.database.neo4j import get_neo4j_driver
from sqlalchemy import text

# Initialize logging and configuration
setup_logging("INFO")
logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start graph sync worker
    worker_task = asyncio.create_task(graph_sync_worker_loop())
    yield
    # Shutdown worker
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
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

