# -*- coding: utf-8 -*-
"""
전문 법률 에이전트(Specialist Agent) 모듈

이 모듈은 민법, 행정, 상법, 헌법 등 각 법률 분야별 특화된 LangChain Agent를 생성하고 실행하는 역할을 담당한다.
분야별 프롬프트와 RAG 검색 도구를 결합하여 특화된 답변을 도출하며, P2.1 검증 단계에서
AgentExecutor가 내부 도구의 반환값(검색된 출처)을 외부로 노출하지 않는 문제를 해결하기 위해
`contextvars`를 활용해 검색된 출처를 별도로 추출하고 반환한다.
"""
from ai_legal_helper.agents.legal.base_agent import build_react_agent, AgentExecutor
from ai_legal_helper.rag.retrieval_factory import make_fixed_retrieval_tool
from ai_legal_helper.agents.constants import get_agent_name, get_tool_name, to_eng
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.context import set_agent_name

SYSTEM_PROMPTS = {
    "민법": "당신은 민법 분야를 담당합니다. 계약/불법행위/물권/가족상속 쟁점을 식별하고 요건사실과 입증책임을 정리하세요.",
    "행정": "당신은 행정 분야를 담당합니다. 행정행위/처분사유/쟁송절차(행정심판·소송) 등을 구조화하여 안내하세요.",
    "상법": "당신은 상법 분야를 담당합니다. 회사/어음·수표/보험 등 세부 파트를 구분하고 상무적 쟁점을 도출하세요.",
    "헌법": "당신은 헌법 분야를 담당합니다. 국가기관의 권한, 기본권 및 헌법재판 소송 절차 등을 명확히 구분하여 설명하세요.",
    "형법": "당신은 형법 분야를 담당합니다. 구성요건 해당성/위법성/책임성 체계적으로 검토하고 판례의 태도를 반영하세요.",
    "국제": "당신은 국제법 분야를 담당합니다. 조약/관습국제법/국제 형사·외교관계 및 분쟁해결 절차 등을 구분하여 설명하세요.",
    "노동": "당신은 노동 분야를 담당합니다. 근로기준법/노동3권/징계·해고 요건/퇴직금 산정 등을 판례 근거와 함께 설명하세요.",
    "조세": "당신은 조세 분야를 담당합니다. 과세표준/세율/불복절차(이의신청·심판·소송) 및 신고기한 등을 정확히 명시하세요."
}

_AGENTS: dict[str, AgentExecutor] = {}

def get_specialist_agent(category_ko: str) -> AgentExecutor:
    """
    특정 법률 분야의 전문 에이전트를 생성하거나 캐시에서 가져온다.

    LangChain Agent 객체 생성 비용이 크기 때문에 전역 변수 `_AGENTS`에 캐싱하여 재사용한다.

    Args:
        category_ko (str): 법률 분야 한글 이름 (예: "민법")

    Returns:
        AgentExecutor: 해당 분야에 특화된 LangChain AgentExecutor 인스턴스
    """
    global _AGENTS
    if category_ko in _AGENTS:
        return _AGENTS[category_ko]
    
    eng = to_eng(category_ko)
    tool_name = get_tool_name(category_ko)
    tool = make_fixed_retrieval_tool(tool_name, eng, category_ko)
    system = SYSTEM_PROMPTS.get(category_ko, f"당신은 {category_ko} 분야를 담당합니다.")
    
    agent = build_react_agent(category_ko, [tool], system_override=system)
    _AGENTS[category_ko] = agent
    return agent

@trace
def run_specialist_agent(category_ko: str, question: str, chat_brief: str) -> tuple[str, str, list]:
    """
    전문 에이전트를 실행하여 질문에 대한 답변과 참조한 법률 근거를 반환한다.

    이 함수는 에이전트를 실행하기 전 P0 관측성 강화를 위해 `contextvars`에 에이전트 이름을 설정하고,
    AgentExecutor가 내부 Tool 실행 결과를 삼키는 문제를 우회하기 위해 `reset_retrieved_sources()`로
    상태를 초기화한 후 실행 종료 시 `get_retrieved_sources()`를 통해 RAG 출처 목록을 수집한다.

    Args:
        category_ko (str): 실행할 법률 분야 (예: "민법")
        question (str): 사용자 질문 내용
        chat_brief (str): 이전 대화 맥락 요약

    Returns:
        tuple[str, str, list]: 
            - 카테고리 (str)
            - 에이전트 답변 (str)
            - RAG 도구가 컨텍스트에 저장한 출처 목록 (list)
              오류 발생 시 답변 텍스트에 오류 메시지를 담고 빈 출처 목록 반환
    """
    from ai_legal_helper.observability.context import reset_retrieved_sources, get_retrieved_sources
    agent = get_specialist_agent(category_ko)
    agent_name_str = get_agent_name(category_ko)
    set_agent_name(agent_name_str) # P0 Observability: Set agent name in context!
    
    reset_retrieved_sources()
    
    try:
        out = agent.invoke({"input": question, "agent_scratchpad": "", "chat_brief": chat_brief})
        text = (out.get("output", "") or "").strip()
        sources = get_retrieved_sources()
        return (category_ko, text or "(답변 없음)", sources)
    except Exception as e:
        return (category_ko, f"전문 에이전트 실행 중 오류: {str(e)}", [])

