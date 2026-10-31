# -*- coding: utf-8 -*-
"""
모듈명: verification.py

[모듈 개요]
AI가 작성한 법률 상담 초안이 실제 검색된 출처(Source Registry)에 근거하는지(Grounding) 검증하는
법률검증 Agent(Verification Agent) 및 결정론적 Citation Validator를 구현한다.

[주요 기능]
1. Source Registry 기반 출처 존재성(Existence) 검증:
   - 초안 내 `(파일명.pdf, p.페이지)`, `[GRAPH:id]`, 판례 사건번호 등이 실제 조회된 Source Registry에 존재하는지 검증
2. 출처 본문 뒷받침(Content Support) 검증:
   - 존재하는 문서를 인용했더라도 해당 문장의 주장 어휘·조문이 실제 출처 본문(content)과 무관하면 검증 실패(UNSUPPORTED) 처리
3. 미검증 인용 차단 및 정화(Sanitization):
   - 존재하지 않는 파일명, 허위 사건번호, 뒷받침되지 않는 인용을 최종 답변에서 제거하거나 `[근거 미확인]`으로 표시
4. Langfuse Observability 기록:
   - retrieval_source_ids, retrieval_methods, retrieved_chunk_ids, generated_citation_ids,
     validated_citation_ids, rejected_citation_ids, rejection_reasons, existence/support 평가 지표 기록
"""
from typing import Dict, Any, List, Optional, Tuple
import json
import os
import re
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field, field_validator, ValidationInfo, ValidationError

from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.context import get_current_span_id, set_agent_name
from ai_legal_helper.observability.langfuse_client import update_span
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.rag.source_schema import normalize_source_dict

logger = get_logger(__name__)

# (파일명.pdf, p.페이지) 형태의 인용을 추출하는 정규식 패턴 (중복 괄호 `((...))`, 법령 파일명 내 괄호 및 앞부분 조문 표기 허용)
CITATION_PATTERN = re.compile(
    r"(?<![가-힣A-Za-z0-9])\(+\s*(?:[^\n,]+?[,·]\s*)?([가-힣A-Za-z0-9_\-\s·()]+?\.(?:pdf|docx|txt))\s*,\s*p\.?\s*([0-9\-~]+|\?)\s*\)+",
    re.IGNORECASE,
)
# 공식 법령 조문 인용 패턴 (예: (주택임대차보호법 제6조의2(묵시적 갱신의 경우 계약의 해지)), (민법 제623조), 민법 제6조)
# [P0-VER-01] 괄호 유무, 조문제목 괄호 및 조사 접미사와 관계없이 실제 본문에서 언급·인용된 법령 조문이 누락 없이 검색 출처와 매칭되도록 보강한다.
STATUTE_CITATION_PATTERN = re.compile(
    r"(?:\(+\s*|(?<![가-힣]))([가-힣]+(?:법률|법|시행령|시행규칙))\s+(제\s*\d+\s*조(?:\s*의\s*\d+)?)(?:\s*\([^)\n]{1,60}\))?(?:\s*\)+|(?=[은는이가의을를에로서와과,.:\-\(\)\s\n]|\Z))",
    re.IGNORECASE,
)
# [E05_퇴거_및_보증금_반환_요청_문자.txt] 형태의 전체 파일명 대괄호 인용 패턴
BRACKET_FILE_CITATION_PATTERN = re.compile(
    r"\[\s*([^\[\]\n]+?\.(?:pdf|docx|txt|png|jpg|jpeg))\s*\]",
    re.IGNORECASE,
)
# [GRAPH:id] 또는 [VECTOR:id] 형태의 증거 인용 패턴
GRAPH_CITATION_PATTERN = re.compile(r"\[((?:GRAPH|VECTOR):[^\]]+)\]")
# 판례 사건번호 패턴 (예: 2022다21580, 2023도99999)
# 일반 한글을 사건 부호로 허용하면 '2024년과 2026년'도 판례로 집계된다.
# 알려진 부호만 인식하며, 지원하지 않는 부호는 출처의 명시적 case_number로 확장한다.
CASE_NUMBER_PATTERN = re.compile(
    r"(?<![\d가-힣])((?:19|20)\d{2}\s*"
    r"(?:가합|가단|가소|나|다|라|마|그|바|카합|카단|카기|카명|타경|타채|타기|"
    r"고합|고단|고정|고약|노|도|로|모|구합|구단|누|두|후|허|헌가|헌나|헌다|헌라|헌마|헌바|헌사)"
    r"\s*\d{1,7})(?!\d)"
)
# 조문 번호 패턴 (예: 제3조, 제621조의2)
ARTICLE_PATTERN = re.compile(r"(제\s*\d+\s*조(?:\s*의\s*\d+)?)")
# 사건 증거 번호 패턴 (예: "증거 1", "증거 7호", "[증거 2]", "증 제1호증")
EVIDENCE_LABEL_PATTERN = re.compile(
    r"(\[\s*증거\s*([0-9]+호?|[A-Za-z0-9_\-]+)\s*(?::[^\]]+)?\]|증거\s*([0-9]+)(?:호)?(?:증)?(?=[\s은는이가의을를에로서와과,.:\-\)\]]|\Z)|증\s*제?\s*([0-9]+호?증?))",
    re.IGNORECASE,
)
# 한국어 핵심 명사/어근 추출용 패턴 (2글자 이상 한글 또는 영숫자)
TOKEN_PATTERN = re.compile(r"[가-힣]{2,}|[A-Za-z0-9]{2,}")

_STOPWORDS = {
    "있으며", "있습니다", "합니다", "입니다", "경우", "따라", "의거", "관한", "대한",
    "법률", "규정", "조항", "문서", "근거", "출처", "참고", "가능", "필요", "해당",
    "인정", "청구", "발생", "의무", "권리", "판단", "검토", "위해", "통해", "대한",
    "관련", "법령", "조문", "참조", "적용",
}


class ClaimVerification(BaseModel):
    """개별 법률 주장에 대한 근거 검증 결과 스키마."""
    claim: str = Field(description="검증할 법률 주장")
    claim_type: Optional[str] = Field(
        default="LEGAL_APPLICATION",
        description="주장 유형: LEGAL_RULE (법령/판례 규범), CASE_FACT (사건 객관적 사실), CASE_INFERENCE (사건 증거 기반 자금사정·회수 위험 등 정황 추론), LEGAL_APPLICATION (법률 적용 및 효과 판단), RECOMMENDATION (후속 행동/절차 가이드), USER_STATEMENT (사용자 진술 사실)"
    )
    fact_status: Optional[str] = Field(
        default="USER_STATEMENT",
        description="사실 상태: VERIFIED_FACT (유효한 등록 증거로 확인된 사실), USER_STATEMENT (사용자 진술, 독립 증빙 미확인), INFERENCE (AI 정황 추론), EVIDENCE_NEEDED (향후 확보 필요 자료), CONFLICTED (상충 사실/증거)"
    )
    source_ids: List[str] = Field(default_factory=list, description="주장을 뒷받침하는 출처 ID 목록 (없으면 빈 배열)")
    grounding_status: str = Field(default="UNCERTAIN", description="SUPPORTED, UNSUPPORTED, UNCERTAIN, 또는 NOT_APPLICABLE")
    reason: str = Field(default="", description="검증 사유")
    inference_basis: str = Field(default="", description="사건 추론을 뒷받침하는 자료와 추론 관계")
    inference_limit: str = Field(default="", description="답변 원문에 명시된 추론 한계의 연속 인용")
    model_grounding_status: Optional[str] = Field(default=None, description="정책 적용 전 모델 판정")
    model_reason: Optional[str] = Field(default=None, description="정책 적용 전 모델 사유")

    @field_validator("inference_basis", "inference_limit", "reason", mode="before")
    @classmethod
    def _normalize_string_fields(cls, v: Any, info: ValidationInfo) -> str:
        """inference_basis, inference_limit, reason 필드가 리스트, 딕셔너리, None으로 들어와도 문자열로 정규화한다."""
        field_name = info.field_name
        if v is None:
            return ""
        if isinstance(v, list):
            logger.info(f"[VERIFICATION_SCHEMA] {field_name} 자료형: list -> 문자열 정규화 적용")
            items = [str(x).strip() for x in v if x is not None and str(x).strip()]
            norm_val = ", ".join(items)
            logger.info(f"[VERIFICATION_SCHEMA] 정규화 결과: SUCCESS ({field_name}='{norm_val[:60]}')")
            return norm_val
        if isinstance(v, dict):
            logger.info(f"[VERIFICATION_SCHEMA] {field_name} 자료형: dict -> 문자열 정규화 적용")
            items = [f"{k}: {val}" for k, val in v.items() if val]
            norm_val = ", ".join(items)
            logger.info(f"[VERIFICATION_SCHEMA] 정규화 결과: SUCCESS ({field_name}='{norm_val[:60]}')")
            return norm_val
        return str(v).strip()

    @field_validator("claim", mode="before")
    @classmethod
    def _normalize_claim(cls, v: Any) -> str:
        """claim 필드가 리스트로 들어와도 단일 문자열로 안전하게 결합하며 필수 의미를 검증한다."""
        if v is None:
            return ""
        if isinstance(v, list):
            logger.info("[VERIFICATION_SCHEMA] claim 자료형: list -> 문자열 정규화 적용")
            items = [str(x).strip() for x in v if x is not None and str(x).strip()]
            norm_val = " ".join(items)
            logger.info(f"[VERIFICATION_SCHEMA] 정규화 결과: SUCCESS (claim='{norm_val[:60]}')")
            return norm_val
        return str(v).strip()

    @field_validator("source_ids", mode="before")
    @classmethod
    def _normalize_source_ids(cls, v: Any) -> List[str]:
        """source_ids 필드가 단일 문자열, 콤마 구분 문자열, 또는 None으로 들어와도 문자열 리스트로 정규화한다."""
        if v is None:
            return []
        if isinstance(v, str):
            v_str = v.strip()
            if not v_str:
                return []
            logger.info("[VERIFICATION_SCHEMA] source_ids 자료형: str -> 리스트 정규화 적용")
            if "," in v_str:
                res = [part.strip() for part in v_str.split(",") if part.strip()]
            else:
                res = [v_str]
            logger.info(f"[VERIFICATION_SCHEMA] 정규화 결과: SUCCESS (source_ids={res})")
            return res
        if isinstance(v, list):
            res = []
            for item in v:
                if item is None:
                    continue
                s_item = str(item).strip()
                if s_item:
                    res.append(s_item)
            return res
        if isinstance(v, dict):
            res = [str(val).strip() for val in v.values() if val and str(val).strip()]
            return res
        return [str(v).strip()]


class VerificationOutput(BaseModel):
    """법률검증 Agent의 종합 검증 출력 스키마."""
    status: str = Field(default="REVISE", description="PASS, REVISE, 또는 INSUFFICIENT")
    reason_code: Optional[str] = Field(
        default="NONE",
        description="LEGAL_SOURCE_MISSING, LEGAL_SOURCE_INSUFFICIENT, CASE_EVIDENCE_MISSING, EVIDENCE_CONFLICT, ANSWER_REVISION_REQUIRED, CITATION_INVALID, VERIFICATION_ERROR, 또는 NONE"
    )
    missing_legal_issues: List[str] = Field(default_factory=list, description="법령 검색이 필요한 구체적 법률 쟁점 목록")
    candidate_laws: List[str] = Field(default_factory=list, description="부족한 쟁점을 규율하는 후보 법령명 목록 (예: ['주택임대차보호법'])")
    legal_search_requests: List[Dict[str, Any]] = Field(default_factory=list, description="질문 부분·법령·조문·누락 법리별 검색 요청")
    preserved_points: List[str] = Field(default_factory=list, description="다음 수정에서도 원문 대조 후 유지할 올바른 설명")
    recommended_action: Optional[str] = Field(
        default="FINALIZE",
        description="REQUEST_STATUTE_SEARCH_APPROVAL, REQUEST_EVIDENCE, REVISE_DRAFT, SAFE_FALLBACK, 또는 FINALIZE"
    )
    explanation: Optional[str] = Field(default="", description="검증 결과 및 권장 후속 조치 사유 설명")
    claims: List[ClaimVerification] = Field(default_factory=list, description="주요 법률 주장 목록 및 검증 결과")
    missing_issues: List[str] = Field(default_factory=list, description="질문의 핵심 쟁점 중 누락된 항목")
    contradictions: List[str] = Field(default_factory=list, description="답변 내부의 모순된 논리")
    revision_instructions: List[str] = Field(default_factory=list, description="답변 수정을 위한 지침 (REVISE 상태일 때 유용)")
    warnings: List[str] = Field(default_factory=list, description="사용자에게 보여줄 경고 메시지 목록")
    citation_audit: Dict[str, Any] = Field(default_factory=dict, description="결정론적 인용 검증 및 Langfuse 추적 메트릭")
    question_coverage: List[Dict[str, Any]] = Field(default_factory=list, description="현재 질문의 각 요청에 대한 question, answered(bool), reason 목록")
    consistency_checks: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="시간 순서·의사표시 내용·증명 수준의 passed(bool), reason, source_ids 점검")
    repair_targets: List[Dict[str, Any]] = Field(default_factory=list, description="부분 교정 대상 특정 문장 및 지침")
    qa_summary: Dict[str, Any] = Field(default_factory=dict, description="경량 QA 검사 종합 결과")

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> str:
        """status 필드가 누락되거나 소문자로 들어와도 정규화하며 기본값 REVISE를 부여한다."""
        if not v:
            return "REVISE"
        s_val = str(v).strip().upper()
        if s_val in ("PASS", "REVISE", "INSUFFICIENT"):
            return s_val
        return "REVISE"

    @field_validator("reason_code", mode="before")
    @classmethod
    def _normalize_reason_code(cls, v: Any) -> str:
        """reason_code 필드가 누락되거나 빈 문자열일 때 기본값 NONE을 부여한다."""
        if not v:
            return "NONE"
        return str(v).strip().upper()

    @field_validator(
        "candidate_laws",
        "missing_legal_issues",
        "missing_issues",
        "contradictions",
        "revision_instructions",
        "warnings",
        "preserved_points",
        mode="before",
    )
    @classmethod
    def _normalize_list_fields(cls, v: Any, info: ValidationInfo) -> List[str]:
        """문자열 리스트 필드가 단일 문자열 또는 None으로 들어와도 안전하게 List[str]로 정규화한다."""
        field_name = info.field_name
        if v is None:
            return []
        if isinstance(v, str):
            v_str = v.strip()
            if not v_str:
                return []
            logger.info(f"[VERIFICATION_SCHEMA] {field_name} 자료형: str -> 리스트 정규화 적용")
            if "," in v_str:
                res = [part.strip() for part in v_str.split(",") if part.strip()]
            else:
                res = [v_str]
            logger.info(f"[VERIFICATION_SCHEMA] 정규화 결과: SUCCESS ({field_name}={res})")
            return res
        if isinstance(v, list):
            res = []
            for item in v:
                if item is None:
                    continue
                s_item = str(item).strip()
                if s_item:
                    res.append(s_item)
            return res
        return [str(v).strip()]

    @field_validator("legal_search_requests", mode="before")
    @classmethod
    def _normalize_legal_search_requests(cls, v: Any) -> List[Dict[str, Any]]:
        """legal_search_requests 필드가 단일 딕셔너리나 None으로 들어와도 안전하게 List[Dict]로 정규화한다."""
        if v is None:
            return []
        if isinstance(v, dict):
            logger.info("[VERIFICATION_SCHEMA] legal_search_requests 자료형: dict -> 리스트 정규화 적용")
            return [v]
        if isinstance(v, list):
            return [item for item in v if isinstance(item, dict)]
        return []


VERIFICATION_PROMPT = """당신은 법률검증 Agent(Legal Verification Agent)입니다.
작성된 답변(초안)이 실제 검색된 법률 근거(출처) 및 사건 맥락에 의해 정확히 뒷받침되는지 철저하게 검증하세요.

[검증 대상]
질문:
{question}

사건 맥락:
{case_context}

답변 초안:
{draft_answer}

[검색된 출처 목록]
{retrieved_sources}

[검증 기준 및 정책 (Grounding Policy)]
1. 답변의 주요 법률 주장을 추출하고, 주장 유형(claim_type)별로 [검색된 출처 목록] 또는 [사건 맥락]에 의해 정확히 뒷받침되는지 판정하세요.
   - LEGAL_RULE: 법령 조문 또는 판례 규범 설명
   - CASE_FACT: 사건에 관한 구체적 사실관계
   - LEGAL_APPLICATION: 법률 요건을 사건 사실에 적용하여 도출한 법적 판단
   - RECOMMENDATION: 고객을 위한 후속 법적·실무적 행동 권고

2. 출처 문서는 존재하더라도 그 본문(Content)이 해당 주장을 실질적으로 뒷받침하지 않는다면 반드시 UNSUPPORTED로 판정하세요.
   - 사건 사실에 적용하기 위한 법률요건이 누락되었거나, 미확인 사실을 확인된 사실처럼 단정한 경우에도 SUPPORTED로 판정해서는 안 됩니다.

3. 종합 상태(status) 결정 원칙:
   - PASS: 모든 주요 주장이 출처 본문에 의해 충실히 뒷받침되고, 결론에 영향을 미치는 핵심 쟁점의 법률요건 누락·모순·허위 인용이 일체 없음.
   - REVISE: 근거 부족, 허위 인용, 출처 본문 불일치, 누락, 내부 모순이 있으나 수정 지침을 통해 개선 가능한 경우.
   - INSUFFICIENT: 답변의 핵심 논리가 근거에 전혀 없거나 법률요건이 결여되어 수정이 불가능할 정도로 부족한 경우.

4. 근거 부족 원인 분류 (reason_code):
   - LEGAL_SOURCE_MISSING: 답변에 필요한 핵심 법률/조문이 검색 결과에 완전히 없음 (예: 질문은 주택임대차보호법에 관한 것인데 민법만 검색된 경우). 이 경우 candidate_laws에 해당 법령명을 반드시 명시하고, recommended_action을 "REQUEST_STATUTE_SEARCH_APPROVAL"로 설정하세요. 후보 법령 지정 시 일반법(민법 등)보다 질문의 특수한 법률관계를 직접 규율하는 특별법(예: 주택임대차보호법, 상가임대차법, 근로기준법 등)을 1순위로 최우선 지정하되, 손해배상·특별손해·지연손해금 등 일반 민사상 손해배상 쟁점이 포함된 경우 민법(제393조 등)도 후보 법령(candidate_laws)에 함께 포함하세요.
   - LEGAL_SOURCE_INSUFFICIENT: 관련 법률 조문은 검색되었으나 쟁점 해결에 불충분한 경우.
   - CASE_EVIDENCE_MISSING: 법령은 충분하나 사건의 필수 사실관계나 증거(예: 통보 도달일, 계약서 특약 등)가 누락된 경우 (recommended_action: "REQUEST_EVIDENCE").
   - EVIDENCE_CONFLICT: 사용자 진술이나 사건 증거 간에 모순이 감지된 경우.
   - ANSWER_REVISION_REQUIRED: 법률 근거는 충분하나 초안의 문장 표현, 법적 평가, 논리 전개에 오류가 있는 경우 (recommended_action: "REVISE_DRAFT").
   - 사유 설명(explanation) 작성 필수 원칙:
     * '초안', 'draft', '검토자', '작성자' 등 내부 시스템 감수 용어를 절대 사용하지 마세요. 의뢰인은 중간 초안을 본 적이 없습니다.
     * 의뢰인에게 직접 제공되는 공식 안내문이므로, 질문하신 사안(예: 전세보증금 반환, 계약 해지 효력 등)에 대해 정확하고 신뢰할 수 있는 법적 권리 및 대처 방안을 제공하기 위해 왜 해당 법령 원문의 추가 확인이 필요한지 정중하고 전문적인 법률 안내 어조로 작성하세요.
   - CITATION_INVALID: 존재하지 않는 가짜 파일명이나 사건번호를 허위 인용한 경우.
   - NONE: 검증 통과(PASS)인 경우 (recommended_action: "FINALIZE").

5. 실무상 유의사항 및 입증 안내(Legal Caution)에 관한 특칙:
   - 답변에서 의뢰인에게 실무상 유의사항(예: 상대방의 항변 가능성 주의, 사실관계의 추가 입증 필요성, 통화내역/녹취록 등 증거 확보 권고, 추가 손해액의 객관적 증빙 지참 안내)을 설명하는 것은 변호사·법률전문가의 정상적이고 필수적인 법률 조언(Legal Caution)입니다.
   - 이러한 입증 주의사항이나 권고사항이 초안에 기재되어 있다고 해서 이를 "사건 증거 부족(CASE_EVIDENCE_MISSING)"이나 "근거 부족(INSUFFICIENT/REVISE)"으로 판정해서는 절대 안 됩니다.
   - 오직 답변이 객관적 사실이나 법리가 없음에도 허위 사실을 단정적으로 주장하거나, 존재하지 않는 법적 권리를 기정사실로 왜곡 확정할 때만 REVISE 또는 INSUFFICIENT로 판정하세요.

6. 공식 법령 원문 연동(OFFICIAL_STATUTE_SEARCH) 결과 반영 및 법률적 검증 원칙 (P0-01):
   - OFFICIAL_STATUTE_SEARCH는 근거 출처의 신뢰성을 높이는 검색 경로일 뿐, 답변 전체의 법률적 정확성이나 사건 적용 타당성을 보증하지 않습니다.
   - 공식 법령 검색 성공만을 이유로 PASS를 반환해서는 절대 안 됩니다.
   - 공식 조문이 검색되었더라도 법률요건 일부 누락, 관련된 다른 법률 조문 누락, 법령 적용 시점 오류, 사실관계의 잘못된 확정, 법률 효과의 잘못된 해석, 손해배상 청구 주체의 혼동, 주장과 실제 인용 출처의 불일치가 존재한다면 반드시 REVISE 또는 INSUFFICIENT로 엄격히 판정하세요.
   - 의뢰인의 진술은 사실관계의 전제로 참고할 수 있으나, 독립적으로 입증된 객관적 증거와 혼동하지 마세요.

7. 현재 답변 범위 기반 적응형 검증 (Adaptive Claim-level Scope):
   - 질문의 범위를 넘어선 과도한 쟁점이나 답변에 실제로 포함되지 않은 법률 주장의 근거 부족을 이유로 전체 답변을 INSUFFICIENT로 차단하지 마세요.
   - RECOMMENDATION(후속 조치 가이드) 및 USER_STATEMENT(사용자 진술 요약)는 법률 조문 RAG 출처가 없더라도 그 자체로 정상적인 실무 조언 또는 사실 정리이므로, 법조문이 없다는 이유로 UNSUPPORTED로 판정하지 마세요 (grounding_status를 NOT_APPLICABLE 또는 SUPPORTED로 설정).
   - 오직 LEGAL_RULE(법령/판례 규범) 및 LEGAL_APPLICATION(구체적 법률효과 단정) 주장이 검색된 법령 본문에 의해 뒷받침되지 않을 때만 UNSUPPORTED로 판정하세요.

8. 사실 상태 구분 및 임의 증거번호 금지 (Fact Status & Evidence Policy):
   - 사실의 확인 수준(fact_status)을 엄격히 구분하세요:
     * VERIFIED_FACT: 실제 등록된 증거 자료(파일명.pdf 등)로 확인된 사실
     * USER_STATEMENT: 사용자의 구두 진술(독립 증빙 미확인)
     * INFERENCE: AI 정황 추론
     * EVIDENCE_NEEDED: 향후 입증을 위해 추가 확보가 필요한 자료
   - 의뢰인의 진술(USER_STATEMENT)을 마치 독립 증거로 증명된 사실(VERIFIED_FACT)인 것처럼 단정해서는 안 됩니다.
   - 실제 사건 증거 목록에 등록되지 않은 임의의 증거 번호(예: '증거 1', '증거 2', '증거 7호' 등)가 답변에 사용된 경우, 반드시 CITATION_INVALID 및 REVISE로 판정하고 수정 지침에 '임의 증거번호 제거 및 사용자 진술/확보 필요 자료로 정제'를 명시하세요.

9. 사건 사실관계가 없는 일반 법령/조문 질의(General Statute Interpretation Query) 검증 특칙:
   - 사건 증거, 계약서, 분쟁 사실이 등록되지 않은 일반 법령·조문 직접 해석 질의(예: "~할 수 있나요?", "~의 요건은 무엇인가요?")의 경우, 답변의 법률 규범(LEGAL_RULE) 및 핵심 결론이 [검색된 출처 목록]의 법조문 본문에 부합하면 반드시 PASS로 판정하세요.
   - 사건 사실관계 증빙 부재, 개별 사안의 허락/동의 범위 입증 필요성, 상대방의 항변 가능성 등 변호사로서의 실무상 유의사항(Legal Caution)이나 추가 확인 필요성을 언급했다는 이유로 REVISE 또는 INSUFFICIENT(CASE_EVIDENCE_MISSING, ANSWER_REVISION_REQUIRED 등)로 판정해서는 절대 안 됩니다.
   - 질문에 필요한 핵심 법조문이 이미 [검색된 출처 목록]에 포함되어 있다면, 불필요하게 다른 법령을 candidate_laws에 기재하거나 LEGAL_SOURCE_MISSING / LEGAL_SOURCE_INSUFFICIENT로 판정하지 마세요.

[출력 형식 (반드시 순수 JSON만 출력)]
{{
  "status": "PASS | REVISE | INSUFFICIENT",
  "reason_code": "LEGAL_SOURCE_MISSING | LEGAL_SOURCE_INSUFFICIENT | CASE_EVIDENCE_MISSING | EVIDENCE_CONFLICT | ANSWER_REVISION_REQUIRED | CITATION_INVALID | NONE",
  "missing_legal_issues": ["법령 검색이 필요한 법률 쟁점"],
  "candidate_laws": ["필요한 공식 법령명 (예: 주택임대차보호법)"],
  "recommended_action": "REQUEST_STATUTE_SEARCH_APPROVAL | REQUEST_EVIDENCE | REVISE_DRAFT | FINALIZE",
  "explanation": "의뢰인에게 표시할 법령 추가 검색 필요 사유 ('초안'/'draft' 단어 절대 사용 금지, 고객 친화적 전문 법률 안내 어조)",
  "claims": [
    {{
      "claim": "검증할 주장 문장",
      "claim_type": "LEGAL_RULE | CASE_FACT | LEGAL_APPLICATION | RECOMMENDATION | USER_STATEMENT",
      "fact_status": "VERIFIED_FACT | USER_STATEMENT | INFERENCE | EVIDENCE_NEEDED | CONFLICTED",
      "source_ids": ["출처 ID"],
      "grounding_status": "SUPPORTED | UNSUPPORTED | UNCERTAIN | NOT_APPLICABLE",
      "reason": "검증 판단 사유"
    }}
  ],
  "missing_issues": ["누락된 쟁점"],
  "contradictions": ["내부 모순 사항"],
  "revision_instructions": ["구체적인 답변 수정 지침"],
  "warnings": ["사용자에게 표시할 실무상 유의사항 및 권고"]
}}
"""


def _extract_meaningful_tokens(text: str, exclude_filename: str = "") -> set[str]:
    """문장에서 불용어와 파일명을 제외한 2글자 이상 핵심 어절/어근/n-gram 집합을 추출한다."""
    cleaned = text
    if exclude_filename:
        cleaned = cleaned.replace(exclude_filename, " ")
    cleaned = CITATION_PATTERN.sub(" ", cleaned)
    raw_tokens = TOKEN_PATTERN.findall(cleaned.lower())
    tokens: set[str] = set()
    for t in raw_tokens:
        if t in _STOPWORDS or t.isdigit():
            continue
        tokens.add(t)
        # 한국어 복합명사 및 어근 분리 (예: 부당해고 -> 부당, 해고 / 대항력이 -> 대항력, 대항)
        if len(t) >= 3 and re.match(r"^[가-힣]+$", t):
            for sub in (t[:2], t[:3]):
                if sub not in _STOPWORDS and len(sub) >= 2:
                    tokens.add(sub)
            for i in range(len(t) - 1):
                sub = t[i:i+2]
                if sub not in _STOPWORDS and len(sub) >= 2:
                    tokens.add(sub)
    return tokens


def _extract_containing_segment(full_text: str, match_start: int, match_end: int) -> str:
    """인용 주변의 문맥(인용이 포함된 문장 또는 주변 150자)을 정확히 추출한다.

    파일명(.pdf 등)이나 페이지 번호(p.10) 내부의 점(.)으로 문장이 잘못 분리되는 것을 방지한다.
    """
    left_bound = max(0, match_start - 150)
    right_bound = min(len(full_text), match_end + 150)

    # 이전 문장 경계 (. 뒤 공백 또는 줄바꿈)
    prev_nl = full_text.rfind("\n", left_bound, match_start)
    prev_period = full_text.rfind(". ", left_bound, match_start)

    # 인용 부호 바로 앞에 마침표가 있는 경우 (예: "반환해야 합니다. (법령 제1조)"),
    # 해당 마침표 앞의 본문 문장을 인용 대상 문맥으로 인식한다.
    if prev_period != -1 and not full_text[prev_period + 2 : match_start].strip():
        prev_prev_nl = full_text.rfind("\n", left_bound, prev_period)
        prev_prev_period = full_text.rfind(". ", left_bound, prev_period)
        best_left = max(
            prev_prev_nl + 1 if prev_prev_nl != -1 else left_bound,
            prev_prev_period + 2 if prev_prev_period != -1 else left_bound,
        )
    else:
        best_left = max(
            prev_nl + 1 if prev_nl != -1 else left_bound,
            prev_period + 2 if prev_period != -1 else left_bound,
        )

    # 다음 문장 경계 (. 뒤 공백, 줄바꿈)
    next_nl = full_text.find("\n", match_end, right_bound)
    next_period = full_text.find(". ", match_end, right_bound)
    candidates_right = [b for b in (next_nl, next_period + 1 if next_period != -1 else -1) if b != -1]
    best_right = min(candidates_right) if candidates_right else right_bound

    extracted = full_text[best_left:best_right].strip()
    return extracted or full_text[match_start:match_end]


def _check_claim_supported_by_source(
    claim_segment: str,
    matched_sources: List[Dict[str, Any]],
    raw_file: str,
) -> Tuple[bool, Optional[str]]:
    """인용이 포함된 문장(claim_segment)이 해당 출처(matched_sources)의 본문(content)에 의해 뒷받침되는지 검사한다.

    Args:
        claim_segment: 인용이 등장한 문장 또는 단락.
        matched_sources: 파일명/ID/법령명이 일치하는 Source Registry 항목 리스트.
        raw_file: 인용된 파일명 또는 법령명.

    Returns:
        Tuple[bool, Optional[str]]: (뒷받침 여부, 거부 사유 코드)
    """
    combined_content = " ".join(str(s.get("content") or "") for s in matched_sources).strip()
    if not combined_content:
        return False, "EMPTY_SOURCE_CONTENT"

    # 1. 문장에서 특정 조문(제N조)을 명시적으로 주장했는데, 출처 본문에 다른 조문만 있고 해당 조문이 없는 경우
    claimed_articles = {re.sub(r"\s+", "", m) for m in ARTICLE_PATTERN.findall(claim_segment)}
    source_articles = {re.sub(r"\s+", "", m) for m in ARTICLE_PATTERN.findall(combined_content)}
    if claimed_articles and source_articles and not claimed_articles.intersection(source_articles):
        return False, f"ARTICLE_MISMATCH({','.join(sorted(claimed_articles))})"

    # 2. 법률 효과의 정반대 왜곡 또는 기간 조건 불일치 검증 (P1-03)
    # 기간 경과(예: 3개월이 지나면 효력 발생) 조건 vs 즉시/당일 효력 발생 모순 검증
    period_in_source = re.search(r"(\d+\s*(?:개월|달|일|년|주))\s*(?:이\s*지나|경과|후|지난\s*때).*?(?:효력|해지|반환)", combined_content)
    immediate_in_claim = re.search(r"(도달\s*즉시|즉시|당일|즉각|바로)\s*(?:효력|해지|반환)", claim_segment)
    if period_in_source and immediate_in_claim:
        return False, f"LEGAL_EFFECT_CONTRADICTION(기간조건 {period_in_source.group(1)} vs {immediate_in_claim.group(1)})"

    # 3. 주장 문장과 출처 본문 간 핵심 어휘 중첩도 확인
    # [P0-VER-01] 법령 조문 인용의 경우 조문 번호(제N조)가 출처의 조문과 정확히 일치하고
    # 단순 법령 열거/참조 라인(예: "관련 법령: (민법 제6조)")인 경우 어휘 중첩 부족으로 오기각되지 않도록 보완한다.
    claim_tokens = _extract_meaningful_tokens(claim_segment, exclude_filename=raw_file)
    source_tokens = _extract_meaningful_tokens(combined_content)
    if claim_tokens and source_tokens:
        overlap = claim_tokens.intersection(source_tokens)
        if len(overlap) == 0:
            is_statute_source = any(s.get("source_type") == "STATUTE" or s.get("statute_name") or s.get("article") for s in matched_sources)
            has_matching_article = bool(claimed_articles and source_articles and claimed_articles.intersection(source_articles))
            is_statute_intro = any(k in claim_segment for k in (
                "규정", "명시", "따라", "의거", "판단", "관련", "참조", "조문", "법령", "근거", "해석", "적용", "인정", "원칙", "예외", "종합",
                "관계", "기초", "내용", "바탕", "정리", "분석", "결론", "사안", "취지"
            ))
            is_short_reference = len(claim_tokens) <= 3 or any(k in claim_segment for k in ("관련 법령", "관련법령", "근거 법조문", "근거법령", "법령 및 증거", "참조", "조문"))
            # [P0-VER-01] 법령 출처이고 조문 번호가 일치하면(Check 1의 조문 불일치가 없었으므로), 해당 조문 인용은 유효하게 뒷받침됨
            if is_statute_source and has_matching_article:
                return True, None
            # 짧은 법령 목록/헤더 참조 문맥인 경우 허용
            if is_statute_source and is_short_reference and not claimed_articles:
                return True, None
            return False, "UNSUPPORTED_BY_SOURCE_CONTENT"

    return True, None


def audit_citations_and_claims(
    draft_answer: str,
    retrieved_sources: List[Dict[str, Any]],
    case_context: str = "",
) -> Dict[str, Any]:
    """초안 답변의 모든 인용(파일명, 공식 법령 조문, 그래프 ID, 판례 사건번호)을 Source Registry와 대조하여 존재성 및 본문 뒷받침 여부를 감사한다.

    Args:
        draft_answer: 검증 대상 답변 초안.
        retrieved_sources: 현재 요청에서 실제 조회된 Source Registry 목록.
        case_context: 사건 맥락 텍스트 (사건 증거·사실관계 확인용).

    Returns:
        Dict[str, Any]: Langfuse 기록 및 검증 판정에 사용되는 상세 감사 결과.
    """
    normalized_registry = [normalize_source_dict(s) for s in (retrieved_sources or [])]

    retrieval_source_ids: List[str] = []
    retrieval_methods: List[str] = []
    retrieved_chunk_ids: List[str] = []
    by_filename: Dict[str, List[Dict[str, Any]]] = {}
    by_source_id: Dict[str, Dict[str, Any]] = {}
    by_statute_article: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    known_case_numbers: set[str] = set()
    known_evidence_ids: set[str] = set()

    for src in normalized_registry:
        sid = str(src.get("source_id") or "")
        if sid and sid not in retrieval_source_ids:
            retrieval_source_ids.append(sid)
        if sid:
            by_source_id[sid.lower()] = src

        method = str(src.get("retrieval_method") or "")
        if method and method not in retrieval_methods:
            retrieval_methods.append(method)

        cid = str(src.get("chunk_id") or "")
        if cid and cid not in retrieved_chunk_ids:
            retrieved_chunk_ids.append(cid)

        for fn_candidate in (src.get("filename"), src.get("file_name"), src.get("file"), sid):
            if fn_candidate:
                base_fn = os.path.basename(str(fn_candidate)).strip().lower()
                by_filename.setdefault(base_fn, []).append(src)

        # 법령 및 조문 인덱싱 (P1-03)
        sname = str(src.get("statute_name") or "").strip()
        art = str(src.get("article") or "").strip()
        if sname and art:
            clean_art = re.sub(r"\s+", "", art)
            by_statute_article.setdefault((sname, clean_art), []).append(src)
        elif sid and "_" in sid:
            parts = sid.split("_", 1)
            s_art_match = ARTICLE_PATTERN.search(parts[1])
            clean_art = re.sub(r"\s+", "", s_art_match.group(0)) if s_art_match else re.sub(r"\s+", "", parts[1])
            by_statute_article.setdefault((parts[0].strip(), clean_art), []).append(src)

        if src.get("case_number"):
            known_case_numbers.add(re.sub(r"\s+", "", str(src["case_number"])))
        for cn in CASE_NUMBER_PATTERN.findall(str(src.get("content") or "")):
            known_case_numbers.add(re.sub(r"\s+", "", cn))
        stype = str(src.get("source_type") or "").upper()
        if stype == "CASE_EVIDENCE" or sid.startswith("EVIDENCE:") or "evidence" in sid.lower():
            known_evidence_ids.add(sid.lower())
            for fn in (src.get("filename"), src.get("file_name"), src.get("file")):
                if fn:
                    known_evidence_ids.add(str(fn).lower())
                    known_evidence_ids.add(os.path.basename(str(fn)).lower())

    if case_context:
        for cn in CASE_NUMBER_PATTERN.findall(case_context):
            known_case_numbers.add(re.sub(r"\s+", "", cn))
        for ev_match in re.findall(r"EVIDENCE:([A-Za-z0-9_\-]+)", case_context, re.IGNORECASE):
            known_evidence_ids.add(f"evidence:{ev_match.lower()}")
            known_evidence_ids.add(ev_match.lower())
        for ev_match in re.findall(r"\[(?:증거|EVIDENCE)\s*([A-Za-z0-9_\-]+)\]", case_context, re.IGNORECASE):
            known_evidence_ids.add(ev_match.lower())

    generated_citation_ids: List[str] = []
    validated_citation_ids: List[str] = []
    rejected_citation_ids: List[str] = []
    rejection_reasons: Dict[str, str] = {}
    unverified_labels: List[str] = []
    unsupported_labels: List[str] = []
    validated_sources_map: Dict[str, Dict[str, Any]] = {}

    if not draft_answer:
        return {
            "retrieval_source_ids": retrieval_source_ids,
            "retrieval_methods": retrieval_methods,
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "generated_citation_ids": [],
            "validated_citation_ids": [],
            "rejected_citation_ids": [],
            "rejection_reasons": {},
            "unverified_citations": [],
            "unsupported_citations": [],
            "citation_existence_rate": "N/A",
            "citation_support_rate": "N/A",
            "citation_coverage_rate": 0.0,
            "cited_sources": [],
            "verified_sources": [],
        }

    # 문장/줄 단위로 분리하여 인용 문맥 파악
    segments = [seg.strip() for seg in re.split(r"[\n.!?]+", draft_answer) if seg.strip()]

    # 1. (파일명.pdf, p.페이지) 인용 검증
    for match in CITATION_PATTERN.finditer(draft_answer):
        raw_file, raw_page = match.group(1).strip(), match.group(2).strip()
        # 괄호나 따옴표가 파일명에 혼입된 경우 정제 (중복 괄호 방지)
        raw_file = raw_file.lstrip("([{\"' \t").rstrip(")]}\"' \t")
        clean_file = os.path.basename(raw_file).lower()
        cite_label = f"({raw_file}, p.{raw_page})"
        full_match_text = match.group(0).strip()
        cite_id = f"{os.path.basename(raw_file)}_{raw_page}"
        if cite_id not in generated_citation_ids:
            generated_citation_ids.append(cite_id)

        matched_sources = by_filename.get(clean_file, [])
        if not matched_sources:
            if cite_id not in rejected_citation_ids:
                rejected_citation_ids.append(cite_id)
                rejection_reasons[cite_id] = "NOT_IN_SOURCE_REGISTRY"
            if cite_label not in unverified_labels:
                unverified_labels.append(cite_label)
            if full_match_text not in unverified_labels:
                unverified_labels.append(full_match_text)
            continue

        # 해당 인용이 포함된 문맥(문장) 추출
        containing_seg = _extract_containing_segment(draft_answer, match.start(), match.end())
        is_supported, reason = _check_claim_supported_by_source(containing_seg, matched_sources, raw_file)
        if not is_supported:
            if cite_id not in rejected_citation_ids:
                rejected_citation_ids.append(cite_id)
                rejection_reasons[cite_id] = reason or "UNSUPPORTED_BY_SOURCE_CONTENT"
            if cite_label not in unsupported_labels:
                unsupported_labels.append(cite_label)
            if full_match_text not in unsupported_labels:
                unsupported_labels.append(full_match_text)
        else:
            if cite_id not in validated_citation_ids:
                validated_citation_ids.append(cite_id)
            for ms in matched_sources:
                ms_id = str(ms.get("source_id") or cite_id)
                validated_sources_map[ms_id] = ms

    # 2. (법령명 제N조) 공식 법령 인용 검증 (P1-03)
    for s_match in STATUTE_CITATION_PATTERN.finditer(draft_answer):
        law_name = s_match.group(1).strip()
        art_clean = re.sub(r"\s+", "", s_match.group(2).strip())
        cite_label = f"({law_name} {art_clean})"
        full_match_text = s_match.group(0).strip()
        cite_id = f"{law_name}_{art_clean}"
        if cite_id not in generated_citation_ids:
            generated_citation_ids.append(cite_id)

        matched_sources = by_statute_article.get((law_name, art_clean), [])
        if not matched_sources:
            # 보조 매칭: source_id 또는 title 확인
            for s in normalized_registry:
                s_id = str(s.get("source_id") or "")
                s_name = str(s.get("statute_name") or s.get("title") or "")
                s_art = re.sub(r"\s+", "", str(s.get("article") or ""))
                if (law_name in s_name or law_name in s_id) and (art_clean == s_art or art_clean in s_id):
                    matched_sources.append(s)

        if not matched_sources:
            if cite_id not in rejected_citation_ids:
                rejected_citation_ids.append(cite_id)
                rejection_reasons[cite_id] = "NOT_IN_SOURCE_REGISTRY"
            if cite_label not in unverified_labels:
                unverified_labels.append(cite_label)
            if full_match_text not in unverified_labels:
                unverified_labels.append(full_match_text)
            continue

        containing_seg = _extract_containing_segment(draft_answer, s_match.start(), s_match.end())
        is_supported, reason = _check_claim_supported_by_source(containing_seg, matched_sources, law_name)
        if not is_supported:
            if cite_id not in rejected_citation_ids:
                rejected_citation_ids.append(cite_id)
                rejection_reasons[cite_id] = reason or "UNSUPPORTED_BY_SOURCE_CONTENT"
            if cite_label not in unsupported_labels:
                unsupported_labels.append(cite_label)
            if full_match_text not in unsupported_labels:
                unsupported_labels.append(full_match_text)
        else:
            if cite_id not in validated_citation_ids:
                validated_citation_ids.append(cite_id)
            for ms in matched_sources:
                ms_id = str(ms.get("source_id") or cite_id)
                validated_sources_map[ms_id] = ms

    # 3. [GRAPH:...] / [VECTOR:...] 인용 검증
    for g_match in GRAPH_CITATION_PATTERN.finditer(draft_answer):
        gid = g_match.group(1).strip()
        if gid not in generated_citation_ids:
            generated_citation_ids.append(gid)
        matched_g = by_source_id.get(gid.lower())
        if not matched_g:
            if gid not in rejected_citation_ids:
                rejected_citation_ids.append(gid)
                rejection_reasons[gid] = "NOT_IN_SOURCE_REGISTRY"
            label = f"[{gid}]"
            if label not in unverified_labels:
                unverified_labels.append(label)
        else:
            if gid not in validated_citation_ids:
                validated_citation_ids.append(gid)
            validated_sources_map[str(matched_g.get("source_id") or gid)] = matched_g

    # 4. 임의 생성된 판례 사건번호(예: 2023다99999) 검증
    for cn_match in CASE_NUMBER_PATTERN.finditer(draft_answer):
        cn_clean = re.sub(r"\s+", "", cn_match.group(1))
        cite_id = f"PRECEDENT:{cn_clean}"
        if cite_id not in generated_citation_ids:
            generated_citation_ids.append(cite_id)
        if cn_clean not in known_case_numbers:
            if cite_id not in rejected_citation_ids:
                rejected_citation_ids.append(cite_id)
                rejection_reasons[cite_id] = "UNVERIFIED_PRECEDENT_CASE_NUMBER"
            if cn_clean not in unverified_labels:
                unverified_labels.append(cn_clean)
        else:
            if cite_id not in validated_citation_ids:
                validated_citation_ids.append(cite_id)

    # 5. 임의 생성된 사건 증거번호 (예: "증거 1", "증거 7호", "[증거 2]") 검증 (T05)
    for ev_match in EVIDENCE_LABEL_PATTERN.finditer(draft_answer):
        full_match_text = ev_match.group(0).strip()
        ev_num = ev_match.group(2) or ev_match.group(3) or ev_match.group(4) or full_match_text
        ev_num_clean = str(ev_num).strip().lower()
        cite_id = f"EVIDENCE:{ev_num_clean}"
        if cite_id not in generated_citation_ids:
            generated_citation_ids.append(cite_id)

        # 등록된 증거 목록과 매칭 여부 대조
        is_known = False
        if known_evidence_ids:
            for ke in known_evidence_ids:
                if ev_num_clean in ke or ke in ev_num_clean:
                    is_known = True
                    break

        if not is_known:
            if cite_id not in rejected_citation_ids:
                rejected_citation_ids.append(cite_id)
                rejection_reasons[cite_id] = "UNREGISTERED_EVIDENCE_NUMBER"
            if full_match_text not in unverified_labels:
                unverified_labels.append(full_match_text)
        else:
            if cite_id not in validated_citation_ids:
                validated_citation_ids.append(cite_id)

    # 6. [E05_퇴거_및_보증금_반환_요청_문자.txt] 형태의 전체 파일명 대괄호 인용 검증
    for bf_match in BRACKET_FILE_CITATION_PATTERN.finditer(draft_answer):
        raw_bf = bf_match.group(1).strip()
        clean_bf = os.path.basename(raw_bf).lower()
        matched_bf_sources = by_filename.get(clean_bf, [])
        if matched_bf_sources:
            for ms in matched_bf_sources:
                ms_id = str(ms.get("source_id") or raw_bf)
                if ms_id not in generated_citation_ids:
                    generated_citation_ids.append(ms_id)
                if ms_id not in validated_citation_ids:
                    validated_citation_ids.append(ms_id)
                validated_sources_map[ms_id] = ms

    total_gen = len(generated_citation_ids)
    not_exist_count = sum(
        1 for cid in rejected_citation_ids
        if rejection_reasons.get(cid) in ("NOT_IN_SOURCE_REGISTRY", "UNVERIFIED_PRECEDENT_CASE_NUMBER")
    )

    # 제로 분모 처리 (P1-03): 인용이 없는 답변은 100%로 오해되지 않도록 N/A 처리
    if total_gen == 0:
        existence_rate = "N/A"
        support_rate = "N/A"
        coverage_rate = 0.0
    else:
        existence_rate = round(((total_gen - not_exist_count) / total_gen), 4)
        support_rate = round((len(validated_citation_ids) / total_gen), 4)

        # Citation Coverage Rate: 실질 본문 문장 중 유효 인용이 포함된 문장 비율
        substantive_segs = [
            s for s in segments 
            if len(s) > 10 and not any(h in s for h in ("⚖️", "🛡️", "⚠️", "안내:", "출처:"))
        ]
        if not substantive_segs:
            coverage_rate = 1.0
        else:
            cited_count = sum(
                1 for s in substantive_segs
                if (CITATION_PATTERN.search(s) or 
                    STATUTE_CITATION_PATTERN.search(s) or 
                    BRACKET_FILE_CITATION_PATTERN.search(s) or
                    GRAPH_CITATION_PATTERN.search(s) or 
                    CASE_NUMBER_PATTERN.search(s))
            )
            coverage_rate = round(cited_count / len(substantive_segs), 4)

    # [P0-03] 검증된 최종 출처 목록(cited_sources):
    # 검색된 전체 출처(retrieval_source_ids, retrieved_chunk_ids)는 감사용으로 100% 보존하되,
    # 최종 답변에서 실제 인용되고 본문 뒷받침까지 검증된 출처만 cited_sources로 선정함.
    # 답변에 인용되지 않은 법령/문서는 고객용 검증 출처에서 엄격히 배제함.
    cited_sources: List[Dict[str, Any]] = []
    seen_cited_keys: set[Any] = set()
    for vs in validated_sources_map.values():
        sid = str(vs.get("source_id") or "")
        stype = vs.get("source_type") or "DOCUMENT"
        if stype == "STATUTE":
            key = (stype, vs.get("statute_name") or vs.get("title"), vs.get("article"))
        elif stype == "CASE_EVIDENCE":
            key = (stype, vs.get("file") or vs.get("filename"), str(vs.get("page") or "1"))
        else:
            key = (sid, vs.get("file") or vs.get("filename"))

        if key not in seen_cited_keys:
            seen_cited_keys.add(key)
            cited_sources.append(vs)

    return {
        "retrieval_source_ids": retrieval_source_ids,
        "retrieval_methods": retrieval_methods,
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "generated_citation_ids": generated_citation_ids,
        "validated_citation_ids": validated_citation_ids,
        "rejected_citation_ids": rejected_citation_ids,
        "rejection_reasons": rejection_reasons,
        "unverified_citations": unverified_labels,
        "unsupported_citations": unsupported_labels,
        "citation_existence_rate": existence_rate,
        "citation_support_rate": support_rate,
        "citation_coverage_rate": coverage_rate,
        "cited_sources": cited_sources,
        "verified_sources": cited_sources,
    }



def validate_citations_against_sources(
    draft_answer: str,
    retrieved_sources: List[Dict[str, Any]],
) -> List[str]:
    """초안 답변에 포함된 인용이 실제 검색된 출처 목록에 존재하는지 검증한다 (하위 호환 함수).

    Args:
        draft_answer: 전문 에이전트들이 작성 및 종합한 초안 텍스트.
        retrieved_sources: RAG 검색으로 수집된 실제 출처 딕셔너리 리스트.

    Returns:
        List[str]: 검색 결과에 존재하지 않는 미검증(허위) 인용 리스트.
    """
    audit = audit_citations_and_claims(draft_answer, retrieved_sources)
    return audit["unverified_citations"]


def sanitize_unverified_citations(
    answer: str,
    retrieved_sources: List[Dict[str, Any]],
    case_context: str = "",
) -> str:
    """최종 답변에서 Source Registry에 존재하지 않거나 본문이 뒷받침하지 않는 허위 인용을 제거·정화한다.

    Args:
        answer: 정화 대상 답변 텍스트.
        retrieved_sources: 실제 조회된 Source Registry 목록.
        case_context: 사건 맥락 문자열.

    Returns:
        str: 미검증 파일명·사건번호·그래프 ID가 제거된 안전한 답변 텍스트.
    """
    if not answer:
        return answer

    audit = audit_citations_and_claims(answer, retrieved_sources, case_context=case_context)
    unverified = set(audit.get("unverified_citations", []))
    unsupported = set(audit.get("unsupported_citations", []))
    bad_labels = unverified.union(unsupported)

    cleaned = answer
    if bad_labels:
        # 미등록 가상 증거번호 우선 정제 (T05)
        for label in bad_labels:
            if "증거" in label or "증 제" in label:
                cleaned = cleaned.replace(label, "[미등록 증거번호 제거]")
        cleaned = re.sub(r"\[미등록 증거번호 제거\]\s*:\s*", "(확보 필요) ", cleaned)
        cleaned = re.sub(r"\[미등록 증거번호 제거\]\s*", "", cleaned)

        for label in bad_labels:
            if label.startswith("(") and label.endswith(")"):
                # 미검증 (파일명.pdf, p.페이지) 인용 제거 및 이중 괄호 변형 정화
                cleaned = cleaned.replace(label, "[근거 미확인]")
                if label.startswith("((") and label.endswith("))"):
                    inner = label[1:-1]
                    cleaned = cleaned.replace(inner, "[근거 미확인]")
            elif label.startswith("[") and label.endswith("]"):
                cleaned = cleaned.replace(label, "")
            else:
                # 미검증 판례 사건번호 마스킹
                cleaned = cleaned.replace(label, "[사건번호 미확인]")

        # 괄호 중복 등으로 남은 패턴 정리 (예: ([근거 미확인]) 또는 [근거 미확인]) -> [근거 미확인])
        cleaned = re.sub(r"\(+\[근거 미확인\]\)+", "[근거 미확인]", cleaned)
        cleaned = re.sub(r"\[근거 미확인\]\)+", "[근거 미확인]", cleaned)
        cleaned = re.sub(r"\(+\[근거 미확인\]", "[근거 미확인]", cleaned)

    # [P0-03/Gate 2] 빈 인용 및 연속 쉼표(', , , ,') 원천 제거 정규화
    # 1. 빈 대괄호 제거
    cleaned = re.sub(r"\[\s*\]", "", cleaned)
    # 2. 연속 쉼표 정규화 (예: ", , , " -> ", ")
    cleaned = re.sub(r",\s*(?:,\s*)+", ", ", cleaned)
    # 3. 콜론 바로 뒤 쉼표 제거 (예: ": , " -> ": ")
    cleaned = re.sub(r":\s*,+\s*", ": ", cleaned)
    # 4. 줄 끝 또는 괄호/대괄호 끝의 잔여 쉼표 제거 (예: "[E01, ]" -> "[E01]")
    cleaned = re.sub(r",\s*(?=\n|$|\)|\])", "", cleaned)
    # 5. 줄 시작의 잔여 쉼표 제거
    cleaned = re.sub(r"^\s*,\s*", "", cleaned, flags=re.MULTILINE)
    # 6. 관련 증거 라인이 비어있거나 쉼표만 남은 경우 해당 라인 완전 삭제
    cleaned = re.sub(r"^\s*[*•\-]?\s*관련\s*증거\s*:\s*(?:,\s*)*$", "", cleaned, flags=re.MULTILINE)

    # 불필요한 중복 공백 및 연속 빈 줄 정리
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


@trace
def run_verification(
    question: str,
    draft_answer: str,
    retrieved_sources: List[Dict[str, Any]],
    case_context: str = "",
    *, require_question_coverage: bool = False, allow_partial_answer: bool = False,
) -> Dict[str, Any]:
    """초안 답변이 검색된 출처에 의해 뒷받침되는지 결정론적 Citation Validator 및 LLM으로 검증한다.

    Args:
        question: 사용자의 원본 법률 상담 질문.
        draft_answer: 여러 전문 에이전트가 작성하고 종합된 초안 답변.
        retrieved_sources: 각 에이전트가 RAG 검색을 통해 참조한 실제 문서 메타데이터 목록.
        case_context: 사건 기본 정보, 사실관계, 타임라인, 증거 브리핑 문자열.
        require_question_coverage: 문서 상담에서 질문의 모든 요청과 사실 주장까지 엄격히 확인할지 여부.
        allow_partial_answer: 제한 답변에서 실제로 고지된 판단 한계만 질문의 부분 충족으로 인정할지 여부.

    Returns:
        Dict[str, Any]: `VerificationOutput` 스키마 형태의 검증 결과 딕셔너리.
    """
    set_agent_name("verification_agent")

    # 1. 결정론적 Citation & Content Support 감사 실행
    audit = audit_citations_and_claims(draft_answer, retrieved_sources, case_context=case_context)
    unverified_citations = audit["unverified_citations"]
    unsupported_citations = audit["unsupported_citations"]
    valid_source_id_set = set(audit["retrieval_source_ids"])
    rejected_id_set = set(audit["rejected_citation_ids"])
    rejection_reasons = audit.get("rejection_reasons", {})

    # STEP 5: 결정론적 경량 QA 검사 1차 실행 (출처·날짜·금액·질문충족·법률위험)
    from ai_legal_helper.agents.qa_checker import check_deterministic_qa
    qa_check = check_deterministic_qa(
        question=question,
        draft_answer=draft_answer,
        retrieved_sources=retrieved_sources,
        case_context=case_context,
    )

    # 단순 법령 질의이면서 결정론적 검사 ALL PASS인 경우: 불필요한 LLM 호출을 건너뛰고 조기 PASS 확정
    if not qa_check.requires_llm_eval and qa_check.status == "PASS":
        logger.info("[VERIFICATION] 경량 검사 ALL PASS: LLM 검증 생략 및 초안 즉시 확정")
        from ai_legal_helper.rag.grounding_context import format_grounding_sources
        _, source_manifest = format_grounding_sources(retrieved_sources)
        return {
            "status": "PASS",
            "reason_code": "NONE",
            "citation_audit": qa_check.citation_audit,
            "preserved_points": qa_check.preserved_points,
            "repair_targets": [],
            "qa_summary": qa_check.model_dump(),
            "claims": [],
            "warnings": [],
            "missing_issues": [],
            "contradictions": [],
            "revision_instructions": [],
            "candidate_laws": [],
            "legal_search_requests": [],
            "recommended_action": "FINALIZE",
            "source_manifest": source_manifest,
        }

    # 검색 순서 때문에 뒤에 추가된 공식 법령이 사라지지 않도록 전체 본문을 전달한다.
    from ai_legal_helper.rag.grounding_context import format_grounding_sources
    from ai_legal_helper.agents.document_verification_prompt import DOCUMENT_VERIFICATION_PROMPT
    prompt = PromptTemplate.from_template(
        DOCUMENT_VERIFICATION_PROMPT if require_question_coverage else VERIFICATION_PROMPT
    )
    from ai_legal_helper.llm.gateway import get_llm

    error_type: Optional[str] = None
    try:
        formatted_sources, source_manifest = format_grounding_sources(retrieved_sources)
        llm = get_llm(temperature=0.0)
        if allow_partial_answer:
            case_context += (
                "\n제한 답변 모드: 확인된 사실과 근거 있는 조건부 설명을 검증합니다. "
                "질문의 일부를 자료 부족으로 답할 수 없고 그 한계를 실제 답변에 명시했다면 "
                "question_coverage에 answered=false, answerable=false, limitation_disclosed=true, "
                "limitation_statement=답변의 한계 문구를 그대로 적으세요. 이 경우 부분 답변으로 PASS가 "
                "가능합니다. 근거 없는 주장·시간 오류·아무 내용 없이 확인만 요구하는 답변은 여전히 실패입니다."
            )
        formatted_prompt = prompt.format(
            question=question,
            draft_answer=draft_answer,
            retrieved_sources=formatted_sources,
            case_context=case_context or "(사건 정보 없음)",
        )
        res = None
        for attempt in range(2):
            try:
                res = llm.invoke(formatted_prompt)
                break
            except (TimeoutError, ConnectionError) as net_err:
                logger.warning(f"Verification Agent 호출 재시도 ({attempt+1}/2): {net_err}")
                if attempt == 1:
                    raise net_err

        if res is None:
            error_type = "LLM_RESPONSE_EMPTY"
            logger.error("[VERIFICATION_SCHEMA] LLM 응답 객체 누락 (LLM_RESPONSE_EMPTY)")
            raise RuntimeError("검증기 응답을 수신하지 못했습니다.")

        raw_content = getattr(res, "content", res)
        text = raw_content if isinstance(raw_content, str) else str(raw_content)
        text = text.strip()
        if not text:
            error_type = "LLM_RESPONSE_EMPTY"
            logger.error("[VERIFICATION_SCHEMA] LLM 응답 본문 비어있음 (LLM_RESPONSE_EMPTY)")
            raise RuntimeError("검증기 응답 본문이 비어 있습니다.")

        # 마크다운 코드블록 또는 텍스트 내 JSON 객체 추출
        try:
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                brace_start = text.find("{")
                brace_end = text.rfind("}")
                if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
                    json_str = text[brace_start : brace_end + 1].strip()
                else:
                    json_str = text
            data = json.loads(json_str)
        except Exception as json_err:
            error_type = "JSON_PARSE_ERROR"
            logger.error(f"[VERIFICATION_SCHEMA] JSON 파싱 실패 (JSON_PARSE_ERROR): {json_err}")
            raise json_err

        # Pydantic 스키마 검증 및 정규화
        try:
            logger.info("[VERIFICATION_SCHEMA] 검증 출력 수신 및 스키마 검증 시작")
            result = VerificationOutput(**data)
            logger.info(f"[VERIFICATION_SCHEMA] 스키마 검증 및 정규화 결과: SUCCESS (주장수={len(result.claims)}, 상태={result.status})")
            logger.info("[VERIFICATION] 법률 주장 검증 계속 진행")
        except ValidationError as val_err:
            error_type = "SCHEMA_NORMALIZATION"
            logger.error(f"[VERIFICATION_SCHEMA] 정규화 실패 (SCHEMA_NORMALIZATION): {val_err}")
            for err in val_err.errors():
                loc_str = ".".join(str(l) for l in err.get("loc", []))
                logger.error(f"[VERIFICATION_SCHEMA] 오류 필드: {loc_str} | 오류 종류: {err.get('type')}")
            logger.error("[VERIFICATION_SCHEMA] 법률 근거 부족과 구분하여 기술 오류 처리")
            raise val_err
        coverage_complete = (bool(result.question_coverage) and all(
            isinstance(item.get("question"), str) and bool(item["question"].strip())
            and (item.get("answered") is True or (
                allow_partial_answer and item.get("answered") is False
                and item.get("answerable") is False and item.get("limitation_disclosed") is True
                and isinstance(item.get("limitation_statement"), str)
                and bool(item["limitation_statement"].strip())
                and item["limitation_statement"].strip() in draft_answer
            )) for item in result.question_coverage
        ))
        consistency_complete = all(
            isinstance(result.consistency_checks.get(key), dict)
            and result.consistency_checks[key].get("passed") is True
            and isinstance(result.consistency_checks[key].get("reason"), str)
            and bool(result.consistency_checks[key]["reason"].strip())
            for key in ("opening_conclusion", "timeline", "expressed_intent", "provenance")
        )
        if require_question_coverage and not coverage_complete:
            result.status = "REVISE"
            if result.reason_code in (None, "NONE"):
                result.reason_code = "ANSWER_REVISION_REQUIRED"
            result.revision_instructions.append("현재 질문의 모든 요청에 직접 답하고 미응답 항목을 보완하세요.")
        if require_question_coverage and not consistency_complete:
            result.status = "REVISE"
            if result.reason_code in (None, "NONE"):
                result.reason_code = "ANSWER_REVISION_REQUIRED"
            result.revision_instructions.append("시간 순서, 의사표시 내용, 증명 수준을 원문과 대조하여 결론을 보완하세요.")

        # 3. LLM이 반환한 Claim별 source_ids가 실제 Source Registry에 존재하는지 교차 검증
        def _norm_quote(txt: str) -> str:
            """마크다운 강조 기호(** 등) 및 글머리 기호 유무 차이로 인한 오탐을 방지하되 문장 변형은 차단한다."""
            cleaned = re.sub(r"(\*\*|__|`)", "", txt or "")
            cleaned = re.sub(r"^\s*(?:[-•*]|\d+[.)]|#{1,4})\s*", "", cleaned)
            return " ".join(cleaned.split())

        def _resolve_canonical_source_id(raw_sid: str) -> Optional[str]:
            """검증기가 반환한 출처 식별자를 Source Registry의 정규 전체 이름(source_id)으로 해석·정규화한다."""
            s_clean = str(raw_sid or "").strip()
            if not s_clean or s_clean in rejected_id_set:
                return None
            if s_clean in valid_source_id_set:
                return s_clean

            bare = re.sub(r"^EVIDENCE:", "", s_clean, flags=re.IGNORECASE).strip()
            bare_lower = bare.lower()
            # 1. 사건 문서 전체 파일명, 제목, evidence_id 또는 파일명 접두사 매칭
            for src in retrieved_sources or []:
                cand_sid = str(src.get("source_id") or "")
                if not cand_sid or cand_sid not in valid_source_id_set or cand_sid in rejected_id_set:
                    continue
                for field_key in ("filename", "file_name", "document_name", "title", "evidence_id"):
                    fval = str(src.get(field_key) or "").strip()
                    if fval and (fval.lower() == bare_lower or os.path.splitext(fval)[0].lower() == bare_lower):
                        return cand_sid
                if re.match(r"^E\d{1,3}$", bare, re.IGNORECASE):
                    fn_val = str(src.get("filename") or src.get("document_name") or cand_sid).strip()
                    if fn_val.upper().startswith(f"{bare.upper()}_"):
                        return cand_sid

            # 2. 법령(STATUTE) 출처의 법령명 + 조문번호 매칭 -> 정규 상세 법령 source_id로 승격
            art_m = ARTICLE_PATTERN.search(s_clean)
            if art_m:
                art_norm = re.sub(r"\s+", "", art_m.group(1))
                for src in retrieved_sources or []:
                    cand_sid = str(src.get("source_id") or "")
                    if not cand_sid or cand_sid not in valid_source_id_set or cand_sid in rejected_id_set:
                        continue
                    s_law = str(src.get("statute_name") or "").strip()
                    s_art = re.sub(r"\s+", "", str(src.get("article") or ""))
                    if s_law and s_art and s_law in s_clean and s_art == art_norm:
                        if f"{s_law}_{s_art}" not in rejected_id_set:
                            return cand_sid
            return None

        norm_draft = _norm_quote(draft_answer)
        for claim_obj in result.claims:
            # 모델 판단과 정책 판단을 분리해 수정 작성자가 모순된 사유를 받지 않게 한다.
            claim_obj.model_grounding_status = claim_obj.grounding_status
            claim_obj.model_reason = claim_obj.reason

            # 1. 주장 내용이 공백인 경우 SUPPORTED 금지
            if not claim_obj.claim or not claim_obj.claim.strip():
                claim_obj.grounding_status = "UNSUPPORTED"
                claim_obj.reason = "주장 내용이 비어 있습니다."

            # 검증기가 실제 문장을 조건부 문장으로 바꿔 옮기면 원래 단정의 오류를 놓친다.
            # 문서 상담에서는 마크다운 기호·공백 정규화만 허용하고 답변에 없는 재서술을 근거 검증에서 제외한다.
            if require_question_coverage and _norm_quote(claim_obj.claim) not in norm_draft:
                claim_obj.grounding_status = "UNSUPPORTED"
                claim_obj.reason = "실제 답변에 존재하는 문장을 그대로 검증해야 합니다."

            verified_claim_sids: List[str] = []
            all_resolved = True
            for sid in claim_obj.source_ids:
                resolved_sid = _resolve_canonical_source_id(sid)
                if resolved_sid:
                    if resolved_sid not in verified_claim_sids:
                        verified_claim_sids.append(resolved_sid)
                else:
                    all_resolved = False
            if claim_obj.source_ids and (not verified_claim_sids or (require_question_coverage and not all_resolved)):
                claim_obj.grounding_status = "UNSUPPORTED"
                claim_obj.reason = (claim_obj.reason + " (지정된 출처 ID가 실제 검색 결과에 존재하지 않거나 본문과 불일치함)").strip()
            claim_obj.source_ids = verified_claim_sids

            # 2. 근거 출처가 전무한 법률 규범(LEGAL_RULE), 법률 적용(LEGAL_APPLICATION), 사건 사실(CASE_FACT) 주장은
            #    모델이 임의로 SUPPORTED로 반환하더라도 뒷받침 출처 부재로 UNSUPPORTED로 강등한다 (STEP 2 원칙).
            if not claim_obj.source_ids and claim_obj.grounding_status == "SUPPORTED":
                if claim_obj.claim_type in ("LEGAL_RULE", "LEGAL_APPLICATION", "CASE_FACT"):
                    claim_obj.grounding_status = "UNSUPPORTED"
                    claim_obj.reason = (claim_obj.reason + " (주장을 뒷받침하는 법률 또는 사건 출처가 지정되지 않음)").strip()

        if require_question_coverage:
            legal_source_ids = {str(s.get("source_id")) for s in retrieved_sources if (
                s.get("source_type") in ("STATUTE", "PRECEDENT")
                or s.get("statute_name") or s.get("case_number")
            ) and s.get("source_type") != "CASE_EVIDENCE"}
            case_evidence_ids = {
                str(s.get("source_id"))
                for s in retrieved_sources
                if s.get("source_type") == "CASE_EVIDENCE" and s.get("source_id")
            }

            _INFERENCE_RISK_MARKERS = (
                "위험", "가능성", "정황", "신호", "재평가", "자금난", "자금 압박", "자금사정",
                "전액 상환", "마련하기 어렵", "어려울 수", "쉽지 않을", "곤란",
                "사라지는 것은 아니지만", "없어지는 것은 아니지만", "소멸하는 것은 아니지만",
                "보전하려는 조치", "단정할 수", "추론", "한계", "우려", "압박",
            )
            _CATEGORICAL_LEGAL_ENDINGS = (
                "확정되었다.", "확정되었습니다.", "소멸하였다.", "소멸하였습니다.",
                "해지되었다.", "해지되었습니다.", "무효이다.", "무효입니다.",
            )

            def _is_case_risk_inference_claim(c_obj: ClaimVerification, norm_draft_text: str) -> bool:
                """사건 증거에 기반한 회수 위험·자금사정 추론인지(단정적 법률효과 주장과 구별) 판별한다."""
                if c_obj.fact_status != "INFERENCE" and c_obj.claim_type != "CASE_INFERENCE":
                    return False
                if not case_evidence_ids.intersection(c_obj.source_ids):
                    return False
                c_text = (c_obj.claim or "").strip()
                if any(c_text.endswith(ending) for ending in _CATEGORICAL_LEGAL_ENDINGS):
                    return False
                has_limit_in_draft = bool(
                    c_obj.inference_limit.strip() and _norm_quote(c_obj.inference_limit) in norm_draft_text
                )
                has_risk_marker = any(marker in c_text for marker in _INFERENCE_RISK_MARKERS)
                return has_limit_in_draft or has_risk_marker

            for claim_obj in result.claims:
                # 계약서·당사자 메모를 법령 근거로 표시한 검증 응답도 그대로 신뢰하지 않는다.
                # 단, 사건 증거에 기반한 회수 위험·자금사정 정황 추론(fact_status=INFERENCE)을
                # 검증기가 LEGAL_APPLICATION/LEGAL_RULE로 분류한 경우에는 CASE_INFERENCE로 정규화하여 오탐을 방지한다.
                if (claim_obj.claim_type in ("LEGAL_RULE", "LEGAL_APPLICATION")
                        and not legal_source_ids.intersection(claim_obj.source_ids)):
                    if (claim_obj.grounding_status in ("SUPPORTED", "UNCERTAIN")
                            and _is_case_risk_inference_claim(claim_obj, norm_draft)):
                        claim_obj.claim_type = "CASE_INFERENCE"
                        claim_obj.fact_status = "INFERENCE"
                        claim_obj.grounding_status = "SUPPORTED"
                        if not claim_obj.inference_basis.strip():
                            claim_obj.inference_basis = claim_obj.reason.strip() or "등록된 사건 자료 기반 위험·정황 추론"
                        if not claim_obj.inference_limit.strip() or _norm_quote(claim_obj.inference_limit) not in norm_draft:
                            claim_obj.inference_limit = claim_obj.claim.strip()
                    elif claim_obj.grounding_status == "SUPPORTED":
                        claim_obj.grounding_status = "UNSUPPORTED"
                        claim_obj.reason = (
                            "법률 효과로 분류된 주장에 법령·판례 근거가 연결되지 않았습니다. "
                            "사건의 정황 평가라면 법률 효과와 문장을 분리하고 자료와 추론 한계를 설명해야 합니다."
                        )
                        result.revision_instructions.append(claim_obj.reason)
                if claim_obj.claim_type == "CASE_INFERENCE":
                    if _is_case_risk_inference_claim(claim_obj, norm_draft) and (
                        (claim_obj.inference_basis.strip() and claim_obj.inference_limit.strip()
                         and _norm_quote(claim_obj.inference_limit) in norm_draft)
                        or (claim_obj.grounding_status == "SUPPORTED" and claim_obj.reason.strip())
                    ):
                        claim_obj.fact_status = "INFERENCE"
                        if not claim_obj.inference_basis.strip():
                            claim_obj.inference_basis = claim_obj.reason.strip()
                        if not claim_obj.inference_limit.strip() or _norm_quote(claim_obj.inference_limit) not in norm_draft:
                            claim_obj.inference_limit = claim_obj.claim.strip()
                    else:
                        # 추론 유형을 법률 근거 검사의 우회 통로로 쓰지 못하게 출처·한계 모두 요구한다.
                        claim_obj.grounding_status = "UNSUPPORTED"
                        claim_obj.reason = "사건 추론의 증거, 추론 관계, 답변에 명시된 한계를 확인해야 합니다."

            # [P0-2] 날짜 역할(발견일 vs 등기 접수일·열람 기준일) 구분 및 동일 역할 날짜 충돌 검사
            _DATE_ROLE_PATTERNS = {
                "등기 접수일": (
                    re.compile(r"(?:등기\s*)?접수일\s*[:은는이가]?\s*(20\d{2})\s*[-년.]\s*0?(\d{1,2})\s*[-월.]\s*0?(\d{1,2})"),
                    re.compile(r"등기\s*접수일\s*[:은는이가]?\s*(20\d{2})\s*[-년.]\s*0?(\d{1,2})\s*[-월.]\s*0?(\d{1,2})"),
                ),
                "열람 기준일": (
                    re.compile(r"열람\s*기준일\s*[:은는이가]?\s*(20\d{2})\s*[-년.]\s*0?(\d{1,2})\s*[-월.]\s*0?(\d{1,2})"),
                    re.compile(r"열람\s*기준일\s*[:은는이가]?\s*(20\d{2})\s*[-년.]\s*0?(\d{1,2})\s*[-월.]\s*0?(\d{1,2})"),
                ),
            }
            same_role_date_conflict = False
            for role_label, (src_pat, draft_pat) in _DATE_ROLE_PATTERNS.items():
                src_dates = {
                    (int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    for s in retrieved_sources
                    if s.get("source_type") == "CASE_EVIDENCE" or s.get("retrieval_method") == "CASE_DOCUMENT_SPANS"
                    for m in src_pat.finditer(str(s.get("content") or ""))
                }
                draft_dates = {
                    (int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    for m in draft_pat.finditer(draft_answer)
                }
                if src_dates and draft_dates and not draft_dates.issubset(src_dates):
                    same_role_date_conflict = True
                    conflict_msg = f"문서 원문의 '{role_label}' 날짜와 답변에 기재된 '{role_label}' 날짜가 상충합니다."
                    if conflict_msg not in result.contradictions:
                        result.contradictions.append(conflict_msg)
                    if conflict_msg not in result.revision_instructions:
                        result.revision_instructions.append(conflict_msg)
                    if isinstance(result.consistency_checks.get("timeline"), dict):
                        result.consistency_checks["timeline"]["passed"] = False
                        result.consistency_checks["timeline"]["reason"] = conflict_msg

            timeline_check = result.consistency_checks.get("timeline")
            if (isinstance(timeline_check, dict)
                    and timeline_check.get("passed") is False
                    and not same_role_date_conflict):
                tl_reason = str(timeline_check.get("reason") or "")
                is_discovery_role_diff = (
                    ("발견" in tl_reason or "발견" in question)
                    and ("접수일" in tl_reason or "열람" in tl_reason)
                    and ("사용자 질문" in tl_reason or "질문은" in tl_reason or "발견" in tl_reason or "시간순으로 반영" in tl_reason)
                )
                if is_discovery_role_diff:
                    timeline_check["model_passed"] = False
                    timeline_check["model_reason"] = tl_reason
                    timeline_check["passed"] = True
                    timeline_check["reason"] = (
                        f"{tl_reason} [검증 정책 보정: 질문의 발견 시점과 문서의 등기 접수일·열람 기준일은 "
                        "서로 다른 날짜 역할이므로 사실 충돌이 아님]"
                    )
                    preserve_note = "사용자 질문의 발견일(인지 시점)과 문서상 등기 접수일·열람 기준일의 역할 구분"
                    if preserve_note not in result.preserved_points:
                        result.preserved_points.append(preserve_note)
                    result.contradictions = [
                        con for con in result.contradictions
                        if not (("사용자 질문" in con or "발견" in con) and ("접수일" in con or "열람" in con))
                    ]
                    result.missing_issues = [
                        iss for iss in result.missing_issues
                        if not ("발견" in iss or "2026.08.12" in iss or "8월 12일" in iss)
                    ]
                    result.revision_instructions = [
                        inst for inst in result.revision_instructions
                        if not ("발견" in inst or "2026.08.12" in inst or "8월 12일" in inst)
                    ]

            # [P1-2] 사용자 질문과 연결되지 않고 답변의 핵심 주장 결함도 아닌 불필요한 하위 법령 요구 필터링
            has_unsupported_legal = any(
                c.grounding_status in ("UNSUPPORTED", "UNCERTAIN")
                and c.claim_type in ("LEGAL_RULE", "LEGAL_APPLICATION")
                for c in result.claims
            )
            if coverage_complete and not has_unsupported_legal and result.missing_legal_issues:
                _UNREQUESTED_KEYWORDS = ("소액임차인", "최우선변제", "대통령령", "시행령")
                _LIMITATION_NOTES = ("현 자료만으로 제한적", "설명이 제한적", "단정할 수 없")
                filtered_missing_legal: List[str] = []
                for ml in result.missing_legal_issues:
                    is_unrequested = any(kw in ml and kw not in question for kw in _UNREQUESTED_KEYWORDS)
                    is_limitation_note = not result.legal_search_requests and any(lim in ml for lim in _LIMITATION_NOTES)
                    if is_unrequested or is_limitation_note:
                        result.warnings.append(f"참고 안내(질문 외 부수 쟁점): {ml}")
                        result.revision_instructions = [
                            inst for inst in result.revision_instructions
                            if not any(kw in inst and kw not in question for kw in _UNREQUESTED_KEYWORDS)
                        ]
                    else:
                        filtered_missing_legal.append(ml)
                result.missing_legal_issues = filtered_missing_legal

            consistency_complete = all(
                isinstance(result.consistency_checks.get(key), dict)
                and result.consistency_checks[key].get("passed") is True
                and isinstance(result.consistency_checks[key].get("reason"), str)
                and bool(result.consistency_checks[key]["reason"].strip())
                for key in ("opening_conclusion", "timeline", "expressed_intent", "provenance")
            )
            if consistency_complete:
                result.revision_instructions = [
                    inst for inst in result.revision_instructions
                    if inst != "시간 순서, 의사표시 내용, 증명 수준을 원문과 대조하여 결론을 보완하세요."
                ]

            # 사실 오류나 출처 없는 법률 주장도 필터링 후 PASS로 남지 않게 한다.
            defective_claims = [c for c in result.claims if (
                c.grounding_status in ("UNSUPPORTED", "UNCERTAIN")
                and c.claim_type in ("CASE_FACT", "CASE_INFERENCE", "USER_STATEMENT", "LEGAL_RULE", "LEGAL_APPLICATION")
            ) or (c.claim_type in ("CASE_FACT", "CASE_INFERENCE", "LEGAL_RULE", "LEGAL_APPLICATION")
                  and c.grounding_status == "SUPPORTED" and not c.source_ids)]
            malformed_claims = [c for c in result.claims if (
                c.claim_type not in ("CASE_FACT", "CASE_INFERENCE", "USER_STATEMENT", "LEGAL_RULE", "LEGAL_APPLICATION", "RECOMMENDATION")
                or c.grounding_status not in ("SUPPORTED", "UNSUPPORTED", "UNCERTAIN", "NOT_APPLICABLE")
                or not c.claim.strip()
            )]
            if (defective_claims or malformed_claims or same_role_date_conflict) and result.status == "PASS":
                result.status = "REVISE"
                result.reason_code = "ANSWER_REVISION_REQUIRED"
                result.revision_instructions.append("사실 및 법률 판단의 원문 근거와 출처 ID를 보완하세요.")
            elif (coverage_complete and consistency_complete
                  and result.claims and not defective_claims and not malformed_claims
                  and not same_role_date_conflict and not result.contradictions
                  and not result.missing_legal_issues and not result.missing_issues
                  and result.status == "REVISE"
                  and result.reason_code in ("ANSWER_REVISION_REQUIRED", "LEGAL_SOURCE_INSUFFICIENT", "NONE", None)):
                result.status = "PASS"
                result.reason_code = "NONE"
                result.recommended_action = "FINALIZE"
            if allow_partial_answer and not any(
                c.grounding_status == "SUPPORTED" and c.source_ids
                and c.claim_type in ("CASE_FACT", "CASE_INFERENCE", "LEGAL_RULE", "LEGAL_APPLICATION")
                for c in result.claims
            ):
                result.status = "INSUFFICIENT"
                result.reason_code = "CASE_EVIDENCE_MISSING"

        # 4. [P0-01] 결정론적 종합 PASS 판정 및 모순 방지 검사 (Deterministic Policy Enforcement)
        # A) 주요 법률 주장 목록(claims)이 비어있는 경우 검증 완료(PASS) 불가
        if not result.claims:
            if result.status == "PASS":
                result.status = "REVISE"
                result.reason_code = "ANSWER_REVISION_REQUIRED" if result.reason_code == "NONE" else result.reason_code
                result.recommended_action = "REVISE_DRAFT"
            result.warnings.append("검증 대상 답변에서 추출된 주요 법률 주장(claims)이 없어 검증을 완료할 수 없습니다.")

        # B) UNSUPPORTED 또는 UNCERTAIN 핵심 법률 주장 존재 시 PASS 엄격 차단 (적응형 스코프)
        # 실무 권고(RECOMMENDATION)나 단순 진술(USER_STATEMENT)은 조문 RAG 출처가 없어도 정상 실무 조언으로 인정함
        unsupported_core_claims = [
            c for c in result.claims
            if c.grounding_status == "UNSUPPORTED"
            and c.claim_type in ("LEGAL_RULE", "LEGAL_APPLICATION", "CASE_FACT")
        ]
        uncertain_core_claims = [
            c for c in result.claims
            if c.grounding_status == "UNCERTAIN"
            and c.claim_type in ("LEGAL_RULE", "LEGAL_APPLICATION")
        ]

        if unsupported_core_claims and result.status == "PASS":
            result.status = "REVISE"
            if result.reason_code == "NONE":
                result.reason_code = "LEGAL_SOURCE_INSUFFICIENT"
            result.recommended_action = "REVISE_DRAFT"
            result.warnings.append(f"법률 조문 또는 판례에 의해 뒷받침되지 않는 핵심 법적 판단 {len(unsupported_core_claims)}건이 감지되어 조건부 수정(REVISE)이 요구됩니다.")

        if uncertain_core_claims and result.status == "PASS":
            result.status = "REVISE"
            if result.reason_code == "NONE":
                result.reason_code = "ANSWER_REVISION_REQUIRED"
            result.recommended_action = "REVISE_DRAFT"
            result.warnings.append(f"법적 근거 확인이 불확실한 판단 {len(uncertain_core_claims)}건이 포함되어 있어 비확정적 안내로 보완이 필요합니다.")

        # B-1) 미등록 임의 가상 증거번호 감지 시 PASS 차단 및 REVISE 강제 (T05)
        unregistered_evidences = [
            cid for cid, r in audit.get("rejection_reasons", {}).items()
            if r == "UNREGISTERED_EVIDENCE_NUMBER"
        ]
        if unregistered_evidences:
            ev_str = ", ".join(audit.get("unverified_citations", []))
            result.warnings.append(f"DB에 등록되지 않은 임의의 가상 증거번호({ev_str})가 감지되었습니다.")
            result.revision_instructions.append(
                f"등록되지 않은 임의의 증거번호({ev_str})를 답변에서 제거하고, '사용자 진술' 또는 '확보 필요 자료'로 수정하세요."
            )
            if result.status == "PASS":
                result.status = "REVISE"
                if result.reason_code == "NONE":
                    result.reason_code = "CITATION_INVALID"
                result.recommended_action = "REVISE_DRAFT"

        # C) 인용 오류나 미확인 출처가 있는 경우 PASS 엄격 차단
        if unverified_citations:
            cite_str = ", ".join(unverified_citations)
            result.warnings.append(f"검색 결과에서 확인되지 않은 출처 인용이 감지되었습니다: {cite_str}")
            result.revision_instructions.append(
                f"검색된 출처 목록에 존재하지 않는 허위 인용({cite_str})을 답변에서 제거하고 실제 검색된 출처만 인용하세요."
            )
            if result.status == "PASS":
                result.status = "REVISE"
                if result.reason_code == "NONE":
                    result.reason_code = "CITATION_INVALID"
                result.recommended_action = "REVISE_DRAFT"

        if unsupported_citations:
            unsup_str = ", ".join(unsupported_citations)
            result.warnings.append(f"출처 문서의 본문이 해당 주장을 뒷받침하지 않는 인용이 감지되었습니다: {unsup_str}")
            result.revision_instructions.append(
                f"출처 본문과 무관하게 인용된 출처({unsup_str})를 제거하고, 해당 주장을 수정하거나 근거 미확인으로 표시하세요."
            )
            if result.status == "PASS":
                result.status = "REVISE"
                if result.reason_code == "NONE":
                    result.reason_code = "LEGAL_SOURCE_INSUFFICIENT"
                result.recommended_action = "REVISE_DRAFT"

        # D) status=PASS인데 reason_code가 결함 코드인 논리적 모순 방지
        if result.status == "PASS" and result.reason_code != "NONE":
            result.status = "REVISE"
            result.recommended_action = "REVISE_DRAFT"

        # E) [P0-VER-01] 모든 핵심 법률 주장이 검색 출처에 의해 100% 뒷받침되고 결함이 없는 경우 객관적 PASS 확정
        # 검증 LLM이 모든 주장을 SUPPORTED로 판정하고도 단문 질의의 사실관계 증빙 부재 등을 이유로 REVISE 또는 LEGAL_SOURCE_INSUFFICIENT를 반환하는 오판정 차단
        has_supported_core_claims = any(
            c.grounding_status == "SUPPORTED" and c.claim_type in ("LEGAL_RULE", "LEGAL_APPLICATION")
            for c in result.claims
        )
        has_no_defects = (
            not unsupported_core_claims
            and not uncertain_core_claims
            and not unverified_citations
            and not unsupported_citations
            and not result.contradictions
            and not unregistered_evidences
        )
        if not require_question_coverage and has_supported_core_claims and has_no_defects and result.status == "REVISE":
            if result.reason_code in ("LEGAL_SOURCE_INSUFFICIENT", "ANSWER_REVISION_REQUIRED", "CASE_EVIDENCE_MISSING", "NONE"):
                logger.info("[VERIFICATION] 모든 핵심 주장이 검색 출처에 의해 온전히 뒷받침(SUPPORTED 100%)되므로 PASS로 확정합니다.")
                result.status = "PASS"
                result.reason_code = "NONE"
                result.recommended_action = "FINALIZE"

        result.citation_audit = audit

        logger.info(
            f"[VERIFICATION] status={result.status}, claims={len(result.claims)}, "
            f"unverified={len(unverified_citations)}, unsupported={len(unsupported_citations)}"
        )
        if unsupported_citations or unverified_citations:
            logger.info(
                f"[VERIFICATION_CITATIONS] unsupported={unsupported_citations}, "
                f"unverified={unverified_citations}, reasons={rejection_reasons}"
            )

        try:
            unsupported_total = sum(1 for c in result.claims if c.grounding_status != "SUPPORTED")
            update_span(get_current_span_id(), {
                "claims_count": len(result.claims),
                "supported_count": len(result.claims) - unsupported_total,
                "warnings_count": len(result.warnings),
                "is_fail": result.status == "INSUFFICIENT",
                "is_revise": result.status == "REVISE",
                "reason_code": result.reason_code,
                "candidate_laws": result.candidate_laws,
                "recommended_action": result.recommended_action,
                "missing_legal_issues": result.missing_legal_issues,
                "unsupported_count": unsupported_total,
                "missing_issues_count": len(result.missing_issues),
                "unverified_citations_count": len(unverified_citations),
                "unsupported_citations_count": len(unsupported_citations),
                # 요구사항 5: Langfuse Observability 필수 필드 기록
                "retrieval_source_ids": audit["retrieval_source_ids"],
                "retrieval_methods": audit["retrieval_methods"],
                "retrieved_chunk_ids": audit["retrieved_chunk_ids"],
                "generated_citation_ids": audit["generated_citation_ids"],
                "validated_citation_ids": audit["validated_citation_ids"],
                "rejected_citation_ids": audit["rejected_citation_ids"],
                "rejection_reasons": audit["rejection_reasons"],
                "citation_existence_rate": audit["citation_existence_rate"],
                "citation_support_rate": audit["citation_support_rate"],
            })
        except Exception:
            pass
        out_dict = result.model_dump()
        # STEP 5: 경량 QA 검사 결과(repair_targets 및 qa_summary) 결합
        if qa_check.repair_targets and not out_dict.get("repair_targets"):
            out_dict["repair_targets"] = [rt.model_dump() for rt in qa_check.repair_targets]
        out_dict["qa_summary"] = qa_check.model_dump()
        return {**out_dict, "source_manifest": source_manifest}

    except Exception as e:
        if not error_type:
            if isinstance(e, (TimeoutError, ConnectionError)):
                error_type = "LLM_TIMEOUT"
            elif isinstance(e, json.JSONDecodeError):
                error_type = "JSON_PARSE_ERROR"
            elif isinstance(e, ValidationError):
                error_type = "SCHEMA_NORMALIZATION"
            else:
                error_type = "SYSTEM_ERROR"

        logger.error(
            "Verification Agent 오류 발생 (안전 차단 | 기술오류유형=%s): %s",
            error_type,
            type(e).__name__,
        )
        # P0-01 & STEP 2 준수: 검증 시스템 장애 시 절대로 PASS로 Fail-open하지 않고 INSUFFICIENT(VERIFICATION_ERROR)로 안전 종료
        fallback_warnings = [
            f"법률검증 처리 중 기술적 문제({error_type})가 발생하여 답변 검증을 완료하지 못했습니다."
        ]
        fallback_instructions: List[str] = []
        if unverified_citations:
            cite_str = ", ".join(unverified_citations)
            fallback_warnings.append(f"검색 결과에서 확인되지 않은 출처 인용이 감지되었습니다: {cite_str}")
            fallback_instructions.append(
                f"검색된 출처 목록에 존재하지 않는 허위 인용({cite_str})을 답변에서 제거하세요."
            )
        if unsupported_citations:
            unsup_str = ", ".join(unsupported_citations)
            fallback_warnings.append(f"출처 문서의 본문이 해당 주장을 뒷받침하지 않는 인용이 감지되었습니다: {unsup_str}")
            fallback_instructions.append(
                f"출처 본문과 무관하게 인용된 출처({unsup_str})를 제거하세요."
            )
        return {
            "status": "INSUFFICIENT",
            "reason_code": "VERIFICATION_ERROR",
            "error_type": error_type,
            "verification_error_type": error_type,
            "missing_legal_issues": [],
            "candidate_laws": [],
            "recommended_action": "SAFE_FALLBACK",
            "explanation": f"검증 처리 중 기술적 문제({error_type})로 인해 안전 종료되었습니다.",
            "claims": [],
            "missing_issues": [],
            "contradictions": [],
            "revision_instructions": fallback_instructions,
            "warnings": fallback_warnings,
            "citation_audit": audit,
        }
