with open('trace_logs.txt', 'r', encoding='utf-8') as f:
    text = f.read()

import re
# Let's search for "coverage" or "consistency" or the raw JSON output around line 500-545
matches = [m.start() for m in re.finditer(r'\[VERIFICATION_SCHEMA\]', text)]
for idx, pos in enumerate(matches):
    start = max(0, pos - 500)
    end = min(len(text), pos + 1000)
    print(f"=== SCHEMA MATCH {idx+1} ===")
    print(text[start:end][:800])

