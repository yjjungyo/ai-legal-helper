# -*- coding: utf-8 -*-
"""
모듈명: schemas.py

[모듈 개요]
Evaluation Harness의 데이터셋, 증거 매니페스트(Manifest) 및 평가 시나리오 데이터 스키마를 정의한다.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class EvidenceFileManifestItem(BaseModel):
    """단일 원본 증거 파일의 식별 및 무결성 메타데이터."""

    filename: str = Field(..., description="증거 파일명 (예: E01_주택임대차계약서.txt)")
    label: str = Field(..., description="증거 번호 라벨 (예: E01)")
    size_bytes: int = Field(..., description="파일 크기(바이트)")
    sha256: str = Field(..., description="SHA-256 해시값 (무결성 검증용)")
    line_count: int = Field(..., description="라인 수")
    is_in_db: bool = Field(False, description="PostgreSQL DB 등록 여부")
    db_document_id: Optional[str] = Field(None, description="DB 등록 시 Document UUID")
    db_status: Optional[str] = Field(None, description="DB 상태 (APPROVED, REVIEW_REQUIRED 등)")
    preview: str = Field("", description="원문 앞 200자 미리보기")


class EvidenceManifest(BaseModel):
    """사건 전체 증거 원본 매니페스트 모델."""

    case_name: str = Field("SC-001_전세보증금미반환_사건자료", description="사건 식별명")
    source_dir: str = Field(..., description="증거 원문 디렉터리 경로")
    total_raw_files: int = Field(..., description="디렉터리 내 전체 파일 개수")
    db_case_id: Optional[str] = Field(None, description="대응하는 DB Case UUID")
    db_registered_count: int = Field(0, description="DB 등록 완료된 파일 수")
    missing_files_in_db: List[str] = Field(default_factory=list, description="DB에 미등록된 파일 목록")
    files: List[EvidenceFileManifestItem] = Field(default_factory=list, description="각 파일별 상세 정보")


class EvaluationScenario(BaseModel):
    """단일 평가 시나리오 정의 모델."""

    scenario_id: str = Field(..., description="시나리오 고유 ID (예: SC01-T01, V01)")
    title: str = Field(..., description="시나리오 제목")
    category: str = Field("CORE", description="분류: CORE, VARIATION, NEGATIVE")
    user_question: str = Field(..., description="사용자 질문 또는 작업 요청")
    expected_focus: str = Field(..., description="핵심 검토 대상 쟁점/요건")
    required_evidence_labels: List[str] = Field(default_factory=list, description="필수 증거 라벨 목록")
    is_variation: bool = Field(False, description="변형/부정 테스트 여부")
    variation_type: Optional[str] = Field(None, description="변형 유형 (V01~V08 등)")
    description: str = Field("", description="시나리오 설명 및 평가 의도")

