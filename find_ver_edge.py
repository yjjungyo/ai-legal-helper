with open('backend/src/ai_legal_helper/workflows/legal_workflow.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if 'add_conditional_edges' in line and 'verification' in line:
        print(f"Line {idx+1}: {line.strip()}")
        for sub in lines[idx:idx+25]:
            print("  ", sub.rstrip())

