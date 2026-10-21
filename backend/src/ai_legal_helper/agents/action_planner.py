# -*- coding: utf-8 -*-
"""
모듈명: action_planner.py

[모듈 개요]
사건의 사실관계, 타임라인, 증거, 법률 쟁점 등 분석된 컨텍스트를 종합하여,
주택 임대차 분쟁 Action Catalog를 바탕으로 사용자가 취할 수 있는 구체적인
법률 대응 행동(Action Plan)을 추천하고 구조화하여 반환하는 LangChain Agent 모듈.

[주요 기능]
1. LLM을 활용한 Action Catalog 기반 행동 계획 생성
2. Pydantic 구조화 출력을 통한 행동 및 요건 정의
3. 기존 사실관계 및 증거 상태와의 매핑

[주의사항]
이 모듈이 반환하는 날짜나 기한은 보조 참고용이며, 정확한 기한 계산은
별도의 Deadline Engine에서 처리한다.
LLM 단독 판단으로 확정적 법률 행위를 강제하지 않는다.
"""

from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
from langchain_core.prompts import PromptTemplate

from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.context import get_current_span_id
from ai_legal_helper.observability.langfuse_client import update_span
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

# 표준 법률 분쟁 대응 Action Catalog (민사, 노동, 상사, 형사, 가사 등 범용 대응)
ACTION_CATALOG = [
    "사실관계 확인 및 입증 증거 자료 확보",
    "계약 체결 및 의사표시 도달 사실 확인",
    "상대방에 대한 권리행사 및 최고(내용증명 등 통지)",
    "관련 법령 요건 및 판례 적합성 검토",
    "원상회복, 손해배상 또는 반환 청구",
    "합의·조정 등 비소송적 분쟁 해결 시도",
    "가압류·가처분 등 보전처분 검토",
    "지급명령, 본안 소송 또는 권리구제 절차 검토",
    "판결 및 집행권원 확보 후 강제집행 절차 검토",
    "전문 변호사·법률전문가 정밀 대면 상담 권고",
]

class PlannedRequirement(BaseModel):
    requirement_type: str = Field(description="요건 유형 (FACT_CONFIRMATION, EVIDENCE_REQUIRED, LEGAL_CONDITION 중 택 1)")
    description: str = Field(description="요건에 대한 상세 설명 (예: 계약 종료 의사 도달 확인 필요)")
    satisfaction_status: str = Field(description="현재 사건 정보 기준 요건 충족 여부 (SATISFIED, UNSATISFIED, UNKNOWN 중 택 1)")

class PlannedDependency(BaseModel):
    depends_on_action_title: str = Field(description="선행되어야 하는 다른 행동의 제목")
    dependency_type: str = Field(description="의존성 유형 (PREREQUISITE, OPTIONAL_PRECURSOR 중 택 1)")

class PlannedAction(BaseModel):
    action_type: str = Field(description="Action Catalog에서 선택하거나, 사건에 특화된 필요한 행동 유형")
    title: str = Field(description="행동의 짧은 제목")
    description: str = Field(description="행동에 대한 상세 설명 및 실행 방법")
    priority: str = Field(description="우선순위 (HIGH, MEDIUM, LOW 중 택 1)")
    rationale: str = Field(description="이 행동을 추천하는 구체적인 사실적/법률적 이유")
    risk_level: str = Field(description="이 행동을 취했을 때 또는 방치했을 때의 예상 위험도 (HIGH, LOW, NONE 중 택 1)")
    requirements: List[PlannedRequirement] = Field(default_factory=list, description="이 행동을 실행하기 위해 충족해야 하는 요건들")
    dependencies: List[PlannedDependency] = Field(default_factory=list, description="이 행동의 선행조건으로 필요한 다른 행동들")

class ActionPlanResponse(BaseModel):
    actions: List[PlannedAction] = Field(description="현재 사건에서 제안되는 행동 목록 (선후관계 고려)")


@trace
def plan_legal_actions(context_text: str) -> ActionPlanResponse:
    """
    사건 컨텍스트를 바탕으로 Action Plan을 생성한다.
    
    Args:
        context_text: 사건의 사실관계, 증거, 이슈, 기존 분석 내용이 포함된 텍스트.
        
    Returns:
        ActionPlanResponse: 구조화된 추천 행동 목록.
    """
    catalog_str = "\n".join(f"- {c}" for c in ACTION_CATALOG)
    
    prompt = PromptTemplate.from_template(
        "당신은 대한민국 법률 분쟁 대응 전략을 수립하는 AI 법률 보조원입니다.\n"
        "다음 사건의 현황(사실, 증거, 분석 결과)을 읽고 사용자가 취해야 할 실질적인 법률 대응 계획을 수립하세요.\n\n"
        "[Action Catalog - 다음 항목들을 우선적으로 검토하여 필요한 행동을 선별하세요]\n"
        "{catalog_str}\n\n"
        "[사건 컨텍스트]\n"
        "{context_text}\n\n"
        "[지침]\n"
        "1. 제공된 사건 정보만을 바탕으로 사건의 실제 성격(민사, 노동, 상사, 형사, 가사 등)에 부합하는 논리적이고 실질적인 행동을 추천하세요.\n"
        "2. 행동은 구체적이어야 하며, 선행되어야 할 행동(Dependency)이 있다면 명시하세요.\n"
        "3. 각 행동을 취하기 위한 법적, 사실적 요건(Requirement)이 만족되었는지(SATISFIED) 부족한지(UNSATISFIED/UNKNOWN) 평가하세요.\n"
        "4. 환각을 방지하기 위해 증거가 없는 주장은 UNSATISFIED 로 처리하세요.\n"
    )
    
    # Azure OpenAI 호환성을 위해 function_calling 방식으로 구조화 출력 호출
    llm = get_llm(temperature=0.0).with_structured_output(ActionPlanResponse, method="function_calling")
    
    try:
        response = llm.invoke(prompt.format(catalog_str=catalog_str, context_text=context_text))
        try:
            update_span(get_current_span_id(), {
                "action_count": len(response.actions),
                "priorities": [a.priority for a in response.actions],
                "missing_requirements": sum(1 for a in response.actions for r in a.requirements if r.satisfaction_status != "SATISFIED")
            })
        except:
            pass
        return response
    except Exception as e:
        logger.error(f"[ACTION_PLANNER] 행동 계획 생성 실패: {e}")
        # 오류 발생 시 빈 리스트 반환 방어 코드
        return ActionPlanResponse(actions=[])

