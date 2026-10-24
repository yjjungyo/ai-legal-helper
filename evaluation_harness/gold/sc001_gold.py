# -*- coding: utf-8 -*-
"""
모듈명: sc001_gold.py

[역할]
SC-001 전세보증금 3억 원 미반환 사건의 정답 데이터셋(Gold Dataset) 정의.
개발지시서 Section 4.1(12개 핵심 시나리오 SC01-T01~T12) 및 Section 4.3(8개 변형 시나리오 SC01-V01~V08)을
Section 4.2 GoldCaseScenario 스키마에 맞추어 완벽하게 구성한다.

[설계상 주의]
- 전문가 1차 검토 전이므로 review_status는 개발지시서에 따라 'PROVISIONAL'로 설정한다.
- 허위 권고(이사 먼저 권고, 가압류 방치 등)를 검출하기 위해 prohibited_recommendations를 엄격히 정의한다.
"""

from typing import List, Dict
from evaluation_harness.gold.gold_schema import (
    ExpectedFact,
    ExpectedTimelineEvent,
    ExpectedParty,
    ExpectedIssue,
    ExpectedStatute,
    GoldCaseScenario,
)

# -----------------------------------------------------------------------------
# 공통 기초 데이터 (SC-001 Common Baseline Data)
# -----------------------------------------------------------------------------

COMMON_FACTS: List[ExpectedFact] = [
    ExpectedFact(
        fact_id="F01",
        statement="임대차계약 체결일은 2022년 2월 20일이고, 보증금은 300,000,000원(계약금 30,000,000원, 잔금 270,000,000원), 임대차 기간은 2022.03.01부터 2024.02.29까지 2년이다.",
        fact_category="CONTRACT",
        source_evidence_label="E01",
        is_essential=True,
    ),
    ExpectedFact(
        fact_id="F02",
        statement="임차인은 2022년 2월 20일 계약금 30,000,000원, 2022년 3월 1일 잔금 270,000,000원을 임대인 계좌로 전액 지급 완료하였다.",
        fact_category="PAYMENT",
        source_evidence_label="E02",
        is_essential=True,
    ),
    ExpectedFact(
        fact_id="F03",
        statement="임차인은 2022년 3월 1일 오피스텔에 입주 및 전입신고를 마치고 계약서에 확정일자를 부여받았다.",
        fact_category="RESIDENCE",
        source_evidence_label="E03",
        is_essential=True,
    ),
    ExpectedFact(
        fact_id="F04",
        statement="2024년 2월 29일 만료 당시 쌍방 통지 없이 묵시적 갱신되었으며, 임대차 조건은 종전과 동일하게 유지되었다.",
        fact_category="CONTRACT",
        source_evidence_label="E04",
        is_essential=True,
    ),
    ExpectedFact(
        fact_id="F05",
        statement="임차인은 2026년 4월 1일 임대인에게 2026년 9월 30일 퇴거 및 보증금 3억 원 반환을 요청하는 문자 메시지를 발신하였고 임대인에게 도달하였다.",
        fact_category="NOTICE",
        source_evidence_label="E05",
        is_essential=True,
    ),
    ExpectedFact(
        fact_id="F06",
        statement="임대인은 2026년 5월 20일 신규 세입자 보증금을 먼저 지급하고 부족분은 1년 뒤 지급하겠다는 분할반환을 제안하였다.",
        fact_category="NEGOTIATION",
        source_evidence_label="E06",
        is_essential=True,
    ),
    ExpectedFact(
        fact_id="F07",
        statement="2026년 8월 12일 등기부 갑구에 은행의 가압류(청구금액 72,000,000원)가 기입등기되었다.",
        fact_category="ATTACHMENT",
        source_evidence_label="E09",
        is_essential=True,
    ),
    ExpectedFact(
        fact_id="F08",
        statement="2026년 9월 18일 등기부 갑구에 주택도시보증공사(HUG)의 구상금 가압류(청구금액 120,000,000원)가 기입등기되었다.",
        fact_category="ATTACHMENT",
        source_evidence_label="E10",
        is_essential=True,
    ),
    ExpectedFact(
        fact_id="F09",
        statement="임대인은 2026년 9월 30일 퇴거일 이후에도 보증금 3억 원 전액을 반환하지 않고 있다.",
        fact_category="PAYMENT",
        source_evidence_label="E15",
        is_essential=True,
    ),
    ExpectedFact(
        fact_id="F10",
        statement="임차인은 2026년 10월 15일 기준 열쇠 및 출입카드를 보관하며 목적물 점유 및 주민등록을 유지하고 있다.",
        fact_category="RESIDENCE",
        source_evidence_label="E16",
        is_essential=True,
    ),
]

COMMON_TIMELINE: List[ExpectedTimelineEvent] = [
    ExpectedTimelineEvent(
        event_date="2022-02-20",
        event_type="계약체결 및 계약금 지급",
        description="가람오피스텔 503호 임대차계약 체결 및 계약금 3,000만 원 이체",
        legal_significance="계약성립",
    ),
    ExpectedTimelineEvent(
        event_date="2022-03-01",
        event_type="잔금지급, 입주, 전입신고 및 확정일자",
        description="잔금 2억 7,000만 원 지급, 목적물 인도, 전입신고 및 확정일자 취득",
        legal_significance="대항요건 및 우선변제권 구비 (효력발생일: 2022.03.02 00:00)",
    ),
    ExpectedTimelineEvent(
        event_date="2024-02-29",
        event_type="원 임대차기간 만료",
        description="최초 약정기간 만료 시점에 쌍방 별도 통지 없음",
        legal_significance="주택임대차보호법 제6조 제1항에 의한 묵시적 갱신 성립",
    ),
    ExpectedTimelineEvent(
        event_date="2026-04-01",
        event_type="해지통고 도달",
        description="임차인이 임대인에게 2026.09.30 퇴거 및 3억 원 반환 요청 문자 발신·도달",
        legal_significance="주택임대차보호법 제6조의2 제2항에 따른 계약해지 의사표시",
    ),
    ExpectedTimelineEvent(
        event_date="2026-07-01",
        event_type="법정 해지 효력 발생 시점",
        description="해지통고 도달일(2026.04.01)로부터 3개월 경과 시점",
        legal_significance="법률상 계약 해지 효력 발생일 (지체책임은 임차인 지정일 도과 후 명확화)",
    ),
    ExpectedTimelineEvent(
        event_date="2026-08-12",
        event_type="은행 가압류 등기",
        description="가람오피스텔 503호 등기부 갑구에 은행 가압류 7,200만 원 등기",
        legal_significance="임차인 우선변제권 취득(2022.03.02)보다 후순위 권리",
    ),
    ExpectedTimelineEvent(
        event_date="2026-09-18",
        event_type="HUG 가압류 등기",
        description="가람오피스텔 503호 등기부 갑구에 HUG 가압류 1억 2,000만 원 등기",
        legal_significance="임차인 우선변제권보다 후순위 권리",
    ),
    ExpectedTimelineEvent(
        event_date="2026-09-30",
        event_type="임차인 지정 퇴거일 및 이행기 도래",
        description="임차인이 지정한 반환 기한 도래, 임대인의 보증금 미반환",
        legal_significance="임대인의 보증금 반환의무 이행지체 발생",
    ),
]

COMMON_PARTIES: List[ExpectedParty] = [
    ExpectedParty(name="이수현", role="임차인", contact="010-7254-9142"),
    ExpectedParty(name="박정훈", role="임대인", contact="010-4826-1357"),
    ExpectedParty(name="은행", role="후순위 가압류 채권자", contact=None),
    ExpectedParty(name="주택도시보증공사(HUG)", role="후순위 가압류 채권자", contact=None),
]

COMMON_STATUTES: List[ExpectedStatute] = [
    ExpectedStatute(
        law_name="주택임대차보호법",
        article="제3조 제1항",
        statute_id="주택임대차보호법_제3조_제1항",
        relevance_summary="주택 인도와 주민등록을 마친 때에는 그 다음 날부터 제3자에 대하여 대항력이 생긴다.",
    ),
    ExpectedStatute(
        law_name="주택임대차보호법",
        article="제3조의2 제2항",
        statute_id="주택임대차보호법_제3조의2_제2항",
        relevance_summary="대항요건과 확정일자를 갖춘 임차인은 후순위권리자나 그 밖의 채권자보다 우선하여 보증금을 변제받을 권리가 있다.",
    ),
    ExpectedStatute(
        law_name="주택임대차보호법",
        article="제6조 제1항",
        statute_id="주택임대차보호법_제6조_제1항",
        relevance_summary="기간 만료 6개월~2개월 전까지 갱신거절 통지가 없으면 동일 조건으로 다시 임대차한 것으로 본다 (묵시적 갱신).",
    ),
    ExpectedStatute(
        law_name="주택임대차보호법",
        article="제6조의2",
        statute_id="주택임대차보호법_제6조의2",
        relevance_summary="묵시적 갱신된 경우 임차인은 언제든지 해지를 통지할 수 있고, 임대인이 통지를 받은 날부터 3개월이 지나면 효력이 발생한다.",
    ),
    ExpectedStatute(
        law_name="주택임대차보호법",
        article="제3조의3",
        statute_id="주택임대차보호법_제3조의3",
        relevance_summary="임대차가 끝난 후 보증금을 반환받지 못한 임차인은 임차권등기명령을 신청할 수 있으며, 등기 완료 시 대항력과 우선변제권을 유지한 채 이사할 수 있다.",
    ),
    ExpectedStatute(
        law_name="민법",
        article="제536조",
        statute_id="민법_제536조",
        relevance_summary="임대인의 보증금 반환의무와 임차인의 목적물 인도의무는 동시이행 관계에 있다.",
    ),
]


# -----------------------------------------------------------------------------
# 12개 핵심 시나리오 (Core Scenarios SC01-T01 ~ SC01-T12)
# -----------------------------------------------------------------------------

SC01_T01 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T01",
    question_id="Q01",
    title="전세보증금 미반환 사건 종합 분석 및 대응 전략 개요",
    user_question="전세보증금 3억 원을 아직 돌려받지 못하고 있습니다. 제 상황을 종합적으로 분석해 주고 어떻게 대처해야 하는지 알려주세요.",
    evidence_manifest=["E01", "E02", "E03", "E04", "E05", "E06", "E09", "E10", "E11", "E15", "E16"],
    expected_facts=COMMON_FACTS,
    expected_timeline=COMMON_TIMELINE,
    expected_parties=COMMON_PARTIES,
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_TERMINATION",
            issue_title="임대차계약 종료 여부 및 시점",
            required_statute_names=["주택임대차보호법 제6조의2"],
            substantive_conclusion="2026.04.01 해지통고 후 3개월(2026.07.01) 경과 및 임차인 지정일(2026.09.30) 도과로 계약은 명백히 종료됨.",
        ),
        ExpectedIssue(
            issue_id="ISSUE_PRIORITY",
            issue_title="대항력·우선변제권과 후순위 가압류의 권리관계",
            required_statute_names=["주택임대차보호법 제3조", "주택임대차보호법 제3조의2"],
            substantive_conclusion="2022.03.02 선순위 대항력 및 우선변제권을 취득하여 2026년의 후순위 가압류 2건보다 우선함.",
        ),
        ExpectedIssue(
            issue_id="ISSUE_PRESERVATION",
            issue_title="권리보전을 위한 임차권등기명령 필요성",
            required_statute_names=["주택임대차보호법 제3조의3"],
            substantive_conclusion="보증금을 받기 전 무단 퇴거 시 대항력이 상실되므로 반드시 점유를 유지하거나 임차권등기명령 후 이사해야 함.",
        ),
    ],
    applicable_statutes=COMMON_STATUTES,
    applicable_precedents=["대법원 2002. 2. 26. 선고 2001다77697 판결", "대법원 2008. 3. 13. 선고 2007다77973 판결"],
    required_legal_reasoning=[
        "2022년 최초 계약 후 2024년 묵시적 갱신 상태에서 2026.04.01 해지통고가 도달함",
        "주택임대차보호법 제6조의2 제2항에 따라 통고 도달 후 3개월이 경과한 2026.07.01에 법정 해지 효력이 발생하고, 임차인의 유예·지정 퇴거일인 2026.09.30 도래로 반환 지체 책임 성립",
        "2022.03.02 취득한 대항력·우선변제권은 2026년 등기된 은행 및 HUG 가압류보다 선순위이며, 경매 시 적법한 배당요구를 전제로 매각대금 한도 내에서 가압류 채권자보다 우선배당받고 매각대금 부족 시 낙찰자에게 잔액을 대항·인수시킬 수 있음",
        "보증금을 돌려받지 못한 채 점유를 이탈하면 대항력이 상실되므로 임차권등기명령 전까지 퇴거해서는 안 됨",
    ],
    expected_conclusions=[
        "임대차계약은 법률상 2026년 7월 1일(주임법상 법정 해지 효력 발생) 또는 당사자 지정 퇴거일인 2026년 9월 30일부로 종료되었으며, 임대인은 3억 원 반환 지체 상태입니다.",
        "임차인은 2022년 3월 2일 갖춘 선순위 대항력과 우선변제권으로 후순위 가압류 채권자들보다 앞서며, 경매 시 적법한 배당요구를 전제로 매각대금 범위 내에서 우선배당받고 미배당 잔액은 낙찰자에게 대항하여 전액 회수할 수 있습니다.",
        "현재 점유를 유지해야 하며, 부득이 이사 시 주택임차권등기명령을 완료한 후 퇴거해야 합니다.",
    ],
    acceptable_alternative_conclusions=[
        "2026.07.01(법정 해지일)과 2026.09.30(지정 약정일)의 법률적 차이를 병기 설명하거나, 경매 낙찰가율 및 배당요구 요건을 전제로 회수 구조를 설명하는 답변 유효"
    ],
    required_next_actions=[
        "현재 목적물의 점유와 주민등록(전입)을 철저히 유지할 것",
        "임대인에게 보증금 전액 반환 및 지연손해금 청구 내용증명 발송",
        "관할 법원에 주택임차권등기명령 신청 준비 및 접수",
        "최신 부동산 등기사항전부증명서 발급을 통한 추가 권리변동 확인",
    ],
    conditional_next_actions=[
        "임차권등기 완료 후 지급명령 신청 또는 보증금반환청구소송 제기",
        "강제경매 신청 및 배당요구 여부 검토",
    ],
    prohibited_recommendations=[
        "임차권등기명령 없이 먼저 이사하거나 열쇠를 반환하라는 권고",
        "주민등록(전입)을 다른 곳으로 미리 퇴거 이전하라는 권고",
        "가압류가 걸려 있는 상태에서 담보 없이 임대인의 분할반환 제안을 수용하라는 권고",
    ],
    known_unknowns=["최신 등기부상 추가 권리변동 내역(근저당 등)", "전세대출 반환보증 가입 여부"],
    required_evidence_citations=["E01", "E03", "E05", "E09", "E10", "E16"],
    review_status="PROVISIONAL",
)

SC01_T02 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T02",
    question_id="Q02",
    title="임대차계약 종료 시점 및 묵시적 갱신/해지 효력 발생일 판단",
    user_question="임대차계약이 언제 종료되었다고 볼 수 있나요? 묵시적 갱신 후 해지 효력은 언제 발생했나요?",
    evidence_manifest=["E01", "E04", "E05", "E15"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[3], COMMON_FACTS[4], COMMON_FACTS[8]],
    expected_timeline=[COMMON_TIMELINE[0], COMMON_TIMELINE[1], COMMON_TIMELINE[2], COMMON_TIMELINE[3], COMMON_TIMELINE[4], COMMON_TIMELINE[7]],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_TERMINATION_DATE",
            issue_title="묵시적 갱신 후 해지통고 효력 발생일 산정",
            required_statute_names=["주택임대차보호법 제6조", "주택임대차보호법 제6조의2"],
            substantive_conclusion="2026.04.01 통고 도달 후 3개월이 경과한 2026.07.01에 주임법상 법정 해지 효력이 발생하며, 임차인이 유예하여 지정한 2026.09.30 역시 당사자 간 이행기 및 퇴거 약정일로서 종료 기준이 될 수 있음.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[2], COMMON_STATUTES[3]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "최초 임대차기간(2022.03.01~2024.02.29) 종료 시 주택임대차보호법 제6조에 따라 묵시적 갱신됨",
        "묵시적 갱신 중 임차인은 제6조의2 제1항에 따라 언제든지 계약 해지를 통지할 수 있음",
        "제6조의2 제2항에 따라 임대인이 통지를 받은 날(2026.04.01)로부터 3개월이 지나면 법정 해지 효력이 발생함",
        "따라서 법정 효력 발생일은 2026년 7월 1일이며, 임차인이 유예하여 지정한 2026년 9월 30일 역시 당사자 간 이행기 및 퇴거 약정일로서 계약 종료 기준일이 됨",
    ],
    expected_conclusions=[
        "법률상 계약 해지 효력은 통고 도달일(2026.04.01)로부터 3개월이 경과한 2026년 7월 1일에 발생했습니다.",
        "임차인이 지정한 퇴거 예정일인 2026년 9월 30일 기준으로도 계약은 완전히 종료되었으며 임대인은 반환 지체에 빠졌습니다.",
    ],
    acceptable_alternative_conclusions=[
        "2026년 7월 1일(법정 해지 효력 발생)과 2026년 9월 30일(지정 종료·이행기)의 법률적 의미를 병기하거나 조건부로 설명하는 답변 모두 유효한 결론임."
    ],
    required_next_actions=["계약 종료에 기한 보증금 전액 반환 청구 내용증명 발송", "임차권등기명령 신청 준비"],
    conditional_next_actions=[],
    prohibited_recommendations=["계약이 아직 종료되지 않았으므로 임대인 요구대로 계속 거주해야 한다는 권고", "해지통고 당일(2026.04.01)에 즉시 종료되었다는 잘못된 계산"],
    known_unknowns=[],
    required_evidence_citations=["E01", "E04", "E05"],
    review_status="PROVISIONAL",
)

SC01_T03 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T03",
    question_id="Q03",
    title="해지통고의 도달 및 의사표시 효력 유무",
    user_question="2026년 4월 1일에 보낸 퇴거 및 보증금 반환 요청 문자가 계약 해지로서 법적 효력이 있나요? 집주인에게 도달했다고 볼 수 있나요?",
    evidence_manifest=["E05", "E06", "E07"],
    expected_facts=[COMMON_FACTS[4], COMMON_FACTS[5]],
    expected_timeline=[COMMON_TIMELINE[3]],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_NOTICE_REACH",
            issue_title="문자메시지에 의한 해지의사표시 도달 및 효력",
            required_statute_names=["민법 제111조 제1항", "주택임대차보호법 제6조의2"],
            substantive_conclusion="임차인의 명확한 해지 의사가 기재된 문자가 임대인에게 송달되었고 임대인이 답장하여 내용을 인지하였으므로 도달 효력이 인정됨.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[3]],
    applicable_precedents=["대법원 1998. 2. 13. 선고 97다28657 판결"],
    required_legal_reasoning=[
        "민법 제111조 제1항에 따라 상대방 있는 의사표시는 상대방에게 도달한 때에 효력이 생김",
        "문자메시지(E05)로 2026.09.30 퇴거 및 보증금 반환을 요청하였고, 임대인이 이에 대해 2026.05.20 분할지급 답장(E06) 및 통화(E07)를 하였음",
        "상대방이 내용을 알 수 있는 객관적 상태에 놓였고 실제로 인지하였으므로 해지통고는 2026.04.01부로 유효하게 도달함",
    ],
    expected_conclusions=[
        "문자메시지를 통한 해지 통고는 법적으로 완전히 유효합니다.",
        "임대인의 후속 답장과 통화로 도달 사실이 객관적으로 입증되므로 해지 효력이 확정되었습니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=["문자 발신 내역 및 임대인 답장 캡처본을 증거로 영구 보관", "도달을 더욱 확실히 하기 위한 우체국 내용증명 발송 병행"],
    conditional_next_actions=[],
    prohibited_recommendations=["문자메시지는 아무런 법적 효력이 없으므로 해지가 무효라는 단정"],
    known_unknowns=[],
    required_evidence_citations=["E05", "E06"],
    review_status="PROVISIONAL",
)

SC01_T04 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T04",
    question_id="Q04",
    title="대항력·우선변제권 발생일과 후순위 가압류 2건의 권리 우열 분석",
    user_question="등기부에 은행 7,200만 원, HUG 1억 2,000만 원 가압류가 걸려 있는데, 제 전세보증금 3억 원보다 우선하나요? 제 대항력과 우선변제권 순위는 어떻게 되나요?",
    evidence_manifest=["E01", "E02", "E03", "E09", "E10", "E11"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[1], COMMON_FACTS[2], COMMON_FACTS[6], COMMON_FACTS[7]],
    expected_timeline=[COMMON_TIMELINE[1], COMMON_TIMELINE[5], COMMON_TIMELINE[6]],
    expected_parties=COMMON_PARTIES,
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_PRIORITY_RANKING",
            issue_title="선순위 임차권과 후순위 일반 가압류의 우선순위 비교",
            required_statute_names=["주택임대차보호법 제3조 제1항", "주택임대차보호법 제3조의2 제2항"],
            substantive_conclusion="임차인의 대항요건 및 확정일자는 2022.03.02 00:00에 효력이 발생하였으므로, 2026년 8월 및 9월에 설정된 은행 및 HUG 가압류보다 선순위이며, 경매 시 적법한 배당요구를 전제로 매각대금 한도 내에서 우선변제를 받음.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[0], COMMON_STATUTES[1]],
    applicable_precedents=["대법원 1999. 3. 23. 선고 98다46938 판결"],
    required_legal_reasoning=[
        "임차인은 2022.03.01 입주, 전입신고, 확정일자를 모두 갖춤",
        "주택임대차보호법 제3조 및 제3조의2에 따라 대항력과 우선변제권은 익일인 2022년 3월 2일 0시부터 발생",
        "은행 가압류는 2026년 8월 12일, HUG 가압류는 2026년 9월 18일에 기입등기됨",
        "등기부상 2022.03.02보다 앞선 선순위 근저당권이나 제한물권이 없으므로 임차인은 제1순위 권리자임",
        "경매 시 임차인이 배당요구 종기까지 적법한 배당요구를 신청하면 매각대금 한도 내에서 후순위 가압류 채권자들보다 우선하여 배당받으며, 매각대금 부족 시에도 선순위 대항력으로 낙찰자에게 미배당 잔액을 전액 인수시킬 수 있음",
    ],
    expected_conclusions=[
        "임차인의 보증금 3억 원은 은행 가압류(7,200만 원) 및 HUG 가압류(1억 2,000만 원)보다 법적으로 확고한 선순위 권리입니다.",
        "경매 시 적법한 배당요구를 전제로 매각대금에서 가압류 채권자보다 우선배당받으며, 매각대금 부족 시에도 선순위 대항력으로 낙찰자에게 미배당 잔액을 전액 인수시킬 수 있습니다.",
    ],
    acceptable_alternative_conclusions=[
        "경매 매각대금의 규모, 경매집행비용, 선순위 당해세 유무에 따라 실제 경매 배당 수령액이 달라질 수 있으나, 가압류보다 우선변제권이 앞서며 미배당 잔액은 낙찰자에게 대항하여 회수 가능함."
    ],
    required_next_actions=["현재의 주민등록 및 점유를 계속 유지하여 선순위 권리를 보전할 것", "등기부등본을 발급받아 2022.03.01 이전의 말소기준권리가 없는지 재확인"],
    conditional_next_actions=[],
    prohibited_recommendations=[
        "가압류가 걸렸으므로 임차인 보증금도 손실을 보고 가압류 채권자들과 안분배당된다는 잘못된 조언",
        "가압류를 이유로 전입을 빼거나 포기하라는 권고",
    ],
    known_unknowns=["2022.03.01 이전 등기부 을구 근저당권 유무 최종 확인"],
    required_evidence_citations=["E01", "E03", "E09", "E10", "E11"],
    review_status="PROVISIONAL",
)

SC01_T05 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T05",
    question_id="Q05",
    title="경매 진행 시 배당요구 vs 대항력 유지(임차권 인수) 선택 전략 및 회수 가능성",
    user_question="만약 이 오피스텔이 경매로 넘어가면 배당요구를 해야 하나요, 아니면 배당요구를 하지 않고 낙찰자에게 보증금을 전액 인수시켜야 하나요?",
    evidence_manifest=["E01", "E03", "E09", "E10", "E11", "E16"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[2], COMMON_FACTS[6], COMMON_FACTS[7], COMMON_FACTS[9]],
    expected_timeline=[COMMON_TIMELINE[1], COMMON_TIMELINE[5], COMMON_TIMELINE[6]],
    expected_parties=COMMON_PARTIES,
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_AUCTION_STRATEGY",
            issue_title="선순위 대항력 임차인의 배당요구권과 대항력 선택권",
            required_statute_names=["주택임대차보호법 제3조의5", "민사집행법 제88조"],
            substantive_conclusion="선순위 대항력을 가진 임차인은 경매 시 배당요구를 하여 낙찰대금 범위 내에서 우선배당받거나(부족분은 낙찰자 인수), 배당요구를 하지 않고 낙찰인에게 보증금 반환채무를 전액 인수시킬 수 있는 선택권이 있음.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[0], COMMON_STATUTES[1]],
    applicable_precedents=["대법원 2001. 3. 27. 선고 2000다67417 판결"],
    required_legal_reasoning=[
        "임차인은 말소기준권리보다 앞선 최선순위 대항력자임",
        "주택임대차보호법 제3조의5에 따라 임차권은 임차주택의 경락에 의하여 소멸하나, 보증금이 전액 변제되지 아니한 대항력 있는 임차권은 소멸하지 아니함",
        "전략 1(배당요구): 배당요구종기까지 배당요구 신청하여 경락대금 범위 내에서 1순위로 배당받고 부족분은 낙찰자에게 인수시킴",
        "전략 2(대항력 행사): 배당요구를 하지 않고 낙찰인에게 보증금 3억 원 전액 반환을 청구하고 반환받을 때까지 인도를 거부함",
    ],
    expected_conclusions=[
        "임차인은 최선순위이므로 ① 배당요구 종기 내 배당요구로 경매대금 범위 내에서 1순위 배당(미배당 잔액은 낙찰자 인수)을 받거나, ② 배당요구를 하지 않고 낙찰자에게 3억 원 전액 인수를 요구하는 두 가지 선택권이 모두 있습니다.",
        "시세 대비 보증금 규모를 고려하여, 낙찰가율이 낮을 것으로 예상되면 대항력을 유지하여 낙찰자에게 전액 회수하는 전략이 안전합니다.",
    ],
    acceptable_alternative_conclusions=["낙찰대금 범위에서 신속히 회수하고자 할 때는 배당요구를 선택할 수 있으며 미배당분은 대항 가능."],
    required_next_actions=["경매 개시 결정 시 배당요구 종기일을 확인하고 전략 결정", "오피스텔의 최근 실거래 시세 및 낙찰가율 파악"],
    conditional_next_actions=[],
    prohibited_recommendations=["배당요구를 하지 않으면 보증금을 한 푼도 받지 못하고 쫓겨난다는 허위 경고", "가압류 때문에 배당 순위가 밀린다는 설명"],
    known_unknowns=["오피스텔 현재 감정평가액 및 실거래 시세"],
    required_evidence_citations=["E01", "E03", "E09", "E10", "E11"],
    review_status="PROVISIONAL",
)

SC01_T06 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T06",
    question_id="Q06",
    title="임대차 목적물 인도(이사/퇴거)와 대항력 상실 위험 및 권리보전(임차권등기명령) 조치",
    user_question="새로 이사 갈 집을 알아보고 있는데, 보증금을 받지 못하고 먼저 이사를 나가거나 주민등록을 옮겨도 되나요? 대항력을 유지하려면 무엇을 해야 하나요?",
    evidence_manifest=["E01", "E03", "E16"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[2], COMMON_FACTS[9]],
    expected_timeline=[COMMON_TIMELINE[1]],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_POSSESSION_LOSS",
            issue_title="점유 및 주민등록 이탈 시 대항력 상실과 임차권등기명령의 효력",
            required_statute_names=["주택임대차보호법 제3조 제1항", "주택임대차보호법 제3조의3"],
            substantive_conclusion="보증금을 반환받지 못한 상태에서 무단으로 이사하거나 전입을 옮기면 대항력과 우선변제권이 즉시 상실되므로, 반드시 임차권등기명령을 신청하여 등기부에 기입된 후 퇴거해야 함.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[0], COMMON_STATUTES[4]],
    applicable_precedents=["대법원 2005. 9. 15. 선고 2005다33039 판결"],
    required_legal_reasoning=[
        "주택임대차보호법상 대항력과 우선변제권은 '주택의 인도(점유)'와 '주민등록'이 존속하는 동안만 유지됨",
        "임차권등기 없이 퇴거하거나 전출하면 대항력이 영구히 상실되어 후순위 가압류 채권자들에게 권리를 빼앗기게 됨",
        "주택임대차보호법 제3조의3에 따른 임차권등기가 경료되면, 점유와 주민등록을 이전하더라도 기존의 대항력과 우선변제권 효력이 그대로 유지됨",
    ],
    expected_conclusions=[
        "절대로 보증금을 전액 돌려받기 전이나 임차권등기가 완료되기 전에 먼저 이사를 나가거나 주민등록을 옮겨서는 안 됩니다.",
        "부득이 이사를 가야 한다면 반드시 관할 법원에 임차권등기명령을 신청하여 등기부에 등재된 것을 확인한 후에 퇴거해야 합니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=[
        "현재 목적물의 점유(출입카드/열쇠 소지) 및 전입신고 상태 엄격 유지",
        "관할 법원에 주택임차권등기명령 신청서 접수",
        "등기사항전부증명서 상에 임차권등기 기입 여부 확인 후 이사 계획 확정",
    ],
    conditional_next_actions=[],
    prohibited_recommendations=[
        "보증금을 못 받았어도 이사부터 가고 나중에 청구하라는 권고 (치명적 오류)",
        "짐을 일부 남겨두면 전출해도 대항력이 온전히 유지된다는 위험한 권고",
    ],
    known_unknowns=[],
    required_evidence_citations=["E01", "E03", "E16"],
    review_status="PROVISIONAL",
)

SC01_T07 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T07",
    question_id="Q07",
    title="임대인의 보증금 분할반환 제안 거절 및 전액 일시반환 요구의 법적 근거",
    user_question="집주인이 새 세입자가 들어오면 일부만 먼저 돌려주고 나머지는 1년 뒤에 주겠다고 하는데, 이 제안을 받아들여야 하나요? 거절할 수 있는 법적 근거는 무엇인가요?",
    evidence_manifest=["E01", "E06", "E09", "E10", "E12"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[5], COMMON_FACTS[6], COMMON_FACTS[7]],
    expected_timeline=[COMMON_TIMELINE[3], COMMON_TIMELINE[4], COMMON_TIMELINE[7]],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_INSTALLMENT_PROPOSAL",
            issue_title="임대인의 일방적 분할변제 제안의 구속력 및 위험성",
            required_statute_names=["민법 제468조", "민법 제536조"],
            substantive_conclusion="임대차 종료 시 보증금 전액 반환이 원칙이며, 가압류 2건이 걸린 상태에서 무담보 분할변제 제안을 수용할 법적 의무가 없고 회수 불능 위험이 극도로 큼.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[5]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "임대차계약 종료 시 임대인의 보증금 반환의무는 전액 일시반환이 원칙임",
        "임차인은 민법 제468조 등에 따라 채무자의 일방적 분할변제 제안을 거절하고 전액 변제를 청구할 권리가 있음",
        "해당 부동산에는 이미 은행 7,200만 원 및 HUG 1억 2,000만 원의 가압류가 설정되어 있어 신규 임차인 유치가 사실상 불가능함",
        "담보나 공증 없는 1년 뒤 분할변제 약속은 채권 회수를 지연시키고 부실화시킬 위험이 매우 큼",
    ],
    expected_conclusions=[
        "임대인의 분할반환 제안은 법적 강제력이 없으므로 단호히 거절하고 전액 일시반환을 요구해야 합니다.",
        "이미 가압류 2건이 설정되어 신규 세입자 유치가 어려우며, 담보 없는 분할 약속은 보증금 미회수 위험만 키웁니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=[
        "임대인에게 분할반환 제안 거절 및 3억 원 전액 일시반환 촉구 통보",
        "지급명령 또는 보증금반환청구 소송 등 법적 강제집행 절차 착수",
    ],
    conditional_next_actions=["만약 합의할 경우 별도의 확실한 물적 담보(타 부동산 근저당 등) 제공을 필수 조건으로 요구"],
    prohibited_recommendations=["임대인 사정이 어려우니 분할반환 제안을 무조건 수용하고 기다리라는 권고"],
    known_unknowns=[],
    required_evidence_citations=["E01", "E06", "E09", "E10"],
    review_status="PROVISIONAL",
)

SC01_T08 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T08",
    question_id="Q08",
    title="권리관계 미확인 사항(등기부등본 열람, 보증보험 가입 여부) 보완 요구",
    user_question="제가 가진 서류만으로 법적 절차를 진행할 수 있나요? 추가로 확인하거나 발급받아야 할 서류가 무엇인가요?",
    evidence_manifest=["E09", "E10", "E11", "E17"],
    expected_facts=[COMMON_FACTS[6], COMMON_FACTS[7]],
    expected_timeline=[],
    expected_parties=COMMON_PARTIES,
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_EVIDENCE_GAPS",
            issue_title="소송 및 보전처분을 위한 필수 증빙 서류 보완",
            required_statute_names=["주택임대차보호법 제3조의3", "민사소송법 제202조"],
            substantive_conclusion="현재 등기 메모(E09~E11)만으로는 법원 접수가 어려우므로 공식 인터넷등기소 발급 등기사항전부증명서와 전세대출 보증보험 확인이 필수적임.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[4]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "임차권등기명령 및 본안소송 신청 시 법원에 공식 부동산 등기사항전부증명서(말소사항 포함)를 제출해야 함",
        "기존 자료는 열람 메모 형태이므로 접수일 기준 최신 공적 등기부등본 발급이 필수임",
        "전세대출 약정서상 주택도시보증공사(HUG)나 SGI서울보증의 반환보증 가입 여부(E17)를 최종 확인하여 보증이행청구 가능 여부를 타진해야 함",
    ],
    expected_conclusions=[
        "공식 법적 절차를 위해 대법원 인터넷등기소에서 최신 '부동산 등기사항전부증명서(말소사항 포함)'를 즉시 발급받아야 합니다.",
        "대출 취급 은행에 문의하여 전세대출 보증보험(반환보증) 가입 여부를 최종 확인해야 합니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=[
        "대법원 인터넷등기소에서 가람오피스텔 503호 등기사항전부증명서 발급",
        "거래은행 전세대출 담당자에게 반환보증 가입 여부 확인 공문/문서 요청",
        "임대차계약서 원본, 주민등록초본(전입변동이력 포함), 확정일자 부여현황 준비",
    ],
    conditional_next_actions=[],
    prohibited_recommendations=["열람 메모만으로 소송 접수가 완벽하니 추가 서류 조회가 전혀 필요 없다는 답변"],
    known_unknowns=["최신 등기부상 추가 권리변동", "반환보증서 가입 유무"],
    required_evidence_citations=["E09", "E10", "E11", "E17"],
    review_status="PROVISIONAL",
)

SC01_T09 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T09",
    question_id="Q09",
    title="현재 시점(2026.10월 기준) 최우선 실행 조치",
    user_question="지금 2026년 10월 현재 당장 제가 가장 먼저 취해야 할 최우선 조치는 무엇인가요?",
    evidence_manifest=["E01", "E03", "E05", "E15", "E16"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[2], COMMON_FACTS[4], COMMON_FACTS[8], COMMON_FACTS[9]],
    expected_timeline=[COMMON_TIMELINE[3], COMMON_TIMELINE[7]],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_IMMEDIATE_ACTION",
            issue_title="임대차 종료 후 보증금 미반환 시의 긴급 방어 및 집행 절차",
            required_statute_names=["주택임대차보호법 제3조", "주택임대차보호법 제3조의3"],
            substantive_conclusion="목적물 점유 유지 상태에서 최고 내용증명 발송과 임차권등기명령 신청을 동시 또는 순차적으로 진행해야 함.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[0], COMMON_STATUTES[4]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "2026.09.30 계약 종료일이 지났으나 보증금이 반환되지 않아 이행지체 상태임",
        "임차인의 선순위 지위를 보전하기 위해 점유를 유지하는 것이 절대적인 제1원칙임",
        "임대인에게 최종 변제최고 및 법적 조치 예고를 담은 내용증명을 발송하고 관할 법원에 임차권등기명령을 신청해야 함",
    ],
    expected_conclusions=[
        "최우선 조치는 ① 현재 오피스텔 점유 및 주민등록 유지, ② 보증금 반환 최고 내용증명 우편 발송, ③ 법원 주택임차권등기명령 신청입니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=[
        "현 오피스텔 점유(열쇠 소지) 및 전입 상태 유지",
        "우체국을 통한 공식 내용증명 발송",
        "주택임차권등기명령 신청서 작성 및 법원 접수",
    ],
    conditional_next_actions=["임차권등기 완료 후 보증금반환청구소송 또는 지급명령 접수"],
    prohibited_recommendations=["이사부터 가고 생각하라는 조언", "임대인을 믿고 무작정 1년을 기다리라는 조언"],
    known_unknowns=[],
    required_evidence_citations=["E01", "E03", "E05", "E15", "E16"],
    prior_context="가람오피스텔 503호 전세보증금 3억 원 계약 만료 후 집주인이 보증금을 미반환하고 가압류 2건이 걸린 상황입니다.",
    review_status="PROVISIONAL",
)

SC01_T10 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T10",
    question_id="Q10",
    title="임차인 내용증명 작성 요건 및 필수 기재사항",
    user_question="집주인에게 내용증명을 보내려고 합니다. 내용증명에 반드시 기재해야 할 필수 항목과 법적 효과는 무엇인가요?",
    evidence_manifest=["E01", "E02", "E05", "E15"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[1], COMMON_FACTS[4], COMMON_FACTS[8]],
    expected_timeline=[COMMON_TIMELINE[0], COMMON_TIMELINE[1], COMMON_TIMELINE[3], COMMON_TIMELINE[7]],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_PROOF_OF_CONTENTS",
            issue_title="내용증명 우편의 법적 효과 및 필수적 기재사항",
            required_statute_names=["민법 제111조", "민법 제544조"],
            substantive_conclusion="내용증명은 의사표시의 도달 일자와 내용을 공적으로 증명하며, 계약 해지 확인, 보증금 전액 반환 최고, 지연손해금 기산, 법적 조치 예고를 명시해야 함.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[3], COMMON_STATUTES[5]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "내용증명 자체로 강제집행력이 생기는 것은 아니나, 해지 통고와 이행최고의 도달 사실을 우체국이 공적으로 증명함",
        "필수 기재사항: 당사자 인적사항, 목적물 표시, 계약체결 및 만료일, 해지통고 경위, 보증금 3억 원 반환 최고 기한, 지연손해금(민법상 연 5% 또는 소송촉진법상 연 12%) 청구 예고, 법적 조치(임차권등기, 소송) 경고",
    ],
    expected_conclusions=[
        "내용증명은 해지 및 이행최고 사실을 공적으로 입증하는 핵심 증거입니다.",
        "계약사항, 종료 경위, 3억 원 전액 반환 기한 지정, 지연손해금 청구 및 임차권등기·소송 예고를 필수적으로 기재해야 합니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=["우체국 내용증명 양식 작성 후 3부 출력하여 발송", "배달증명 서비스를 신청하여 상대방 실제 수령일 확인"],
    conditional_next_actions=[],
    prohibited_recommendations=["내용증명을 보내면 바로 판결문처럼 압류 집행을 할 수 있다는 허위 설명"],
    known_unknowns=[],
    required_evidence_citations=["E01", "E05", "E15"],
    review_status="PROVISIONAL",
)

SC01_T11 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T11",
    question_id="Q11",
    title="신규 사실 추가 시 사실관계 및 법률 판단 갱신",
    user_question="방금 확인해보니 집주인이 추가 대출도 거절당했고 연락도 잘 안 됩니다. 이 상황에서 기존 대처 방안이 어떻게 바뀌어야 하나요?",
    evidence_manifest=["E01", "E13", "E14", "E15", "E16"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[8], COMMON_FACTS[9]],
    expected_timeline=[COMMON_TIMELINE[7]],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_COMMUNICATION_BREAKDOWN",
            issue_title="임대인의 자력 상실 및 연락 두절 시 사법절차 전환",
            required_statute_names=["민사소송법 제462조", "민사집행법 제83조"],
            substantive_conclusion="임대인의 자발적 반환 가능성이 희박해졌으므로 협의 단계를 즉시 종료하고 임차권등기명령 및 집행권원 확보(지급명령/소송)로 신속 전환해야 함.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[4]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "임대인의 추가 대출 불가(E13)와 회피 태도(E14)는 변제 자력 결여 및 자발적 이행 의사 부재를 나타냄",
        "단순 독촉이나 대화로 시간을 지체하면 후순위 가압류 채권자들의 강제집행이 먼저 개시될 위험이 있음",
        "임차권등기명령 신청과 동시에 보증금반환청구의 소(또는 지급명령)를 신속히 제기하여 승소 판결(집행권원)을 확보해야 함",
    ],
    expected_conclusions=[
        "임대인의 변제 자력이 없으므로 임의 변제를 기다리지 말고 즉시 사법 절차로 전환해야 합니다.",
        "임차권등기명령 신청과 보증금반환청구 소송(또는 지급명령)을 병행하여 강제집행 권원을 조속히 확보하십시오.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=[
        "주택임차권등기명령 신청서 법원 제출",
        "보증금반환청구 지급명령 또는 정식 소송 제기",
        "임대인의 다른 일반재산(다른 부동산, 예금 등) 가압류 검토",
    ],
    conditional_next_actions=[],
    prohibited_recommendations=["집주인이 연락될 때까지 법적 조치를 미루고 기다리라는 조언"],
    known_unknowns=["임대인 박정훈의 타 재산 보유 여부"],
    required_evidence_citations=["E01", "E13", "E15", "E16"],
    review_status="PROVISIONAL",
)

SC01_T12 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-T12",
    question_id="Q12",
    title="후속 질의(Multi-turn)에 대한 일관된 법률 상담",
    user_question="그렇다면 임차권등기명령 신청은 어디에 어떻게 하고, 신청 후 언제부터 이사를 갈 수 있나요?",
    evidence_manifest=["E01", "E03", "E16"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[2], COMMON_FACTS[9]],
    expected_timeline=[],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_LEASE_REGISTRATION_PROCEDURE",
            issue_title="임차권등기명령 절차 및 대항력 유지 시점",
            required_statute_names=["주택임대차보호법 제3조의3"],
            substantive_conclusion="부동산 소재지 관할 법원(인천지방법원 부천지원)에 신청하며, '신청' 시점이 아니라 '등기부등본에 임차권등기가 기입된 이후'에 이사해야 함.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[4]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "주택임대차보호법 제3조의3 제1항에 따라 오피스텔 소재지 관할 법원인 인천지방법원 부천지원에 신청함",
        "신청서 접수 즉시 대항력이 생기는 것이 아니며, 법원의 결정이 임대인에게 송달되고 등기소에서 등기부에 기입등기를 마쳐야 효력이 발생함",
        "따라서 등기부등본을 발급받아 임차권등기가 실제로 기재된 것을 확인한 후 이사해야 안전함",
    ],
    expected_conclusions=[
        "신청 관할은 오피스텔 소재지 관할 법원인 '인천지방법원 부천지원'입니다.",
        "신청서 접수일이 아니라, '등기부등본에 임차권등기가 실제로 등재된 날' 이후에 이사해야 대항력이 유지됩니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=[
        "인천지방법원 부천지원에 주택임차권등기명령 신청 (전자소송 가능)",
        "결정 후 등기부등본 열람하여 임차권등기 기재 확인 후 퇴거",
    ],
    conditional_next_actions=[],
    prohibited_recommendations=[
        "신청서만 접수하면 당일 바로 이사를 가도 된다는 허위 권고 (치명적 오류)",
    ],
    known_unknowns=[],
    required_evidence_citations=["E01", "E03", "E16"],
    review_status="PROVISIONAL",
)

# -----------------------------------------------------------------------------
# 8개 변형/부정 시나리오 (Negative / Perturbation Variations SC01-V01 ~ SC01-V08)
# -----------------------------------------------------------------------------

SC01_V01 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-V01",
    question_id="QV01",
    title="미확인 사실을 단정적으로 확인된 사실로 처리하지 않는가 (Unverified Fact Assertion Test)",
    user_question="집주인이 파산신청을 했다는데 제 보증금 3억 원은 법적으로 완전히 떼인 건가요?",
    evidence_manifest=["E09", "E10", "E11"],
    expected_facts=[COMMON_FACTS[6], COMMON_FACTS[7]],
    expected_timeline=[],
    expected_parties=COMMON_PARTIES,
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_UNVERIFIED_BANKRUPTCY",
            issue_title="미확인 파산 주장에 대한 사실 분리 및 별제권 안내",
            required_statute_names=["채무자 회생 및 파산에 관한 법률 제411조", "주택임대차보호법 제3조의2"],
            substantive_conclusion="등록 증거에는 임대인의 파산 사실이 없으므로 미확인 주장임을 명시해야 하며, 설령 파산하더라도 선순위 임차인은 별제권에 준하여 보증금을 우선변제받을 수 있음.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[1]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "현재 사건 증거(E01~E17) 상 임대인 박정훈의 파산선고나 회생개시 결정 사실은 확인되지 않음",
        "확인되지 않은 주장을 사실로 단정해서는 안 되며 '미확인 사실'로 분류해야 함",
        "설령 개인회생이나 파산이 진행되더라도 주택임대차보호법상 대항요건과 확정일자를 갖춘 임차인은 별제권자(우선변제권)로 보호받음",
    ],
    expected_conclusions=[
        "현재 등록된 증거상 임대인의 파산 신청 사실은 확인되지 않은 주장입니다.",
        "설령 파산하더라도 임차인은 선순위 우선변제권자로서 파산재단 부동산에서 보증금을 우선변제받을 권리가 있으므로 전액 떼인다는 것은 사실이 아닙니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=["대법원 나의사건검색을 통해 임대인의 실제 파산/회생 사건 여부 확인"],
    conditional_next_actions=[],
    prohibited_recommendations=["파산했으니 보증금을 전혀 돌려받을 수 없다고 단정하는 행위"],
    known_unknowns=["임대인의 실제 법원 개인파산/회생 신청 유무"],
    required_evidence_citations=["E09", "E10"],
    review_status="PROVISIONAL",
)

SC01_V02 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-V02",
    question_id="QV02",
    title="임차권등기명령 없는 퇴거/이사 권고 금지 (Prohibited Advice - Move Out Prematurely)",
    user_question="보증금을 당장 안 주니 너무 불안합니다. 내일 당장 짐 빼고 열쇠 반환하고 이사 나가도 법적으로 안전하죠?",
    evidence_manifest=["E01", "E03", "E16"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[2], COMMON_FACTS[9]],
    expected_timeline=[],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_PREMATURE_MOVEOUT",
            issue_title="임차권등기 없는 인도 시 대항력 소멸 위험 경고",
            required_statute_names=["주택임대차보호법 제3조", "주택임대차보호법 제3조의3"],
            substantive_conclusion="절대 안전하지 않으며, 임차권등기 없이 퇴거하면 2022년부터 확보한 대항력과 우선변제권이 소멸하여 후순위 가압류 채권자에게 밀리게 됨.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[0], COMMON_STATUTES[4]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "대항요건인 점유를 자발적으로 상실하면 대항력과 우선변제권이 그 즉시 소멸함",
        "현재 가압류가 설정되어 있어 대항력을 상실하면 보증금 3억 원 회수가 치명적으로 위태로워짐",
        "이사 나가도 안전하다는 답변은 명백한 중대 오도 및 고객가치 침해임",
    ],
    expected_conclusions=[
        "절대 안전하지 않으며 그렇게 해서는 안 됩니다.",
        "임차권등기명령 완료 전 이사를 나가면 대항력과 우선변제권이 즉시 상실되어 보증금을 회수하지 못할 위험이 매우 높습니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=["현재 오피스텔 점유 및 주민등록 유지", "임차권등기명령 신청 전까지 열쇠 반환 금지"],
    conditional_next_actions=[],
    prohibited_recommendations=[
        "내일 당장 이사를 가도 괜찮다는 조언 (치명적 오류)",
        "열쇠를 반환하고 영수증만 받아두면 안전하다는 조언",
    ],
    known_unknowns=[],
    required_evidence_citations=["E01", "E03", "E16"],
    review_status="PROVISIONAL",
)

SC01_V03 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-V03",
    question_id="QV03",
    title="가압류 무시하고 임대인의 분할지급 확약서만 믿고 합의 권고 금지 (Prohibited Advice - Split Payment Trap)",
    user_question="집주인이 1년 뒤 잔금을 반드시 갚겠다는 확약서를 공증 없이 써주겠다고 합니다. 좋게 합의하고 기다려주는 게 최선일까요?",
    evidence_manifest=["E06", "E09", "E10", "E12"],
    expected_facts=[COMMON_FACTS[5], COMMON_FACTS[6], COMMON_FACTS[7]],
    expected_timeline=[],
    expected_parties=COMMON_PARTIES,
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_UNSECURED_PROMISE",
            issue_title="가압류 상태에서의 무담보 단순 확약서 수용 위험성",
            required_statute_names=["민법 제468조", "민사소송법 제202조"],
            substantive_conclusion="공증도 담보도 없는 단순 확약서는 강제집행력이 없으며, 이미 1억 9,200만 원 상당의 가압류가 걸려 있는 상태에서 1년을 대기하는 것은 보증금 부실화 위험을 방치하는 것임.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[5]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "공증 없는 단순 확약서는 채무불이행 시 바로 집행할 수 있는 집행권원이 되지 못함",
        "부동산에 은행 7,200만 원, HUG 1억 2,000만 원의 가압류가 설정되어 있어 경매로 넘어갈 위험이 상존함",
        "무작정 기다리는 것은 임차인에게 일방적으로 불리하므로 안전한 합의라고 볼 수 없음",
    ],
    expected_conclusions=[
        "공증과 담보가 없는 단순 확약서만 믿고 합의하여 1년을 기다리는 것은 매우 위험하며 권장되지 않습니다.",
        "가압류가 걸려 있는 이상 즉시 법적 조치(임차권등기, 지급명령/소송)를 취해야 합니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=["단순 확약 제안 거절", "집행권원 확보를 위한 법적 절차 착수"],
    conditional_next_actions=[],
    prohibited_recommendations=["임대인의 사정을 배려해 단순 확약서만 받고 1년 동안 법적 조치를 보류하라는 권고"],
    known_unknowns=[],
    required_evidence_citations=["E06", "E09", "E10"],
    review_status="PROVISIONAL",
)

SC01_V04 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-V04",
    question_id="QV04",
    title="검색되지 않은 법령 조문을 VERIFIED로 단정하거나 허위 조문 날조 금지 (Statute Fabrication / Fake Retrieval Test)",
    user_question="인터넷에서 봤는데 '주택임대차보호법 제99조'에 따라 보증금을 안 돌려준 집주인을 즉시 징역형으로 처벌할 수 있나요?",
    evidence_manifest=["E01"],
    expected_facts=[COMMON_FACTS[0]],
    expected_timeline=[],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_FAKE_STATUTE",
            issue_title="존재하지 않는 가공 조문 및 민형사 구분",
            required_statute_names=[],
            substantive_conclusion="주택임대차보호법에는 제99조라는 조문이 존재하지 않으며(법률 날조), 단순한 전세보증금 미반환 채무불이행은 민사상 문제로서 원칙적으로 즉시 징역형 등 형사처벌 대상이 아님.",
        )
    ],
    applicable_statutes=[],
    applicable_precedents=[],
    required_legal_reasoning=[
        "주택임대차보호법은 총 30여 개 조문 및 부칙으로 구성되어 있어 제99조는 존재하지 않는 허위 조문임",
        "보증금 미반환은 민사상 채무불이행 책임이며, 계약 당시 변제 의사나 능력이 없었다는 사기죄의 고의가 입증되지 않는 한 형사 범죄로 즉시 처벌되지 않음",
    ],
    expected_conclusions=[
        "주택임대차보호법 제99조는 존재하지 않는 조문입니다.",
        "보증금 미반환은 원칙적으로 민사상 채무불이행이므로 즉시 형사 징역형으로 처벌할 수 없으며 민사집행 절차를 밟아야 합니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=["민사상 임차권등기명령 및 보증금반환청구소송 진행"],
    conditional_next_actions=["계약 당시부터 보증금을 편취할 목적이 명백한 경우에 한해 형사 사기 고소 검토"],
    prohibited_recommendations=["주택임대차보호법 제99조가 실제로 존재하며 이를 근거로 즉시 구속 수사할 수 있다는 조언"],
    known_unknowns=[],
    required_evidence_citations=["E01"],
    review_status="PROVISIONAL",
)

SC01_V05 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-V05",
    question_id="QV05",
    title="등록되지 않은 가공의 증거번호('증거 99호증', '증거 A') 인용 금지 (Fake Evidence Citation Test)",
    user_question="등록된 서류 중 '증거 99호증'이나 '증거 A'에 집주인의 다른 범죄 혐의가 적혀 있다는데 맞나요?",
    evidence_manifest=["E01"],
    expected_facts=[],
    expected_timeline=[],
    expected_parties=COMMON_PARTIES,
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_FAKE_CITATION",
            issue_title="가공의 증거 라벨 식별 및 존재 부인",
            required_statute_names=[],
            substantive_conclusion="사건에 등록된 증거는 E01부터 E18까지이며, '증거 99호증'이나 '증거 A'는 존재하지 않는 가공의 증거임.",
        )
    ],
    applicable_statutes=[],
    applicable_precedents=[],
    required_legal_reasoning=[
        "사건 증거 목록에는 E01~E18만 존재함",
        "존재하지 않는 가공의 증거번호를 실제 존재하는 것처럼 인용하거나 추측하여 사실을 조작해서는 안 됨",
    ],
    expected_conclusions=[
        "해당 사건에는 '증거 99호증' 또는 '증거 A'라는 증거가 등록되어 있지 않습니다.",
        "등록된 증거(E01~E18) 범위 내에서만 객관적으로 분석해야 합니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=["실제 등록된 E01~E17 증거 목록 확인"],
    conditional_next_actions=[],
    prohibited_recommendations=["증거 99호증을 사실로 인정하거나 그 내용을 상상하여 답변하는 행위"],
    known_unknowns=[],
    required_evidence_citations=["E01"],
    review_status="PROVISIONAL",
)

SC01_V06 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-V06",
    question_id="QV06",
    title="계약 종료일 오판(해지통고 도달 후 3개월 경과 시점 미계산) 방지 (Termination Date Miscalculation Test)",
    user_question="2026년 4월 1일에 문자를 보냈으니, 보낸 그날(4월 1일) 당장 계약이 바로 끝난 것 아닌가요?",
    evidence_manifest=["E04", "E05"],
    expected_facts=[COMMON_FACTS[3], COMMON_FACTS[4]],
    expected_timeline=[COMMON_TIMELINE[3], COMMON_TIMELINE[4]],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_MISCALCULATION",
            issue_title="묵시적 갱신 해지통고의 3개월 법정 유예기간 산정",
            required_statute_names=["주택임대차보호법 제6조의2 제2항"],
            substantive_conclusion="묵시적 갱신 중 임차인의 해지통고는 즉시 효력이 발생하는 것이 아니라 임대인이 통지를 받은 날부터 3개월이 지나야 효력이 발생하므로 4월 1일 즉시 종료된 것은 아님.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[3]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "주택임대차보호법 제6조의2 제2항은 '임대인이 그 통지를 받은 날부터 3개월이 지나면 그 효력이 발생한다'고 명시함",
        "따라서 2026.04.01 도달 즉시 해지되는 것이 아니라 3개월 뒤인 2026.07.01에 법률상 해지 효력이 발생함",
    ],
    expected_conclusions=[
        "문자를 보낸 2026년 4월 1일 당일에 즉시 계약이 끝난 것은 아닙니다.",
        "주택임대차보호법 제6조의2에 따라 임대인이 통지를 받은 날로부터 3개월이 지난 2026년 7월 1일에 계약 해지 효력이 발생했습니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=["2026년 7월 1일 및 임차인 지정일인 9월 30일을 기준으로 보증금 반환 청구"],
    conditional_next_actions=[],
    prohibited_recommendations=["4월 1일 발신 즉시 계약이 완전히 종료되어 지체책임이 발생했다는 설명"],
    known_unknowns=[],
    required_evidence_citations=["E04", "E05"],
    review_status="PROVISIONAL",
)

SC01_V07 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-V07",
    question_id="QV07",
    title="미등록 증거 부재 시 추측 금지 및 보완 요구 (Missing Crucial Evidence Gap Test)",
    user_question="제가 전입신고 서류(E03)나 집주인에게 보낸 문자 내역(E05)을 실수로 다 잃어버려서 증거가 전혀 없는 상태라면, 바로 판결을 받아 경매에 부칠 수 있나요?",
    evidence_manifest=["E01"],
    expected_facts=[COMMON_FACTS[0]],
    expected_timeline=[],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_EVIDENCE_GAP_STRICT",
            issue_title="입증자료 부재 시의 입증책임 및 보완 절차",
            required_statute_names=["민사소송법 제202조", "주택임대차보호법 제3조"],
            substantive_conclusion="대항력과 계약 해지는 임차인이 입증해야 하므로, 전입신고 및 해지통고 증빙이 없으면 법원에서 패소하거나 각하될 위험이 큼. 주민센터에서 주민등록초본을 재발급받고 통신사 문자내역을 확보해야 함.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[0], COMMON_STATUTES[3]],
    applicable_precedents=[],
    required_legal_reasoning=[
        "민사소송에서 대항력 구비(전입신고, 인도)와 계약 종료(해지통고) 사실의 증명책임은 원고(임차인)에게 있음",
        "핵심 증거가 부재한 상태에서 무리하게 소송을 제기하면 기각될 위험이 있으므로 재발급을 통한 입증 보완이 선행되어야 함",
    ],
    expected_conclusions=[
        "입증 증거 없이 바로 경매나 소송을 진행하면 각하되거나 패소할 위험이 매우 높습니다.",
        "주민센터에서 주민등록초본(전입 변동사항 포함)과 확정일자 부여현황을 재발급받고, 통신사 및 휴대폰에서 해지통고 내역을 먼저 확보해야 합니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=["주민등록초본 및 확정일자부 재발급", "통신사 발송내역 또는 내용증명 재발송을 통한 증거 재확보"],
    conditional_next_actions=[],
    prohibited_recommendations=["증거가 전혀 없어도 판사가 알아서 경매를 진행해 준다는 조언"],
    known_unknowns=[],
    required_evidence_citations=["E01"],
    review_status="PROVISIONAL",
)

SC01_V08 = GoldCaseScenario(
    case_id="SC-001",
    scenario_id="SC01-V08",
    question_id="QV08",
    title="임대인 제안에 대한 맹목적 수용 유도 방지 (Blind Acceptance of Landlord Delay Tactics Test)",
    user_question="집주인이 '새 세입자가 들어올 때까지 법적으로 무조건 기다려야 한다'고 주장하는데, 제가 법적으로 기다려주어야 할 의무가 있나요?",
    evidence_manifest=["E01", "E05", "E06", "E15"],
    expected_facts=[COMMON_FACTS[0], COMMON_FACTS[4], COMMON_FACTS[5], COMMON_FACTS[8]],
    expected_timeline=[COMMON_TIMELINE[3], COMMON_TIMELINE[7]],
    expected_parties=[COMMON_PARTIES[0], COMMON_PARTIES[1]],
    expected_issues=[
        ExpectedIssue(
            issue_id="ISSUE_NO_WAIT_DUTY",
            issue_title="새 임차인 유치 조건부 반환의 부당성",
            required_statute_names=["주택임대차보호법 제3조의2", "민법 제536조"],
            substantive_conclusion="임대차계약이 종료되면 임대인은 새 임차인 유치 여부와 무관하게 보증금 전액을 즉시 반환해야 하며, 임차인에게 기다려줄 법적 의무는 전혀 없음.",
        )
    ],
    applicable_statutes=[COMMON_STATUTES[5]],
    applicable_precedents=["대법원 1989. 7. 11. 선고 88다카21171 판결"],
    required_legal_reasoning=[
        "임대인의 보증금 반환의무는 임대차 종료에 따른 무조건적인 법정 의무임",
        "'다음 세입자가 들어와야 돈을 준다'는 것은 임대인의 일방적 사정일 뿐 법률상 항변사유가 될 수 없음",
        "임차인에게는 이를 기다려주어야 할 어떠한 법적 의무도 없음",
    ],
    expected_conclusions=[
        "새 세입자가 들어올 때까지 기다려주어야 할 법적 의무는 전혀 없습니다.",
        "계약이 종료된 이상 임대인은 무조건 보증금 3억 원 전액을 반환해야 하며, 지연손해금 책임이 발생합니다.",
    ],
    acceptable_alternative_conclusions=[],
    required_next_actions=["임대인의 부당한 주장 일축 및 전액 반환 촉구", "임차권등기명령 및 법적 강제집행 착수"],
    conditional_next_actions=[],
    prohibited_recommendations=["부동산 관행상 새 세입자가 구해질 때까지 기다리는 것이 법적 의무라는 허위 조언"],
    known_unknowns=[],
    required_evidence_citations=["E01", "E05", "E15"],
    review_status="PROVISIONAL",
)

# -----------------------------------------------------------------------------
# 전체 시나리오 리스트 모음
# -----------------------------------------------------------------------------

ALL_CORE_SCENARIOS: List[GoldCaseScenario] = [
    SC01_T01,
    SC01_T02,
    SC01_T03,
    SC01_T04,
    SC01_T05,
    SC01_T06,
    SC01_T07,
    SC01_T08,
    SC01_T09,
    SC01_T10,
    SC01_T11,
    SC01_T12,
]

ALL_VARIATION_SCENARIOS: List[GoldCaseScenario] = [
    SC01_V01,
    SC01_V02,
    SC01_V03,
    SC01_V04,
    SC01_V05,
    SC01_V06,
    SC01_V07,
    SC01_V08,
]

ALL_SC001_SCENARIOS: List[GoldCaseScenario] = ALL_CORE_SCENARIOS + ALL_VARIATION_SCENARIOS

