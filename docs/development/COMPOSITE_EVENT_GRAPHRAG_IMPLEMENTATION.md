# Composite Event GraphRAG — isolated implementation contract

Status: DESIGN / NOT ENABLED. Branch: `feat/composite-event-graphrag-20261109`. Main remains unchanged.

## Goal
Build evidence-grounded, semantically complete event nodes from reviewed claims and their spans; use Neo4j Structured GraphRAG as the primary *case evidence retrieval* path during consultations, with selective original span access. Preserve statute RAG, Verification, source attribution and fallback.

## Observed baseline
- `legal_workflow.py` explicitly sets `graph_evidence.search_mode=DISABLED_FOR_CONSULTATION` (ARCH-DEFENSE-20261108).
- `graph_rag.py` already supports PostgreSQL seed → Neo4j traversal → PostgreSQL path validation and fallback.
- `entity_sync.py` derives Event and Party from Fact; it must not be mistaken for full semantic event analysis.
- Consultation's document answer path still consumes full approved document contents. Merely enabling graph state will not reduce raw-evidence tokens.

## Semantic event contract
An Event represents ONE coherent occurrence/communication, not a sentence summary. Fields (schema to be implemented): event_id, case_id, event_type, participants with roles, action(s), object, communication_channel, occurred_at, referenced_effective_date, event_summary, assertion_modality (request/proposal/acknowledgement/agreement/etc.), epistemic_status, unresolved_questions, supporting_claim_ids, supporting_span_ids, contradictory_claim_ids, source_case_version.

Examples:
- 'Tenant told landlord of intended September 30 move and requested deposit return during April 6 call' may be supported.
- 'Landlord agreed that the contract legally terminates September 30' MUST NOT be inferred from 'understood' alone.
- Date of communication and intended future date are separate.
- The same evidence may support multiple atomic claims; preserve their IDs and review state.
- User approval confirms the recorded interpretation, not an adjudication of legal effect.

## Build and sync
1. Keep atomic Fact, Claim, Span and PostgreSQL as source of truth.
2. On approved/edited claim changes, group related claims by document conversation, participants, temporal and semantic linkage. LLM generates candidate structured events using only cited approved claims and exact span IDs; reject unknown IDs and unsupported statements.
3. User reviews composite events; record provenance, edit/reject status, and version. No automatic legal conclusions.
4. Sync reviewed Event and edges to Neo4j idempotently; retract derived edges when supporting claims are rejected/edited. Do not overwrite manual Event.
5. Query Neo4j via relevant Event nodes and expand to reviewed Claim/Fact and supporting spans; validate every path against PostgreSQL case/version/review state.
6. Answer using event context and minimal exact source spans; on incomplete graph or missing provenance, fallback to existing full-document consultation. Never silently suppress evidence.

## Rollout
Phase 1: schema/data-contract and extraction regression fixtures (no consultation behavior change).
Phase 2: event extraction, review, idempotent graph sync and retraction tests.
Phase 3: GraphRAG retrieval in shadow mode, compare graph events vs source documents and track missed facts.
Phase 4: feature-flagged consultation integration; coordinate document writer, verifier and citation manifest. Full-document fallback stays available.
Phase 5: evaluate SC001–SC003: factual coverage, contradiction false positives, legal conclusion accuracy, full filename citation accuracy, input/output tokens, latency and cost per Langfuse trace. Promote only if quality gates pass.

## Safety and acceptance
- No fabricated agreement, receipt, termination or payment.
- Provenance must resolve to actual approved/edited Claim and Span in same case.
- Preserve independent atomic facts and disputes; don't collapse mutually incompatible assertions into one accepted event.
- Do not use regex to determine legal effect or temporal applicability.
- No change to main or default consultation mode before regression and E2E validation.
