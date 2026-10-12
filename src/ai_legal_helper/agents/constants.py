# -*- coding: utf-8 -*-
from typing import Dict, List

CATEGORIES: List[str] = [
    "헌법", "민법", "형법", "상법", "노동", "행정", "조세", "국제",
]

CATEGORY_KO_TO_ENG: Dict[str, str] = {
    "헌법": "constitution",
    "민법": "civil",
    "형법": "criminal",
    "상법": "commercial",
    "노동": "labor",
    "행정": "administrative",
    "조세": "tax",
    "국제": "international",
}

CATEGORY_ENG_TO_KO: Dict[str, str] = {v: k for k, v in CATEGORY_KO_TO_ENG.items()}

_ALLOWED_ENG_KEYS = set(CATEGORY_KO_TO_ENG.values())

def to_eng(category: str) -> str:
    if not category:
        return ""
    return CATEGORY_KO_TO_ENG.get(category, category)

def collection_name_for(category: str) -> str:
    eng = to_eng(category)
    return f"law_docs_{eng}"

def get_agent_name(category: str) -> str:
    eng = to_eng(category)
    if eng not in _ALLOWED_ENG_KEYS:
        raise KeyError(f"Unsupported category: '{category}'")
    return f"{eng}_agent"

def get_tool_name(category: str) -> str:
    eng = to_eng(category)
    if eng not in _ALLOWED_ENG_KEYS:
        raise KeyError(f"Unsupported category: '{category}'")
    return f"{eng}_retrieval_tool"

