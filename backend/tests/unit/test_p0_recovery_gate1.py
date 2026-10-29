# -*- coding: utf-8 -*-
"""
테스트 모듈: test_p0_recovery_gate1.py

[테스트 목적]
P0 상담 품질 복구 개발지시서 v1.0 Gate 1 (사실 무결성) 전용 검증 테스트 스위트.
R01부터 R10까지 허위 Case Delta 차단, 가공 증거명 배제, 사실-판단 일관성, 모순 방지를 전수 검증한다.

[테스트 대상]
1. R01: 등록 증거 4건, 가압류 사실 부재 시 허위 가압류 델타 생성 0건
2. R02: 사용자 질문에 '가압류' 단어만 언급되어도 가압류 발생 사실 생성 금지
3. R03: resolved_query에 '경매/배당/가압류' 키워드가 삽입되어도 사건 변경 없으면 Delta 없음
4. R04: 최초 상담 시 사건 상태 변화 없으면 Delta 없음 (has_delta == False / None)
5. R05: 후속 상담 시 Fact/Evidence 변경 없으면 Delta 없음
6. R06: 신규 미검증 가압류 구두 주장 시 USER_ALLEGED로 분리 및 가공 등기부 파일명 미생성
7. R07: 신규 검증된 가압류 증거 등록 시 실제 증거 파일명 연결 및 변경사항 정상 생성
8. R08: 실제 등기부 미등록 상태에서 find_case_attachment_evidence_name()의 가짜 등기부명('부동산등기사항전부증명서') 반환 금지
9. R09: 계약 기간 만료 및 임대인 확인 회신 시 계약 종료 유형별 정확한 확정 검증(VERIFIED)
10. R10: 검증 Fact와 법률 결론 상충(종료 확인 vs 종료 불명 모순) 교차 검증 및 차단
"""

import pytest
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing,
    FactItemBrief,
    EvidenceItemBrief,
)
from ai_legal_helper.case_intelligence.settlement_calculator import evaluate_notice_status
from ai_legal_helper.workflows.final_disposition import (
    detect_case_delta,
    find_case_attachment_evidence_name,
    extract_case_attachment_info,
    assemble_grounded_answer,
)
from ai_legal_helper.workflows.issue_planner import LegalIssueTask
from ai_legal_helper.agents.issue_verifier import (
    verify_issue,
    IssueVerificationResult,
)


@pytest.fixture
def base_sc001_briefing() -> CaseEvidenceBriefing:
    """실제 사용자 상담 실패 사례와 동일한 기초 사건 브리핑 픽스처.
    4건의 정식 증거(계약서, 주민등록, 문자, 송금내역)가 등록되어 있으며 가압류는 전혀 없다.
    """
    return CaseEvidenceBriefing(
        case_id="case_p0_recovery_001",
        title="2억 2천만 원 전세보증금 미반환 사건",
        facts=[
            FactItemBrief(
                fact_id="f_lease",
                statement="임대차계약 체결일은 2024년 9월 1일이고, 보증금은 220,000,000원, 임대차 기간은 2024.09.01부터 2026.08.31까지 2년이다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E01",
                document_name="01_주택임대차계약_주요내용.txt",
            ),
            FactItemBrief(
                fact_id="f_movein",
                statement="임차인은 2024년 9월 1일 주택을 인도받고 2024년 9월 2일 전입신고를 마쳤으며 2024년 9월 3일 확정일자를 받았다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E02",
                document_name="02_전입신고_확정일자_입주확인.txt",
            ),
            FactItemBrief(
                fact_id="f_notice_sent",
                statement="임차인은 2026년 6월 10일 임대인에게 계약 종료 및 보증금 반환을 요청하는 문자를 발송하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
                document_name="03_계약종료_통지_문자대화_202606.txt",
            ),
            FactItemBrief(
                fact_id="f_notice_ack",
                statement="임대인이 계약 종료 및 반환 요청을 확인했다는 회신",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
                document_name="03_계약종료_통지_문자대화_202606.txt",
            ),
            FactItemBrief(
                fact_id="f_notice_delay",
                statement="임대인의 보증금 반환 곤란 통보",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E03",
                document_name="03_계약종료_통지_문자대화_202606.txt",
            ),
            FactItemBrief(
                fact_id="f_transfer",
                statement="임차인은 2024년 9월 1일 임대인 계좌로 보증금 220,000,000원을 전액 송금 완료하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                evidence_label="E04",
                document_name="04_최초보증금_임차인송금내역.txt",
            ),
        ],
        evidences=[
            EvidenceItemBrief(
                evidence_id="ev_01",
                evidence_label="E01",
                document_name="01_주택임대차계약_주요내용.txt",
                document_type="CONTRACT",
                status="APPROVED",
            ),
            EvidenceItemBrief(
                evidence_id="ev_02",
                evidence_label="E02",
                document_name="02_전입신고_확정일자_입주확인.txt",
                document_type="RESIDENCE",
                status="APPROVED",
            ),
            EvidenceItemBrief(
                evidence_id="ev_03",
                evidence_label="E03",
                document_name="03_계약종료_통지_문자대화_202606.txt",
                document_type="NOTICE",
                status="APPROVED",
            ),
            EvidenceItemBrief(
                evidence_id="ev_04",
                evidence_label="E04",
                document_name="04_최초보증금_임차인송금내역.txt",
                document_type="FINANCIAL",
                status="APPROVED",
            ),
        ],
        source_registry={
            "E01": {"evidence_id": "ev_01", "document_name": "01_주택임대차계약_주요내용.txt"},
            "E02": {"evidence_id": "ev_02", "document_name": "02_전입신고_확정일자_입주확인.txt"},
            "E03": {"evidence_id": "ev_03", "document_name": "03_계약종료_통지_문자대화_202606.txt"},
            "E04": {"evidence_id": "ev_04", "document_name": "04_최초보증금_임차인송금내역.txt"},
        },
        as_of_date="2026.10.28",
    )


def test_r01_registered_evidences_no_attachment_generates_zero_fake_attachment(base_sc001_briefing):
    """R01: 등록 증거 4건에 가압류가 없는 실제 사안에서 허위 가압류 델타 생성이 0건이어야 한다."""
    has_att, att_date, doc_name, is_verified = extract_case_attachment_info(base_sc001_briefing)
    assert has_att is False
    assert att_date is None
    assert doc_name == ""
    assert is_verified is False

    delta = detect_case_delta(
        briefing=base_sc001_briefing,
        current_question="계약이 끝났는데 집주인이 전세보증금 2억 2천만 원을 주지 않습니다. 어떤 조치를 해야 하나요?",
        resolved_query="",
    )
    assert delta is None


def test_r02_question_mentioning_attachment_does_not_create_attachment_fact(base_sc001_briefing):
    """R02: 사용자 질문에 단순히 '가압류' 단어가 포함(가정적 질문)되더라도 사건에 가압류 발생 사실을 생성하지 않는다."""
    delta = detect_case_delta(
        briefing=base_sc001_briefing,
        current_question="혹시 목적물에 가압류가 생기면 어떻게 대처해야 하나요?",
        resolved_query="가압류 발생 시 일반적 대처 방안",
    )
    # 실제 가압류 증거가 없고 신규 확정 사실도 없으므로 가압류 접수 델타가 생성되어서는 안 됨
    if delta is not None:
        assert not any("가압류 등기 사실 추가 확인" in cf for cf in delta.get("changed_facts", []))
        assert not any("부동산등기사항전부증명서" in cf for cf in delta.get("changed_facts", []))


def test_r03_resolved_query_with_attachment_keywords_generates_no_delta_without_case_change(base_sc001_briefing):
    """R03: resolved_query에 '경매', '배당', '권리순위', '가압류' 등의 키워드가 포함되어도 사건 변경이 없으면 Delta를 생성하지 않는다."""
    delta = detect_case_delta(
        briefing=base_sc001_briefing,
        current_question="보증금을 받기 위해 어떤 법적 조치를 취해야 하나요?",
        resolved_query="임대차계약 종료 후 보증금 반환 청구 및 경매 배당 권리순위 조치 검토",
    )
    assert delta is None


def test_r04_initial_consultation_without_state_change_produces_no_delta(base_sc001_briefing):
    """R04: 최초 상담 시 사건 상태에 어떠한 변경도 없는 경우 delta는 None(또는 has_delta False)이어야 한다."""
    delta = detect_case_delta(
        briefing=base_sc001_briefing,
        conv_context=None,
        current_question="계약이 끝났는데 집주인이 전세보증금 2억 2천만 원을 주지 않습니다. 어떤 조치를 해야 하나요?",
    )
    assert delta is None


def test_r05_followup_consultation_without_fact_evidence_change_produces_no_delta(base_sc001_briefing):
    """R05: 2번째 턴 후속 상담이더라도 Fact나 Evidence의 변경이 없으면 Case Delta를 임의 생성하지 않는다."""
    conv_ctx = {"conversation_id": "conv_123", "turns": [{"turn_index": 1, "question": "보증금 미반환"}]}
    delta = detect_case_delta(
        briefing=base_sc001_briefing,
        conv_context=conv_ctx,
        current_question="내용증명을 보내려면 어떻게 작성해야 하나요?",
    )
    assert delta is None


def test_r06_new_unverified_attachment_allegation_isolated_as_user_alleged(base_sc001_briefing):
    """R06: 의뢰인이 등기부에 가압류가 새로 들어왔다고 명시적으로 구두 주장한 경우 USER_ALLEGED로 분리하고 가짜 등기부명을 날조하지 않는다."""
    delta = detect_case_delta(
        briefing=base_sc001_briefing,
        current_question="등기부에 가압류가 들어왔다는데 제 순위는 어떻게 되나요?",
        resolved_query="신규 가압류 주장에 따른 권리순위 검토",
    )
    assert delta is not None
    assert delta["has_delta"] is True
    # '등기일자 미검증 / 권리순위 미확정' 안내 및 USER_ALLEGED 표기
    assert any("등기일자 미검증 / 권리순위 미확정" in cf for cf in delta["changed_facts"])
    assert any("USER_ALLEGED" in cf for cf in delta["changed_facts"])
    # 가공의 '부동산등기사항전부증명서' 파일명이 인용으로 나타나지 않음
    assert not any("부동산등기사항전부증명서" in cf for cf in delta["changed_facts"])


def test_r07_new_verified_attachment_evidence_produces_grounded_delta(base_sc001_briefing):
    """R07: 신규 검증된 가압류 증거가 등록되었을 때만 실제 등록된 증거 파일명을 연결하여 Delta를 생성한다."""
    # 신규 등기부 증거 및 Fact 추가
    briefing_with_att = base_sc001_briefing.model_copy(deep=True)
    briefing_with_att.evidences.append(
        EvidenceItemBrief(
            evidence_id="ev_05",
            evidence_label="E05",
            document_name="05_부동산등기부_을구_가압류.txt",
            document_type="REGISTRY",
            status="APPROVED",
        )
    )
    briefing_with_att.facts.append(
        FactItemBrief(
            fact_id="f_att_verified",
            statement="2026년 9월 15일 목적물에 채권자 한국자산관리공사의 30,000,000원 가압류 등기가 설정되었다.",
            adjudication_status="EVIDENCE_SUPPORTED",
            evidence_label="E05",
            document_name="05_부동산등기부_을구_가압류.txt",
        )
    )
    briefing_with_att.source_registry["E05"] = {
        "evidence_id": "ev_05",
        "document_name": "05_부동산등기부_을구_가압류.txt",
    }

    delta = detect_case_delta(
        briefing=briefing_with_att,
        current_question="가압류가 등기부에 추가되었는데 제 보증금 순위가 어떻게 되나요?",
    )
    assert delta is not None
    assert delta["has_delta"] is True
    # 실제 등록된 원본 파일명 연결 확인
    assert any("05_부동산등기부_을구_가압류.txt" in cf for cf in delta["changed_facts"])
    assert any("가압류 등기 사실 추가 확인" in cf for cf in delta["changed_facts"])


def test_r08_unregistered_registry_document_returns_empty_name(base_sc001_briefing):
    """R08: 사건에 등기부 문서가 등록되지 않았을 때 find_case_attachment_evidence_name()은 가공의 이름을 반환하지 않고 빈 문자열을 반환한다."""
    doc_name = find_case_attachment_evidence_name(base_sc001_briefing)
    assert doc_name == ""
    assert doc_name != "부동산등기사항전부증명서"


def test_r09_contract_expiry_and_landlord_acknowledgement_verifies_termination(base_sc001_briefing):
    """R09: 계약 기간 만료일(2026.08.31)이 경과하였고 임대인 확인 회신이 존재하는 경우, 종료 여부를 유보하지 않고 VERIFIED로 확정 판정한다."""
    notice_info = evaluate_notice_status(base_sc001_briefing, reference_date="2026.10.28")
    assert notice_info["has_reached"] is True
    assert notice_info["has_landlord_acknowledgement"] is True
    assert notice_info["is_implicit_renewal"] is False

    # 1. ISSUE_LEASE_TERMINATION 검증
    task_term = LegalIssueTask(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="임대차계약 종료 시점 및 효력 발생",
        required_statutes=["주택임대차보호법 제6조"],
        relevant_fact_ids=["f_lease", "f_notice_sent", "f_notice_ack"],
    )
    res_term = verify_issue(
        task_term,
        "계약 만료 종료",
        base_sc001_briefing,
        [{"source_id": "s1", "source_type": "STATUTE", "source_law": "주택임대차보호법", "title": "주택임대차보호법 제6조", "content": "제6조"}],
    )
    assert res_term.status == "VERIFIED"
    assert "TERMINATION_FACTS_AND_LAW_SUPPORTED" in res_term.reason_codes

    # 2. ISSUE_NOTICE_REACH 검증
    task_reach = LegalIssueTask(
        issue_id="ISSUE_NOTICE_REACH",
        issue_title="문자메시지에 의한 해지의사표시 도달 및 효력",
        required_statutes=["주택임대차보호법 제6조", "민법 제111조"],
        relevant_fact_ids=["f_notice_sent", "f_notice_ack"],
    )
    res_reach = verify_issue(
        task_reach,
        "도달 검증",
        base_sc001_briefing,
        [
            {"source_id": "s1", "source_type": "STATUTE", "source_law": "주택임대차보호법", "title": "주택임대차보호법 제6조", "content": "제6조"},
            {"source_id": "s2", "source_type": "STATUTE", "source_law": "민법", "title": "민법 제111조", "content": "제111조"},
        ],
    )
    assert res_reach.status == "VERIFIED"
    assert "NOTICE_REACH_FACTS_AND_LAW_SUPPORTED" in res_reach.reason_codes


def test_r10_verified_facts_and_determinations_eliminate_contradictions(base_sc001_briefing):
    """R10: 한 응답 내에서 '계약 종료 확인'과 '계약 종료 여부 미확인/유보'가 상충 공존하지 않도록 교차 검증 및 모순을 배제한다."""
    verified_issue = IssueVerificationResult(
        issue_id="ISSUE_LEASE_TERMINATION",
        issue_title="임대차계약 종료 시점 및 보증금 반환의무 발생",
        status="VERIFIED",
        safe_recommendations=["임대차계약 기간이 만료되어 보증금 2억 2천만 원 반환 채무는 확정적으로 이행기에 도달하였습니다."],
        supported_source_ids=["E01", "E03"],
        supported_statute_ids=["주택임대차보호법 제6조"],
    )

    # 과거 결함처럼 조건부 쟁점에서 도달일 미확인으로 계약 종료 여부 유보 문구가 섞여 들어왔을 때
    conditional_issue = IssueVerificationResult(
        issue_id="ISSUE_NOTICE_REACH",
        issue_title="문자메시지에 의한 해지의사표시 도달",
        status="CONDITIONAL",
        safe_recommendations=["해지 통고 발송은 확인되나 상대방 도달 일자가 확인되지 않아, 계약 종료 여부가 조건부 상태입니다."],
        supported_source_ids=["E03"],
        supported_statute_ids=["민법 제111조"],
    )

    answer = assemble_grounded_answer(
        issue_results=[verified_issue, conditional_issue],
        briefing=base_sc001_briefing,
        draft_answer="초안 답변",
        disposition="CAUTIONARY",
        current_question="계약이 끝났는데 보증금을 안 줘요",
    )

    # 동일 답변 내에 '계약 종료 여부가 조건부 상태입니다'라는 상충 모순 문구가 제거/정돈되어야 함
    assert "계약 종료 여부가 조건부 상태입니다" not in answer
    assert "계약 종료 여부는 전혀 확인할 수 없습니다" not in answer
    # 확정된 기간 만료 종료 사실과 정합하게 정돈되어 사용자에게 전달됨
    assert "보증금 2억 2천만 원 반환 채무는 확정적으로 이행기" in answer

