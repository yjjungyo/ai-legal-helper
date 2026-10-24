# -*- coding: utf-8 -*-
"""
모듈명: consultation_adapter.py

[역할]
AI Legal Helper Evaluation Harness의 상담 워크플로우 어댑터(Consultation Adapter).
제품 코드를 일체 수정하지 않고(Zero Modification 원칙), 비파괴적으로 `run_legal_consultation`을 호출하여
평가 시나리오에 대한 실행 결과(답변, 처분 상태, 출처, 지연시간 등)를 획득한다.

[주요 기능]
- `run_scenario`: 골드 시나리오를 입력받아 상담 파이프라인 비동기 실행
- HILT(Human-In-The-Loop) 승인 요청 감지 시 자동 승인(auto_approve_hilt) 및 워크플로우 완결
- MemorySaver 기반 격리 실행을 지원하여 운영 DB 변경 방지
- 소요 시간(latency) 및 상태 메타데이터 정밀 기록
"""

import sys
import time
import uuid
import asyncio
from typing import Dict, Any, Optional

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from langgraph.checkpoint.memory import MemorySaver
from ai_legal_helper.workflows.legal_workflow import run_legal_consultation
from ai_legal_helper.workflows.conversation_context import ConversationContext
from evaluation_harness.gold.gold_schema import GoldCaseScenario
from evaluation_harness.config import config


class ConsultationAdapter:
    """법률 상담 파이프라인 비동기 어댑터."""

    def __init__(self, case_id: str = config.default_case_id, use_memory_checkpointer: bool = True):
        """어댑터 초기화.

        Args:
            case_id: 대상 사건의 UUID
            use_memory_checkpointer: 운영 DB 오염 방지를 위해 MemorySaver 사용 여부
        """
        self.case_id = case_id
        self.use_memory_checkpointer = use_memory_checkpointer

    async def run_scenario_async(
        self,
        scenario: GoldCaseScenario,
        auto_approve_hilt: bool = True,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """시나리오 질문을 상담 파이프라인에 비동기로 전달하고 결과를 수집한다.

        Args:
            scenario: 평가 대상 GoldCaseScenario
            auto_approve_hilt: HILT 승인 대기 시 자동으로 승인하고 답변 생성을 완료할지 여부
            thread_id: 대화 스레드 ID (미지정 시 고유 UUID 생성)

        Returns:
            Dict[str, Any]: 채점 표준 포맷 결과 딕셔너리
        """
        t_id = thread_id or f"eval_{scenario.scenario_id}_{uuid.uuid4().hex[:8]}"
        checkpointer = MemorySaver() if self.use_memory_checkpointer else None

        prior_context = getattr(scenario, "prior_context", None)
        if prior_context:
            from ai_legal_helper.workflows.conversation_context import ConversationTurn
            prior_turn = ConversationTurn(
                turn_index=1,
                request_id=f"prior_{uuid.uuid4().hex[:6]}",
                question=prior_context,
                answer=(
                    "임대차계약 만료 후 보증금을 반환받지 못한 경우 임차인은 주택 인도 및 주민등록 전입을 유지하여 "
                    "대항력과 우선변제권을 보전해야 하며, 내용증명 발송 및 관할 법원에 임차권등기명령을 신청해야 합니다."
                ),
                answer_status="DELIVERED",
                verification_status="PASS",
            )
            conv_context = ConversationContext(
                case_id=self.case_id,
                current_question=scenario.user_question,
                conversation_id=t_id,
                turn_index=2,
                previous_turns=[prior_turn],
                last_answer=prior_turn.answer,
                last_answer_status="DELIVERED",
                conversation_summary=f"의뢰인은 {prior_context} 상황에서 권리보전 및 보증금 회수 방안을 연속 상담 중임.",
            )
        else:
            conv_context = ConversationContext(
                case_id=self.case_id,
                current_question=scenario.user_question,
                conversation_id=t_id,
                turn_index=1,
            )

        start_time = time.perf_counter()

        # 1차 실행
        result = await run_legal_consultation(
            question=scenario.user_question,
            thread_id=t_id,
            checkpointer=checkpointer,
            conversation_context=conv_context,
        )

        # HILT 승인 대기 발생 시 후속 재개 처리
        if result.get("status") == "APPROVAL_REQUIRED" and auto_approve_hilt:
            # 승인 데이터와 함께 워크플로우 완결 재개
            resume_data = {
                "approved": True,
                "scope": result.get("approval_request", {}).get("scope", "FULL"),
            }
            result = await run_legal_consultation(
                question="",
                thread_id=t_id,
                resume_data=resume_data,
                checkpointer=checkpointer,
                conversation_context=conv_context,
            )

        latency = time.perf_counter() - start_time

        # 결과 데이터 정규화
        answer = result.get("answer", "") or ""
        disposition = result.get("final_disposition") or result.get("disposition") or "UNKNOWN"
        sources = result.get("cited_sources") or result.get("sources") or []

        return {
            "scenario_id": scenario.scenario_id,
            "thread_id": t_id,
            "status": result.get("status", "SUCCESS"),
            "execution_status": result.get("execution_status", "COMPLETED"),
            "disposition": disposition,
            "answer": answer,
            "sources": sources,
            "retrieved_sources": result.get("retrieved_sources", []),
            "verification_result": result.get("verification_result", {}),
            "verification_status": result.get("verification_status", "UNVERIFIED"),
            "warnings": result.get("warnings", []),
            "latency_seconds": round(latency, 3),
            "token_usage": result.get("token_usage", {}),
            "raw_result": result,
        }

    def run_scenario(
        self,
        scenario: GoldCaseScenario,
        auto_approve_hilt: bool = True,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """동기 호출 래퍼 함수."""
        return asyncio.run(self.run_scenario_async(scenario, auto_approve_hilt=auto_approve_hilt, thread_id=thread_id))

