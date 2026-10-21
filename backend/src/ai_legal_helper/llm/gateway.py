# -*- coding: utf-8 -*-
"""
모듈명: gateway.py

[모듈 개요]
Azure OpenAI 모델 인스턴스 생성 및 통합 콜백(Token Tracking, Langfuse 추적) 연결을 담당하는 게이트웨이 모듈이다.

[주요 기능]
1. 채팅 LLM(AzureChatOpenAI) 인스턴스 반환 및 내부 관측성 콜백 자동 바인딩
2. 텍스트 임베딩(AzureOpenAIEmbeddings) 인스턴스 반환
3. TokenTrackingCallbackHandler 및 Langfuse CallbackHandler 연동

[주의사항]
- Langfuse가 활성화된 경우(LANGFUSE_ENABLED=true), LLM의 모든 호출(입력/출력/토큰/지연시간)이 Langfuse 대시보드에 자동 기록된다.
- 토큰 카운팅 및 비용 통계를 위해 내부 TokenTrackingCallbackHandler가 항상 기본 등록된다.
"""
import os
from pathlib import Path
from typing import Optional, List, Any
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))
_env_path = Path(__file__).resolve().parents[3] / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_core.language_models.chat_models import BaseChatModel
from ai_legal_helper.observability.callbacks import TokenTrackingCallbackHandler
from ai_legal_helper.observability.langfuse_client import get_langfuse_callback_handler


def get_llm(
    model_name: Optional[str] = None,
    temperature: float = 0.0,
    callbacks: Optional[List[Any]] = None,
) -> BaseChatModel:
    """토큰 추적 및 Langfuse 관측성 콜백이 바인딩된 Azure OpenAI 채팅 모델 인스턴스를 반환한다.

    Args:
        model_name: 배포 모델명 (기본값: AZURE_OPENAI_DEPLOYMENT_CHAT 또는 gpt-4o)
        temperature: 샘플링 온도 (기본값: 0.0)
        callbacks: 추가로 등록할 LangChain 콜백 핸들러 리스트 (선택사항)

    Returns:
        BaseChatModel: 관측성 콜백이 부착된 AzureChatOpenAI 인스턴스
    """
    model_name = model_name or os.getenv("AZURE_OPENAI_DEPLOYMENT_CHAT", "gpt-4o")

    cb_list: List[Any] = [TokenTrackingCallbackHandler()]

    # LANGFUSE_CAPTURE_CONTENT=true일 때만 LangChain 원본 콜백 핸들러를 추가 등록한다.
    # 기본값(false)에서는 TokenTrackingCallbackHandler가 마스킹 정책을 준수하며 단일 Generation을 기록하므로
    # 중복 Generation 기록 및 상담 원문 노출을 동시에 방지한다.
    if os.getenv("LANGFUSE_CAPTURE_CONTENT", "false").lower() == "true":
        lf_handler = get_langfuse_callback_handler()
        if lf_handler:
            cb_list.append(lf_handler)

    if callbacks:
        cb_list.extend(callbacks)

    llm = AzureChatOpenAI(
        azure_deployment=model_name,
        temperature=temperature,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
        callbacks=cb_list,
    )
    return llm


def get_embeddings() -> AzureOpenAIEmbeddings:
    """Azure OpenAI 텍스트 임베딩 모델 인스턴스를 반환한다.

    Returns:
        AzureOpenAIEmbeddings: 설정된 임베딩 배포 인스턴스
    """
    return AzureOpenAIEmbeddings(
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_EMBED", "text-embedding-3-large"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
    )
