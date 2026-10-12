# -*- coding: utf-8 -*-
"""
마이그레이션 스크립트: migrate_to_kst.py

[스크립트 개요]
기존 UTC 기준으로 저장되어 있던 데이터베이스 레코드의 타임스탬프를 한국 표준시(KST, UTC+9)로 일괄 보정한다.
"""
from ai_legal_helper.database.session import SessionLocal, engine
from sqlalchemy import inspect, text

def run_migration():
    insp = inspect(engine)
    db = SessionLocal()
    
    for table in insp.get_table_names():
        ts_cols = [
            c['name'] for c in insp.get_columns(table) 
            if c['name'].endswith('_at') and str(c['type']).startswith('TIMESTAMP')
        ]
        if not ts_cols:
            continue
            
        set_clauses = [f"{col} = {col} + interval '9 hours'" for col in ts_cols]
        query = f"UPDATE {table} SET {', '.join(set_clauses)};"
        try:
            res = db.execute(text(query))
            db.commit()
            print(f"Table {table} ({', '.join(ts_cols)}): updated {res.rowcount} rows")
        except Exception as e:
            db.rollback()
            print(f"Error on {table}: {e}")

if __name__ == "__main__":
    run_migration()

