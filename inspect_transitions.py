with open('trace_logs.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")
for idx, l in enumerate(lines):
    # Print key transition lines
    if any(k in l for k in [
        '[SUPERVISOR_INIT]', '[INTENT_ANALYSIS]', '[DOC_ROUTING]',
        '[VERIFICATION]', '[VERIFICATION_SCHEMA]', '[DOC_FINALIZE]',
        'finish_answer', 'insufficient_node', 'revise_node',
        'statute_search_approval', 'execute_statute_search',
        'HILT', 'status=', 'status: '
    ]):
        print(f"{idx+1}: {l.strip()}")

