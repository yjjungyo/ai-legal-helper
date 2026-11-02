# -*- coding: utf-8 -*-
"""
P2 Law Catalog/Law Resolver 회귀 테스트.

사용자 데이터, 유료 LLM, OpenLaw 실 호출, ChromaDB, 운영 PostgreSQL 없이
메모리 SQLite와 인공 법령 XML로 재현한다.
"""
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from ai_legal_helper.database.session import Base
from ai_legal_helper.database.models import (
    LawCatalogEntry, LawCatalogAlias, LawCatalogSyncRun,
)
from ai_legal_helper.legal_knowledge.law_catalog import (
    CatalogParseError,
    LawCatalogItem, LawCatalogPage, parse_law_catalog_page,
    fetch_law_catalog_page, normalize_law_name,
)
from ai_legal_helper.legal_knowledge.catalog_store import (
    LawCatalogStore, sync_official_catalog,
)
from ai_legal_helper.legal_knowledge.law_resolver import LawResolver


def _xml(page=1, total=3, entries=()):
    root = ET.Element("LawSearch")
    if total is not None:
        ET.SubElement(root, "totalCnt").text = str(total)
    ET.SubElement(root, "page").text = str(page)
    for law_id, name, short_name, law_type in entries:
        node = ET.SubElement(root, "law")
        ET.SubElement(node, "법령ID").text = law_id
        ET.SubElement(node, "법령명한글").text = name
        ET.SubElement(node, "법령약칭명").text = short_name
        ET.SubElement(node, "법령구분명").text = law_type
        ET.SubElement(node, "법령일련번호").text = f"MST-{law_id}"
        ET.SubElement(node, "공포일자").text = "20260601"
        ET.SubElement(node, "시행일자").text = "20270115"
    return ET.tostring(root, encoding="utf-8")


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        LawCatalogEntry.__table__,
        LawCatalogAlias.__table__,
        LawCatalogSyncRun.__table__,
    ])
    with Session(engine) as session:
        yield session
    engine.dispose()


def _seed(db):
    """실제 법률의 의미를 하드코딩하지 않는 독립 테스트 카탈로그."""
    rows = [
        ("101", "주택임대차보호법", "주임법", "법률"),
        ("102", "주택임대차보호법 시행령", "", "대통령령"),
        ("103", "주택임대차보호법 시행규칙", "", "부령"),
        ("104", "민법", "", "법률"),
        ("105", "난민법", "", "법률"),
    ]
    page = parse_law_catalog_page(_xml(total=5, entries=rows))
    LawCatalogStore(db).upsert_page(page)
    db.commit()


def test_official_catalog_parser_preserves_identity_alias_and_list_only_date():
    data = _xml(total=1, entries=[("ID-1", "가상 보호법", "가상법", "법률")])
    page = parse_law_catalog_page(data)
    assert page.total_count == 1
    assert page.returned_count == 1
    assert page.skipped_count == 0
    item = page.items[0]
    assert item.law_id == "ID-1"
    assert item.official_name == "가상 보호법"
    assert item.short_name == "가상법"
    assert item.mst == "MST-ID-1"
    assert item.promulgation_date == "2026-06-01"
    assert item.list_effective_date == "2027-01-15"
    assert normalize_law_name(item.official_name) == "가상보호법"


@pytest.mark.parametrize("payload", [
    b"",
    b"<broken",
    b"<unexpected />",
    b'<!DOCTYPE foo [<!ENTITY x "y">]><LawSearch/>',
])
def test_invalid_or_unsafe_xml_is_not_catalog(payload):
    with pytest.raises(CatalogParseError):
        parse_law_catalog_page(payload)


def test_catalog_parser_rejects_missing_id_and_mismatched_page():
    payload = _xml(total=2, entries=[
        ("", "가상법", "", "법률"),
        ("XYZ", "유효법", "", "법률"),
    ])
    parsed = parse_law_catalog_page(payload)
    assert parsed.skipped_count == 1
    assert len(parsed.items) == 1
    with pytest.raises(CatalogParseError, match="PAGE_MISMATCH"):
        parse_law_catalog_page(payload, expected_page=2)


def test_catalog_sync_is_idempotent_and_replaces_only_official_alias(db):
    _seed(db)
    store = LawCatalogStore(db)
    original = db.get(LawCatalogEntry, "101")
    assert len(original.aliases) == 1
    assert original.aliases[0].alias_name == "주임법"
    store.upsert_page(parse_law_catalog_page(_xml(
        total=1, entries=[("101", "주택임대차보호법", "주임법", "법률")]
    )))
    db.commit()
    assert db.scalar(select(func.count()).select_from(LawCatalogEntry)) == 5
    assert db.scalar(select(func.count()).select_from(LawCatalogAlias)) == 1
    store.upsert_page(parse_law_catalog_page(_xml(
        total=1, entries=[("101", "주택임대차보호법", "새약칭", "법률")]
    )))
    db.commit()
    assert [a.alias_name for a in db.get(LawCatalogEntry, "101").aliases] == ["새약칭"]


def test_resolver_recognizes_explicit_special_law_and_family(db):
    _seed(db)
    resolver = LawResolver(LawCatalogStore(db))
    result = resolver.resolve("주택임대차보호법 제6조의2를 확인해줘.")
    assert result.status == "FOUND"
    assert [c.law_id for c in result.laws] == ["101"]
    assert {c.law_id for c in result.family_suggestions} == {"102", "103"}
    assert all(x.relation_status == "NAME_FAMILY_CANDIDATE" for x in result.family_suggestions)
    assert result.official_search_required is False


def test_resolver_does_not_treat_law_name_as_substring_of_other_law(db):
    _seed(db)
    resolver = LawResolver(LawCatalogStore(db))
    result = resolver.resolve("난민법 제2조가 적용됩니까?")
    assert result.status == "FOUND"
    assert [law.law_id for law in result.laws] == ["105"]
    assert "104" not in [law.law_id for law in result.laws]


def test_resolver_handles_official_alias_and_multiple_independent_laws(db):
    _seed(db)
    resolver = LawResolver(LawCatalogStore(db))
    alias = resolver.resolve("주임법상 임차인 보호는?")
    assert alias.status == "FOUND"
    assert alias.laws[0].law_id == "101"
    multiple = resolver.resolve("민법과 주택임대차보호법을 비교해줘.")
    assert multiple.status == "MULTIPLE"
    assert {law.law_id for law in multiple.laws} == {"104", "101"}


def test_resolver_preserves_shared_alias_ambiguity(db):
    _seed(db)
    db.add(LawCatalogAlias(law_id="104", alias_name="주임법",
                           alias_key=normalize_law_name("주임법"), source="REVIEWED"))
    db.commit()
    result = LawResolver(LawCatalogStore(db)).resolve("주임법은?")
    assert result.status == "AMBIGUOUS"
    assert {law.law_id for law in result.laws} == {"101", "104"}
    assert result.official_search_required is True


def test_resolver_does_not_promote_hallucinated_law(db):
    _seed(db)
    resolver = LawResolver(LawCatalogStore(db))
    missing = resolver.resolve("새로운 법률 해석", suggested_laws=["존재하지 않는 마법"])
    assert missing.status == "NO_MATCH"
    assert missing.laws == []
    assert missing.official_search_required is True
    suggested = resolver.resolve("계약 분쟁", suggested_laws=["주택임대차보호법"])
    assert suggested.status == "SUGGESTED"
    assert suggested.laws[0].law_id == "101"


def test_catalog_empty_requires_official_catalog_sync(db):
    result = LawResolver(LawCatalogStore(db)).resolve("민법 제6조")
    assert result.status == "CATALOG_EMPTY"
    assert result.official_search_required is True


def test_official_catalog_full_two_page_sync_and_audit(db):
    requests = []
    def fetch(url):
        parts = parse_qs(urlsplit(url).query)
        assert parts["target"] == ["law"]
        assert parts["display"] == ["100"]
        page = int(parts["page"][0])
        requests.append(page)
        if page == 1:
            return _xml(page=1, total=3, entries=[
                ("101", "테스트법", "약칭", "법률"),
                ("102", "테스트법 시행령", "", "대통령령"),
            ])
        return _xml(page=2, total=3, entries=[("103", "테스트법 시행규칙", "", "부령")])
    summary = sync_official_catalog(db, api_key="mock-secret", fetch_xml=fetch)
    assert summary.status == "COMPLETE"
    assert summary.items_seen == summary.total_expected == 3
    assert summary.pages_completed == 2
    assert requests == [1, 2]
    assert db.scalar(select(func.count()).select_from(LawCatalogEntry)) == 3
    run = db.get(LawCatalogSyncRun, summary.run_id)
    assert run.status == "COMPLETE"


def test_partial_catalog_sync_never_claims_complete(db):
    def fetch(url):
        return _xml(page=1, total=300, entries=[
            ("111", "테스트법", "테스트약칭", "법률"),
        ])
    summary = sync_official_catalog(
        db, api_key="mock-secret", fetch_xml=fetch, max_pages=1,
    )
    assert summary.status == "PARTIAL"
    assert summary.pages_completed == 1
    assert summary.error_code == "PAGE_LIMIT_REACHED"
    assert db.scalar(select(func.count()).select_from(LawCatalogEntry)) == 1


def test_failed_second_page_keeps_first_page_and_marks_partial(db):
    def fetch(url):
        page = int(parse_qs(urlsplit(url).query)["page"][0])
        return (_xml(page=1, total=2, entries=[("111", "테스트법", "", "법률")])
                if page == 1 else b"bad xml")
    summary = sync_official_catalog(db, api_key="mock-secret", fetch_xml=fetch)
    assert summary.status == "PARTIAL"
    assert summary.pages_completed == 1
    assert db.get(LawCatalogEntry, "111") is not None


def test_sync_without_total_count_is_not_marked_complete(db):
    summary = sync_official_catalog(
        db, api_key="mock-secret", max_pages=1,
        fetch_xml=lambda _: _xml(page=1, total=None,
                                 entries=[("111", "테스트법", "", "법률")]),
    )
    assert summary.status == "PARTIAL"
    assert summary.error_code == "TOTAL_COUNT_UNCONFIRMED"


def test_missing_api_key_stops_before_any_network(db):
    called = []
    with pytest.raises(ValueError, match="LAW_OPENAPI_KEY_MISSING"):
        sync_official_catalog(db, api_key="", fetch_xml=lambda url: called.append(url))
    assert called == []


def test_duplicate_law_id_never_counts_as_complete_inventory(db):
    """API 페이지 겹침으로 count만 맞아도 실제 법령 목록은 불완전할 수 있다."""
    def fetch(url):
        return _xml(page=1, total=2, entries=[
            ("111", "테스트법", "", "법률"),
            ("111", "테스트법", "", "법률"),
        ])
    summary = sync_official_catalog(db, api_key="mock-secret", fetch_xml=fetch)
    assert summary.status == "PARTIAL"
    assert summary.pages_completed == 1
    assert summary.items_seen == 2
    assert db.scalar(select(func.count()).select_from(LawCatalogEntry)) == 1
