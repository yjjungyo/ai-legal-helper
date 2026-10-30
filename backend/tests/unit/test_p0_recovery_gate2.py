"""
Gate 2: 사용자 답변 품질 복구 (P0-03 & P0-04) 단위 테스트 스위트

테스트 대상:
1. R11: 동일 보증금 표현 다수(계약서, 송금내역, 영수증 등) -> 의미론적 중복 제거 및 대표 사실 1개 선별 검증
2. R12: ClaimCitation 빈 참조 -> 빈 인용(', , , ,') 및 빈 괄호('[]') 미표시 검증
3. R13: 동일 증거 다중 인용 -> 참고 출처 목록 중복 제거 검증
4. R14: 증거 라벨/파일명 -> 실제 증거 식별자 및 원본 파일명 정확한 매핑 확인
5. R15: 일반 미반환 질문 -> 행동 권고 3~5개 제한 및 우선순위(대항력 유지 -> 내용증명 -> 임차권등기 -> 사법절차) 검증
6. R16: 경매 미개시 사건 -> 경매 배당 관련 조치 미출력 검증
7. R17: 일부 반환 증거 추가 시 -> 미반환 잔액과 권고 일치 확인
8. R18: 증거 등록 순서 변경 -> 법률 결론 및 핵심 요건사실 불변 확인
9. R19: 다른 사건으로 전환 시 -> 이전 사건의 사실·출처 혼입 배제(사건 격리) 검증
"""

import pytest
from typing import List, Dict, Any

from ai_legal_helper.workflows.final_disposition import (
    assemble_grounded_answer,
    select_grounded_facts_for_display,
    build_claim_citations,
    _extract_semantic_fact_key,
)
from ai_legal_helper.agents.verification import sanitize_unverified_citations
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing,
    FactItemBrief,
    EvidenceItemBrief,
    EvidenceGapBrief,
)
from ai_legal_helper.agents.issue_verifier import IssueVerificationResult


@pytest.fixture
def base_scenario_gate2():
    """Gate 2 기준 표준 전세보증금 미반환 사건 픽스처."""
    briefing = CaseEvidenceBriefing(
        case_id="case_gate2_std",
        title="전세보증금 2억 2천만 원 미반환 사건",
        facts=[
            FactItemBrief(
                fact_id="f_lease",
                statement="임대차보증금은 220,000,000원이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
                document_name="E01_주택임대차계약서.pdf",
            ),
            FactItemBrief(
                fact_id="f_transfer",
                statement="보증금 2억 2천만 원을 임대인 계좌로 전액 송금 완료하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
                document_name="E02_계좌이체확인증.pdf",
            ),
            FactItemBrief(
                fact_id="f_receipt",
                statement="임대인은 220000000원 영수증을 발행하여 수령을 확인하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
                document_name="E03_보증금영수증.pdf",
            ),
            FactItemBrief(
                fact_id="f_period",
                statement="계약기간은 2024.09.01부터 2026.08.31까지 24개월이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
                document_name="E01_주택임대차계약서.pdf",
            ),
            FactItemBrief(
                fact_id="f_oppo",
                statement="주민등록 전입신고 및 주택 인도와 확정일자를 부여받아 대항력을 취득하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E04",
                document_name="E04_주민등록초본_확정일자.pdf",
            ),
            FactItemBrief(
                fact_id="f_notice",
                statement="임대인에게 계약 종료 3개월 전 해지 통지 문자를 발송하였고 임대인이 확인했다고 회신하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E05",
                document_name="E05_계약해지_문자내역.pdf",
            ),
        ],
        evidences=[
            EvidenceItemBrief(evidence_id="ev_01", evidence_label="E01", document_name="E01_주택임대차계약서.pdf", document_type="CONTRACT"),
            EvidenceItemBrief(evidence_id="ev_02", evidence_label="E02", document_name="E02_계좌이체확인증.pdf", document_type="BANK_TRANSFER"),
            EvidenceItemBrief(evidence_id="ev_03", evidence_label="E03", document_name="E03_보증금영수증.pdf", document_type="RECEIPT"),
            EvidenceItemBrief(evidence_id="ev_04", evidence_label="E04", document_name="E04_주민등록초본_확정일자.pdf", document_type="RESIDENCE"),
            EvidenceItemBrief(evidence_id="ev_05", evidence_label="E05", document_name="E05_계약해지_문자내역.pdf", document_type="MESSENGER"),
        ],
        source_registry={
            "E01": {"evidence_id": "ev_01", "document_name": "E01_주택임대차계약서.pdf"},
            "E02": {"evidence_id": "ev_02", "document_name": "E02_계좌이체확인증.pdf"},
            "E03": {"evidence_id": "ev_03", "document_name": "E03_보증금영수증.pdf"},
            "E04": {"evidence_id": "ev_04", "document_name": "E04_주민등록초본_확정일자.pdf"},
            "E05": {"evidence_id": "ev_05", "document_name": "E05_계약해지_문자내역.pdf"},
        },
        evidence_gaps=[
            EvidenceGapBrief(
                gap_id="gap_01",
                gap_type="REGISTRY_GAP",
                target_proposition="최신 부동산 등기사항전부증명서",
                recommended_action="인터넷등기소 최신 말소사항포함 등기부 열람",
                priority="권장",
            )
        ],
    )
    return briefing


def test_r11_duplicate_deposit_expressions_merged_to_single_representative_fact(base_scenario_gate2):
    """R11: 동일 보증금 표현 3개(계약서, 송금내역, 영수증)가 의미론적 중복 제거를 통해 대표 사실 하나로 선별되는지 검증."""
    briefing = base_scenario_gate2
    selected = select_grounded_facts_for_display(briefing, query="보증금 2억 2천 얼마 돌려받나요?", max_facts=5)

    # 1. 반환된 사실 개수가 5개 이하인지 확인
    assert len(selected) <= 5

    # 2. 보증금 관련 사실은 오직 1건만 선별되었는지 확인 (동일 금액 그룹화 검증)
    deposit_facts = [
        f for f in selected
        if any(w in f.statement for w in ("220,000,000", "2억 2천", "220000000"))
    ]
    assert len(deposit_facts) == 1, f"Expected 1 deposit fact but got {len(deposit_facts)}: {[f.statement for f in deposit_facts]}"

    # 3. assemble_grounded_answer에서도 보증금 진술문이 중복 3회 반복되지 않고 1회만 노출되는지 확인
    answer = assemble_grounded_answer(
        issue_results=[],
        briefing=briefing,
        draft_answer="보증금 반환 문의",
        disposition="DELIVERED",
    )
    # [2. 판단 근거 (핵심 사실)] 섹션 추출
    assert "[2. 판단 근거 (핵심 사실)]" in answer
    facts_section = answer.split("[2. 판단 근거 (핵심 사실)]")[1].split("[3. 우선 행동 가이드]")[0]
    count_deposit_in_facts = facts_section.count("220,000,000") + facts_section.count("2억 2천") + facts_section.count("220000000")
    assert count_deposit_in_facts == 1


def test_r12_claim_citation_empty_reference_eliminates_empty_commas():
    """R12: ClaimCitation 빈 참조 또는 미검증 라벨 치환 시 빈 인용(', , , ,') 및 빈 브래킷이 원천 제거되는지 검증."""
    raw_draft = (
        "임대차계약은 기간 만료로 종료되었습니다.\n"
        "  * 관련 증거: [E01], , [미등록], , , \n"
        "  * 적용 법령: 주택임대차보호법 제3조, \n"
        "임대인의 반환 채무는 이행기에 도달했습니다 [].\n"
        "  * 관련 증거: , , , , \n"
    )
    cleaned = sanitize_unverified_citations(
        answer=raw_draft,
        retrieved_sources=[{"evidence_label": "E01", "document_name": "계약서.pdf"}],
        case_context="사건 컨텍스트",
    )

    # 연속 쉼표 ', ,' 미존재 확인
    assert ", ," not in cleaned
    assert ",," not in cleaned
    # 콜론 바로 뒤 쉼표 ': ,' 미존재 확인
    assert ": ," not in cleaned
    # 빈 브래킷 '[]' 미존재 확인
    assert "[]" not in cleaned
    # 빈 증거 행 '관련 증거:' 단독 또는 쉼표만 남은 행 미존재 확인
    assert "* 관련 증거: ," not in cleaned
    assert "관련 증거: \n" not in cleaned


def test_r13_multiple_citations_of_same_evidence_has_no_duplicates_in_sources(base_scenario_gate2):
    """R13: 여러 쟁점에서 동일 증거가 중복 인용되더라도 [6. 참고 법률 및 증거 출처] 목록에 중복이 없는지 검증."""
    briefing = base_scenario_gate2
    issue1 = IssueVerificationResult(
        issue_id="ISSUE_TERMINATION",
        issue_title="계약 기간 만료 종료",
        status="VERIFIED",
        supported_source_ids=["E01", "E05"],
        supported_statute_ids=["주택임대차보호법 제6조"],
        safe_recommendations=["계약은 확정적으로 종료되었습니다."],
    )
    issue2 = IssueVerificationResult(
        issue_id="ISSUE_OPPOSABILITY",
        issue_title="대항력 및 우선변제권 유지",
        status="VERIFIED",
        supported_source_ids=["E01", "E04"],
        supported_statute_ids=["주택임대차보호법 제3조", "주택임대차보호법 제6조"],
        safe_recommendations=["대항력을 계속 유지해야 합니다."],
    )

    answer = assemble_grounded_answer(
        issue_results=[issue1, issue2],
        briefing=briefing,
        draft_answer="초안",
        disposition="DELIVERED",
    )

    assert "[6. 참고 법률 및 증거 출처]" in answer
    sources_section = answer.split("[6. 참고 법률 및 증거 출처]")[1]

    # 계약서가 2회 이상 중복 등록되지 않았는지 확인
    assert sources_section.count("[E01_주택임대차계약서.pdf]") == 1
    # 법령도 중복 없이 1회만 표시되었는지 확인
    assert sources_section.count("주택임대차보호법 제6조") == 1


def test_r14_evidence_label_accurately_maps_to_registered_document_name(base_scenario_gate2):
    """R14: 증거 라벨 E01~E05가 실제 등록된 고유 파일명으로 정확히 매핑되는지 확인."""
    briefing = base_scenario_gate2
    selected = select_grounded_facts_for_display(briefing, max_facts=5)

    for f in selected:
        assert f.document_name is not None
        assert f.document_name.endswith(".pdf")
        assert f.evidence_label in ("E01", "E02", "E03", "E04", "E05")

    # assemble_grounded_answer 인용에도 실제 파일명이 기본 인용명으로 표기
    ans = assemble_grounded_answer(
        issue_results=[],
        briefing=briefing,
        draft_answer="초안",
        disposition="DELIVERED",
    )
    assert "[E01_주택임대차계약서.pdf]" in ans or "[E04_주민등록초본_확정일자.pdf]" in ans


def test_r15_standard_unreturned_deposit_restricts_actions_to_3_to_5_prioritized(base_scenario_gate2):
    """R15: 일반 미반환 질문 시 행동 권고가 3~5개로 엄격히 제한되고 우선순위가 준수되는지 검증."""
    briefing = base_scenario_gate2
    answer = assemble_grounded_answer(
        issue_results=[],
        briefing=briefing,
        draft_answer="계약이 끝났는데 집주인이 전세보증금 2억 2천만 원을 주지 않습니다. 어떤 조치를 해야 하나요?",
        disposition="DELIVERED",
        current_question="계약이 끝났는데 집주인이 전세보증금 2억 2천만 원을 주지 않습니다. 어떤 조치를 해야 하나요?",
    )

    assert "[3. 우선 행동 가이드]" in answer
    action_section = answer.split("[3. 우선 행동 가이드]")[1].split("[4. 미확인 사항 및 주의사항]")[0]

    # 번호 항목(1. 2. 3. ...) 파싱
    import re
    action_items = re.findall(r"^\d+\.\s*(.+)$", action_section, flags=re.MULTILINE)

    # 1. 행동 항목 수가 3~5개 사이인지 검증 (과잉 12~14개 완전 배제)
    assert 3 <= len(action_items) <= 5, f"Expected 3~5 actions, got {len(action_items)}"

    # 2. 1순위: 대항력 및 점유 절대 유지
    assert "점유" in action_items[0] and ("상실" in action_items[0] or "유지" in action_items[0])

    # 3. 2순위: 내용증명 발송 (이행최고)
    assert "내용증명" in action_items[1]

    # 4. 3순위: 임차권등기명령 신청
    assert "임차권등기명령" in action_items[2]


def test_r16_no_auction_case_strictly_excludes_auction_dividend_action(base_scenario_gate2):
    """R16: 경매가 개시되지 않은 일반 사건에서 무관한 '경매 배당요구 종기 확인' 조치가 출력되지 않는지 검증."""
    briefing = base_scenario_gate2  # 경매 언급이 전혀 없는 일반 사건
    answer = assemble_grounded_answer(
        issue_results=[],
        briefing=briefing,
        draft_answer="보증금 돌려받는 절차 질문",
        disposition="DELIVERED",
        current_question="보증금 언제 어떻게 돌려받나요?",
    )

    # 행동 가이드에 경매 배당 관련 과잉 행동이 포함되지 않음을 검증
    action_section = answer.split("[3. 우선 행동 가이드]")[1].split("[4. 미확인 사항 및 주의사항]")[0]
    assert "배당요구 종기" not in action_section
    assert "낙찰자에게 대항" not in action_section
    assert "우선배당받을지 신중히 선택" not in action_section


def test_r17_partial_repayment_reconciles_balance_and_recommendation(base_scenario_gate2):
    """R17: 5,000만 원 일부 반환 확인 시 미반환 잔액 1억 7천만 원과 행동 권고가 정합하게 일치하는지 검증."""
    briefing = base_scenario_gate2
    # 5,000만 원 반환 증거 추가
    briefing.facts.append(
        FactItemBrief(
            fact_id="f_part_repay",
            statement="임대인이 의뢰인에게 50,000,000원을 일부 반환하여 입금되었다.",
            adjudication_status="EVIDENCE_SUPPORTED",
            evidence_label="E06",
            document_name="E06_일부반환입금내역.pdf",
        )
    )
    briefing.evidences.append(
        EvidenceItemBrief(evidence_id="ev_06", evidence_label="E06", document_name="E06_일부반환입금내역.pdf", document_type="BANK_TRANSFER")
    )
    briefing.source_registry["E06"] = {"evidence_id": "ev_06", "document_name": "E06_일부반환입금내역.pdf"}

    answer = assemble_grounded_answer(
        issue_results=[],
        briefing=briefing,
        draft_answer="일부만 받았는데 나머지는 어떻게 하나요?",
        disposition="DELIVERED",
        current_question="일부만 받았는데 나머지는 어떻게 하나요?",
    )

    # 잔액 1억 7천만 원이 핵심 결론 또는 행동 가이드에 반영되어 있는지 검증
    assert "1억 7,000만 원" in answer or "1억 7천" in answer or "170,000,000" in answer


def test_r18_evidence_registration_order_change_preserves_legal_determinations(base_scenario_gate2):
    """R18: 증거 목록의 등록 순서를 역순으로 변경해도 동일한 법률 결론 및 핵심 사실이 도출되는지 확인."""
    briefing_orig = base_scenario_gate2

    # 증거 및 사실 순서를 역순으로 뒤집은 새 브리핑 생성
    briefing_reversed = CaseEvidenceBriefing(
        case_id="case_gate2_reversed",
        title=briefing_orig.title,
        facts=list(reversed(briefing_orig.facts)),
        evidences=list(reversed(briefing_orig.evidences)),
        source_registry=briefing_orig.source_registry,
        evidence_gaps=briefing_orig.evidence_gaps,
    )

    selected_orig = select_grounded_facts_for_display(briefing_orig, max_facts=5)
    selected_rev = select_grounded_facts_for_display(briefing_reversed, max_facts=5)

    # 1. 선별된 사실 개수가 동일함
    assert len(selected_orig) == len(selected_rev)

    # 2. 선별된 의미론적 요건사실 키 집합이 순서와 무관하게 100% 동일함
    keys_orig = {_extract_semantic_fact_key(f.statement) for f in selected_orig}
    keys_rev = {_extract_semantic_fact_key(f.statement) for f in selected_rev}
    assert keys_orig == keys_rev


def test_r19_case_switching_guarantees_strict_fact_and_source_isolation(base_scenario_gate2):
    """R19: 사건 A(마포 오피스텔 2억 2천)에서 사건 B(서초 아파트 5억)로 전환 시 상호 사실·출처가 일절 혼입되지 않는지 검증."""
    briefing_a = base_scenario_gate2

    briefing_b = CaseEvidenceBriefing(
        case_id="case_b_seocho",
        title="서초 래미안 아파트 5억 원 전세보증금 반환 사건",
        facts=[
            FactItemBrief(
                fact_id="fb_01",
                statement="임대차 목적물은 서울 서초구 서초동 래미안아파트 101동 502호이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
                document_name="래미안_임대차계약서.pdf",
            ),
            FactItemBrief(
                fact_id="fb_02",
                statement="임대차 보증금은 500,000,000원(5억 원)이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
                document_name="래미안_임대차계약서.pdf",
            ),
        ],
        evidences=[
            EvidenceItemBrief(evidence_id="ev_b1", evidence_label="E01", document_name="래미안_임대차계약서.pdf", document_type="CONTRACT"),
        ],
        source_registry={"E01": {"evidence_id": "ev_b1", "document_name": "래미안_임대차계약서.pdf"}},
    )

    ans_a = assemble_grounded_answer(
        issue_results=[],
        briefing=briefing_a,
        draft_answer="초안",
        disposition="DELIVERED",
    )
    ans_b = assemble_grounded_answer(
        issue_results=[],
        briefing=briefing_b,
        draft_answer="초안",
        disposition="DELIVERED",
    )

    # 사건 A 검증
    assert "2억 2천" in ans_a or "220,000,000" in ans_a
    assert "래미안" not in ans_a
    assert "5억" not in ans_a

    # 사건 B 검증
    assert "5억" in ans_b or "500,000,000" in ans_b
    assert "래미안_임대차계약서.pdf" in ans_b
    assert "2억 2천" not in ans_b
    assert "E01_주택임대차계약서.pdf" not in ans_b


def test_verify_legal_source_reference_handles_none_fields():
    """출처 메타데이터 내 statute_name, title, article 등이 None이어도 TypeError 없이 정상 처리되는지 검증."""
    from ai_legal_helper.workflows.final_disposition import verify_legal_source_reference

    sources_with_none = [
        {
            "source_id": "test_src_1",
            "statute_name": None,
            "title": None,
            "article": None,
            "content": None,
        },
        {
            "source_id": "민법_제6조_c1",
            "statute_name": "민법",
            "title": "민법 제6조",
            "article": "제6조",
            "content": "[민법] 제6조 처분을 허락한 재산",
        },
    ]

    # 1. statute_name=None 인 출처가 포함되어 있어도 오류 없이 판정되어야 함
    s_id, s_name, art, status, exp = verify_legal_source_reference("민법 제6조", sources_with_none)
    assert status == "SUPPORTED"
    assert s_id == "민법_제6조_c1"

    # 2. statute_str 자체가 None 또는 빈 값이어도 TypeError 없이 정상 반환되어야 함
    s_id, s_name, art, status, exp = verify_legal_source_reference(None, sources_with_none)
    assert status == "UNVERIFIED_SOURCE"

