with open('backend/src/ai_legal_helper/agents/verification.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for idx in range(1040, 1490):
    l = lines[idx]
    if 'status' in l or 'reason_code' in l or 'REVISE' in l or 'if ' in l:
        print(f"L{idx+1}: {l.strip()}")

