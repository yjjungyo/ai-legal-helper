# -*- coding: utf-8 -*-
"""SC-001 승인된 사건 원문만 작성·검증 근거로 사용."""
from ai_legal_helper.workflows.document_consultation import document_sources


def test_only_approved_nonempty_case_documents_are_grounding_sources():
    state = {
        "case_evidence_briefing": {
            "source_documents": [
                {"document_name": "E01_contract.txt", "review_status": "APPROVED", "content": "계약 내용"},
                {"document_name": "E02_pending.txt", "review_status": "PENDING", "content": "미승인 내용"},
                {"document_name": "E03_empty.txt", "review_status": "APPROVED", "content": ""},
            ]
        },
        "retrieved_sources": [
            {"source_id": "LAW:1", "source_type": "STATUTE", "content": "법률 조문"}
        ],
    }
    sources = document_sources(state)
    assert [s["source_id"] for s in sources] == ["E01_contract.txt", "LAW:1"]
    assert "미승인 내용" not in str(sources)
