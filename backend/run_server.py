"""
모듈명: run_server.py

[모듈 개요]
AI Legal Helper FastAPI 애플리케이션 로컬 실행 러너.
Windows 환경에서 psycopg3 비동기 통신과 호환되도록 WindowsSelectorEventLoopPolicy 및 uvicorn loop factory를 선제적으로 지정한다.
"""
import sys
import asyncio

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        import uvicorn.loops.asyncio
        uvicorn.loops.asyncio.asyncio_loop_factory = lambda use_subprocess=False: asyncio.SelectorEventLoop
    except Exception:
        pass

import uvicorn

if __name__ == "__main__":
    uvicorn.run("ai_legal_helper.api.main:app", host="127.0.0.1", port=8000, loop="asyncio")

