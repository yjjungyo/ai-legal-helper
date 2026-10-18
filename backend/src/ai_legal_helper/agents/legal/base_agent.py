# -*- coding: utf-8 -*-
"""
모듈명: base_agent.py

[모듈 개요]
하위 법률 전문 에이전트(Specialist Agent)의 ReAct 프롬프트 템플릿 및 실행기(AgentExecutor)를 정의한다.
법률 RAG 검색 도구 호출 결과(Observation)와 사건 브리핑 맥락(chat_brief)을 결합하여
Azure OpenAI LLM이 실제 검색 근거에 기반한 법률 답변을 생성하도록 제어한다.

[주요 기능]
1. BASE_SYSTEM / REACT_TEMPLATE: 도메인별 법률 전문 에이전트 시스템 규칙 및 프롬프트 템플릿
2. AgentExecutor: RAG 검색 도구 실행 결과를 agent_scratchpad에 주입하고 사건 맥락(chat_brief)을 포함하여 LLM 호출
3. build_react_agent: 카테고리별 시스템 프롬프트와 RAG 도구를 결합한 에이전트 인스턴스 생성
"""
from typing import List, Optional, Any, Dict
from langchain_core.prompts import PromptTemplate
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.observability.context import set_agent_name, get_agent_name

logger = get_logger(__name__)

BASE_SYSTEM = """당신은 대한민국 {category} 분야 법률 전문가입니다.
- 반드시 아래 벡터검색 도구 관찰 결과(Observation)와 사건 맥락(chat_brief)에 근거하여 사용자의 질문에 답변하세요.
- 벡터검색 도구는 최대 1회만 사용하세요. (결과가 0건일 때만 1회 추가 사용)
- 도구 관찰에서 관련 조문/근거가 보이면 즉시 'Final Answer:'로 답변을 마무리하세요.
- 같은 목적의 도구 사용을 반복하지 마세요.
- 인용한 법령·판례 출처는 반드시 Observation에 실제로 등장한 '(실제파일명.pdf, p.페이지)' 형식으로만 명시하세요.
- 검색 결과(Observation)에 존재하지 않는 파일명이나 페이지를 임의로 지어내어 인용하는 것은 엄격히 금지합니다.
- 한국어로 간결하고 명확하게 답하세요.
"""

REACT_TEMPLATE = """{system}

You have access to the following tools:
{tools}

Use the following format exactly:

Question: the input question to answer
Thought: think step-by-step about whether you need to use a tool
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation sequence may repeat AT MOST ONCE)
Thought: I now know the final answer
Final Answer: the final answer in Korean, citing legal sources strictly in '(파일명.pdf, p.페이지)' format ONLY from the actual Observation results above. Never invent or guess filenames that are not in Observation.

Begin!

[사건 및 대화 맥락]
{chat_brief}

Question: {input}
{agent_scratchpad}
"""


def _primary_tool_name(tools: List) -> str:
    """에이전트에 할당된 첫 번째 도구의 이름을 반환한다.

    Args:
        tools: 에이전트에 등록된 도구 리스트.

    Returns:
        str: 대표 도구 이름 (미존재 시 'retrieval_tool').
    """
    try:
        return getattr(tools[0], "name", "") or "retrieval_tool"
    except Exception:
        return "retrieval_tool"


class AgentExecutor:
    """법률 RAG 검색 도구와 프롬프트 템플릿을 결합하여 실행하는 에이전트 실행기.

    검색 도구를 먼저 호출하여 반환된 법령·판례 텍스트(Observation)를 `agent_scratchpad`에 주입하고,
    사건 맥락(`chat_brief`)과 함께 LLM을 호출하여 근거 기반 답변을 생성한다.
    """

    def __init__(self, agent: Any, tools: List, **kwargs):
        """AgentExecutor 인스턴스를 초기화한다.

        Args:
            agent: 렌더링할 PromptTemplate 또는 Runnable 객체.
            tools: 법률 RAG 검색 도구 리스트.
            **kwargs: 실행 옵션 인자.
        """
        self.agent = agent
        self.tools = tools

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """RAG 검색 도구를 실행하고 검색 결과(Observation)와 사건 맥락(chat_brief)을 주입해 LLM 답변을 생성한다.

        Args:
            inputs: 'input'(사용자 질문) 및 'chat_brief'(사건 요약/증거/그래프 경로)를 포함한 입력 딕셔너리.

        Returns:
            Dict[str, Any]: 생성된 최종 답변 문자열을 담은 {'output': str} 딕셔너리.
        """
        llm = get_llm(temperature=0.0)
        tool_names = ", ".join([t.name for t in self.tools if hasattr(t, "name")])
        tools_desc = "\n".join([f"{t.name}: {getattr(t, 'description', '')}" for t in self.tools if hasattr(t, "name")])

        # 프롬프트 템플릿 필수 변수 보강 (chat_brief 누락 방지)
        inputs_data = dict(inputs)
        if "tools" not in inputs_data:
            inputs_data["tools"] = tools_desc
        if "tool_names" not in inputs_data:
            inputs_data["tool_names"] = tool_names
        if not inputs_data.get("chat_brief"):
            inputs_data["chat_brief"] = "(제공된 사건 맥락 없음)"
        if "agent_scratchpad" not in inputs_data:
            inputs_data["agent_scratchpad"] = ""

        # 도구 실행 (RAG 검색 출처 수집 및 반환된 Observation을 agent_scratchpad에 주입)
        try:
            if self.tools and hasattr(self.tools[0], "invoke"):
                tool = self.tools[0]
                query_str = inputs.get("input", "")
                tool_obs = tool.invoke({"query": query_str})
                if tool_obs and not inputs_data["agent_scratchpad"]:
                    t_name = getattr(tool, "name", "retrieval_tool")
                    inputs_data["agent_scratchpad"] = (
                        f"Thought: 질문에 답하기 위해 {t_name} 도구로 관련 법령 및 판례를 검색합니다.\n"
                        f"Action: {t_name}\n"
                        f"Action Input: {query_str}\n"
                        f"Observation: {tool_obs}\n"
                        f"Thought: 위 Observation에서 확인된 법령·판례 근거와 [사건 및 대화 맥락]을 종합하여 최종 답변을 작성합니다.\n"
                        f"Final Answer: "
                    )
        except Exception as e:
            logger.error(f"도구 실행 오류: {e}")

        try:
            if hasattr(self.agent, "invoke"):
                rendered = self.agent.invoke(inputs_data)
                prompt_text = rendered.to_string() if hasattr(rendered, "to_string") else str(rendered)
            else:
                prompt_text = str(inputs_data)

            resp = llm.invoke(prompt_text)
            output = resp.content if hasattr(resp, "content") else str(resp)
            if "Final Answer:" in output:
                output = output.split("Final Answer:")[-1].strip()
        except Exception as e:
            logger.error(f"에이전트 LLM 호출 오류: {e}")
            output = f"오류: {e}"

        return {"output": output}


def create_react_agent(llm: Any, tools: List, prompt: Any) -> Any:
    """ReAct 프롬프트 객체를 반환하는 헬퍼 함수.

    Args:
        llm: 언어 모델 인스턴스.
        tools: 도구 리스트.
        prompt: 프롬프트 템플릿.

    Returns:
        Any: 바인딩된 프롬프트 템플릿 객체.
    """
    return prompt


@trace
def build_react_agent(
    category: str,
    tools: List,
    system_override: Optional[str] = None,
) -> AgentExecutor:
    """카테고리별 법률 전문 ReAct 에이전트 실행기(AgentExecutor)를 생성한다.

    Args:
        category: 법률 분야 카테고리명 (예: 주택임대차, 민사, 노동 등).
        tools: 해당 카테고리의 RAG 검색 도구 리스트.
        system_override: 도메인 특화 추가 지침 문자열 (선택사항).

    Returns:
        AgentExecutor: 초기화된 에이전트 실행기.
    """
    llm = get_llm(temperature=0.0)
    primary_tool = _primary_tool_name(tools)

    sys_prompt = BASE_SYSTEM.format(category=category)
    if system_override:
        sys_prompt = sys_prompt + "\n" + system_override.strip()

    tool_names = ", ".join([t.name for t in tools if hasattr(t, "name")])
    tools_desc = "\n".join([f"{t.name}: {getattr(t, 'description', '')}" for t in tools if hasattr(t, "name")])

    prompt = PromptTemplate.from_template(REACT_TEMPLATE).partial(
        system=sys_prompt,
        tools=tools_desc,
        tool_names=tool_names,
    )

    agent = create_react_agent(llm, tools, prompt)

    exec_ = AgentExecutor(
        agent=agent,
        tools=tools,
        handle_parsing_errors=True,
        verbose=True,
        max_iterations=3,
        max_execution_time=60,
        early_stopping_method="force",
        return_intermediate_steps=False,
    )
    logger.debug(f"[AGENT] built: category={category} tools={len(tools)} primary_tool={primary_tool}")
    return exec_

