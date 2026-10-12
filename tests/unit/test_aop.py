import pytest
import asyncio
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.context import (
    get_trace_id, set_trace_id, get_context_dict, reset_trace_id
)
import uuid

@trace
def sample_sync_func(x: int) -> int:
    return x * 2

@trace
def sample_sync_error():
    msg = (
        "Test Error with API_KEY=secret_12345, sk-abcde1234567890123456789, "
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ, "
        "AZURE_OPENAI_ENDPOINT=https://my-azure-instance.openai.azure.com/, "
        "email: test@example.com, SSN: 800101-1234567, Phone: 010-1234-5678"
    )
    raise ValueError(msg)

@trace
async def sample_async_func(x: int) -> int:
    await asyncio.sleep(0.01)
    return x * 2

@trace
async def sample_async_error():
    raise ValueError("Async Test Error")

def test_sync_aop_success():
    res = sample_sync_func(10)
    assert res == 20
    # The trace ID should be cleaned up if it was newly created
    assert get_trace_id() is None

def test_sync_aop_error(caplog):
    import logging
    caplog.set_level(logging.ERROR)
    with pytest.raises(ValueError, match="Test Error"):
        sample_sync_error()
    assert get_trace_id() is None
    
    # Check if stack trace and message in logs were scrubbed
    log_record = caplog.records[0]
    stack_trace = log_record.stack_trace
    msg = log_record.message
    
    for text in [stack_trace, msg]:
        assert "API_KEY=***" in text
        assert "secret_12345" not in text
        assert "sk-abcde1234567890123456789" not in text
        assert "Bearer ***" in text
        assert "eyJhbGciOi" not in text
        assert "AZURE_OPENAI_ENDPOINT=***" in text
        assert "https://my-azure-instance" not in text
        assert "***@***.***" in text
        assert "test@example.com" not in text
        assert "******-*******" in text
        assert "800101-1234567" not in text
        assert "010-****-****" in text
        assert "010-1234-5678" not in text

@pytest.mark.asyncio
async def test_async_aop_success():
    res = await sample_async_func(10)
    assert res == 20
    assert get_trace_id() is None

@pytest.mark.asyncio
async def test_async_aop_error():
    with pytest.raises(ValueError, match="Async Test Error"):
        await sample_async_error()
    assert get_trace_id() is None

@trace
def nested_func_inner():
    return get_trace_id()

@trace
def nested_func_outer():
    return nested_func_inner()

def test_nested_trace_id():
    # Outer function creates a trace_id and inner function uses it.
    inner_trace_id = nested_func_outer()
    assert inner_trace_id is not None
    assert get_trace_id() is None

@pytest.mark.asyncio
async def test_concurrent_trace_ids():
    @trace
    async def get_my_trace_id():
        await asyncio.sleep(0.05)
        return get_trace_id()

    # Run two concurrently, they should have different trace IDs
    res1, res2 = await asyncio.gather(
        get_my_trace_id(),
        get_my_trace_id()
    )

    assert res1 is not None
    assert res2 is not None
    assert res1 != res2

import concurrent.futures
import contextvars

def test_threadpool_executor_context():
    # ContextVar does not automatically propagate to ThreadPoolExecutor in Python < 3.11 unless we use copy_context().run or to_thread
    t_token = set_trace_id("threadpool-trace")
    
    @trace
    def get_my_trace_id_sync():
        return get_trace_id()

    ctx = contextvars.copy_context()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        # We must use ctx.run
        future = executor.submit(ctx.run, get_my_trace_id_sync)
        res = future.result()
        
    assert res == "threadpool-trace"
    reset_trace_id(t_token)


