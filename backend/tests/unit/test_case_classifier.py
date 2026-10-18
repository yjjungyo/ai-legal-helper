# -*- coding: utf-8 -*-
"""
단위 테스트: test_case_classifier.py

사건 등록 시 사용자가 유형을 직접 선택하지 않거나 'AI 자동 분류'를 지정했을 때,
사건 제목과 설명으로부터 올바른 법률 분쟁 유형이 자동 추론되는지 검증한다.
"""

import pytest
from ai_legal_helper.case_intelligence.classifier import classify_case_type, _heuristic_fallback


def test_heuristic_fallback_categories():
    """키워드 기반 사건 분류 휴리스틱 폴백 정확도 검증."""
    # 주택임대차
    assert _heuristic_fallback("전세보증금 반환 청구 소송") == "주택임대차 (보증금/원상복구/계약갱신)"
    assert _heuristic_fallback("월세 계약 만료 후 원상복구 분쟁") == "주택임대차 (보증금/원상복구/계약갱신)"
    
    # 상가임대차
    assert _heuristic_fallback("상가 권리금 회수 방해 손해배상") == "상가임대차 (권리금/임대료 분쟁)"
    
    # 근로 및 임금체불
    assert _heuristic_fallback("퇴직금 및 주휴수당 미지급 진정") == "근로 및 임금체불 (퇴직금/부당해고/산재)"
    assert _heuristic_fallback("부당해고 구제신청") == "근로 및 임금체불 (퇴직금/부당해고/산재)"
    
    # 형사
    assert _heuristic_fallback("투자 사기 및 횡령 고소장 작성") == "형사 사건 (사기/횡령/폭행/고소)"
    
    # 가사
    assert _heuristic_fallback("이혼 및 재산분할 청구") == "가사 분쟁 (이혼/재산분할/상속/유류분)"
    assert _heuristic_fallback("상속재산분할 및 유류분 반환") == "가사 분쟁 (이혼/재산분할/상속/유류분)"
    
    # 대여금/채권
    assert _heuristic_fallback("차용증 기반 대여금 반환 소송") == "대여금 및 채권추심 (차용증/미수금)"
    
    # 행정/조세
    assert _heuristic_fallback("일반음식점 영업정지 처분 취소 행정심판") == "행정 및 조세 (영업정지/처분취소/과징금)"


def test_classify_case_type_empty_and_default():
    """빈 입력 또는 일반 분쟁 시 기본값 정상 반환 검증."""
    assert classify_case_type("", "") == "일반 민사 분쟁"
    assert classify_case_type("기타 일상 분쟁입니다") == "일반 민사 분쟁"

