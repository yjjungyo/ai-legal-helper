# -*- coding: utf-8 -*-
"""검증 Agent 프롬프트 컨텍스트 다이어트(최적화 1번) 단위 테스트 모듈.

[테스트 목적]
1. `normalize_statute_key`: 법령명과 조문 번호 정규화 로직 검증.
2. `prune_sources_for_verification`:
   - 공식 검색, 로컬 적재, Vector 검색 간 동일 법령 조문 중복 제거 검증.
   - 초안 인용 증거의 전문 보존 및 미인용 증거의 본문 스니펫 축약 검증.
3. `prune_case_context_for_verification`:
   - 수만 자에 달하는 과거 대화 턴 누적 및 장문 사실관계를 4,000자 이내로 압축 검증.
4. `run_verification` 연동 검증:
   - 프롬프트 경량화 적용 및 `source_manifest`의 원본 정보 보존 검증.
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any, List

from ai_legal_helper.rag.grounding_context import (
    normalize_statute_key,
    prune_sources_for_verification,
    prune_case_context_for_verification,
    format_grounding_sources,
)
from ai_legal_helper.agents.verification import run_verification


def test_normalize_statute_key():
    """다양한 형식의 법령 출처 메타데이터로부터 일관된 '법령명:조문' 키가 도출되는지 검증한다."""
    # 1. 명시적 statute_name + article
    s1 = {"statute_name": "주택임대차보호법", "article": "제3조의2"}
    assert normalize_statute_key(s1) == "주택임대차보호법:제3조의2"

    # 2. title / filename 정규식 매칭
    s2 = {"title": "주택임대차보호법 제3조의3(임차권등기명령)"}
    assert normalize_statute_key(s2) == "주택임대차보호법:제3조의3"

    # 3. OFFICIAL source_id 파싱
    s3 = {"source_id": "OFFICIAL:001248:276291:제3조의2:58bc3115eeaa116b"}
    assert normalize_statute_key(s3) == "주택임대차보호법:제3조의2"

    # 4. STATUTE source_id 파싱
    s4 = {"source_id": "STATUTE:001706:284415:제536조:de77a32c9d72536a"}
    assert normalize_statute_key(s4) == "민법:제536조"


def test_prune_sources_deduplicates_identical_statutes():
    """동일한 법령 조문이 여러 출처 ID로 중복 수집된 경우 공식 원문 1개만 남기고 중복 제거되는지 검증한다."""
    sources = [
        {
            "source_id": "STATUTE:001248:276291:제3조의2:vector1",
            "statute_name": "주택임대차보호법",
            "article": "제3조의2",
            "retrieval_method": "CHROMA_VECTOR",
            "content": "벡터 검색으로 수집된 짧은 본문",
        },
        {
            "source_id": "OFFICIAL:001248:276291:제3조의2:official1",
            "statute_name": "주택임대차보호법",
            "article": "제3조의2",
            "retrieval_method": "OFFICIAL_STATUTE_SEARCH",
            "content": "국가법령정보센터 공식 법령 원문 제3조의2 전문...",
        },
        {
            "source_id": "주택임대차보호법 제3조의2(보증금의 회수)",
            "title": "주택임대차보호법 제3조의2",
            "retrieval_method": "LOCAL_INDEX",
            "content": "로컬 인덱스 적재 본문...",
        },
    ]

    pruned = prune_sources_for_verification(sources, draft_answer="제3조의2에 따라 우선변제권 행사")

    # 동일 조문 3건 중 OFFICIAL 1건만 남아야 함
    assert len(pruned) == 1
    assert pruned[0]["retrieval_method"] == "OFFICIAL_STATUTE_SEARCH"
    assert "국가법령정보센터 공식 법령 원문" in pruned[0]["content"]


def test_prune_sources_preserves_cited_and_condenses_uncited():
    """초안에 인용된 증거 문서는 전문을 보존하고, 미인용 증거 문서는 본문 스니펫으로 축약되는지 검증한다."""
    long_content = "매우 상세하고 긴 증거 원문 텍스트입니다. " * 30  # 약 800자

    sources = [
        # 인용된 증거
        {
            "source_id": "E01",
            "filename": "E01_임대차계약서.txt",
            "content": long_content,
        },
        # 미인용 증거
        {
            "source_id": "E02",
            "filename": "E02_무관한_영수증.txt",
            "content": long_content,
        },
    ]

    draft = "임대차 계약에 따르면 보증금은 3억 원입니다 [E01_임대차계약서.txt]."

    pruned = prune_sources_for_verification(sources, draft_answer=draft, max_unreferenced_snippet=50)

    assert len(pruned) == 2
    # E01은 전문 보존
    assert pruned[0]["filename"] == "E01_임대차계약서.txt"
    assert len(pruned[0]["content"]) == len(long_content)

    # E02는 축약됨
    assert pruned[1]["filename"] == "E02_무관한_영수증.txt"
    assert len(pruned[1]["content"]) < 150
    assert "초안 미인용 증거: 상세 본문 생략" in pruned[1]["content"]


def test_prune_case_context_compresses_multi_turn_history():
    """수만 자에 달하는 다중 턴 상담 이력 및 사실관계가 4,000자 이내로 압축되는지 검증한다."""
    # 2만 자짜리 장문 컨텍스트 모의 생성
    multi_turn_text = "\n".join([f"[Turn {i}]\n질문: 보증금 미반환\n답변: 법률 의견서 상세 본문입니다... " * 10 for i in range(15)])
    facts_text = "\n[2. 사건 사실관계 및 증거]\n" + "\n".join([f"- [입증된 사실] Fact #{i}: 임대인과 임차인 계약 사실..." for i in range(100)])
    huge_context = multi_turn_text + facts_text

    assert len(huge_context) > 10000

    pruned_ctx = prune_case_context_for_verification(huge_context, draft_answer="임대차 계약 사실", max_chars=3000)

    assert len(pruned_ctx) <= 3500
    assert "상담 턴 경과" in pruned_ctx or "상세 생략" in pruned_ctx


def test_run_verification_integrates_diet_pruning():
    """`run_verification` 실행 시 내부에서 다이어트된 프롬프트로 LLM이 호출되는지 검증한다."""
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content="""```json
{
  "status": "PASS",
  "reason_code": "NONE",
  "explanation": "모든 주장이 충실히 뒷받침됩니다.",
  "claims": [
    {
      "claim": "임차권등기명령을 신청해야 합니다.",
      "claim_type": "RECOMMENDATION",
      "fact_status": "VERIFIED_FACT",
      "source_ids": ["E01_계약서.txt"],
      "grounding_status": "SUPPORTED",
      "reason": "계약서에 의해 뒷받침됨"
    }
  ]
}
```""")

    sources = [
        {
            "source_id": "OFFICIAL:001248:제3조의2:1",
            "statute_name": "주택임대차보호법",
            "article": "제3조의2",
            "retrieval_method": "OFFICIAL_STATUTE_SEARCH",
            "content": "조문 내용",
        },
        {
            "source_id": "E01",
            "filename": "E01_계약서.txt",
            "content": "계약서 상세 본문 " * 20,
        },
        {
            "source_id": "E02",
            "filename": "E02_미인용문서.txt",
            "content": "미인용 상세 본문 " * 50,
        },
    ]

    huge_case_ctx = "[사건 기본 정보]\n보증금: 3억\n" + "\n".join([f"Fact #{i}: 사실내용" for i in range(200)])

    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=mock_llm), \
         patch("ai_legal_helper.agents.qa_checker.check_deterministic_qa") as mock_qa:
        
        mock_qa.return_value = MagicMock(status="PASS", requires_llm_eval=True, citation_audit={}, preserved_points=[])

        out = run_verification(
            question="보증금 반환 절차는?",
            draft_answer="임차권등기명령을 신청해야 합니다 [E01_계약서.txt].",
            retrieved_sources=sources,
            case_context=huge_case_ctx,
            force_llm=True,
        )

        assert out["status"] == "PASS"
        mock_llm.invoke.assert_called_once()
        invoked_prompt = mock_llm.invoke.call_args[0][0]

        # LLM에 주입된 프롬프트에 미인용 증거 본문 생략 표기가 반영되었는지 검증
        assert "초안 미인용 증거: 상세 본문 생략" in invoked_prompt
        # source_manifest는 전체 3개 출처를 모두 인지하고 있는지 검증
        assert out["source_manifest"]["source_count"] == 3



def test_verification_prompt_contains_claims_pruning_guidelines():
    """`VERIFICATION_PROMPT` 및 `DOCUMENT_VERIFICATION_PROMPT`에 핵심 6~8개 주장 선별 지침이 포함되어 있는지 검증한다."""
    from ai_legal_helper.agents.verification import VERIFICATION_PROMPT
    from ai_legal_helper.agents.document_verification_prompt import DOCUMENT_VERIFICATION_PROMPT

    # 1. VERIFICATION_PROMPT 검증
    assert "핵심 6~8개 주장" in VERIFICATION_PROMPT
    assert "단순 실무 권고" in VERIFICATION_PROMPT
    assert "1~2문장의 간결한 핵심 요약" in VERIFICATION_PROMPT

    # 2. DOCUMENT_VERIFICATION_PROMPT 검증
    assert "핵심 6~8개 주장" in DOCUMENT_VERIFICATION_PROMPT
    assert "1~2문장의 간결한 핵심 요약" in DOCUMENT_VERIFICATION_PROMPT


def test_verification_handles_compact_6_claims_successfully():
    """핵심 6개 주장으로 경량화된 검증 출력이 주어졌을 때 정상적으로 검증이 완료되는지 검증한다."""
    from ai_legal_helper.agents.verification import VerificationOutput, ClaimVerification

    claims_data = [
        {
            "claim": f"핵심 법률 주장 #{i}",
            "claim_type": "LEGAL_APPLICATION",
            "fact_status": "VERIFIED_FACT",
            "source_ids": ["E01_계약서.txt"],
            "grounding_status": "SUPPORTED",
            "reason": "해당 증거와 일치함",
        }
        for i in range(1, 7)  # 6개 핵심 주장
    ]

    vo = VerificationOutput(
        status="PASS",
        reason_code="NONE",
        explanation="핵심 주장 검증 완료",
        claims=claims_data,
    )

    assert vo.status == "PASS"
    assert len(vo.claims) == 6
