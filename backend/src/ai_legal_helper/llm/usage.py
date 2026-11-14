# -*- coding: utf-8 -*-
"""
모듈명: usage.py

[모듈 개요]
LLM 호출별 입출력 토큰 사용량, 지연 시간, 상태(SUCCESS/ERROR)를 기록하고
Trace/Agent 단위로 집계하는 토큰 사용량 추적 모듈이다.
"""
from typing import Optional, Dict, Any
from pydantic import BaseModel

# 장기 실행 서버에서 메모리 무한 증식을 방지하기 위한 최대 보관 레코드 수
MAX_TOKEN_RECORDS = 5000

class LLMUsageRecord(BaseModel):
    """단일 LLM 호출에 대한 토큰 사용량 및 메타데이터 레코드."""
    call_id: str
    trace_id: Optional[str] = None
    case_id: Optional[str] = None
    agent_name: Optional[str] = None
    node_name: Optional[str] = None
    model_id: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    usage_source: str = "unavailable"  # actual, estimated, unavailable
    latency_ms: float = 0.0
    retry_count: int = 0
    status: str = "SUCCESS"
    error_type: Optional[str] = None

class TokenTracker:
    """인메모리 LLM 토큰 사용량 추적기 (최대 보관 개수 제한을 통한 메모리 누수 방지 포함)."""
    def __init__(self, max_records: int = MAX_TOKEN_RECORDS):
        self.max_records = max_records
        self.records: list[LLMUsageRecord] = []

    def add_record(self, record: LLMUsageRecord) -> None:
        """새로운 LLM 호출 레코드를 추가하고 최대 보관 한도를 초과하면 가장 오래된 레코드를 정리한다."""
        self.records.append(record)
        if len(self.records) > self.max_records:
            del self.records[: len(self.records) - self.max_records]

    def get_summary(self) -> Dict[str, int]:
        """전체 누적 호출 횟수 및 입출력 토큰 총합을 반환한다."""
        total_input = sum(r.input_tokens for r in self.records if r.input_tokens is not None)
        total_output = sum(r.output_tokens for r in self.records if r.output_tokens is not None)
        return {
            "total_calls": len(self.records),
            "total_input": total_input,
            "total_output": total_output,
            "total": total_input + total_output,
        }

    def get_trace_usage(self, trace_id: str) -> Dict[str, Any]:
        """특정 trace_id에 해당하는 토큰 통계 및 에이전트별 토큰 합계를 단일 패스로 집계한다."""
        agg: Dict[str, Any] = {
            "total_calls": 0,
            "actual_calls": 0,
            "estimated_calls": 0,
            "unavailable_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "errors": 0,
            "agent_usage": {},
        }
        if not trace_id:
            return agg

        agent_usage: Dict[str, int] = {}
        for r in self.records:
            if r.trace_id != trace_id:
                continue
            agg["total_calls"] += 1
            if r.usage_source == "actual":
                agg["actual_calls"] += 1
            elif r.usage_source == "estimated":
                agg["estimated_calls"] += 1
            else:
                agg["unavailable_calls"] += 1

            if r.input_tokens is not None:
                agg["input_tokens"] += r.input_tokens
            if r.output_tokens is not None:
                agg["output_tokens"] += r.output_tokens
            if r.total_tokens is not None:
                agg["total_tokens"] += r.total_tokens
            if r.status == "ERROR":
                agg["errors"] += 1

            agent = r.agent_name or "unknown"
            if agent not in agent_usage:
                agent_usage[agent] = 0
            if r.total_tokens:
                agent_usage[agent] += r.total_tokens

        agg["agent_usage"] = agent_usage
        return agg

    def aggregate_by(self, field: str) -> Dict[str, Dict[str, int]]:
        """지정된 필드(agent_name, node_name, trace_id, case_id, call_id 등) 기준으로 토큰 통계를 그룹화한다."""
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
                    "errors": 0,
                }

            agg = summary[key]
            agg["total_calls"] += 1
            if r.usage_source == "actual":
                agg["actual_calls"] += 1
            elif r.usage_source == "estimated":
                agg["estimated_calls"] += 1
            else:
                agg["unavailable_calls"] += 1

            if r.input_tokens is not None:
                agg["input_tokens"] += r.input_tokens
            if r.output_tokens is not None:
                agg["output_tokens"] += r.output_tokens
            if r.total_tokens is not None:
                agg["total_tokens"] += r.total_tokens

            if r.status == "ERROR":
                agg["errors"] += 1

        return summary

# Global tracker for P0, later can be DB-backed.
global_token_tracker = TokenTracker()
