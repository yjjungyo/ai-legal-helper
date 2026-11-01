"""P4.2 frozen presentation snapshot unit tests."""
import copy
import hashlib

from ai_legal_helper.presentation.snapshot import freeze_presentation, validate_presentation_snapshot


def fixture():
    answer = "확인된 내용입니다.\n\n### 법적 근거\n민법 제6조입니다."
    verified = {"status": "PASS", "verified_answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
                "claims": [{"claim": "확인된 내용입니다.", "claim_type": "CASE_FACT",
                            "fact_status": "VERIFIED_FACT", "source_ids": ["E1"],
                            "grounding_status": "SUPPORTED"}]}
    sources = [{"source_id": "E1", "source_type": "CASE_EVIDENCE",
                "filename": "E01_계약서.txt", "evidence_id": "uuid-original",
                "text_excerpt": "원문에 기재된 사실"}]
    return answer, verified, sources


def freeze_fixture():
    answer, verified, sources = fixture()
    result = freeze_presentation(
        answer=answer, verification_result=verified,
        verification_status="PASS", answer_status="DELIVERED",
        sources=sources, captured_at="2026-11-01T00:00:00+00:00",
    )
    assert result is not None
    return answer, verified, sources, result


def test_snapshot_stores_version_and_exact_original_evidence_names():
    answer, verified, sources, snapshot = freeze_fixture()
    assert snapshot["snapshot_version"] == "1.0"
    assert snapshot["presentation"]["sources"][0]["document_name"] == "E01_계약서.txt"
    assert snapshot["answer_sha256"] == hashlib.sha256(answer.encode()).hexdigest()
    restored = validate_presentation_snapshot(snapshot, answer=answer, verification_result=verified, sources=sources)
    assert restored is not None
    assert "".join(b.markdown for b in restored.blocks) == answer


def test_live_evidence_changes_cannot_affect_frozen_snapshot():
    answer, verified, sources, snapshot = freeze_fixture()
    # The current evidence database can change. The original consultation's own
    # persisted source record remains the authoritative historical input.
    new_live_document = {"source_id": "E1", "filename": "후속_수정본.txt"}
    assert new_live_document["filename"] != sources[0]["filename"]
    assert validate_presentation_snapshot(snapshot, answer=answer, verification_result=verified, sources=sources)


def test_tampering_with_answer_sources_verification_or_snapshot_fails_closed():
    answer, verified, sources, snapshot = freeze_fixture()
    assert validate_presentation_snapshot(snapshot, answer=answer+"변경", verification_result=verified, sources=sources) is None
    changed_sources = copy.deepcopy(sources)
    changed_sources[0]["filename"] = "E02_다른자료.txt"
    assert validate_presentation_snapshot(snapshot, answer=answer, verification_result=verified, sources=changed_sources) is None
    changed_verification = copy.deepcopy(verified)
    changed_verification["status"] = "REVISE"
    assert validate_presentation_snapshot(snapshot, answer=answer, verification_result=changed_verification, sources=sources) is None
    changed_snapshot = copy.deepcopy(snapshot)
    changed_snapshot["presentation"]["blocks"][0]["markdown"] = "다른 답변"
    assert validate_presentation_snapshot(changed_snapshot, answer=answer, verification_result=verified, sources=sources) is None


def test_invalid_snapshot_is_never_upgraded_from_stored_sources():
    answer, verified, sources, snapshot = freeze_fixture()
    snapshot["snapshot_version"] = "2.0"
    assert validate_presentation_snapshot(snapshot, answer=answer, verification_result=verified, sources=sources) is None


def test_unverified_or_withheld_do_not_get_frozen_snapshot():
    answer, verified, sources = fixture()
    assert freeze_presentation(answer=answer, verification_result=verified,
                               verification_status="REVISE", answer_status="CAUTIONARY", sources=sources) is None
    assert freeze_presentation(answer=answer, verification_result=verified,
                               verification_status="PASS", answer_status="WITHHELD", sources=sources) is None


def test_missing_original_verification_sha_is_preserved_as_weaker_binding():
    answer, verified, sources = fixture()
    verified.pop("verified_answer_sha256")
    snap = freeze_presentation(answer=answer, verification_result=verified,
                               verification_status="PASS", answer_status="DELIVERED", sources=sources)
    assert snap is not None
    assert snap["presentation"]["verification_binding"] == "STATUS_MATCHED"


def test_write_once_rejects_changed_answer_and_preserves_original_snapshot():
    from types import SimpleNamespace
    from ai_legal_helper.presentation.snapshot import freeze_record_once
    answer, verified, sources = fixture()
    rec = SimpleNamespace(
        answer=answer, verification_result=verified, verification_status="PASS",
        answer_status="DELIVERED", sources=sources, presentation_snapshot=None,
    )
    resp = SimpleNamespace(status="SUCCESS")
    frozen = freeze_record_once(rec, resp)
    assert frozen is rec.presentation_snapshot
    assert freeze_record_once(rec, resp) == frozen
    rec.answer = answer + "다른 결론"
    try:
        freeze_record_once(rec, resp)
    except ValueError as exc:
        assert "FROZEN_PRESENTATION_RECORD_CHANGED" in str(exc)
    else:
        raise AssertionError("expected immutable snapshot protection")
    assert rec.presentation_snapshot == frozen


def test_invalid_non_dict_snapshot_fails_closed():
    answer, verified, sources = fixture()
    assert validate_presentation_snapshot("invalid", answer=answer, verification_result=verified, sources=sources) is None
    assert validate_presentation_snapshot(None, answer=answer, verification_result=verified, sources=sources) is None


def test_wrong_request_or_case_identity_rejected():
    answer, verified, sources = fixture()
    from ai_legal_helper.presentation.snapshot import freeze_presentation
    snap = freeze_presentation(
        answer=answer, verification_result=verified,
        verification_status="PASS", answer_status="DELIVERED",
        sources=sources, request_id="consult-1", case_id="case-1",
    )
    assert validate_presentation_snapshot(
        snap, answer=answer, verification_result=verified, sources=sources,
        request_id="consult-2", case_id="case-1",
        verification_status="PASS", answer_status="DELIVERED",
    ) is None
    assert validate_presentation_snapshot(
        snap, answer=answer, verification_result=verified, sources=sources,
        request_id="consult-1", case_id="case-1",
        verification_status="PASS", answer_status="WITHHELD",
    ) is None
