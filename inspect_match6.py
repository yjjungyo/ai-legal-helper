with open('trace_logs.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for idx in range(515, 546):
    if idx < len(lines):
        print(f"Line {idx+1}: {lines[idx].strip()}")

