"""
@fileoverview STEP 6 사용자 친화적인 답변 생성 및 프런트엔드 UI 개선 검증 단위 테스트

[검증 항목]
1. document_answer.py 프롬프트 지침: 첫 문단 직접 답변, 유연한 소제목, 간결한 법령 인용
2. synthesizer.py 프롬프트 지침: 고정 5단계 보고서 템플릿 강제 제거, 4대 핵심 원칙 준수
3. 사건 증거 전체 파일명 보존 및 공포번호 나열 지양 검증
"""

import pytest
from ai_legal_helper.agents.document_answer import DOCUMENT_ANSWER_SYSTEM
from ai_legal_helper.agents.document_verification_prompt import DOCUMENT_VERIFICATION_PROMPT
from ai_legal_helper.agents.synthesizer import SYNTH_SYSTEM, SYNTH_FEWSHOT


class TestStep6UserFriendlyAnswer:
    """STEP 6 답변 품질 및 프롬프트 개선 단위 테스트 스위트"""

    def test_document_answer_lead_direct_answer(self):
        """첫 문단에서 사용자의 질문에 직접 답변하도록 지시하는지 검증"""
        # 첫 문단 직접 답변 및 불필요한 시스템 서론(검증 완료, 6단계 등) 방지 문구 확인
        assert "첫 문단에서 사용자의 질문에 직접 답변하는 핵심 결론" in DOCUMENT_ANSWER_SYSTEM
        assert "검증 완료" in DOCUMENT_ANSWER_SYSTEM
        assert "소제목" in DOCUMENT_ANSWER_SYSTEM

    def test_document_answer_dynamic_sections_and_no_boilerplate(self):
        """긴 통글 대신 유연한 소제목(###)과 불필요한 소송 절차 강제 배제 검증"""
        assert "소제목(`###" in DOCUMENT_ANSWER_SYSTEM
        assert "소송 절차 안내를 강제하지 마세요" in DOCUMENT_ANSWER_SYSTEM
        assert "면책 문구를 남발하지 마세요" in DOCUMENT_ANSWER_SYSTEM

    def test_document_answer_clean_citations(self):
        """본문 출처 표기 시 증거 파일명 보존 및 법령 인용 간결화 지시 검증"""
        assert "사건 문서(사실 문장)는 반드시 전체 파일명 그대로" in DOCUMENT_ANSWER_SYSTEM
        assert "주택임대차보호법 제6조의2" in DOCUMENT_ANSWER_SYSTEM
        # 과도한 공포번호나 시행일 나열을 지양하고 간결하게 표기하도록 안내하는지 확인
        assert "긴 공포번호나 시행일자를 나열하지 말고" in DOCUMENT_ANSWER_SYSTEM

    def test_synthesizer_removed_rigid_five_step_template(self):
        """고정된 5단계 보고서 템플릿([1. 핵심 결론], [2. 사건 사실관계 등]) 강제가 제거되었는지 검증"""
        # 과거 강제 양식 키워드가 프롬프트 본문에서 제거되었는지 확인
        assert "반드시 다음 5단계 표준 구조 체계를 사용하세요" not in SYNTH_SYSTEM
        assert "[3. 쟁점별 법률 분석]에서는 각 주요 쟁점별로 다음 5가지 요소를 빠짐없이 구조화하여 분석하세요" not in SYNTH_SYSTEM

    def test_synthesizer_four_core_principles(self):
        """STEP 6 4대 핵심 원칙(직접 답변, 필요한 만큼만 설명, 불필요한 반복 제거, 자연스러운 출처) 반영 검증"""
        assert "답변 작성 4대 핵심 원칙 (STEP 6)" in SYNTH_SYSTEM
        assert "질문에 바로 직접 답변" in SYNTH_SYSTEM
        assert "필요한 만큼만 설명 (동적 섹션 구성)" in SYNTH_SYSTEM
        assert "불필요한 반복 제거" in SYNTH_SYSTEM
        assert "출처를 자연스럽게 표시" in SYNTH_SYSTEM

    def test_synthesizer_natural_fewshot_example(self):
        """퓨샷 예시가 고정 5단계 보고서가 아닌 자연스러운 질의응답 구조인지 검증"""
        assert "### 현재 판단" in SYNTH_FEWSHOT
        assert "### 지금 할 일" in SYNTH_FEWSHOT
        assert "실제 사건의 사실이나 법률 근거가 아닙니다" in SYNTH_FEWSHOT
        assert "주택임대차보호법" not in SYNTH_FEWSHOT
        assert "[1. 핵심 결론]" not in SYNTH_FEWSHOT



class TestDocumentPromptGroundingRegression:
    """프롬프트의 사실 구분 및 독립 검증 정책을 정적 회귀 검사한다.

    실제 LLM 판정 품질은 별도 통제 응답/실모델 테스트가 필요하다.
    """

    def test_user_statement_not_promoted_to_verified_fact(self):
        assert "별도 증명서류가 없다는 이유만으로 그 진술을 부정하거나 판단 불가로 처리하지 마세요" in DOCUMENT_ANSWER_SYSTEM
        assert "진술하지 않은 별개의 법률 요건" in DOCUMENT_ANSWER_SYSTEM

    def test_verification_independent_of_predefined_lease_conclusion(self):
        assert "특정 법률 결론을 사전에 정답으로 가정하지 마세요" in DOCUMENT_VERIFICATION_PROMPT
        assert "선순위 대항요건(인도+전입)과 확정일자를 갖추고" not in DOCUMENT_VERIFICATION_PROMPT
        assert "USER_STATEMENT 자체는 결함이 아닙니다" in DOCUMENT_VERIFICATION_PROMPT

    def test_verification_keeps_output_contract_and_revise(self):
        for token in ("question_coverage", "claims", "consistency_checks", "preserved_points", "legal_search_requests", "REVISE"):
            assert token in DOCUMENT_VERIFICATION_PROMPT
        assert "수정 요청이 있으면 지적된 오류를 원문과 대조해 고치되" in DOCUMENT_ANSWER_SYSTEM


def test_current_occupancy_statement_is_accepted_without_registration_document():
    """현재 거주 진술은 점유 상담 전제로 인정하되 전입신고는 별도 요건이다."""
    assert "현재 거주·점유" in DOCUMENT_ANSWER_SYSTEM
    assert "전입신고, 확정일자" in DOCUMENT_ANSWER_SYSTEM
    assert "증명서류가 없다는 이유만으로 해당 진술을 UNCERTAIN/UNSUPPORTED로 강등하거나 REVISE하지 마세요" in DOCUMENT_VERIFICATION_PROMPT
