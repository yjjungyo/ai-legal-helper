"""P4.3 evidence manifest regression. No DB required."""
from ai_legal_helper.presentation.evidence_manifest import build_manifest, compare_case_evidence_manifests

def source(id, name, status="APPROVED", claim=""):
    return {"evidence_id": id, "filename": name, "sha256": "sha-"+id,
            "status": status, "claims_hash": claim, "claims_count": 1 if claim else 0}

def test_order_independent_manifest_and_identical_status():
    a = build_manifest([source("a","E01_계약서.txt"),source("b","E02_송금.txt")])
    b = build_manifest([source("b","E02_송금.txt"),source("a","E01_계약서.txt")])
    assert a == b
    assert compare_case_evidence_manifests(a,b)["status"] == "CURRENT"

def test_new_document_is_detected_and_full_name_is_shown():
    old = build_manifest([source("a","E01_계약서.txt")])
    new = build_manifest([source("a","E01_계약서.txt"),source("b","E10_가압류_등기자료.pdf")])
    diff = compare_case_evidence_manifests(old,new)
    assert diff["status"] == "EVIDENCE_CHANGED"
    assert diff["added"] == ["E10_가압류_등기자료.pdf"]
    assert diff["removed"] == []
    assert diff["modified"] == []

def test_deleted_document_is_detected():
    old = build_manifest([source("a","E01_계약서.txt"),source("b","E02_등기.pdf")])
    new = build_manifest([source("a","E01_계약서.txt")])
    assert compare_case_evidence_manifests(old,new)["removed"] == ["E02_등기.pdf"]

def test_extraction_review_or_claim_edit_is_detected():
    old = build_manifest([source("a","E01_계약서.txt",status="REVIEW_REQUIRED",claim="c1")])
    new = build_manifest([source("a","E01_계약서.txt",status="APPROVED",claim="c2")])
    diff = compare_case_evidence_manifests(old,new)
    assert diff["modified"] == ["E01_계약서.txt"]
    assert diff["status"] == "EVIDENCE_CHANGED"

def test_pending_state_reported_without_pretending_analysis_is_ready():
    old = build_manifest([])
    new = build_manifest([source("c","E03_새자료.pdf",status="EXTRACTING")])
    assert compare_case_evidence_manifests(old,new)["pending_count"] == 1

def test_legacy_baseline_must_not_be_called_current():
    assert compare_case_evidence_manifests(None,build_manifest([]))["status"] == "UNKNOWN_BASELINE"

def test_duplicate_ids_rejected():
    import pytest
    with pytest.raises(ValueError):
        build_manifest([source("a","E01.txt"),source("a","E02.txt")])

def test_tampered_historical_evidence_fingerprint_is_not_trusted():
    import copy
    saved = build_manifest([source("a", "E01_계약서.txt")])
    forged = copy.deepcopy(saved)
    forged["documents"][0]["filename"] = "E99_조작된자료.txt"
    assert compare_case_evidence_manifests(forged, saved)["status"] == "UNKNOWN_BASELINE"
