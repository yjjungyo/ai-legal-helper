# -*- coding: utf-8 -*-
"""
모듈명: gold_schema.py

[모듈 개요]
AI Legal Helper Evaluation Harness v1.0의 정답 데이터셋(Gold Set) 스키마를 정의한다.
개발지시서 Section 4.2의 모든 필수 구성 항목을 Pydantic 모델로 엄격하게 구현한다.
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class ExpectedFact(BaseModel):
    """기대 사실관계 항목."""

    fact_id: str = Field(..., description="사실 고유 식별자")
    statement: str = Field(..., description="확인되어야 할 사실 문장")
    fact_category: Literal["CONTRACT", "PAYMENT", "RESIDENCE", "NOTICE", "ATTACHMENT", "NEGOTIATION", "GAP"] = Field(
        ..., description="사실 분류 카테고리"
    )
    source_evidence_label: str = Field(..., description="근거 증거 라벨 (예: E01, E02)")
    is_essential: bool = Field(True, description="핵심 요건사실 여부")
    status_note: Optional[str] = Field(None, description="기재 사실 vs 실제 행위 등 비고")


class ExpectedTimelineEvent(BaseModel):
    """기대 타임라인 사건 일자."""

    event_date: str = Field(..., description="날짜 (YYYY-MM-DD)")
    event_type: str = Field(..., description="이벤트 유형 (계약체결, 만료일, 통고도달 등)")
    description: str = Field(..., description="사건 설명")
    legal_significance: str = Field(..., description="법률적 의미 (기산점, 이행기 등)")


class ExpectedParty(BaseModel):
    """기대 당사자 정보."""

    name: str = Field(..., description="당사자 성명/기관명")
    role: str = Field(..., description="실체적 법률 역할 (임대인, 임차인, 가압류채권자 등)")
    contact: Optional[str] = Field(None, description="연락처")


class ExpectedIssue(BaseModel):
    """기대 법률 쟁점."""

    issue_id: str = Field(..., description="쟁점 식별자 (예: ISSUE_LEASE_TERMINATION)")
    issue_title: str = Field(..., description="쟁점 명칭")
    required_statute_names: List[str] = Field(default_factory=list, description="필수 관련 법령 조문")
    substantive_conclusion: str = Field(..., description="기대되는 실질적 법률 판단 요지")


class ExpectedStatute(BaseModel):
    """기대 적용 법령 조문."""

    law_name: str = Field(..., description="법령명 (예: 주택임대차보호법)")
    article: str = Field(..., description="조문 번호 (예: 제6조의2 제2항)")
    statute_id: str = Field(..., description="조문 식별자 (예: 주택임대차보호법_제6조의2)")
    relevance_summary: str = Field(..., description="본 사건에서의 적용 요건 및 효과")


class GoldCaseScenario(BaseModel):
    """단일 평가 시나리오의 정답(Gold Standard) 데이터 모델 (Section 4.2 규격)."""

    case_id: str = Field(..., description="사건 식별자")
    scenario_id: str = Field(..., description="시나리오 ID (예: SC01-T01)")
    question_id: str = Field(..., description="질문 ID")
    title: str = Field(..., description="시나리오 제목")
    user_question: str = Field(..., description="평가 질문 원문")

    # 증거 매니페스트 및 기대 기초 데이터
    evidence_manifest: List[str] = Field(default_factory=list, description="해당 시나리오의 관련 증거 라벨 목록")
    expected_facts: List[ExpectedFact] = Field(default_factory=list, description="식별되어야 할 기대 사실 목록")
    expected_timeline: List[ExpectedTimelineEvent] = Field(default_factory=list, description="기대 타임라인 목록")
    expected_parties: List[ExpectedParty] = Field(default_factory=list, description="기대 당사자 목록")
    expected_issues: List[ExpectedIssue] = Field(default_factory=list, description="기대 법률 쟁점 목록")

    # 적용 법령 및 판례
    applicable_statutes: List[ExpectedStatute] = Field(default_factory=list, description="적용 법령 조문 목록")
    applicable_precedents: List[str] = Field(default_factory=list, description="적용 판례 번호/요지 목록")

    # 법률 추론 및 결론
    required_legal_reasoning: List[str] = Field(default_factory=list, description="필수 법률 요건 포섭 추론 단계")
    expected_conclusions: List[str] = Field(default_factory=list, description="기대되는 최종 법률 결론")
    acceptable_alternative_conclusions: List[str] = Field(default_factory=list, description="허용 가능한 조건부/대안적 결론")

    # 대응 조치 및 권고사항
    required_next_actions: List[str] = Field(default_factory=list, description="필수 안내 실행 조치")
    conditional_next_actions: List[str] = Field(default_factory=list, description="조건부 안내 실행 조치")
    prohibited_recommendations: List[str] = Field(default_factory=list, description="금지되는 유해/허위 권고 (Safety)")

    # 미확인 사항 및 인용
    known_unknowns: List[str] = Field(default_factory=list, description="반드시 미확인으로 명시해야 할 사항")
    required_evidence_citations: List[str] = Field(default_factory=list, description="필수 인용되어야 할 증거 라벨")
    prior_context: Optional[str] = Field(None, description="후속 질문 시나리오의 직전 상담 맥락/선행 질문")

    # 검토 메타데이터
    review_status: Literal["VERIFIED_EXPERT", "PROVISIONAL"] = Field(
        "PROVISIONAL", description="검토 상태 (전문가 검토 전은 PROVISIONAL)"
    )
    reviewer: str = Field("AI Legal Helper Verification Team", description="검토자")
    gold_version: str = Field("1.2", description="Gold 데이터 버전 (v1.2 Freeze)")

