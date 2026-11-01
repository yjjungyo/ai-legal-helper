"""P4.2 frozen presentation snapshot.

The snapshot is written once after consultation finalization and validated without
reading live EvidenceDocument, GraphDB or statute index. Hashes detect accidental
mutation (they are not digital signatures or tamper-proof audit logs).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from ai_legal_helper.api.schemas.consultation import ConsultationPresentation
from ai_legal_helper.presentation.builder import build_consultation_presentation

SNAPSHOT_VERSION = "1.0"


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_sources(sources: Sequence[Any] | None) -> list[dict]:
    normalized = []
    for source in sources or []:
        if isinstance(source, dict):
            normalized.append(source)
        elif hasattr(source, "model_dump"):
            normalized.append(source.model_dump(mode="json"))
        else:
            raise ValueError("UNSUPPORTED_SNAPSHOT_SOURCE")
    return normalized


def freeze_presentation(
    *, answer: str | None, verification_result: Mapping[str, Any] | None,
    verification_status: str | None, answer_status: str | None,
    sources: Sequence[Any] | None,
    captured_at: str | None = None,
    request_id: str | None = None,
    case_id: str | None = None,
) -> Optional[dict]:
    """Freeze a verified presentation and fingerprints of the original registry.

    Unsupported or withheld answers are never silently converted into verified
    records; the caller stores a NULL snapshot.
    """
    verification = dict(verification_result or {})
    original_sources = _normalized_sources(sources)
    presentation = build_consultation_presentation(
        answer=answer,
        verification_result=verification,
        verification_status=verification_status,
        answer_status=answer_status,
        sources=original_sources,
    )
    if presentation is None:
        return None
    payload = {
        "snapshot_version": SNAPSHOT_VERSION,
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "case_id": case_id,
        "answer_status": answer_status,
        "verification_status": verification_status,
        "answer_sha256": presentation.source_answer_sha256,
        "sources_sha256": _canonical_hash(original_sources),
        "verification_sha256": _canonical_hash(verification),
        "presentation": presentation.model_dump(mode="json"),
    }
    return {**payload, "snapshot_sha256": _canonical_hash(payload)}


def validate_presentation_snapshot(
    snapshot: Any, *, answer: str | None,
    verification_result: Mapping[str, Any] | None,
    sources: Sequence[Any] | None,
    request_id: str | None = None,
    case_id: str | None = None,
    verification_status: str | None = None,
    answer_status: str | None = None,
) -> Optional[ConsultationPresentation]:
    """Never repair or regenerate an invalid persisted snapshot on read."""
    if not isinstance(snapshot, dict) or snapshot.get("snapshot_version") != SNAPSHOT_VERSION:
        return None
    envelope = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    if not isinstance(snapshot.get("snapshot_sha256"), str):
        return None
    try:
        if _canonical_hash(envelope) != snapshot["snapshot_sha256"]:
            return None
        if request_id is not None and snapshot.get("request_id") != request_id:
            return None
        if case_id is not None and snapshot.get("case_id") != case_id:
            return None
        if verification_status is not None and snapshot.get("verification_status") != verification_status:
            return None
        if answer_status is not None and snapshot.get("answer_status") != answer_status:
            return None
        if not isinstance(answer, str) or hashlib.sha256(answer.encode("utf-8")).hexdigest() != snapshot.get("answer_sha256"):
            return None
        if _canonical_hash(_normalized_sources(sources)) != snapshot.get("sources_sha256"):
            return None
        if _canonical_hash(dict(verification_result or {})) != snapshot.get("verification_sha256"):
            return None
        presentation = ConsultationPresentation.model_validate(snapshot["presentation"])
        if presentation.schema_version != "1.0":
            return None
        if presentation.source_answer_sha256 != snapshot["answer_sha256"]:
            return None
        if "".join(block.markdown for block in presentation.blocks) != answer:
            return None
        if any(answer[block.start:block.end] != block.markdown for block in presentation.blocks):
            return None
        source_ids = {s.source_id for s in presentation.sources}
        claim_ids = {c.claim_id for c in presentation.claims}
        if any(set(block.source_refs) - source_ids or set(block.claim_refs) - claim_ids for block in presentation.blocks):
            return None
        if any(set(claim.source_refs) - source_ids or answer[claim.start:claim.end] != claim.text for claim in presentation.claims):
            return None
        return presentation
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def freeze_record_once(record: Any, response: Any) -> Optional[dict]:
    """Commit-time gate: a persisted historical snapshot is never overwritten.

    Caller must invoke this in the same DB transaction after writing the final
    answer, sources and verification result. Raising aborts the transaction.
    """
    existing = getattr(record, "presentation_snapshot", None)
    if existing is not None:
        checked = validate_presentation_snapshot(
            existing, answer=record.answer,
            verification_result=record.verification_result,
            sources=record.sources,
            request_id=getattr(record, "request_id", None),
            case_id=getattr(record, "case_id", None),
            verification_status=getattr(record, "verification_status", None),
            answer_status=getattr(record, "answer_status", None),
        )
        if checked is None:
            raise ValueError("FROZEN_PRESENTATION_RECORD_CHANGED")
        return existing
    if getattr(response, "status", "") != "SUCCESS":
        return None
    frozen = freeze_presentation(
        answer=record.answer,
        verification_result=record.verification_result,
        verification_status=record.verification_status,
        answer_status=record.answer_status,
        sources=record.sources,
        request_id=getattr(record, "request_id", None),
        case_id=getattr(record, "case_id", None),
    )
    if frozen is not None:
        record.presentation_snapshot = frozen
    return frozen
