# -*- coding: utf-8 -*-
from typing import List
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.agents.constants import get_agent_name

logger = get_logger(__name__)

@trace
def plan_tools(categories: List[str]) -> List[str]:
    plan = [get_agent_name(c) for c in categories]
    logger.debug(f"[쟁점 도구 계획] 분야={categories} -> 실행도구={plan}")
    return plan
