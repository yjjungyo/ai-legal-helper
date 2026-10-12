from pydantic import BaseModel, Field
from typing import Optional

class LLMUsageRecord(BaseModel):
    call_id: str
    trace_id: Optional[str] = None
    case_id: Optional[str] = None
    agent_name: Optional[str] = None
    node_name: Optional[str] = None
    model_id: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    usage_source: str = "unavailable" # actual, estimated, unavailable
    latency_ms: float = 0.0
    retry_count: int = 0
    status: str = "SUCCESS"
    error_type: Optional[str] = None
    
    # We can add a method to merge retries or similar, but typically a DB/Tracker handles it.

class TokenTracker:
    def __init__(self):
        self.records: list[LLMUsageRecord] = []
        
    def add_record(self, record: LLMUsageRecord):
        self.records.append(record)

    def get_summary(self):
        total_input = sum(r.input_tokens for r in self.records if r.input_tokens is not None)
        total_output = sum(r.output_tokens for r in self.records if r.output_tokens is not None)
        return {
            "total_calls": len(self.records),
            "total_input": total_input,
            "total_output": total_output,
            "total": total_input + total_output
        }

    def aggregate_by(self, field: str):
        # field can be 'agent_name', 'node_name', 'trace_id', 'case_id', 'call_id'
        summary = {}
        for r in self.records:
            key = getattr(r, field, "unknown")
            if not key:
                key = "unknown"
                
            if key not in summary:
                summary[key] = {
                    "total_calls": 0,
                    "actual_calls": 0,
                    "estimated_calls": 0,
                    "unavailable_calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "errors": 0
                }
            
            agg = summary[key]
            agg["total_calls"] += 1
            if r.usage_source == "actual":
                agg["actual_calls"] += 1
            elif r.usage_source == "estimated":
                agg["estimated_calls"] += 1
            else:
                agg["unavailable_calls"] += 1
                
            if r.input_tokens is not None: agg["input_tokens"] += r.input_tokens
            if r.output_tokens is not None: agg["output_tokens"] += r.output_tokens
            if r.total_tokens is not None: agg["total_tokens"] += r.total_tokens
            
            if r.status == "ERROR":
                agg["errors"] += 1
                
        return summary
        
# Global tracker for P0, later can be DB-backed.
global_token_tracker = TokenTracker()

