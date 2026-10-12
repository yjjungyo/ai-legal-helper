# ADR 002: Observability Stack

**Date**: 2026-10-08
**Status**: Accepted

## Context
LLM applications require complex tracing across chains, agents, and API boundaries. We must track tokens, execution time, and errors precisely.

## Decision
1. **Context Management**: Python `contextvars` to support asynchronous tracking seamlessly.
2. **Logging**: `python-json-logger` for structured logs outputting context variables automatically.
3. **Tracing**: OpenTelemetry (`opentelemetry-api`, `opentelemetry-sdk`) to provide standard distributed tracing (currently using Console Exporter).
4. **Token Tracking**: LangChain callbacks integrated into a centralized gateway `get_llm()` rather than relying on external paid observability platforms like LangSmith.

## Consequences
- High visibility into token costs and agent paths locally.
- Easy integration with Jaeger or standard observability tools in the future.
- Minimal vendor lock-in.

