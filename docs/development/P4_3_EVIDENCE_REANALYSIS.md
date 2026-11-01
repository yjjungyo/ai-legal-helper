# P4.3 Evidence-Changed Consultation Reanalysis

## Behavior
A consultation is one immutable answer at a particular case state. A repeated question **creates a new request_id/turn_index** and re-runs the full workflow; it does not overwrite the old frozen presentation.

- On starting a consultation: capture the FULL case evidence manifest, not just sources cited in the answer.
- Manifest contains document UUID, complete original filename, file content SHA256, extraction status/version and hashes of review-state, claim statements and text spans. Statements/entire files are not copied into the manifest.
- On reading prior consultations: compare recorded manifest with CURRENT evidence/claim/span state. `CURRENT`, `EVIDENCE_CHANGED`, and `UNKNOWN_BASELINE` are distinct.
- Add/remove/modify detection returns full original filenames, with pending extraction/review count.
- For reanalysis requests: validate the prior consultation is complete, belongs to the SAME case/user, and uses the SAME question. New consultation gets a new request ID with `reanalysis_of_request_id`.
- React displays the change notice and allows the user to request reanalysis. The comparison UI displays both raw answers **without making up judgment changes**.
- If the case evidence differs (or historical baseline unknown), an old consultation's evidence drawer shows only saved-at-consultation text_excerpt when available. It never substitutes the latest extracted Claim/Span as a historical excerpt. No excerpt means "cannot verify exact historical quote."

## Strict limits
Evidence manifest SHA proves data equality between stored records; it is not a signature or independent proof of legal truth. New uploads do not themselves guarantee a different legal conclusion. Existing consultations prior to this migration lack baselines and must be shown as `UNKNOWN_BASELINE`, not fresh. A document can be uploaded but still be EXTRACTING / REVIEW_REQUIRED; the UI warns.

Case facts changed outside evidence documents, or statutes updated externally, are NOT yet captured by this evidence-only manifest. Comparison of legal conclusions is NOT automated. Past full original document bytes are NOT archived by this feature.

## Migration and acceptance
Backup PostgreSQL, then:
```powershell
cd backend
alembic heads
alembic upgrade head
alembic current
```
Revision `d4c3e2a1f903` follows `c402b8e5a201`. Two nullable fields on `consultations`: `case_evidence_manifest` JSON and `reanalysis_of_request_id` string+index. Older records stay NULL.

1. Start consultation Q with E01 only; confirm `CURRENT`.
2. Add E02 / finish extraction & review; prior result must show `EVIDENCE_CHANGED` and E02 full filename.
3. Click "same question reanalysis"; check a fresh request_id and old/new answers remain visible.
4. Confirm `reanalysis_of_request_id` points to the previous same-case completed consultation.
5. Edit/approve a Claim or delete a document; prior evidence baseline must detect the change.
6. Reload browser / restart backend, compare again, ensure prior snapshot immutable.
7. Attempt reanalysis of another case's request ID or with different question; expect 404/400.
8. With older NULL manifest, show UNKNOWN_BASELINE and do not claim case unchanged.
9. Click old evidence after modifications; no latest source is shown as the original historical quote.

## Tests
`backend/tests/unit/test_p4_case_evidence_manifest.py` uses pure deterministic manifest functions.
Workflow runs TypeScript/Vite build, all UI regression tests, Python presentation/snapshot and manifest tests, and Alembic single-head checks.
