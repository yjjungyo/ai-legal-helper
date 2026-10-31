import json

with open('record_dump.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

print('=== Consultation Record Details ===')
print('ID:', d.get('id'))
print('Request ID:', d.get('request_id'))
print('Trace ID:', d.get('trace_id'))
print('Turn Index:', d.get('turn_index'))
print('Question:', d.get('question'))
print('Answer:', d.get('answer'))
print('Status:', d.get('status'))
print('Execution Status:', d.get('execution_status'))
print('Verification Status:', d.get('verification_status'))
print('Answer Status:', d.get('answer_status'))
print('Routing Status:', d.get('routing_status'))
print('Elapsed ms:', d.get('elapsed_ms'))

prog = d.get('progress')
if isinstance(prog, str):
    prog = json.loads(prog)
if prog:
    print('\n=== Progress ===')
    print('Current step:', prog.get('current_step'))
    for s in prog.get('steps', []):
        print(f"  [{s.get('step_id')}] {s.get('title')}: {s.get('status')} - {s.get('message')}")

ver = d.get('verification_result')
if isinstance(ver, str):
    ver = json.loads(ver)
if ver:
    print('\n=== Verification Result ===')
    print('Status:', ver.get('status'))
    print('Reason Code:', ver.get('reason_code'))
    print('Recommended Action:', ver.get('recommended_action'))
    print('Explanation:', ver.get('explanation'))
    print('Candidate Laws:', ver.get('candidate_laws'))
    print('Missing Legal Issues:', ver.get('missing_legal_issues'))
    print('Revision Instructions:', ver.get('revision_instructions'))
    print('Warnings:', ver.get('warnings'))
    print('Claims count:', len(ver.get('claims', [])))
    for idx, c in enumerate(ver.get('claims', [])):
        print(f"  Claim {idx+1}: [{c.get('grounding_status')}] (type={c.get('claim_type')}, fact_status={c.get('fact_status')}) {c.get('claim')[:80]}...")
        if c.get('grounding_status') != 'SUPPORTED':
            print(f"    -> Reason: {c.get('reason')}")
            print(f"    -> Model Reason: {c.get('model_reason')}")
            print(f"    -> Source IDs: {c.get('source_ids')}")

appr = d.get('approval_request')
if isinstance(appr, str):
    appr = json.loads(appr)
if appr:
    print('\n=== Approval Request ===')
    print('Type:', appr.get('type'))
    print('Reason:', appr.get('reason'))
    print('Approval Required:', appr.get('approval_required'))
    print('Explanation:', appr.get('explanation'))
    print('Candidate Laws:', appr.get('candidate_laws'))

