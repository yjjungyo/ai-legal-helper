"""Verified claim semantic labeling for presentation only. No legal conclusion is generated."""
def classify_claim(claim_type: str | None, fact_status: str | None) -> str:
    kind = (claim_type or "").upper()
    state = (fact_status or "").upper()
    if state in {"CONFLICTED", "EVIDENCE_NEEDED"}:
        return "UNCERTAINTY"
    if kind == "CASE_FACT":
        return "FACT" if state == "VERIFIED_FACT" else "INFERENCE" if state == "INFERENCE" else "USER_STATEMENT"
    return {
        "USER_STATEMENT": "USER_STATEMENT",
        "CASE_INFERENCE": "INFERENCE",
        "LEGAL_RULE": "LEGAL_RULE",
        "LEGAL_APPLICATION": "LEGAL_APPLICATION",
        "RECOMMENDATION": "ACTION",
    }.get(kind, "OTHER")
