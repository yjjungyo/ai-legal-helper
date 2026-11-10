# -*- coding: utf-8 -*-
import json
from ai_legal_helper.database.session import SessionLocal
from sqlalchemy import text

target_uuid = "7eab3101-2414-4aca-88a1-d1a8ae36f7e4"

with SessionLocal() as db:
    row = db.execute(
        text("SELECT * FROM consultations WHERE trace_id = :uid"),
        {"uid": target_uuid}
    ).mappings().first()
    
    if not row:
        print("No row found.")
        exit(0)
        
    print("=== Consultation Details ===")
    for k, v in row.items():
        if isinstance(v, (dict, list)):
            print(f"[{k}]: (JSON/Dict)")
            print(json.dumps(v, ensure_ascii=False, indent=2)[:500])
        elif isinstance(v, str) and len(v) > 200:
            print(f"[{k}]: (Length {len(v)})")
            print(v[:300] + "...")
        else:
            print(f"[{k}]: {v}")
