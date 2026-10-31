with open('trace_logs.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for idx, l in enumerate(lines):
    # Search for nodes execution and decisions
    if any(k in l for k in [
        'next_verification_step', '[DOC_ROUTING]',
        'statute_search_approval', 'execute_statute_search',
        'revise_node', 'write_document_answer',
        'finish_answer', '[FINALIZE]', '[DOC_FINALIZE]',
        '제한 답변', 'limited', 'status=REVISE', 'status=INSUFFICIENT',
        'status=PASS', 'APPROVAL_REQUIRED', 'HILT', 'APPROVAL',
        'process_consultation', 'on_step'
    ]):
        print(f"L{idx+1:03d}: {l.strip()}")

