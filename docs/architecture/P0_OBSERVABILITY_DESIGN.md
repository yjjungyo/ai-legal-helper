# P0 Observability Design

## Goals
Ensure every user request, LLM call, and exception is fully traceable across synchronous and asynchronous boundaries.

## AOP Logging
- Python decorators (`@trace`) wrap critical functions.
- Context is maintained via `contextvars`, supporting concurrency.
- Structured JSON logging emits variables like `trace_id`, `request_id`, `agent_name`, `source_file`, `elapsed_ms`.
- Strict distinction between where the error is caught vs where the error originates using traceback inspection.

## OpenTelemetry
- Integrated OpenTelemetry API and SDK.
- The AOP decorator creates an OTel Span, recording the execution time, attributes, and exceptions.
- Currently exports to Console, designed to easily plug in Jaeger later.

## LLM Tracking
- LangChain Callback `TokenTrackingCallbackHandler` captures input, output, and total tokens from model responses.
- Records are stored in a centralized `TokenTracker` struct.
- Differentiates between `actual`, `estimated`, and `unavailable` token usage sources.
- Captures model latency, retry counts, and traces IDs seamlessly without double counting.

