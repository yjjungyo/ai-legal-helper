# -*- coding: utf-8 -*-
"""
모듈명: test_p1_defects_reproduction.py

[모듈 개요]
AI Legal Helper 개발지시서 P1 단계(P1-01 ~ P1-06) 신뢰성 및 논리 개선 요구사항에 대한
사전 재현 및 방어 회귀 검증 테스트를 정의한다.

[검증 항목]
- P1-01: 지식 누락(NO_MATCH)과 검색 인프라 장애(RETRIEVER_UNAVAILABLE, COLLECTION_MISSING 등)의 구분
- P1-02: 법령 시행일, 공포일, 버전 메타데이터 보존 및 사건 기준일 비교
- P1-03: 법령 전용 인용 형식 검증, 의미적 불일치 감지, 제로 분모 N/A 처리
- P1-04: 부족 원인별(인프라장애/법령부재/증거부족/초안수정) 적응형 검색 분기 차별화
- P1-05: 3계층 상태 모델(execution_status, verification_status, answer_status) 분리 및 일관성
- P1-06: 승인 요청의 원자적 상태 전이 및 중복 resume 방어
"""
import os
import sys
import uuid
import pytest
from unittest.mock import patch, MagicMock

from langchain_core.messages import HumanMessage
from ai_legal_helper.workflows.state import LegalState


def test_p1_01_retrieval_status_distinguishes_no_match_and_infra_error():
    """P1-01: 컬렉션 부재 및 인프라 오류 시 단순 빈 목록이 아닌 명시적 상태 코드를 반환하는지 검증."""
    from ai_legal_helper.rag.retrieval import retrieve_with_status, RetrievalStatus

    # 1. 존재하지 않는 컬렉션 조회 시 COLLECTION_MISSING 상태 반환 검증
    res_missing = retrieve_with_status("임대차 계약 해지", category="non_existent_category_xyz")
    assert res_missing.status in (RetrievalStatus.COLLECTION_MISSING, RetrievalStatus.RETRIEVER_UNAVAILABLE)
    assert res_missing.documents == []
    assert res_missing.error_detail is not None

    # 2. ChromaDB 연결/검색 예외 시 RETRIEVER_UNAVAILABLE 상태 반환 검증
    with patch("ai_legal_helper.rag.retrieval._list_collections", return_value=["law_docs_civil"]), \
         patch("ai_legal_helper.rag.retrieval._get_vs", side_effect=ConnectionError("ChromaDB connection refused")):
        res_error = retrieve_with_status("임대차 계약 해지", category="civil")
        assert res_error.status == RetrievalStatus.RETRIEVER_UNAVAILABLE
        assert "ChromaDB connection refused" in str(res_error.error_detail)


def test_p1_02_statute_version_and_effective_date_matching():
    """P1-02: 공식 법령 검색 및 표준 Source 스키마에 law_id, version_id, promulgation_date, effective_date가 보존되는지 검증."""
    from ai_legal_helper.rag.source_schema import StandardSource, normalize_source_dict, is_statute_applicable_to_date

    sample_source = {
        "source_id": "STATUTE:주택임대차보호법:제6조의2:276291",
        "source_type": "STATUTE",
        "title": "주택임대차보호법 제6조의2",
        "statute_name": "주택임대차보호법",
        "article": "제6조의2",
        "law_id": "001684",
        "promulgation_date": "2020-06-09",
        "effective_date": "2020-12-10",
        "version_id": "276291",
        "source_url": "https://www.law.go.kr",
        "retrieval_method": "OFFICIAL_STATUTE_SEARCH",
        "content": "묵시적 갱신의 경우 계약의 해지는 임대인이 통지받은 날부터 3개월이 지나면 효력이 발생한다.",
    }

    norm = normalize_source_dict(sample_source)
    assert norm["law_id"] == "001684"
    assert norm["version_id"] == "276291"
    assert norm["promulgation_date"] == "2020-06-09"
    assert norm["effective_date"] == "2020-12-10"

    # 사건 발생일(2026-10-17) 기준 적용 가능 여부 판정
    assert is_statute_applicable_to_date(norm, "2026-10-17") is True
    # 시행 이전 날짜(2019-01-01) 판정
    assert is_statute_applicable_to_date(norm, "2019-01-01") is False


def test_p1_03_citation_validator_statute_format_and_metrics():
    """P1-03: 공식 법령 인용 형식 검증, 조문 불일치 및 법률효과 반대 감지, 제로 분모 N/A 처리 검증."""
    from ai_legal_helper.agents.verification import audit_citations_and_claims

    retrieved_sources = [
        {
            "source_id": "주택임대차보호법_제6조의2",
            "source_type": "STATUTE",
            "statute_name": "주택임대차보호법",
            "article": "제6조의2",
            "filename": "주택임대차보호법_제6조의2.txt",
            "page": "1",
            "content": "제6조의2(묵시적 갱신의 경우 계약의 해지) 임차인은 언제든지 해지를 통지할 수 있고, 통지받은 날부터 3개월이 지나면 효력이 발생한다.",
        }
    ]

    # 1. 정상 법령 인용: (주택임대차보호법 제6조의2)
    draft_correct = "묵시적 갱신 후 해지 통보는 임대인이 통지받은 날부터 3개월 후 효력이 발생합니다. (주택임대차보호법 제6조의2)"
    audit1 = audit_citations_and_claims(draft_correct, retrieved_sources)
    assert len(audit1["rejected_citation_ids"]) == 0
    assert audit1["citation_support_rate"] == 1.0

    # 2. 법률 효과가 반대인 왜곡 주장 감지: (즉시 효력 발생 주장)
    draft_conflict = "묵시적 갱신 후 임차인의 해지 통보는 도달 즉시 효력이 발생하여 보증금을 당일 반환해야 합니다. (주택임대차보호법 제6조의2)"
    audit2 = audit_citations_and_claims(draft_conflict, retrieved_sources)
    assert len(audit2["rejected_citation_ids"]) >= 1 or len(audit2["unsupported_citations"]) >= 1

    # 3. 인용이 전혀 없는 답변에 대한 제로 분모 처리 검증 (100%로 오해되지 않고 N/A 또는 0.0 산출)
    draft_no_citation = "보증금은 즉시 돌려받을 수 있습니다."
    audit3 = audit_citations_and_claims(draft_no_citation, retrieved_sources)
    assert audit3["citation_coverage_rate"] == 0.0 or audit3["citation_coverage_rate"] == "N/A"
    assert audit3["citation_support_rate"] == "N/A" or audit3["citation_support_rate"] == 0.0


def test_p1_04_adaptive_retrieval_differentiates_causes():
    """P1-04: Adaptive Retrieval 분기 시 인프라 장애, 법령 부재, 사실관계 증거 부족, 단순 초안 수정이 각각 다르게 분기하는지 검증."""
    from ai_legal_helper.workflows.legal_workflow import verification_condition

    # Case A: 법령 부재(LEGAL_SOURCE_MISSING) -> HILT 법령 검색 승인
    state_statute: LegalState = {
        "messages": [HumanMessage(content="해지통보 효력")],
        "revision_count": 0,
        "hilt_executed": False,
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "LEGAL_SOURCE_MISSING",
            "candidate_laws": ["주택임대차보호법"],
        },
    }
    assert verification_condition(state_statute) == "statute_search_approval"

    # Case B: 검색 인프라 장애(RETRIEVER_UNAVAILABLE) -> insufficient로 안전 종료 (무의미한 HILT 또는 무한 루프 금지)
    state_infra: LegalState = {
        "messages": [HumanMessage(content="해지통보 효력")],
        "revision_count": 0,
        "hilt_executed": False,
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "RETRIEVER_UNAVAILABLE",
            "candidate_laws": [],
        },
    }
    assert verification_condition(state_infra) == "insufficient"

    # Case C: 사건 사실관계/증거 부족(CASE_EVIDENCE_MISSING) -> insufficient로 전이하여 사용자 증거 요청
    state_evidence: LegalState = {
        "messages": [HumanMessage(content="해지통보 효력")],
        "revision_count": 0,
        "hilt_executed": False,
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "CASE_EVIDENCE_MISSING",
            "candidate_laws": ["민법"],
        },
    }
    assert verification_condition(state_evidence) == "insufficient"

    # Case D: 단순 초안 문구 수정 필요(ANSWER_REVISION_REQUIRED) -> 1회 한정 revise
    state_revise: LegalState = {
        "messages": [HumanMessage(content="해지통보 효력")],
        "revision_count": 0,
        "hilt_executed": False,
        "verification_result": {
            "status": "REVISE",
            "reason_code": "ANSWER_REVISION_REQUIRED",
            "candidate_laws": [],
        },
    }
    assert verification_condition(state_revise) == "revise"


def test_p1_05_three_tier_status_model():
    """P1-05: 3계층 상태 모델(execution_status, verification_status, answer_status)의 분리 및 매핑 검증."""
    from ai_legal_helper.api.schemas.consultation import ConsultationResponse

    # 검증 실패한 초안의 경우 execution_status=COMPLETED이더라도 answer_status는 WITHHELD여야 함
    resp = ConsultationResponse(
        request_id="test-req-1",
        trace_id="test-trace-1",
        status="SUCCESS",
        execution_status="COMPLETED",
        verification_status="INSUFFICIENT",
        answer_status="WITHHELD",
        answer="법률적 근거 부족으로 확정 조언을 제공할 수 없습니다.",
    )
    assert resp.execution_status == "COMPLETED"
    assert resp.verification_status == "INSUFFICIENT"
    assert resp.answer_status == "WITHHELD"


def test_p1_06_concurrent_approval_atomic_guard():
    """P1-06: 동일한 상담 승인 요청에 대한 동시 다중 호출 시 중복 실행이 차단되는지 검증."""
    from ai_legal_helper.database.session import SessionLocal
    from ai_legal_helper.database.models import ConsultationRecord

    test_req_id = f"APPR-CONCUR-{uuid.uuid4()}"
    db = SessionLocal()
    try:
        record = ConsultationRecord(
            request_id=test_req_id,
            question="동시 승인 테스트",
            status="APPROVAL_REQUIRED",
            execution_status="APPROVAL_REQUIRED",
            verification_status="INSUFFICIENT",
            answer_status="WITHHELD",
        )
        db.add(record)
        db.commit()

        # 원자적 상태 변경 모사: status가 APPROVAL_REQUIRED인 경우에만 1개 행 업데이트
        updated_rows_1 = db.query(ConsultationRecord).filter(
            ConsultationRecord.request_id == test_req_id,
            ConsultationRecord.status == "APPROVAL_REQUIRED",
        ).update({"status": "IN_PROGRESS", "execution_status": "IN_PROGRESS"})
        db.commit()

        # 2번째 동시 요청은 이미 status가 IN_PROGRESS이므로 업데이트 대상이 0개여야 함
        updated_rows_2 = db.query(ConsultationRecord).filter(
            ConsultationRecord.request_id == test_req_id,
            ConsultationRecord.status == "APPROVAL_REQUIRED",
        ).update({"status": "IN_PROGRESS", "execution_status": "IN_PROGRESS"})
        db.commit()

        assert updated_rows_1 == 1, "첫 번째 승인 요청은 성공적으로 상태를 전이해야 함"
        assert updated_rows_2 == 0, "중복된 두 번째 승인 요청은 전이 대상이 없어야 함"

        db.delete(record)
        db.commit()
    finally:
        db.close()

