with open('trace_logs.txt', 'r', encoding='utf-8') as f:
    text = f.read()

import re
# Let's find VERIFICATION logs
matches = [m.start() for m in re.finditer(r'\[VERIFICATION\] status=', text)]
for idx, pos in enumerate(matches):
    start = max(0, pos - 1500)
    end = min(len(text), pos + 1500)
    print(f"=== VERIFICATION MATCH {idx+1} ===")
    print(text[start:end])

