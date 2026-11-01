# P4.1 Verified Presentation Semantic Metadata

This release enriches lossless, verified answer blocks with explicit types copied from Verification metadata. It does not re-answer questions, modify legal conclusions, or add LLM calls.

## Rules

- CASE_FACT is FACT only when fact_status is VERIFIED_FACT.
- USER_STATEMENT and CASE_INFERENCE never become FACT.
- CONFLICTED or EVIDENCE_NEEDED becomes UNCERTAINTY.
- LEGAL_RULE, LEGAL_APPLICATION and RECOMMENDATION map to legal rule, application and action.
- Unknown categories map to OTHER.
- Source badges are displayed only for SUPPORTED claims anchored exactly once in the verified answer, tied to a known source ID and with HASH_MATCHED binding.
- The count is for individually linked claims, not for the whole paragraph or the whole consultation.
- Existing answer, source registry, verification result, and P2 response remain compatible.

## Validation (local Windows)

```powershell
cd backend
python -m pytest tests/unit/test_verified_presentation.py tests/unit/test_p4_presentation_semantics.py -q
cd ..\frontend
npm ci
npm run build
node --test tests/presentation-semantics.test.cjs tests/presentation-layout.test.cjs tests/consultation-sources.test.cjs
```

No database migration is included in P4.1. Structured snapshot persistence and historical schema migrations remain a separate work item.
