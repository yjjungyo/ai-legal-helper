# -*- coding: utf-8 -*-
"""
모듈명: test_p0_followup_defects.py

[모듈 개요]
AI Legal Helper P0 핵심 결함 4건에 대한 재현(수정 전 실패 확인) 및 수정 후 방어 검증 테스트:
- P0-01 (V-01 ~ V-08): Verifier의 강제 PASS 규칙 제거 및 법률 주장별/종합 PASS 조건 검증
- P0-02 (A-01 ~ A-08): WITHHELD 상태 미검증 초안 고객 노출 차단 및 답변 전달 정책 검증
- P0-03 (S-01 ~ S-08): 검색된 출처(retrieved_sources)와 검증된 출처(cited_sources) 계층 분리 검증
- P0-04 (H-01 ~ H-08): HILT 재분석 프롬프트의 전세보증금 하드코딩 제거 및 도메인 중립화 검증
"""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage

from ai_legal_helper.agents.verification import (
    VERIFICATION_PROMPT,
    audit_citations_and_claims,
    run_verification,
)
from ai_legal_helper.workflows.legal_workflow import (
    insufficient_node,
    re_analyze_node,
    finalize_node,
)
from ai_legal_helper.workflows.state import LegalState


# ==============================================================================
# P0-01: Verifier 강제 PASS 및 검증 누락 검증 (V-01 ~ V-08)
# ==============================================================================

def test_v01_v02_prompt_does_not_contain_forced_official_statute_pass():
    """V-01, V-02: VERIFICATION_PROMPT에 공식 법령 검색 시 무조건 PASS하라는 강제 규칙이 제거되었는지 검증."""
    # 기존 결함 문구: "OFFICIAL_STATUTE_SEARCH... status는 반드시 'PASS'로 판정하세요"
    assert "status는 반드시 \"PASS\"로 판정" not in VERIFICATION_PROMPT, (
        "P0-01 결함: 공식 법령 검색 성공 시 무조건 PASS하도록 하는 강제 규칙이 여전히 존재합니다."
    )
    assert "status는 반드시 'PASS'로 판정" not in VERIFICATION_PROMPT


def test_v02_v03_post_verification_rejects_pass_when_claims_unsupported():
    """V-02, V-03: LLM이 PASS를 반환했더라도 UNSUPPORTED 주장이 있으면 결정론적으로 PASS를 거부하는지 검증."""
    mock_llm_output = {
        "status": "PASS",
        "reason_code": "NONE",
        "missing_legal_issues": [],
        "candidate_laws": [],
        "recommended_action": "FINALIZE",
        "explanation": "검증 완료",
        "claims": [
            {
                "claim": "상대방의 배우자에게 알린 것만으로 즉시 적법한 통지가 완성됩니다.",
                "source_ids": ["statute_law_1"],
                "grounding_status": "UNSUPPORTED",
                "reason": "해당 법령 조문에 대리권 없는 배우자 수령 시 즉시 효력 발생 규정 없음",
            }
        ],
        "missing_issues": [],
        "contradictions": [],
        "revision_instructions": [],
        "warnings": [],
    }

    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=str(mock_llm_output).replace("'", '"'))
        mock_get.return_value = mock_llm

        res = run_verification(
            question="배우자에게 전화로 통지하면 바로 해지 효력이 발생하나요?",
            draft_answer="배우자에게 전화로 알린 것만으로 즉시 적법한 통지가 완성됩니다. (주택임대차보호법 제6조의2)",
            retrieved_sources=[{
                "source_id": "statute_law_1",
                "statute_name": "주택임대차보호법",
                "article": "제6조의2",
                "content": "임차인은 언제든지 해지통지를 할 수 있고 3개월이 지나면 효력이 발생한다.",
                "retrieval_method": "OFFICIAL_STATUTE_SEARCH",
            }],
        )

        assert res["status"] != "PASS", "P0-01 결함: 핵심 주장이 UNSUPPORTED인데 PASS로 확정되었습니다."
        assert res["status"] in ("REVISE", "INSUFFICIENT")


def test_v05_rejects_pass_when_claims_list_is_empty():
    """V-05: 주요 법률 주장 목록(claims)이 비어있는 경우 검증 완료(PASS)로 오인하지 않고 차단하는지 검증."""
    mock_llm_output = {
        "status": "PASS",
        "reason_code": "NONE",
        "missing_legal_issues": [],
        "candidate_laws": [],
        "recommended_action": "FINALIZE",
        "explanation": "통과",
        "claims": [],  # 비어있는 주장 목록
        "missing_issues": [],
        "contradictions": [],
        "revision_instructions": [],
        "warnings": [],
    }

    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=str(mock_llm_output).replace("'", '"'))
        mock_get.return_value = mock_llm

        res = run_verification(
            question="보증금 3억 반환 청구 가능한가요?",
            draft_answer="네 반환 청구가 가능합니다.",
            retrieved_sources=[{"source_id": "s1", "content": "내용"}],
        )

        assert res["status"] != "PASS", "P0-01 결함: 주요 법률 주장(claims)이 비어있음에도 PASS가 허용되었습니다."


# ==============================================================================
# P0-02: 미검증 답변 고객 노출 차단 검증 (A-01 ~ A-08)
# ==============================================================================

def test_a02_a05_insufficient_node_does_not_contain_unverified_draft():
    """A-02, A-05: insufficient_node가 미검증 초안(draft_answer)을 고객용 final_answer에 포함하지 않는지 검증."""
    unverified_draft = "피고는 원고에게 3억원을 지급할 의무가 확실히 있습니다. (가상의 근거)"
    state: LegalState = {
        "question": "보증금 받을 수 있나요?",
        "draft_answer": unverified_draft,
        "retrieved_sources": [],
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "LEGAL_SOURCE_MISSING",
            "missing_issues": ["주택임대차보호법 조문 누락"],
            "warnings": ["법률 근거가 전혀 검색되지 않았습니다."],
        },
        "warnings": [],
        "messages": [],
    }

    res = insufficient_node(state)
    final_ans = res.get("final_answer", "")

    # 미검증 초안 문장이 고객용 final_answer에 포함되어서는 안 됨
    assert unverified_draft not in final_ans, (
        "P0-02 결함: INSUFFICIENT(WITHHELD) 상태임에도 미검증 초안 내용이 고객용 final_answer에 노출되었습니다."
    )
    # 고객용 안내(판단 유보 사유 및 안전 안내)가 포함되어야 함
    assert "법률적 근거 부족" in final_ans or "판단 유보" in final_ans or "안내" in final_ans


# ==============================================================================
# P0-03: 검색 출처와 검증 출처 분리 검증 (S-01 ~ S-08)
# ==============================================================================

def test_s01_s03_audit_separates_retrieved_and_cited_sources():
    """S-01, S-03: 10개 검색 출처 중 답변에서 1개만 인용했을 때 cited_sources에는 인용된 1개만 포함되는지 검증."""
    retrieved = [
        {"source_id": "statute_1", "statute_name": "민법", "article": "제1조", "content": "민사에 관하여 법률에 규정이 없으면 관습법에 의하고 관습법이 없으면 조리에 의한다."}
    ] + [
        {"source_id": f"statute_{i}", "statute_name": "민법", "article": f"제{i}조", "content": f"민법 제{i}조 내용 규정"}
        for i in range(2, 11)
    ]
    # 답변 초안에서는 오직 민법 제1조만 인용하고 제2~10조는 인용하지 않음
    draft = "법률에 규정이 없으면 관습법에 의합니다. (민법 제1조)"

    audit = audit_citations_and_claims(draft, retrieved)

    # 1. 원본 검색 출처(retrieval_source_ids)는 10개 모두 보존되어야 함
    assert len(audit.get("retrieval_source_ids", [])) == 10

    # 2. 실제 답변에서 인용되고 검증된 출처(cited_sources)는 인용된 1개여야 함 (인용 안 된 9개 조문 배제)
    cited = audit.get("cited_sources") or audit.get("verified_sources")
    # P0-03 기준: 인용되지 않은 법령이 '검증된 출처'에 10개 모두 남아있다면 결함
    assert len(cited) == 1, (
        f"P0-03 결함: 답변에 인용되지 않은 9개 법령이 여전히 검증 출처에 포함되어 있습니다 (총 {len(cited)}개)."
    )
    assert cited[0].get("article") == "제1조"


def test_s02_chunk_preservation_and_deduplication():
    """S-02: 동일 문서 3개 청크가 검색되었을 때 원본 청크는 보존되고 cited_sources는 정돈되는지 검증."""
    retrieved = [
        {"source_id": f"doc1_chunk_{i}", "file": "임대차계약서.pdf", "page": "1", "chunk_id": f"c_{i}", "content": "보증금 3억원"}
        for i in range(1, 4)
    ]
    draft = "보증금은 3억원으로 정해져 있습니다. (임대차계약서.pdf, p.1)"

    audit = audit_citations_and_claims(draft, retrieved)

    # 원본 청크 ID들은 모두 기록되어 있어야 함
    assert len(audit.get("retrieved_chunk_ids", [])) == 3
    # cited_sources에는 해당 문서가 식별되어야 함
    cited = audit.get("cited_sources") or audit.get("verified_sources")
    assert len(cited) >= 1


# ==============================================================================
# P0-04: HILT 재분석 프롬프트의 도메인 하드코딩 제거 검증 (H-01 ~ H-08)
# ==============================================================================

def test_v04_unsupported_claim_fails_pass():
    """V-04: 존재하는 출처를 인용했더라도 본문이 뒷받침하지 않는 주장이면 PASS를 거부하는지 검증."""
    mock_llm_output = {
        "status": "PASS",
        "reason_code": "NONE",
        "missing_legal_issues": [],
        "candidate_laws": [],
        "recommended_action": "FINALIZE",
        "explanation": "통과",
        "claims": [
            {
                "claim": "임대인은 임차인의 통지 즉시 24시간 이내에 보증금을 전액 반환해야 합니다.",
                "source_ids": ["s_law_1"],
                "grounding_status": "UNSUPPORTED",
                "reason": "출처 본문에는 3개월의 유예기간이 규정되어 있음",
            }
        ],
        "missing_issues": [],
        "contradictions": [],
        "revision_instructions": [],
        "warnings": [],
    }

    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=str(mock_llm_output).replace("'", '"'))
        mock_get.return_value = mock_llm

        res = run_verification(
            question="보증금 즉시 반환 의무",
            draft_answer="임대인은 임차인의 통지 즉시 24시간 이내에 보증금을 전액 반환해야 합니다. (주택임대차보호법 제6조의2)",
            retrieved_sources=[{
                "source_id": "s_law_1",
                "statute_name": "주택임대차보호법",
                "article": "제6조의2",
                "content": "임대인이 통지를 받은 날부터 3개월이 지나면 효력이 발생한다.",
            }],
        )
        assert res["status"] != "PASS"


def test_v06_uncertain_claim_leads_to_revise():
    """V-06: 결론에 영향을 미치는 UNCERTAIN 주장이 존재하면 PASS가 아닌 REVISE로 보완 요구하는지 검증."""
    mock_llm_output = {
        "status": "PASS",
        "reason_code": "NONE",
        "missing_legal_issues": [],
        "candidate_laws": [],
        "recommended_action": "FINALIZE",
        "explanation": "통과",
        "claims": [
            {
                "claim": "배우자의 일상가사대리권 범위에 임대차 해지 수령이 포함되는지 여부는 불확실합니다.",
                "source_ids": ["s_law_1"],
                "grounding_status": "UNCERTAIN",
                "reason": "구체적 위임장 또는 인감증명서 증빙 필요",
            }
        ],
        "missing_issues": [],
        "contradictions": [],
        "revision_instructions": [],
        "warnings": [],
    }

    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=str(mock_llm_output).replace("'", '"'))
        mock_get.return_value = mock_llm

        res = run_verification(
            question="배우자 수령 효력",
            draft_answer="배우자의 일상가사대리권 범위에 임대차 해지 수령이 포함되는지 여부는 불확실합니다.",
            retrieved_sources=[{"source_id": "s_law_1", "content": "민법 조문"}],
        )
        assert res["status"] != "PASS"
        assert res["status"] == "REVISE"


def test_v07_verifier_syntax_error_fails_safe():
    """V-07: LLM이 잘못된 JSON을 반환하거나 문법 오류 시 FAIL-OPEN되지 않고 INSUFFICIENT로 안전 차단하는지 검증."""
    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="이것은 잘못된 JSON 형식의 응답입니다.")
        mock_get.return_value = mock_llm

        res = run_verification(
            question="질문",
            draft_answer="답변",
            retrieved_sources=[],
        )
        assert res["status"] == "INSUFFICIENT"
        assert res["reason_code"] == "VERIFICATION_ERROR"


# ==============================================================================
# P0-02: 답변 전달 정책 및 레거시 호환 검증 (A-01 ~ A-08)
# ==============================================================================

def test_a01_delivered_when_verified_pass():
    """A-01: finalize_node 실행 시 검증 완료된 최종 답변 및 출처가 정상 생성되는지 검증."""
    state: LegalState = {
        "draft_answer": "임대인은 3개월 후 보증금을 반환해야 합니다. (주택임대차보호법 제6조의2)",
        "retrieved_sources": [{
            "source_id": "s_law_1",
            "statute_name": "주택임대차보호법",
            "article": "제6조의2",
            "content": "임차인은 언제든지 임대인에게 계약해지를 통지할 수 있고 3개월이 지나면 효력이 발생한다.",
        }],
        "case_context": "",
        "warnings": [],
        "verification_result": {"status": "PASS", "warnings": []},
    }
    res = finalize_node(state)
    assert res.get("final_answer")
    assert len(res.get("sources", [])) == 1


def test_a06_legacy_history_safe_fallback():
    """A-06: answer_status가 없는 레거시 DB 레코드 조회 시 verification_status에 따라 안전하게 보정되는지 검증."""
    from ai_legal_helper.api.routes.consultation import _resolve_legacy_answer_status

    # 1. 과거 검증 통과(PASS) 기록은 DELIVERED로 보정
    assert _resolve_legacy_answer_status(None, "PASS", "SUCCESS") == "DELIVERED"
    # 2. 과거 REVISE 기록은 CAUTIONARY로 보정
    assert _resolve_legacy_answer_status(None, "REVISE", "SUCCESS") == "CAUTIONARY"
    # 3. 과거 실패/미검증/승인대기 기록은 반드시 WITHHELD로 안전 처리 (임의 DELIVERED 절대 금지)
    assert _resolve_legacy_answer_status(None, "INSUFFICIENT", "SUCCESS") == "WITHHELD"
    assert _resolve_legacy_answer_status(None, "FAIL", "SUCCESS") == "WITHHELD"
    assert _resolve_legacy_answer_status(None, None, "APPROVAL_REQUIRED") == "WITHHELD"
    assert _resolve_legacy_answer_status(None, "UNVERIFIED", "ERROR") == "WITHHELD"


# ==============================================================================
# P0-03: 가짜 조문 차단 및 인용 정합성 검증 (S-04 ~ S-08)
# ==============================================================================

def test_s04_unverified_article_citation_audit():
    """S-04: 검색 결과에 존재하지 않는 가짜 조문 인용 시 rejected_citations에 기록되고 검증 실패하는지 검증."""
    retrieved = [{
        "source_id": "law_1",
        "statute_name": "주택임대차보호법",
        "article": "제3조",
        "content": "대항력 요건",
    }]
    # 검색된 것은 제3조뿐인데 초안이 제999조를 인용함
    draft = "임대인은 즉시 퇴거해야 합니다. (주택임대차보호법 제999조)"

    audit = audit_citations_and_claims(draft, retrieved)
    assert len(audit.get("rejected_citation_ids", [])) >= 1
    assert any("999" in cid for cid in audit["rejected_citation_ids"])
    # 고객용 cited_sources에는 가짜 조문이 절대 포함되지 않음
    assert len(audit.get("cited_sources", [])) == 0


# ==============================================================================
# P0-04: HILT 노동 분쟁 및 도메인 중립화 시나리오 검증 (H-03, H-05)
# ==============================================================================

def test_h03_labor_dispute_hilt():
    """H-03: 노동 분쟁(임금 체불) 사건 재분석 시 근로기준법 기반 분석이 적용되고 임대차 용어가 없는지 검증."""
    state: LegalState = {
        "question": "퇴직 후 14일이 지났는데 퇴직금 1,500만원을 받지 못했습니다. 지연이자 청구가 가능한가요?",
        "categories": ["노동", "임금"],
        "case_context": "퇴직일: 2024-01-01, 지급기일 연장 합의 없음",
        "statute_search_results": [{
            "source_id": "labor_37",
            "statute_name": "근로기준법",
            "article": "제37조",
            "content": "사용자는 임금 및 퇴직금의 전부 또는 일부를 지급하지 아니한 경우 연 100분의 20의 지연이자를 지급하여야 한다.",
        }],
        "revision_count": 0,
    }

    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get:
        mock_llm = MagicMock()
        captured_prompt = None
        def mock_invoke(p):
            nonlocal captured_prompt
            captured_prompt = str(p)
            return MagicMock(content="[1. 핵심 결론]\n근로기준법 제37조에 따라 연 20% 지연이자 청구가 가능합니다.\n[2. 지금 해야 할 일]\n노동청 진정")
        mock_llm.invoke.side_effect = mock_invoke
        mock_get.return_value = mock_llm

        res = re_analyze_node(state)
        assert captured_prompt is not None
        assert "임차권등기명령" not in captured_prompt
        assert "전세보증금" not in captured_prompt
        assert "근로기준법" in captured_prompt
        assert "노동" in captured_prompt
        assert res.get("draft_answer")


def test_h02_h04_re_analyze_prompt_neutral_for_loan_dispute():
    """H-02, H-04: 개인 간 대여금 분쟁(SC-003) 재분석 시 임차권등기명령/임대인/보증금 등 임대차 하드코딩이 프롬프트에 없는지 검증."""
    state: LegalState = {
        "question": "친구에게 5,000만원을 빌려줬는데 갚지 않습니다. 어떻게 회수하나요?",
        "categories": ["민사", "대여금"],
        "case_context": "차용증 작성 완료, 변제기 2023-12-31 경과",
        "statute_search_results": [{
            "source_id": "minbub_598",
            "statute_name": "민법",
            "article": "제598조",
            "content": "소비대차는 당사자 일방이 금전 기타 대체물의 소유권을 상대방에게 이전할 것을 약정하고...",
        }],
        "revision_count": 0,
    }

    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get:
        mock_llm = MagicMock()
        captured_prompt = None
        def mock_invoke(p):
            nonlocal captured_prompt
            captured_prompt = str(p)
            return MagicMock(content="[1. 핵심 결론]\n대여금 반환 청구가 가능합니다.\n[2. 지금 해야 할 일]\n지급명령 신청")
        mock_llm.invoke.side_effect = mock_invoke
        mock_get.return_value = mock_llm

        re_analyze_node(state)

        assert captured_prompt is not None
        assert "임차권등기명령" not in captured_prompt
        assert "임대인 본인에게 내용증명" not in captured_prompt
        assert "민법" in captured_prompt
        assert "대여금" in captured_prompt

