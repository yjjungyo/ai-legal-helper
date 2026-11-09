# Composite GraphRAG branch — implementation and release gate (2026-11-09)

## Implemented on this branch
- CompositeEventCandidate schema and claim/span referential validation.
- LLM extraction boundary (callback-based), with no implicit approval.
- Read-only ORM adapter for reviewed claim-span input, scoped to the current case.
- Verified Neo4j retrieval into exact approved PostgreSQL spans, with source filename and fallback on invalid/oversized paths.
- Opt-in `COMPOSITE_GRAPHRAG_CONSULTATION=true` path in legal_workflow and document_consultation; default off.
- Unit test source files for candidate, extraction and consultation source flag.

## NOT IMPLEMENTED / NOT VERIFIED
- LLM extraction callback wired to the production model client.
- Composite event candidate review UI/API, durable PostgreSQL schema, Alembic migration, and graph projection.
- Event-centric Cypher retrieval (current opt-in path reuses atomic Fact/Claim graph traversal).
- Query-wide evidence coverage check; `evidence_gaps=[]` is NOT proof all relevant documents were retrieved. Current opt-in source reduction can omit evidence and must not be enabled for users.
- Test execution, real Neo4j/PostgreSQL integration, Langfuse token/cost comparisons, SC001–SC003 E2E and citation quality.
- No main merge; no release readiness claim.

## Mandatory next steps before activation
1. Persist and approve composite events, with case revision/provenance and retract-on-edit/reject lifecycle.
2. Extend graph_sync snapshot and Cypher with CompositeEvent nodes and claim/span/party/event edges.
3. Event-first retrieval plus robust question/issue coverage; if coverage cannot be demonstrated, use original documents.
4. Validate source filenames, complete citations, semantic consistency and law verification.
5. Run pytest and E2E, compare against current original-document baseline with Langfuse traces.
6. Only then enable feature flag and consider main merge.

## Security and accuracy notes
The existing graph path validator verifies approved Claim and same-case document but does not itself establish that a retrieved path semantically entails a legal conclusion. `build_verified_graph_source_pack` rechecks Claim-Span linkage, document approval and case ownership. Neither step replaces semantic verification or user review.
