# -*- coding: utf-8 -*-
"""SC-001: 특별법 검색 완전성은 특정 법령명 하드코딩 없이 검증해야 한다.

TODO: Law Resolver가 제공한 필수 법령 목록을 검색 결과와 비교하는
범용 게이트가 구현되면 해당 계약을 검증하는 테스트로 교체한다.
"""


def test_special_law_coverage_contract_is_not_case_specific():
    # 법령명과 법률 분야를 고정한 임시 게이트는 제거했다.
    from ai_legal_helper.workflows import document_consultation

    assert not hasattr(document_consultation, "enforce_housing_special_law_coverage")
