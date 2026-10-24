# -*- coding: utf-8 -*-
"""
모듈명: llm_judge.py

[역할]
AI Legal Helper Evaluation Harness의 정성적 LLM 심사관(LLM-as-a-Judge) 모듈.
Azure OpenAI(gpt-5.4)를 활용하여 정답 시나리오 대비 실제 상담 답변의
추론 품질, 행동 지침의 실용성, 고객 전달 명료성, 출처 추적성을 5점 척도로 평가한다.

[주요 기능]
- Rubric 기반 프롬프트 구성 및 JSON 구조화 평가 결과 획득
- 통신 오류 또는 비연결 상태 시 결정론적 휴리스틱 폴백(Fallback) 제공
- 평가 사유(Reasoning) 및 치명적 결함(Critical Flaws) 도출
"""

import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from evaluation_harness.gold.gold_schema import GoldCaseScenario
from evaluation_harness.judges.rubric import (
    RUBRIC_REASONING_QUALITY,
    RUBRIC_ACTIONABILITY,
    RUBRIC_CUSTOMER_CLARITY,
    RUBRIC_TRACEABILITY,
)

logger = logging.getLogger(__name__)


class LLMJudgeScore(BaseModel):
    """LLM 심사관의 정성 평가 결과 모델."""

    reasoning_quality: int = Field(..., ge=1, le=5, description="법률 추론 품질 (1~5점)")
    actionability: int = Field(..., ge=1, le=5, description="고객 행동 실행성 (1~5점)")
    customer_clarity: int = Field(..., ge=1, le=5, description="고객 전달 명료성 (1~5점)")
    traceability: int = Field(..., ge=1, le=5, description="출처 추적 신뢰도 (1~5점)")
    average_score: float = Field(0.0, ge=1.0, le=5.0, description="4개 항목 평균 점수")
    evaluation_summary: str = Field(..., description="종합 심사평 요약")
    critical_flaws: List[str] = Field(default_factory=list, description="발견된 중대 결함 목록")


class LLMJudge:
    """LLM-as-a-Judge 평가기."""

    def __init__(self, temperature: float = 0.0):
        self.temperature = temperature

    def judge(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> LLMJudgeScore:
        """골드 시나리오와 실제 출력을 비교하여 5점 척도 정성 심사를 수행한다.

        Args:
            scenario: 골드 시나리오
            actual_output: 시스템 실행 결과 (answer, sources 등)

        Returns:
            LLMJudgeScore: 5점 척도 항목별 점수 및 심사평
        """
        answer_text = actual_output.get("answer", "") or ""

        # 답변이 완전히 비어 있거나 WITHHELD로 처분이 거절된 경우
        if not answer_text.strip() or actual_output.get("disposition") == "WITHHELD":
            return LLMJudgeScore(
                reasoning_quality=1,
                actionability=1,
                customer_clarity=2,
                traceability=1,
                average_score=1.25,
                evaluation_summary="답변이 생성되지 않았거나 시스템 처분이 WITHHELD(보류)되어 고객가치를 제공하지 못함.",
                critical_flaws=["답변 미생성 또는 검증 보류"],
            )

        try:
            return self._call_llm_judge(scenario, actual_output)
        except Exception as e:
            logger.warning(f"LLM Judge API 호출 실패 ({e}). 휴리스틱 폴백 심사를 수행합니다.")
            return self._heuristic_fallback(scenario, actual_output)

    def _call_llm_judge(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> LLMJudgeScore:
        """Azure OpenAI를 호출하여 심사 점수를 생성한다."""
        from ai_legal_helper.llm.gateway import get_llm
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = get_llm(temperature=self.temperature)

        prompt = f"""당신은 대한민국 주택임대차보호법 및 민사집행법 전문 부장판사 출신의 수석 법률 심사관입니다.
다음 제공된 '사건 및 정답 기준(Gold Standard)'과 AI 법률도우미의 '실제 답변'을 엄격하게 비교 평가하십시오.

[평가 기준 루브릭]
1. 법률 추론 품질 (reasoning_quality: 1~5점)
{json.dumps(RUBRIC_REASONING_QUALITY, ensure_ascii=False, indent=2)}

2. 행동 지침 실행성 (actionability: 1~5점)
{json.dumps(RUBRIC_ACTIONABILITY, ensure_ascii=False, indent=2)}

3. 고객 전달 명료성 (customer_clarity: 1~5점)
{json.dumps(RUBRIC_CUSTOMER_CLARITY, ensure_ascii=False, indent=2)}

4. 출처 추적 신뢰도 (traceability: 1~5점)
{json.dumps(RUBRIC_TRACEABILITY, ensure_ascii=False, indent=2)}

[정답 기준 (Gold Standard)]
- 사건 ID: {scenario.case_id}
- 시나리오 ID: {scenario.scenario_id} ({scenario.title})
- 사용자 질문: {scenario.user_question}
- 기대되는 필수 법률 결론:
{json.dumps(scenario.expected_conclusions, ensure_ascii=False, indent=2)}
- 필수 다음 행동:
{json.dumps(scenario.required_next_actions, ensure_ascii=False, indent=2)}
- 절대 금지되는 유해 권고:
{json.dumps(scenario.prohibited_recommendations, ensure_ascii=False, indent=2)}

[AI 법률도우미 실제 답변]
{actual_output.get("answer", "")}

[응답 형식]
반드시 다음 JSON 형식으로만 응답하십시오. Markdown 코드 블록이나 다른 설명은 절대 추가하지 마십시오.
{{
  "reasoning_quality": <1~5 정수>,
  "actionability": <1~5 정수>,
  "customer_clarity": <1~5 정수>,
  "traceability": <1~5 정수>,
  "evaluation_summary": "<구체적인 심사평 요약 (한국어 2~3문장)>",
  "critical_flaws": ["<발견된 결함 1>", "<발견된 결함 2>"]
}}
"""

        messages = [
            SystemMessage(content="당신은 엄격하고 객관적인 AI 법률 품질 감사관입니다. 반드시 JSON으로만 응답하십시오."),
            HumanMessage(content=prompt),
        ]

        response = llm.invoke(messages)
        content = response.content.strip()

        # markdown 코드 블록 제거
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        data = json.loads(content)
        rq = int(data.get("reasoning_quality", 3))
        act = int(data.get("actionability", 3))
        cc = int(data.get("customer_clarity", 3))
        tr = int(data.get("traceability", 3))
        avg = round((rq + act + cc + tr) / 4.0, 2)

        return LLMJudgeScore(
            reasoning_quality=rq,
            actionability=act,
            customer_clarity=cc,
            traceability=tr,
            average_score=avg,
            evaluation_summary=data.get("evaluation_summary", "심사 완료"),
            critical_flaws=data.get("critical_flaws", []),
        )

    def _heuristic_fallback(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> LLMJudgeScore:
        """API 부재 또는 네트워크 장애 시 정적 규칙으로 채점한다."""
        answer = actual_output.get("answer", "")
        flaws: List[str] = []

        # 1. 추론 품질
        rq = 3
        if "3개월" in answer or "대항력" in answer:
            rq = 4
        if len(answer) < 150:
            rq = 2
            flaws.append("답변 분량이 지나치게 빈약함")

        # 2. 실행성
        act = 3
        if "임차권등기" in answer and "내용증명" in answer:
            act = 4
        elif "임차권등기" not in answer:
            act = 2
            flaws.append("핵심 구제수단인 임차권등기명령 미안내")

        # 3. 전달 명료성
        cc = 4 if len(answer) >= 200 else 3

        # 4. 추적성
        tr = 3
        if "E01" in answer or "E03" in answer:
            tr = 4

        avg = round((rq + act + cc + tr) / 4.0, 2)
        return LLMJudgeScore(
            reasoning_quality=rq,
            actionability=act,
            customer_clarity=cc,
            traceability=tr,
            average_score=avg,
            evaluation_summary="휴리스틱 규칙 기반으로 기본 점수가 산출되었습니다.",
            critical_flaws=flaws,
        )

