"""Feature-flagged consultation source selection regression."""
from ai_legal_helper.workflows.document_consultation import document_sources


def state():
    return {
        "case_evidence_briefing": {
            "source_documents": [{
                "evidence_id": "doc-1", "document_name": "통화녹취록.txt",
                "review_status": "APPROVED", "content": "full original evidence text",
            }],
        },
        "verified_graph_source_pack": [{
            "source_id": "통화녹취록.txt", "document_name": "통화녹취록.txt",
            "content": "short verified excerpt", "source_type": "CASE_EVIDENCE",
        }],
        "graph_evidence": {
            "search_mode": "VERIFIED_GRAPH_EXACT_SPAN",
            "evidence_gaps": [], "invalid_count": 0,
        },
        "retrieved_sources": [{
            "source_id": "LAW:1", "source_type": "STATUTE", "content": "law text",
        }],
    }


def test_default_keeps_full_original(monkeypatch):
    monkeypatch.delenv("COMPOSITE_GRAPHRAG_CONSULTATION", raising=False)
    sources = document_sources(state())
    assert sources[0]["content"] == "full original evidence text"
    assert any(s["source_id"] == "LAW:1" for s in sources)


def test_opt_in_uses_verified_excerpt(monkeypatch):
    monkeypatch.setenv("COMPOSITE_GRAPHRAG_CONSULTATION", "true")
    sources = document_sources(state())
    assert sources[0]["content"] == "short verified excerpt"
    assert any(s["source_id"] == "LAW:1" for s in sources)


def test_graph_gaps_force_original_fallback(monkeypatch):
    monkeypatch.setenv("COMPOSITE_GRAPHRAG_CONSULTATION", "true")
    data = state()
    data["graph_evidence"]["evidence_gaps"] = [{"missing": "contract"}]
    assert document_sources(data)[0]["content"] == "full original evidence text"


def test_invalid_graph_paths_force_original_fallback(monkeypatch):
    monkeypatch.setenv("COMPOSITE_GRAPHRAG_CONSULTATION", "true")
    data = state()
    data["graph_evidence"]["invalid_count"] = 1
    assert document_sources(data)[0]["content"] == "full original evidence text"
