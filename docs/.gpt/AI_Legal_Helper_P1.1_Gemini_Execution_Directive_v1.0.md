---
document_id: ALH-DIRECTIVE-P1.1
title: Gemini Antigravity Execution Directive - P1.1 Case Model
version: 1.0
status: Ready
task: P1.1
---

# Gemini Antigravity 실행지시서 — P1.1 Case Model

## ROLE

You are the implementation engineer for the AI Legal Helper project.

The product owner/supervisor has already defined the product direction and architecture.

Your responsibility is to inspect the existing repository, implement the approved specification, test it, and report the result.

You do **not** have authority to redefine product requirements or architecture.

---

# SOURCE OF TRUTH

Read these documents before implementation, in this priority order:

1. `ALH-DEV-001` — Master Development Plan
2. `ALH-DOMAIN-P1.1` — P1.1 Case Model 상세설계
3. Existing repository documentation relevant to domain models and project conventions

If repository behavior conflicts with the approved specification, STOP and report the conflict.

Do not silently choose one.

---

# CURRENT TASK

```text
Phase: P1 Core Domain Model
Task: P1.1 Case Model
```

Implement only P1.1.

Do not proceed to P1.2 or later tasks.

---

# STEP 1 — REPOSITORY INSPECTION

Before modifying code, inspect the repository.

Identify:

- project language(s)
- framework(s)
- package/module structure
- existing domain models
- persistence approach
- schema/validation library
- ID generation convention
- datetime convention
- test framework
- existing Case-like objects
- existing legal RAG/Agent integration points

Do not create a parallel architecture if an appropriate existing structure already exists.

Produce a short implementation assessment before coding.

---

# STEP 2 — GAP ANALYSIS

Compare the existing repository with `ALH-DOMAIN-P1.1`.

Classify each requirement as:

```text
EXISTS
PARTIAL
MISSING
CONFLICT
```

If there is a material `CONFLICT`, stop implementation and report:

```text
DESIGN CONFLICT
Requirement:
Existing Implementation:
Conflict:
Impact:
Recommended Options:
```

Do not resolve material architecture conflicts without approval.

---

# STEP 3 — IMPLEMENTATION

Implement the Case domain according to the approved design.

Required concepts:

```text
Case
CaseStatus
ResolutionStatus
Case validation
Case creation
Case retrieval support
Case update
Case status transition
revision handling
timestamps
reference arrays
```

Reuse the repository's existing conventions when they do not conflict with the specification.

---

# STEP 4 — TESTS

Add automated tests for at least:

```text
valid case creation
missing required values
invalid CaseStatus
invalid ResolutionStatus
revision initialization
revision increment
status update
invalid status input
reference defaults
serialization round trip
```

Run the relevant existing regression tests as well.

Do not report COMPLETE if tests fail.

---

# STEP 5 — DOCUMENTATION IMPACT

Check whether implementation requires changes to the approved design.

If no:

```text
Design Deviation: NONE
```

If yes, do not silently alter the architecture.

Report:

```text
PROPOSED DESIGN CHANGE
Current Specification:
Problem:
Proposed Change:
Reason:
Affected Components:
Backward Compatibility:
```

Wait for supervisor approval where the change is material.

---

# HARD CONSTRAINTS

DO NOT:

- implement P1.2 Party Model
- implement Evidence Model
- implement Fact Model
- redesign the entire repository
- hard-code lease-specific fields into Case
- add legal win probability
- add unapproved legal decision fields
- store evidence contents directly in Case
- store statute or precedent bodies directly in Case
- replace original evidence with LLM summaries
- invent legal business rules
- change unrelated code for cleanup purposes
- proceed to the next task automatically

---

# ENGINEERING REQUIREMENTS

Prefer:

- typed models
- explicit enums
- deterministic validation
- timezone-aware timestamps
- testable services
- minimal coupling
- existing repository conventions
- backwards compatibility where practical

Avoid unnecessary dependencies.

If a new dependency is required, report why it is necessary.

---

# STOP CONDITIONS

Stop and ask/report rather than guessing when:

1. the repository cannot be inspected
2. the specification is ambiguous in a way that affects architecture
3. an existing model materially conflicts with this specification
4. a required dependency is unavailable
5. implementing P1.1 requires changing unrelated architecture
6. tests reveal a pre-existing critical failure that prevents validation

---

# COMPLETION REPORT

Return exactly enough information for supervisor review.

Use this structure:

```text
TASK COMPLETION REPORT

Task ID: P1.1
Status: COMPLETE | PARTIAL | BLOCKED

Repository Assessment:
- Language:
- Framework:
- Domain Structure:
- Validation:
- Test Framework:

Implemented:
- ...

Changed Files:
- path — reason

Tests Added:
- ...

Test Results:
- command:
- result:

Regression Tests:
- command:
- result:

Requirement Coverage:
- requirement — PASS/FAIL

Design Deviations:
- NONE
or
- details

Known Issues:
- ...

Dependencies Added:
- NONE
or
- package + reason

Recommended Next Step:
- Await supervisor review of P1.1.
```

Do not start P1.2 after reporting completion.
