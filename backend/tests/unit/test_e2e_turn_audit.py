# -*- coding: utf-8 -*-
"""E2E V6 1단계: 외부 DB/LLM 없이 시간순 증거 격리와 Trace 프로비넌스 회귀 검사."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.evaluation.e2e_turn_audit import answer_provenance, evidence_snapshot


def _doc(name: str, payload: bytes, *, evidence_id: str = "id"):
    return SimpleNamespace(
        id=evidence_id, original_filename=name,
        sha256=sha256(payload).hexdigest(), status="APPROVED",
    )


def _stages(tmp_path: Path):
    evidence_base = tmp_path / "증거"
    first, second, third = (evidence_base / f"{idx}차" for idx in (1, 2, 3))
    for directory in (first, second, third):
        directory.mkdir(parents=True)
    samples = {
        "E01_계약서.txt": b"lease",
        "E02_계좌내역.txt": b"receipt",
        "E03_사망진단서.txt": b"death",
        "E04_상속인자료.txt": b"heirs",
        "E05_장남문자.txt": b"future claim",
    }
    for idx, name in enumerate(samples):
        directory = first if idx < 2 else second if idx < 4 else third
        (directory / name).write_bytes(samples[name])
    return evidence_base, samples


def test_turn_two_snapshot_excludes_future_third_turn(tmp_path):
    base, samples = _stages(tmp_path)
    documents = [_doc(name, data, evidence_id=f"doc-{idx}") for idx, (name, data) in enumerate(list(samples.items())[:4])]
    manifest = evidence_snapshot(case_id="fresh-case", turn_index=2, evidence_base=str(base), documents=documents)
    assert manifest["scope_status"] == "MATCHED"
    assert manifest["document_count"] == 4
    assert manifest["case_id"] == "fresh-case"
    assert all(not name.startswith("E05") for name in manifest["expected_filenames"])
    assert len(manifest["manifest_sha256"]) == 64


def test_stage_one_does_not_require_later_evidence(tmp_path):
    base, samples = _stages(tmp_path)
    names = list(samples)[:2]
    manifest = evidence_snapshot(case_id="new", turn_index=1, evidence_base=str(base),
                                 documents=[_doc(n, samples[n]) for n in names])
    assert manifest["document_count"] == 2


def test_future_evidence_in_db_fails_before_consultation(tmp_path):
    base, samples = _stages(tmp_path)
    documents = [_doc(n, v) for n, v in samples.items()]
    with pytest.raises(ValueError, match="EVIDENCE_STAGE_MISMATCH.*E05"):
        evidence_snapshot(case_id="reused-case", turn_index=2, evidence_base=str(base), documents=documents)


def test_missing_document_in_db_is_not_silently_ignored(tmp_path):
    base, samples = _stages(tmp_path)
    with pytest.raises(ValueError, match="EVIDENCE_STAGE_MISMATCH.*E04"):
        evidence_snapshot(case_id="new", turn_index=2, evidence_base=str(base),
                          documents=[_doc(n, samples[n]) for n in list(samples)[:3]])


def test_duplicate_db_document_is_rejected(tmp_path):
    base, samples = _stages(tmp_path)
    documents = [_doc(n, v) for n, v in list(samples.items())[:4]]
    documents.append(_doc("E04_상속인자료.txt", samples["E04_상속인자료.txt"]))
    with pytest.raises(ValueError, match="duplicates"):
        evidence_snapshot(case_id="new", turn_index=2, evidence_base=str(base), documents=documents)


def test_content_digest_mismatch_is_rejected(tmp_path):
    base, samples = _stages(tmp_path)
    documents = [_doc(n, v) for n, v in list(samples.items())[:4]]
    documents[0].sha256 = sha256(b"tampered").hexdigest()
    with pytest.raises(ValueError, match="EVIDENCE_HASH_MISMATCH"):
        evidence_snapshot(case_id="new", turn_index=2, evidence_base=str(base), documents=documents)


def test_missing_stage_directory_is_rejected(tmp_path):
    base, samples = _stages(tmp_path)
    (base / "2차").rename(base / "archived")
    with pytest.raises(ValueError, match="missing evidence stage directory"):
        evidence_snapshot(case_id="new", turn_index=2, evidence_base=str(base), documents=[])


def test_duplicate_names_across_stages_rejected(tmp_path):
    base, _ = _stages(tmp_path)
    (base / "2차" / "E01_계약서.txt").write_bytes(b"duplicate")
    with pytest.raises(ValueError, match="duplicate staged evidence filename"):
        evidence_snapshot(case_id="new", turn_index=2, evidence_base=str(base), documents=[])


def test_provenance_exact_match():
    p = answer_provenance("final answer", {
        "observations": [{"name": "finalize_node", "output": {"answer": "final answer"}}]
    })
    assert p["status"] == "MATCH" and p["same_text"] is True
    assert p["api_answer_sha256"] == p["workflow_answer_sha256"]


def test_provenance_preserves_different_workflow_and_api_answers():
    # SC-012에서 확인한 것처럼 출력 층의 차이는 지우지 않는다.
    p = answer_provenance("answer after presentation", {
        "observations": [{"name": "finalize_node", "output": {"answer": "raw final answer"}}]
    })
    assert p["status"] == "DIFFERENT" and p["same_text"] is False
    assert p["api_answer_sha256"] != p["workflow_answer_sha256"]
    assert p["api_answer_length"] == len("answer after presentation")
    assert p["workflow_answer_length"] == len("raw final answer")


@pytest.mark.parametrize("trace,reason", [
    (None, "TRACE_OBSERVATIONS_UNAVAILABLE"),
    ({}, "TRACE_OBSERVATIONS_UNAVAILABLE"),
    ({"observations": []}, "FINALIZE_NODE_UNAVAILABLE"),
    ({"observations": [{"name": "finalize_node", "output": {}}]}, "FINALIZE_ANSWER_UNAVAILABLE"),
])
def test_provenance_unknown_is_never_reported_as_match(trace, reason):
    p = answer_provenance("api", trace)
    assert p["status"] == "UNAVAILABLE"
    assert p["same_text"] is None
    assert p["reason"] == reason


def test_no_api_answer_not_compared_to_final():
    p = answer_provenance(None, {"observations": [
        {"name": "finalize_node", "output": {"answer": "draft"}}
    ]})
    assert p["status"] == "UNAVAILABLE"
    assert p["reason"] == "NO_API_ANSWER"
