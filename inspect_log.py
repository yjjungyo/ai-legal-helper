import sys

log_path = 'backend/logs/app.log.2026-10-31'
trace_id = '45d9a33c'
req_id = '95ab72e5'

matched_lines = []
with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
        if trace_id in line or req_id in line:
            matched_lines.append(line.rstrip())

print(f"Total matched log lines: {len(matched_lines)}")
with open('trace_logs.txt', 'w', encoding='utf-8') as out:
    for line in matched_lines:
        out.write(line + '\n')

print("Wrote trace_logs.txt. Showing first 30 and last 30 lines:")
for l in matched_lines[:30]:
    print(l)
print("...")
for l in matched_lines[-30:]:
    print(l)

