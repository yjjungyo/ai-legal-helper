# -*- coding: utf-8 -*-
"""
단위 테스트 모듈명: test_text_formatter_evidence_citations.py

[테스트 개요]
답변 본문 내 증거 인용 표기에서 [01], [03], [E01], [01, 03] 등 축약된 형태가 등록된 사건의 실제 전체 파일명
(예: `[01_임대차_주요내용.txt]`, `[E01_주택임대차계약서.txt]`)으로 안전하고 정확하게 자동 복원/확장되는지 검증한다.
(Option B: 전체 파일명 보존 표준)
"""
import pytest
from ai_legal_helper.utils.text_formatter import expand_evidence_citations, extract_all_registered_evidence_sources


@pytest.fixture
def sample_string_sources():
    """문자열 형태의 증거 파일명 목록 픽스처."""
    return [
        "01_임대차_주요내용.txt",
        "02_내용증명_20260401.txt",
        "03_계약_해지_문자대화_202606.txt",
        "04_주택인도_및_열쇠반환_사진.jpg",
    ]


@pytest.fixture
def sample_dict_sources():
    """딕셔너리 형태의 Source Registry 출처 목록 픽스처."""
    return [
        {
            "source_id": "01_임대차_주요내용.txt",
            "document_name": "01_임대차_주요내용.txt",
            "source_type": "CASE_EVIDENCE",
        },
        {
            "source_id": "02_내용증명_20260401.txt",
            "document_name": "02_내용증명_20260401.txt",
            "source_type": "CASE_EVIDENCE",
        },
        {
            "source_id": "03_계약_해지_문자대화_202606.txt",
            "document_name": "03_계약_해지_문자대화_202606.txt",
            "source_type": "CASE_EVIDENCE",
        },
        {
            "source_id": "주택임대차보호법_제6조",
            "statute_name": "주택임대차보호법",
            "article": "제6조",
            "source_type": "STATUTE",
        },
    ]


@pytest.fixture
def sample_prefixed_e_sources():
    """'E' 접두사 파일명을 사용하는 사건 출처 픽스처."""
    return [
        "E01_주택임대차계약서.txt",
        "E02_전입세대확인서.txt",
        "E03_부동산등기사항전부증명서.pdf",
    ]


def test_expand_separated_brackets(sample_string_sources):
    """[01], [03] 처럼 개별 대괄호로 분리된 축약 번호가 각각 전체 파일명으로 확장되는지 검증."""
    input_text = "계약 종료일은 2026.8.31이고, 보증금 3억 원은 등록증거와 불일치합니다. [01], [03]"
    expected = (
        "계약 종료일은 2026.8.31이고, 보증금 3억 원은 등록증거와 불일치합니다. "
        "[01_임대차_주요내용.txt], [03_계약_해지_문자대화_202606.txt]"
    )
    result = expand_evidence_citations(input_text, sample_string_sources)
    assert result == expected


def test_expand_combined_comma_bracket(sample_string_sources):
    """[01, 03] 처럼 단일 대괄호 내 콤마로 묶인 축약 표기가 각각 분리 확장되는지 검증."""
    input_text = "계약 종료와 미반환 사실을 입증합니다. [01, 03]"
    expected = (
        "계약 종료와 미반환 사실을 입증합니다. "
        "[01_임대차_주요내용.txt], [03_계약_해지_문자대화_202606.txt]"
    )
    result = expand_evidence_citations(input_text, sample_string_sources)
    assert result == expected


def test_expand_with_dict_sources(sample_dict_sources):
    """딕셔너리 구조의 sources 목록에서도 파일명이 정확히 추출되어 확장되는지 검증."""
    input_text = "임대차 계약서 [01] 및 문자메시지 [03]에 의하면 확인됩니다."
    expected = (
        "임대차 계약서 [01_임대차_주요내용.txt] 및 문자메시지 "
        "[03_계약_해지_문자대화_202606.txt]에 의하면 확인됩니다."
    )
    result = expand_evidence_citations(input_text, sample_dict_sources)
    assert result == expected


def test_expand_prefixed_e_sources(sample_prefixed_e_sources):
    """E01, E03 형태의 증거 표기가 E 접두사 전체 파일명으로 확장되는지 검증."""
    input_text = "계약서 [E01] 및 등기사항증명서 [E03]에 따른 권리관계입니다."
    expected = (
        "계약서 [E01_주택임대차계약서.txt] 및 등기사항증명서 "
        "[E03_부동산등기사항전부증명서.pdf]에 따른 권리관계입니다."
    )
    result = expand_evidence_citations(input_text, sample_prefixed_e_sources)
    assert result == expected


def test_idempotence_full_filename_preserved(sample_string_sources):
    """이미 전체 파일명이 표기되어 있는 경우 중복 변환이나 손상 없이 원문 그대로 보존되는지 검증."""
    input_text = "계약서는 [01_임대차_주요내용.txt]에 명시되어 있습니다."
    result = expand_evidence_citations(input_text, sample_string_sources)
    assert result == input_text


def test_non_evidence_brackets_preserved(sample_string_sources):
    """법률 조문 브래킷([주택임대차보호법])이나 섹션 헤더([현재 계약 상태]) 등은 변환되지 않고 유지되는지 검증."""
    input_text = (
        "[현재 계약 상태]\n"
        "[주택임대차보호법 제6조]에 따라 계약은 묵시적으로 갱신되었습니다. [01]"
    )
    expected = (
        "[현재 계약 상태]\n"
        "[주택임대차보호법 제6조]에 따라 계약은 묵시적으로 갱신되었습니다. [01_임대차_주요내용.txt]"
    )
    result = expand_evidence_citations(input_text, sample_string_sources)
    assert result == expected


def test_unknown_number_preserved(sample_string_sources):
    """등록되지 않은 미등록 번호([99])는 임의 확장되지 않고 원문 그대로 유지되는지 검증."""
    input_text = "등록되지 않은 증거 [99]호입니다."
    result = expand_evidence_citations(input_text, sample_string_sources)
    assert result == input_text


def test_empty_or_none_inputs():
    """빈 텍스트나 빈 출처 목록이 전달될 때 예외 없이 안전하게 처리되는지 검증."""
    assert expand_evidence_citations("", ["01_계약서.txt"]) == ""
    assert expand_evidence_citations("기존 답변 [01]", None) == "기존 답변 [01]"
    assert expand_evidence_citations("기존 답변 [01]", []) == "기존 답변 [01]"


def test_user_reported_actual_deposit_citations():
    """사용자가 지적한 실제 보증금 반환 관련 인용 표기([01], [04], [05], [06]) 복원 검증."""
    case_sources = [
        "01_주택임대차계약_주요내용.txt",
        "02_전입신고_확정일자_입주확인.txt",
        "03_계약종료_통지_문자대화_202606.txt",
        "04_최초보증금_임차인송금내역.txt",
        "05_1차반환_이체확인내용_20260920.txt",
        "06_은행거래내역_반환2건_20261010.txt",
    ]
    input_text = (
        "1.\n"
        "현재 자료상 바로 청구할 수 있는 미반환 보증금 원금은 1억 7천만 원으로 보는 것이 가장 안전합니다.\n"
        "•\n"
        "계약상 보증금: 2억 2천만 원 [01]\n"
        "•\n"
        "임차인이 실제 지급한 보증금 확인: 2억 2천만 원 [04]\n"
        "•\n"
        "객관적으로 확인되는 반환액: 5천만 원 [05], [06]"
    )
    expected = (
        "1.\n"
        "현재 자료상 바로 청구할 수 있는 미반환 보증금 원금은 1억 7천만 원으로 보는 것이 가장 안전합니다.\n"
        "•\n"
        "계약상 보증금: 2억 2천만 원 [01_주택임대차계약_주요내용.txt]\n"
        "•\n"
        "임차인이 실제 지급한 보증금 확인: 2억 2천만 원 [04_최초보증금_임차인송금내역.txt]\n"
        "•\n"
        "객관적으로 확인되는 반환액: 5천만 원 [05_1차반환_이체확인내용_20260920.txt], [06_은행거래내역_반환2건_20261010.txt]"
    )
    result = expand_evidence_citations(input_text, case_sources)
    assert result == expected


def test_extract_all_registered_evidence_sources_from_state():
    """State 객체의 여러 경로(briefing, retrieved_sources, source_registry)에서 증거 파일이 통합 수집되는지 검증."""
    state = {
        "case_evidence_briefing": {
            "source_documents": [
                {"document_name": "01_주택임대차계약_주요내용.txt"},
                {"document_name": "04_최초보증금_임차인송금내역.txt"},
            ],
            "source_registry": {
                "05": {"document_name": "05_1차반환_이체확인내용_20260920.txt"}
            }
        },
        "retrieved_sources": [
            {"source_id": "06_은행거래내역_반환2건_20261010.txt", "document_name": "06_은행거래내역_반환2건_20261010.txt"},
            {"source_id": "주택임대차보호법_제6조", "source_type": "STATUTE"}
        ]
    }
    sources = extract_all_registered_evidence_sources(state)
    names = [s if isinstance(s, str) else (s.get("document_name") or s.get("source_id")) for s in sources]
    assert "01_주택임대차계약_주요내용.txt" in names
    assert "04_최초보증금_임차인송금내역.txt" in names
    assert "05_1차반환_이체확인내용_20260920.txt" in names
    assert "06_은행거래내역_반환2건_20261010.txt" in names
