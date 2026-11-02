# -*- coding: utf-8 -*-
"""P2 Alembic 마이그레이션 업그레이드/다운그레이드 검증 (SQLite 격리 실행).

[목적]
실제 운영 PostgreSQL에 연결하거나 기존 데이터 테이블을 건드리지 않고,
P2 신규 테이블과 인덱스·FK·별칭 유일성 규칙이 Alembic 코드대로 생성되는지
검사한다. 전체 운영 Alembic 마이그레이션 체인을 검증했다는 뜻은 아니다.
"""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_p2_migration_upgrade_and_downgrade_only_new_tables():
    path = (Path(__file__).resolve().parents[2] / "alembic" / "versions"
            / "90d4e30c2a71_add_official_law_catalog.py")
    spec = importlib.util.spec_from_file_location("p2_law_catalog_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "90d4e30c2a71"
    assert module.down_revision == "d4c3e2a1f903"

    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            operations = Operations(context)
            old_op = module.op
            module.op = operations
            try:
                module.upgrade()
                inspector = inspect(connection)
                assert {
                    "law_catalog", "law_catalog_aliases", "law_catalog_sync_runs"
                }.issubset(set(inspector.get_table_names()))
                assert "law_id" in {
                    x["name"] for x in inspector.get_columns("law_catalog")
                }
                assert "alias_key" in {
                    x["name"] for x in inspector.get_columns("law_catalog_aliases")
                }
                assert "status" in {
                    x["name"] for x in inspector.get_columns("law_catalog_sync_runs")
                }
                constraints = inspector.get_unique_constraints("law_catalog_aliases")
                assert any(
                    set(item["column_names"]) == {"law_id", "alias_key"}
                    for item in constraints
                )
                module.downgrade()
                assert not {
                    "law_catalog", "law_catalog_aliases", "law_catalog_sync_runs"
                }.intersection(set(inspect(connection).get_table_names()))
            finally:
                module.op = old_op
    finally:
        engine.dispose()
