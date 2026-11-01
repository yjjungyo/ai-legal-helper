# AI Legal Helper P4.2 — Frozen Consultation Presentation

## Goal
Preserve the presentation model and the evidence-source registry **as it existed at consultation finalization**, so a later evidence upload/review cannot silently rewrite the historical answer UI.

## DB migration (required before restarting the updated backend)

```powershell
cd backend
alembic heads
alembic upgrade head
alembic current
```

- Back up PostgreSQL before running the migration.
- New nullable `consultations.presentation_snapshot` JSON column is added.
- Old consultations remain NULL. No retroactive snapshot/backfill: existing data does not prove what the user originally saw.
- Rolling back requires care; `alembic downgrade -1` removes that column and loses frozen snapshot data. Prefer a backup/restore plan.

## Snapshot content and behavior
- Schema version `snapshot_version=1.0`, captured timestamp, request ID, case ID and status fields.
- Original answer SHA-256, normalized source-list SHA-256, verification-result SHA-256.
- Complete immutable presentation output with claim/source links and the checksum of the full snapshot envelope.
- Original `consultations.sources` already stores consultation-time source metadata and excerpts. Its hash binds that historical evidence registry to the snapshot; the snapshot avoids a second, large copy of source contents.
- A repeated completion for the same request cannot replace a frozen snapshot or change the bound answer/source/verification data without failing the DB transaction.
- Pydantic excludes internal snapshot JSON from regular API responses; the client receives `presentation` and `presentation_origin`.
- `FROZEN`: snapshot is intact and validated against DB data. No current Neo4j/Chroma/EvidenceDocument query is performed by the presentation reader.
- `INVALID_SNAPSHOT`: integrity mismatch; show original answer, suppress structured UI and emit a diagnostic log. Never rebuild a corrupted frozen snapshot.
- `LEGACY_REBUILT`: historical record with NULL snapshot; rebuilt for display from existing stored answer/source/verification, explicitly *not* claimed to be an original-time snapshot.
- `UNAVAILABLE`: no valid structured presentation for an error/unverified/withheld result.

## Verification boundary
Existing Verification is NOT rerun and LLM is NOT called during storage or replay. Hashes detect accidental or unauthorized data mutation; hashes alone are not cryptographic signatures or proof of the legal correctness of the underlying content.

## Logging
- `[PRESENTATION_FREEZE]`: request prefix, schema version, verification binding (never log full PII)
- `[PRESENTATION_SNAPSHOT]`: invalid historical snapshot
- `[PRESENTATION_LEGACY]`: pre-migration reconstruction
- `[PRESENTATION_READ]`: safe fallback diagnostics

## Automated tests
`backend/tests/unit/test_p4_presentation_snapshot.py` tests success, source/evidence changes, hash mismatch, status/identity mismatch, idempotence and write-once rejection.
GitHub Actions verifies frontend build, existing UI tests, Python unit tests, migration syntax and one Alembic head.

## Manual E2E acceptance
1. Create a new case, upload 2 pieces of evidence, complete a PASS consultation.
2. Verify `presentation_snapshot IS NOT NULL` in PostgreSQL and `presentation_origin=FROZEN` in GET.
3. Restart backend, reload consultation and compare `presentation` to pre-restart result.
4. Add/change case evidence and confirm the old consultation display and its source filename remain unchanged.
5. Corrupt a copy of snapshot/source metadata in a test database and verify `INVALID_SNAPSHOT` and no structured result (do NOT modify production data).
6. For old consultations, confirm `LEGACY_REBUILT` rather than incorrectly claiming frozen history.
7. Trigger failed/withheld verification and confirm `presentation_snapshot` stays NULL.

Note: source excerpt fidelity depends on consultation-time sources being retained. Uploading a newer version does not change the recorded excerpt, but the snapshot is not an archival copy of every original document byte.
