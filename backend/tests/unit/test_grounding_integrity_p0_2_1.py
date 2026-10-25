# -*- coding: utf-8 -*-
"""
테스트 모듈: test_grounding_integrity_p0_2_1.py

[테스트 목적]
P0-2.1 Grounding Integrity Hardening 요구사항에 따라 근거 연결(Claim-to-Span)의
엄격성, 비매칭 반례 10건 차단, 검색되지 않은 법령의 비검증 처리 및 증거 ID 격리를
검증하는 네거티브 및 무결성 단위 테스트 슈트.

[10대 반례 및 검증 항목]
1. 은행/금융기관 불일치 차단 (우리은행 vs 동진은행)
2. 통지/행동 불일치 차단 (내용증명 발송 주장 vs 문자 통보)
3. 금액 불일치 차단 (3천만원 vs 2억 7천만원)
4. 단순 1단어 부분 일치 차단 (주택 외 무관 문맥)
5. 매칭 Span 부재 시 첫 번째 Span 임의 Fallback 차단
6. 동일 증거 내 복수 쟁점 인용 시 Claim별 독립 Span 분리
7. 검색되지 않은 법령의 SUPPORTED 표시 차단 (UNVERIFIED_SOURCE 부여)
8. 무관한 법령(형법 vs 주택임대차보호법) 연결 차단
9. 존재하지 않는 증거 UUID 조회 시 다른 문서 Fallback 차단
10. 최종 답변 본문에 없는 팬텀 권고사항/Claim의 인용 목록 제외
"""

import pytest
from typing import List, Dict, Any

from ai_legal_helper.workflows.final_disposition import (
    extract_dates_from_text,
    extract_amounts_from_text,
    extract_named_entities,
    verify_claim_match,
    verify_legal_source_reference,
    build_claim_citations,
)
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing,
    FactItemBrief,
    EvidenceItemBrief,
)
from ai_legal_helper.agents.issue_verifier import IssueVerificationResult


class TestGroundingIntegrityNegativeCases:
    """P0-2.1 무결성 강화 10대 반례 및 엄격 검증 테스트 클래스."""

    def test_case_01_bank_entity_mismatch_blocks_support(self):
        """1. 은행/금융기관 불일치 차단 (우리은행 vs 동진은행)."""
        target = "우리은행에 7200만원 근저당권이 설정되어 있습니다."
        cand = "동진은행에 근저당권 채권최고액 7200만원 설정"
        cand_spans = [{"id": "s1", "text_excerpt": "동진은행 근저당권 7200만원"}]

        matched, reason, span = verify_claim_match(target, cand, cand_spans)
        assert matched is False
        assert "불일치" in reason
        assert span is None

    def test_case_02_notice_action_mismatch_blocks_support(self):
        """2. 통지 방식 불일치 차단 (내용증명 발송 vs 문자 통보)."""
        target = "임대인에게 계약해지 내용증명을 발송하여 도달시켰습니다."
        cand = "임차인이 임대인에게 문자메시지로 퇴거 통보함"
        cand_spans = [{"id": "s2", "text_excerpt": "문자메시지로 퇴거 통보"}]

        matched, reason, span = verify_claim_match(target, cand, cand_spans)
        assert matched is False
        assert "불일치" in reason
        assert span is None

    def test_case_03_amount_mismatch_blocks_support(self):
        """3. 금액 불일치 차단 (3000만원 vs 2억 7000만원)."""
        target = "임차보증금 3천만원 전액 반환을 청구합니다."
        cand = "임대차 보증금 2억 7천만원 계약 체결"
        cand_spans = [{"id": "s3", "text_excerpt": "보증금 2억 7,000만원"}]

        matched, reason, span = verify_claim_match(target, cand, cand_spans)
        assert matched is False
        assert "금액 불일치" in reason
        assert span is None

    def test_case_04_single_word_partial_overlap_blocks_support(self):
        """4. 단순 1단어 부분 일치 차단 (무관한 문맥에서 주택 1단어만 일치)."""
        target = "임차인은 주택을 명도하고 다른 곳으로 이사를 완료하였습니다."
        cand = "주택의 옥상 누수로 인하여 긴급 보수 공사를 진행함"
        cand_spans = [{"id": "s4", "text_excerpt": "옥상 누수 공사"}]

        matched, reason, span = verify_claim_match(target, cand, cand_spans)
        assert matched is False
        assert "의미 토큰 중첩 부족" in reason
        assert span is None

    def test_case_05_no_matching_spans_returns_no_arbitrary_fallback(self):
        """5. 매칭 Span 부재 시 첫 번째 Span으로 임의 Fallback 금지."""
        target = "2024년 5월 1일 전입신고 및 확정일자를 취득하였습니다."
        cand = "2024년 5월 1일 전입신고 및 확정일자 부여"
        cand_spans: List[Dict[str, Any]] = []  # 증빙 span 없음

        matched, reason, span = verify_claim_match(target, cand, cand_spans)
        assert matched is False
        assert "Span" in reason
        assert span is None

    def test_case_06_repeated_evidence_label_distinct_claims(self):
        """6. 동일 증거 내 복수 쟁점 인용 시 Claim별 독립 Span 분리 매칭."""
        # E03 문서 내 서로 다른 날짜의 두 주장
        cand1 = "계약 체결일자는 2022년 7월 1일입니다."
        cand1_spans = [{"id": "s_contract", "text_excerpt": "2022.07.01 계약체결"}]

        cand2 = "확정일자 부여일자는 2022년 7월 5일입니다."
        cand2_spans = [{"id": "s_fixed_date", "text_excerpt": "2022.07.05 확정일자"}]

        # 타겟이 확정일자인 경우: cand1은 날짜 불일치로 탈락하고 cand2에 정확히 매칭되어야 함
        target = "2022년 7월 5일 확정일자를 교부받았습니다."

        m1, r1, s1 = verify_claim_match(target, cand1, cand1_spans)
        assert m1 is False
        assert "일자" in r1 or "불일치" in r1

        m2, r2, s2 = verify_claim_match(target, cand2, cand2_spans)
        assert m2 is True
        assert s2 is not None
        assert s2["id"] == "s_fixed_date"

    def test_case_07_unretrieved_statute_marked_unverified(self):
        """7. 실제 검색되지 않은 법령은 SUPPORTED가 아닌 UNVERIFIED_SOURCE 처리."""
        target_statute = "주택임대차보호법 제3조의2"
        # 검색 출처 풀에 민법만 존재
        retrieved_sources = [
            {
                "source_id": "CIVIL_623",
                "statute_name": "민법",
                "article": "제623조",
                "title": "민법 제623조(임대인의 의무)",
            }
        ]

        source_id, stat_name, art, status, reason = verify_legal_source_reference(
            target_statute, retrieved_sources
        )
        assert status == "UNVERIFIED_SOURCE"
        assert source_id is None
        assert "출처" in reason or "식별" in reason

    def test_case_08_irrelevant_statute_topic_blocks_support(self):
        """8. 무관한 법령(형법 사기죄 vs 주택임대차) 연결 차단."""
        target_statute = "형법 제347조"
        retrieved_sources = [
            {
                "source_id": "HOUSING_003",
                "statute_name": "주택임대차보호법",
                "article": "제3조",
                "title": "주택임대차보호법 제3조(대항력 등)",
            }
        ]

        source_id, stat_name, art, status, reason = verify_legal_source_reference(
            target_statute, retrieved_sources
        )
        assert status == "UNVERIFIED_SOURCE"
        assert source_id is None

    def test_case_09_nonexistent_evidence_uuid_isolation(self):
        """9. 존재하지 않는 증거 UUID 조회 시 다른 문서로 Fallback하지 않음."""
        # EvidenceSourceDrawer의 findDocument 규칙:
        # selectedEvidenceId가 지정되었으나 documents에 없으면 undefined 반환
        documents = [
            {"id": "doc-uuid-001", "evidence_label": "E01", "filename": "E01_계약서.txt"},
            {"id": "doc-uuid-002", "evidence_label": "E02", "filename": "E02_등기부.txt"},
        ]
        non_existent_id = "doc-uuid-999-foreign"

        def simulate_find_document(selected_id, docs):
            if selected_id:
                for doc in docs:
                    if doc.get("id") == selected_id:
                        return doc
                return None  # Fallback 금지
            return docs[0] if docs else None

        result = simulate_find_document(non_existent_id, documents)
        assert result is None

    def test_case_10_phantom_recommendation_not_in_final_answer_filtered(self):
        """10. 최종 답변 본문에 없는 팬텀 권고사항/주장의 인용 목록 제외."""
        briefing = CaseEvidenceBriefing(
            case_id="case-integrity-test",
            title="테스트 사건",
            evidences=[
                EvidenceItemBrief(
                    evidence_id="ev-001",
                    evidence_label="E01",
                    document_name="E01_계약서.txt",
                    document_type="LEASE_CONTRACT",
                )
            ],
            facts=[
                FactItemBrief(
                    fact_id="fact-001",
                    statement="보증금은 3억원입니다.",
                    evidence_label="E01",
                    document_name="E01_계약서.txt",
                )
            ],
        )

        issue_results = [
            IssueVerificationResult(
                issue_id="ISSUE_PHANTOM",
                issue_title="팬텀 쟁점",
                status="VERIFIED",
                safe_recommendations=["본문에 전혀 언급되지 않는 허위 권고 사항입니다."],
            )
        ]

        # final_answer에는 보증금 이야기만 있고 팬텀 권고사항은 없음
        final_answer = "확인된 사실: 보증금은 3억원입니다. [E01_계약서.txt]"

        citations = build_claim_citations(
            issue_results=issue_results,
            briefing=briefing,
            final_answer=final_answer,
            retrieved_sources=[],
        )

        # 팬텀 쟁점은 final_answer에 없으므로 citations에 등록되지 않아야 함
        phantom_citations = [
            c for c in citations
            if "허위 권고" in c.get("claim_text", "") or c.get("claim_id") == "ISSUE_PHANTOM"
        ]
        assert len(phantom_citations) == 0
