from typing import List, Optional, Any, Dict
from langchain_core.prompts import PromptTemplate
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.observability.context import set_agent_name, get_agent_name

logger = get_logger(__name__)

BASE_SYSTEM = """당신은 대한민국 {category} 분야 법률 전문가입니다.
- 벡터검색 결과를 참고하여 사용자의 질문에 답변하세요.
- 벡터검색 도구는 최대 1회만 사용하세요. (결과가 0건일 때만 1회 추가 사용)
- 도구 관찰에서 관련 조문/근거가 보이면 즉시 'Final Answer:'로 답변을 마무리하세요.
- 같은 목적의 도구 사용을 반복하지 마세요.
- 답변에는 **파일명과 페이지(또는 범위)**를 포함한 근거를 요약하세요.
- 한국어로 간결하게 답하세요.
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
Final Answer: the final answer in Korean, including brief citations with file names and page numbers

Begin!

Question: {input}
{agent_scratchpad}
"""

def _primary_tool_name(tools: List) -> str:
    try:
        return getattr(tools[0], "name", "") or "retrieval_tool"
    except Exception:
        return "retrieval_tool"

class AgentExecutor:
    """테스트를 위한 Mock AgentExecutor 구현체."""
    def __init__(self, agent: Any, tools: List, **kwargs):
        self.agent = agent
        self.tools = tools
        
    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Mock invoke 메서드."""
        llm = get_llm(temperature=0.0)
        tool_names = ", ".join([t.name for t in self.tools if hasattr(t, "name")])
        tools_desc = "\n".join([f"{t.name}: {getattr(t, 'description', '')}" for t in self.tools if hasattr(t, "name")])
        
        # 프롬프트 템플릿 필수 변수 보강
        inputs_data = dict(inputs)
        if "tools" not in inputs_data:
            inputs_data["tools"] = tools_desc
        if "tool_names" not in inputs_data:
            inputs_data["tool_names"] = tool_names
        if "agent_scratchpad" not in inputs_data:
            inputs_data["agent_scratchpad"] = ""
        
        # 도구 실행 (RAG 검색 출처 수집)
        try:
            if self.tools and hasattr(self.tools[0], "invoke"):
                self.tools[0].invoke({"query": inputs.get("input", "")})
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
        except Exception as e:
            logger.error(f"에이전트 LLM 호출 오류: {e}")
            output = f"오류: {e}"
            
        return {"output": output}

def create_react_agent(llm: Any, tools: List, prompt: Any) -> Any:
    """Mock create_react_agent 구현체."""
    return prompt

@trace
def build_react_agent(
    category: str,
    tools: List,
    system_override: Optional[str] = None,
) -> AgentExecutor:
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
        tool_names=tool_names
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
