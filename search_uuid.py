# -*- coding: utf-8 -*-
"""UUID를 데이터베이스 및 로그에서 검색하는 스크립트."""
from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import Case, EvidenceDocument, Fact
from sqlalchemy import text

target_uuid = "7eab3101-2414-4aca-88a1-d1a8ae36f7e4"

with SessionLocal() as db:
    # 1. Case
    case = db.query(Case).filter(Case.id == target_uuid).first()
    if case:
        print(f"[Found in Case] id: {case.id}, title: {case.title}, status: {case.status}, created_at: {case.created_at}")

    # 2. EvidenceDocument
    ev = db.query(EvidenceDocument).filter(EvidenceDocument.id == target_uuid).first()
    if ev:
        print(f"[Found in EvidenceDocument] id: {ev.id}, filename: {ev.original_filename}, case_id: {ev.case_id}, status: {ev.status}")

    # 3. Check all public tables
    q = text("""
        SELECT table_name, column_name 
        FROM information_schema.columns 
        WHERE table_schema = 'public'
          AND data_type IN ('uuid', 'character varying', 'text')
    """)
    rows = db.execute(q).fetchall()
    checked = set()
    for t_name, c_name in rows:
        key = (t_name, c_name)
        if key in checked:
            continue
        checked.add(key)
        try:
            cnt = db.execute(
                text(f"SELECT count(*) FROM {t_name} WHERE CAST({c_name} AS TEXT) = :uid"),
                {"uid": target_uuid}
            ).scalar()
            if cnt > 0:
                print(f"[MATCH] Table: {t_name}, Column: {c_name}, Count: {cnt}")
        except Exception:
            pass

print("Search completed.")
