import json

with open('record_dump.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

ver = d.get('verification_result')
if isinstance(ver, str):
    ver = json.loads(ver)

print("Status:", ver.get('status'))
print("Reason code:", ver.get('reason_code'))
print("Recommended action:", ver.get('recommended_action'))
print("Revision instructions:", ver.get('revision_instructions'))
print("Missing legal issues:", ver.get('missing_legal_issues'))
print("Missing issues:", ver.get('missing_issues'))
print("Contradictions:", ver.get('contradictions'))
print("Warnings:", ver.get('warnings'))

claims = ver.get('claims', [])
for i, c in enumerate(claims):
    gs = c.get('grounding_status')
    ct = c.get('claim_type')
    fs = c.get('fact_status')
    txt = c.get('claim', '')[:70]
    sids = c.get('source_ids', [])
    m_gs = c.get('model_grounding_status')
    if gs != 'SUPPORTED' or m_gs != 'SUPPORTED' or not sids:
        print(f"Claim {i+1} [gs={gs}, model_gs={m_gs}, type={ct}, fact={fs}]: {txt} -> sids={sids}")
        print(f"   Reason: {c.get('reason')}")
        print(f"   Model Reason: {c.get('model_reason')}")

