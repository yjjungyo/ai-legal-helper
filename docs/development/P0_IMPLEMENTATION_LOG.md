# P0 Implementation Log

## 1. Goal and Problem
**Problem**: The legacy legal assistant lacked proper logging and token tracking, making it hard to debug execution paths and LLM costs.
**Goal**: Build a fresh foundation with rigorous AOP-based logging and token tracking.

## 2. Technology Choices
- Python 3.10+
- `contextvars` for context management (native, asyncio-friendly).
- `opentelemetry-api/sdk` for standard tracing.
- `python-json-logger` for structured logging.
- `pytest` and `pytest-asyncio` for testing.

## 3. Implementation Details
- `observability/context.py`: Defines context variables.
- `observability/decorators.py`: Implements `@trace` which starts an OpenTelemetry span, computes execution time, and catches/logs errors with traceback parsing.
- `observability/callbacks.py`: LangChain callback capturing token usage (`actual`, `estimated`, `unavailable`).
- `llm/gateway.py`: Gateway function `get_llm()` to instantiate LLMs with our tracking callbacks.
- `ui/app.py`: Basic Streamlit verification app.

## 4. Tests and Verification
- Wrote `test_aop.py` to ensure trace context leaks do not happen during async and concurrent execution.
- Wrote `test_llm_tracking.py` verifying usage data parsing via fake chat models.
- All tests pass (8 passed, 0 failed).

## 5. Next Steps
- P1: Integrate GraphRAG and existing legacy codebase safely using our observability stack.

