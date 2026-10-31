with open('trace_logs.txt', 'r', encoding='utf-8') as f:
    text = f.read()

import re
# Let's search for the drafted answer content or SHA in app.log
matches = [m.start() for m in re.finditer(r'\[DOCUMENT_ANSWER\] 답변 초안 작성 완료', text)]
print(f"Found {len(matches)} drafted answers")
for idx, pos in enumerate(matches):
    print(text[pos:pos+300])

