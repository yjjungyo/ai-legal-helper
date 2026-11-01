"""Consultation-time evidence manifest and deterministic case change tracking.

No LLM use and no interpretation of whether a document is legally decisive.
Source document content is NOT duplicated; evidence SHA, IDs, statuses and
hashed claim assertions are captured for change detection.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional



def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def build_manifest(documents: list[dict]) -> dict:
    normalized = []
    for doc in documents:
        item = {
            "evidence_id": str(doc["evidence_id"]),
            "filename": str(doc["filename"]),
            "sha256": str(doc.get("sha256") or ""),
            "status": str(doc.get("status") or ""),
            "claims_hash": str(doc.get("claims_hash") or ""),
            "spans_hash": str(doc.get("spans_hash") or ""),
            "extraction_version": str(doc.get("extraction_version") or ""),
            "claims_count": int(doc.get("claims_count") or 0),
        }
        normalized.append(item)
    normalized.sort(key=lambda d: d["evidence_id"])
    if len({d["evidence_id"] for d in normalized}) != len(normalized):
        raise ValueError("DUPLICATE_EVIDENCE_IDS")
    return {"version": "1.0", "documents": normalized,
            "fingerprint": canonical_hash(normalized)}


def capture_case_evidence_manifest(db: Any, case_id: Optional[str]) -> Optional[dict]:
    if not case_id:
        return None
    from ai_legal_helper.database.models import EvidenceDocument, EvidenceClaim, EvidenceSpan
    docs = db.query(EvidenceDocument).filter(EvidenceDocument.case_id == case_id).all()
    claims = db.query(EvidenceClaim).filter(EvidenceClaim.case_id == case_id).all()
    spans = db.query(EvidenceSpan).filter(
        EvidenceSpan.evidence_id.in_([d.id for d in docs])
    ).all() if docs else []
    spans_by_doc: dict[str, list[dict]] = {}
    for span in spans:
        spans_by_doc.setdefault(span.evidence_id, []).append({
            "id": span.id,
            "text_sha256": hashlib.sha256((span.text_excerpt or "").encode("utf-8")).hexdigest(),
            "location": [span.page_number, span.paragraph_index, span.char_start, span.char_end],
        })
    by_doc: dict[str, list[dict]] = {}
    for claim in claims:
        by_doc.setdefault(claim.evidence_id, []).append({
            "id": claim.id,
            "review_status": claim.review_status or "",
            "assertion_status": claim.assertion_status or "",
            "statement_hash": hashlib.sha256((claim.statement or "").encode("utf-8")).hexdigest(),
        })
    rows = []
    for doc in docs:
        claim_rows = sorted(by_doc.get(doc.id, []), key=lambda c: c["id"])
        rows.append({
            "evidence_id": doc.id,
            "filename": doc.original_filename,
            "sha256": doc.sha256 or "",
            "status": doc.status or "",
            "claims_hash": canonical_hash(claim_rows),
            "spans_hash": canonical_hash(sorted(spans_by_doc.get(doc.id, []), key=lambda r: r["id"])),
            "extraction_version": doc.extraction_version or "",
            "claims_count": len(claim_rows),
        })
    return build_manifest(rows)


def compare_case_evidence_manifests(previous: Optional[dict], current: Optional[dict]) -> dict:
    if not isinstance(previous, dict) or not isinstance(current, dict):
        return {"status": "UNKNOWN_BASELINE", "added": [], "removed": [],
                "modified": [], "pending_count": 0, "current_count": 0}
    if previous.get("version") != "1.0" or current.get("version") != "1.0":
        return {"status": "UNKNOWN_BASELINE", "added": [], "removed": [],
                "modified": [], "pending_count": 0, "current_count": 0}
    for manifest in (previous, current):
        documents = manifest.get("documents")
        if not isinstance(documents, list):
            return {"status": "UNKNOWN_BASELINE", "added": [], "removed": [],
                    "modified": [], "pending_count": 0, "current_count": 0}
        if canonical_hash(documents) != manifest.get("fingerprint"):
            return {"status": "UNKNOWN_BASELINE", "added": [], "removed": [],
                    "modified": [], "pending_count": 0, "current_count": 0}
        if len({d.get("evidence_id") for d in documents}) != len(documents):
            return {"status": "UNKNOWN_BASELINE", "added": [], "removed": [],
                    "modified": [], "pending_count": 0, "current_count": 0}
    before = {d["evidence_id"]: d for d in previous.get("documents", [])}
    after = {d["evidence_id"]: d for d in current.get("documents", [])}
    added = [after[k]["filename"] for k in sorted(after.keys() - before.keys())]
    removed = [before[k]["filename"] for k in sorted(before.keys() - after.keys())]
    modified = [after[k]["filename"] for k in sorted(after.keys() & before.keys())
                if after[k] != before[k]]
    pending = sum(d.get("status") in {"UPLOADED", "EXTRACTING", "REVIEW_REQUIRED"}
                  for d in after.values())
    return {
        "status": "EVIDENCE_CHANGED" if (added or removed or modified) else "CURRENT",
        "added": added, "removed": removed, "modified": modified,
        "pending_count": pending, "current_count": len(after),
    }
