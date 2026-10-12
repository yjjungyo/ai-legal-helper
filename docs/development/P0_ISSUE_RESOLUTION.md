# P0 Issue Resolution

## 1. Issue: Correct Exception Location Tracking
- **Problem**: When `@trace` catches an error, logging `inspect.getfile(func)` would only point to the decorator wrapper, not where the error actually happened.
- **Solution**: We parse the exception's `__traceback__` object to drill down to the deepest frame (`tb_next`) and extract the `co_filename` and `tb_lineno` to accurately pinpoint the error source.

## 2. Issue: Concurrent Context Leaks
- **Problem**: In asynchronous execution (like `asyncio.gather`), trace IDs could leak across tasks if not managed properly.
- **Solution**: Used Python's built-in `contextvars`. A new token is set at the start of a trace and `reset()` is called in the `finally` block of the decorator. Testing confirmed complete isolation.

## 3. Issue: OpenTelemetry Integration
- **Problem**: Need OTel spans that mirror our internal logs.
- **Solution**: Intertwined `tracer.start_as_current_span` within the `@trace` decorator. Spans automatically receive `trace_id`, `agent_name`, and exception records.

