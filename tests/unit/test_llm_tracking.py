import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from ai_legal_helper.observability.callbacks import TokenTrackingCallbackHandler
from ai_legal_helper.llm.usage import global_token_tracker
from ai_legal_helper.observability.context import set_agent_name, set_trace_id, reset_trace_id, reset_agent_name

@pytest.fixture(autouse=True)
def reset_tracker():
    global_token_tracker.records = []
    yield

def test_llm_token_tracking_actual():
    class CustomFakeChatModel(FakeListChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            res = super()._generate(messages, stop, run_manager, **kwargs)
            res.llm_output = {
                "token_usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 25,
                    "total_tokens": 40
                }
            }
            return res

    cb = TokenTrackingCallbackHandler()
    llm = CustomFakeChatModel(responses=["Test response"], callbacks=[cb])
    
    t_token = set_trace_id("test-trace")
    a_token = set_agent_name("TestAgent")
    
    llm.invoke([HumanMessage(content="Hello")])
    
    reset_trace_id(t_token)
    reset_agent_name(a_token)

    summary = global_token_tracker.get_summary()
    assert summary["total_calls"] == 1
    assert summary["total_input"] == 15
    assert summary["total_output"] == 25
    
    agg = global_token_tracker.aggregate_by("agent_name")
    assert "TestAgent" in agg
    assert agg["TestAgent"]["total_tokens"] == 40
    
    record = global_token_tracker.records[0]
    assert record.usage_source == "actual"
    assert record.status == "SUCCESS"

def test_llm_token_tracking_unavailable():
    cb = TokenTrackingCallbackHandler()
    llm = FakeListChatModel(responses=["No usage here"], callbacks=[cb])
    
    llm.invoke([HumanMessage(content="Hello")])
    
    summary = global_token_tracker.get_summary()
    assert summary["total_calls"] == 1
    assert summary["total_input"] == 0
    assert summary["total_output"] == 0
    
    record = global_token_tracker.records[0]
    assert record.usage_source == "unavailable"

def test_llm_token_tracking_error_and_retry():
    # Simulate a failing model
    class FailingChatModel(FakeListChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise ValueError("LLM Failure")
            
    cb = TokenTrackingCallbackHandler()
    llm = FailingChatModel(responses=["Ignored"], callbacks=[cb])
    
    with pytest.raises(ValueError, match="LLM Failure"):
        llm.invoke([HumanMessage(content="Hello")])
        
    summary = global_token_tracker.get_summary()
    assert summary["total_calls"] == 1
    assert summary["total_input"] == 0
    assert summary["total_output"] == 0
    
    record = global_token_tracker.records[0]
    assert record.status == "ERROR"
    assert record.error_type == "ValueError"
    assert record.usage_source == "unavailable"
    
    agg = global_token_tracker.aggregate_by("call_id")
    # There should be 1 call
    assert len(agg) == 1
    for key, val in agg.items():
        assert val["errors"] == 1
        assert val["total_tokens"] == 0

def test_llm_token_tracking_multiple_retries():
    # Simulate an Agent node making multiple attempts (retries)
    # 2 failures, 1 success
    cb = TokenTrackingCallbackHandler()

    from typing import ClassVar
    class FlakyChatModel(FakeListChatModel):
        attempt: ClassVar[int] = 0
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.__class__.attempt += 1
            if self.__class__.attempt <= 2:
                raise ValueError("Flaky Failure")
                
            res = super()._generate(messages, stop, run_manager, **kwargs)
            res.llm_output = {
                "token_usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30
                }
            }
            return res

    llm = FlakyChatModel(responses=["Success response"], callbacks=[cb])
    call_id = "test-call-id"
    
    for i in range(3):
        try:
            llm.invoke([HumanMessage(content="Hello")], config={"run_id": f"{call_id}-{i}"})
        except ValueError:
            pass
            
    summary = global_token_tracker.get_summary()
    assert summary["total_calls"] == 3
    assert summary["total_input"] == 10
    assert summary["total_output"] == 20
    assert summary["total"] == 30
    
    agg = global_token_tracker.aggregate_by("usage_source")
    assert agg["unavailable"]["total_calls"] == 2
    assert agg["actual"]["total_calls"] == 1
    assert agg["actual"]["total_tokens"] == 30
