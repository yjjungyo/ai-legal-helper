# -*- coding: utf-8 -*-
"""
모듈명: test_parties_timeline_sync.py

[모듈 개요]
Evidence → Facts → Parties / Timeline 자동 생성 및 동기화 개선(P0-01 ~ P0-04, P1)에 대한
필수 검증 시나리오(T01 ~ T18)를 검증하는 단위·통합 테스트 스위트이다.
"""

from unittest.mock import patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_legal_helper.api.schemas.case import CaseDetailSchema
from ai_legal_helper.case_intelligence.entity_sync import (
    extract_parties_from_facts,
    rebuild_case_entities,
    synchronize_case_entities,
    synchronize_case_parties,
    synchronize_case_timeline,
)
from ai_legal_helper.case_intelligence.evidence_manager import process_evidence_review
from ai_legal_helper.case_intelligence.timeline import (
    build_timeline_from_facts,
    extract_events_from_fact,
)
from ai_legal_helper.database.graph_sync import collect_case_snapshot
from ai_legal_helper.database.models import (
    Case,
    Event,
    EvidenceClaim,
    EvidenceDocument,
    Fact,
    Party,
)
from ai_legal_helper.database.session import Base


@pytest.fixture()
def db_session():
    """인메모리 SQLite 세션을 생성하여 각 테스트의 트랜잭션 격리를 보장한다."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _create_case_with_doc(db, title: str = "테스트 사건") -> tuple[Case, EvidenceDocument]:
    """테스트용 Case와 EvidenceDocument를 생성한다."""
    case = Case(title=title, case_type="주택임대차")
    db.add(case)
    db.flush()
    doc = EvidenceDocument(
        case_id=case.id,
        original_filename="E01_계약서.txt",
        safe_storage_key=f"safe_{case.id}.txt",
        media_type="text/plain",
        size_bytes=512,
        sha256="a" * 64,
        status="REVIEW_REQUIRED",
    )
    db.add(doc)
    db.flush()
    return case, doc


class TestPartiesAndTimelineSync:
    """T01 ~ T18: 당사자(Parties) 및 타임라인(Timeline) 자동 생성·동기화 검증."""

    def test_t01_basic_party_extraction(self, db_session):
        """T01. 기본 당사자 추출: 확정 사실에서 임대인/임차인 Party가 정확히 생성된다."""
        case, _ = _create_case_with_doc(db_session)
        f1 = Fact(case_id=case.id, statement="임대인은 박정훈이다.", fact_type="PARTY_INFO")
        f2 = Fact(case_id=case.id, statement="임차인은 이수현이다.", fact_type="PARTY_INFO")
        db_session.add_all([f1, f2])
        db_session.commit()

        synchronize_case_parties(db_session, case.id)
        db_session.commit()

        parties = db_session.query(Party).filter_by(case_id=case.id).all()
        party_pairs = {(p.name, p.role) for p in parties}
        assert party_pairs == {("박정훈", "임대인"), ("이수현", "임차인")}
        for p in parties:
            assert p.source_type == "EVIDENCE_DERIVED"
            assert len(p.related_fact_ids) == 1

    def test_t02_party_deduplication_and_auxiliary_role_merge(self, db_session):
        """T02. 당사자 중복 제거 및 보조 역할(수신자/발신자)·연락처 병합 검증."""
        case, _ = _create_case_with_doc(db_session)
        facts = [
            Fact(case_id=case.id, statement="임대인은 박정훈이다.", fact_type="PARTY_INFO"),
            Fact(
                case_id=case.id,
                statement="문서에는 임대인이 박정훈으로 기재되어 있고 서명란이 있다.",
                fact_type="DOC_INFO",
            ),
            Fact(
                case_id=case.id,
                statement="문자 대화의 수신자는 박정훈이다.",
                fact_type="PARTY_INFO",
            ),
            Fact(
                case_id=case.id,
                statement="임대인의 연락처는 010-4826-1357이다.",
                fact_type="PARTY_INFO",
            ),
        ]
        db_session.add_all(facts)
        db_session.commit()

        synchronize_case_parties(db_session, case.id)
        db_session.commit()

        parties = db_session.query(Party).filter_by(case_id=case.id).all()
        assert len(parties) == 1
        p = parties[0]
        assert p.name == "박정훈"
        assert p.role == "임대인"
        assert "010-4826-1357" in (p.notes or "")
        assert "수신자" in (p.notes or "")
        assert len(p.related_fact_ids) == 4

    def test_t03_word_order_independent_party_extraction(self):
        """T03. 어순 다른 당사자 문장 처리: 세 가지 어순 모두 동일한 (박정훈, 임대인)으로 정규화된다."""
        statements = [
            "임대인은 박정훈이다.",
            "임대인 박정훈",
            "박정훈은 임대인이다.",
            "주택임대차계약서에는 임대인 박정훈의 서명 표시가 있다.",
        ]
        for stmt in statements:
            f = Fact(id="f-1", case_id="c-1", statement=stmt, fact_type="PARTY_INFO")
            cands = extract_parties_from_facts([f])
            assert len(cands) == 1, f"Failed for statement: {stmt}"
            assert (cands[0].name, cands[0].role) == ("박정훈", "임대인")

    def test_t04_unconfirmed_name_protection(self, db_session):
        """T04. 이름 미확정 사실 보호: 일반 명사나 행위 서술에서 쓰레기 Party를 생성하지 않는다."""
        case, _ = _create_case_with_doc(db_session)
        facts = [
            Fact(case_id=case.id, statement="임대인은 보증금 반환을 지연했다.", fact_type="ACTION_FACT"),
            Fact(case_id=case.id, statement="임차인은 계약 갱신을 거절하였다.", fact_type="ACTION_FACT"),
            Fact(
                case_id=case.id,
                statement="이 문서는 임대인과 임차인 사이의 통화 녹취록 형식의 문서이다.",
                fact_type="DOC_INFO",
            ),
            Fact(case_id=case.id, statement="임대인은 성명미상이다.", fact_type="PARTY_INFO"),
        ]
        db_session.add_all(facts)
        db_session.commit()

        synchronize_case_parties(db_session, case.id)
        db_session.commit()

        parties = db_session.query(Party).filter_by(case_id=case.id).all()
        assert len(parties) == 0

    def test_t05_single_date_event_generation(self, db_session):
        """T05. 단일 날짜 이벤트 생성: occurred_at이 비어 있어도 본문에서 날짜·기일을 추출한다."""
        case, _ = _create_case_with_doc(db_session)
        fact = Fact(
            case_id=case.id,
            statement="계약금 지급기일은 2022년 2월 20일이다.",
            fact_type="DATE_INFO",
            occurred_at=None,
        )
        db_session.add(fact)
        db_session.commit()

        synchronize_case_timeline(db_session, case.id)
        db_session.commit()

        events = db_session.query(Event).filter_by(case_id=case.id).all()
        assert len(events) == 1
        ev = events[0]
        assert ev.event_date == "2022-02-20"
        assert ev.event_type == "지급기일"
        assert ev.occurrence_status == "SCHEDULED"
        assert fact.id in ev.related_fact_ids

    def test_t06_date_range_fact_splits_into_start_and_end_events(self, db_session):
        """T06. 기간 문장 이벤트 분리: 시작일과 종료일이 2개의 개별 Event로 분리 생성된다."""
        case, _ = _create_case_with_doc(db_session)
        fact = Fact(
            case_id=case.id,
            statement="임대차 기간은 2022년 3월 1일부터 2024년 2월 28일까지이다.",
            fact_type="DATE_INFO",
        )
        db_session.add(fact)
        db_session.commit()

        synchronize_case_timeline(db_session, case.id)
        db_session.commit()

        events = (
            db_session.query(Event)
            .filter_by(case_id=case.id)
            .order_by(Event.event_date.asc())
            .all()
        )
        assert len(events) == 2
        assert events[0].event_date == "2022-03-01"
        assert events[0].event_type == "계약 시작"
        assert events[0].occurrence_status == "SCHEDULED"
        assert fact.id in events[0].related_fact_ids

        assert events[1].event_date == "2024-02-28"
        assert events[1].event_type == "계약 종료"
        assert events[1].occurrence_status == "SCHEDULED"
        assert fact.id in events[1].related_fact_ids

    def test_t07_same_date_multiple_events_preserved(self, db_session):
        """T07. 동일 날짜 다중 이벤트 보존: 같은 날의 서로 다른 법적 일정이 손실 없이 모두 보존된다."""
        case, _ = _create_case_with_doc(db_session)
        f1 = Fact(case_id=case.id, statement="잔금 지급기일은 2022년 3월 1일이다.", fact_type="DATE_INFO")
        f2 = Fact(
            case_id=case.id,
            statement="임대차 기간은 2022년 3월 1일부터 2024년 2월 28일까지이다.",
            fact_type="DATE_INFO",
        )
        f3 = Fact(case_id=case.id, statement="주택 인도 예정일은 2022년 3월 1일이다.", fact_type="DATE_INFO")
        db_session.add_all([f1, f2, f3])
        db_session.commit()

        synchronize_case_timeline(db_session, case.id)
        db_session.commit()

        march_events = (
            db_session.query(Event)
            .filter_by(case_id=case.id, event_date="2022-03-01")
            .all()
        )
        assert len(march_events) == 3
        event_types = {e.event_type for e in march_events}
        assert event_types == {"지급기일", "계약 시작", "인도 예정일"}
        all_related_fids = {fid for e in march_events for fid in (e.related_fact_ids or [])}
        assert {f1.id, f2.id, f3.id}.issubset(all_related_fids)

    def test_t08_invalid_calendar_date_defense(self, db_session):
        """T08. 잘못된 달력 날짜 방어: 2026년 2월 31일 같은 무효 날짜는 Event로 생성하지 않는다."""
        case, _ = _create_case_with_doc(db_session)
        invalid_fact = Fact(
            case_id=case.id,
            statement="계약금 지급일은 2026년 2월 31일이다.",
            fact_type="DATE_INFO",
        )
        undated_fact = Fact(
            case_id=case.id,
            statement="보증금은 300,000,000원이다.",
            fact_type="AMOUNT_INFO",
        )
        db_session.add_all([invalid_fact, undated_fact])
        db_session.commit()

        synchronize_case_timeline(db_session, case.id)
        db_session.commit()

        events = db_session.query(Event).filter_by(case_id=case.id).all()
        assert len(events) == 0

    @patch("ai_legal_helper.database.graph_sync_worker.queue_sync_task")
    def test_t09_claim_edit_updates_party_and_removes_stale_party(self, mock_queue, db_session):
        """T09. EvidenceClaim EDIT 정합성: 당사자 이름 수정 시 이전 단독 근거 Party가 제거되고 새 Party로 갱신된다."""
        case, doc = _create_case_with_doc(db_session)
        claim = EvidenceClaim(
            case_id=case.id,
            evidence_id=doc.id,
            statement="임대인은 박정훈이다.",
            claim_type="PARTY_INFO",
            review_status="PENDING",
        )
        db_session.add(claim)
        db_session.commit()

        # 1차 승인
        process_evidence_review(db=db_session, claim_id=claim.id, action="APPROVE")
        parties_after_approve = db_session.query(Party).filter_by(case_id=case.id).all()
        assert [(p.name, p.role) for p in parties_after_approve] == [("박정훈", "임대인")]

        # 2차 EDIT ("임대인은 김정훈이다.")
        process_evidence_review(
            db=db_session,
            claim_id=claim.id,
            action="EDIT",
            new_statement="임대인은 김정훈이다.",
        )
        parties_after_edit = db_session.query(Party).filter_by(case_id=case.id).all()
        assert [(p.name, p.role) for p in parties_after_edit] == [("김정훈", "임대인")]

    @patch("ai_legal_helper.database.graph_sync_worker.queue_sync_task")
    def test_t10_claim_reject_removes_sole_derived_party_and_event(self, mock_queue, db_session):
        """T10. EvidenceClaim REJECT 정합성: 단독 근거 Claim 반려 시 파생된 Fact, Party, Event가 모두 제거된다."""
        case, doc = _create_case_with_doc(db_session)
        c_party = EvidenceClaim(
            case_id=case.id,
            evidence_id=doc.id,
            statement="임대인은 박정훈이다.",
            claim_type="PARTY_INFO",
            review_status="PENDING",
        )
        c_date = EvidenceClaim(
            case_id=case.id,
            evidence_id=doc.id,
            statement="잔금 지급기일은 2022년 3월 1일이다.",
            claim_type="DATE_INFO",
            review_status="PENDING",
        )
        db_session.add_all([c_party, c_date])
        db_session.commit()

        process_evidence_review(db=db_session, claim_id=c_party.id, action="APPROVE")
        process_evidence_review(db=db_session, claim_id=c_date.id, action="APPROVE")
        assert db_session.query(Party).filter_by(case_id=case.id).count() == 1
        assert db_session.query(Event).filter_by(case_id=case.id).count() == 1

        # 두 Claim 모두 REJECT
        process_evidence_review(db=db_session, claim_id=c_party.id, action="REJECT")
        process_evidence_review(db=db_session, claim_id=c_date.id, action="REJECT")

        assert db_session.query(Fact).filter_by(case_id=case.id).count() == 0
        assert db_session.query(Party).filter_by(case_id=case.id).count() == 0
        assert db_session.query(Event).filter_by(case_id=case.id).count() == 0

    @patch("ai_legal_helper.database.graph_sync_worker.queue_sync_task")
    def test_t11_multi_evidence_support_preserves_party_on_single_reject(self, mock_queue, db_session):
        """T11. 다중 근거 Claim REJECT 보호: 두 개의 승인된 Claim 중 하나만 반려되면 Party와 Fact는 유지된다."""
        case, doc1 = _create_case_with_doc(db_session)
        doc2 = EvidenceDocument(
            case_id=case.id,
            original_filename="E02_문자.txt",
            safe_storage_key=f"safe2_{case.id}.txt",
            media_type="text/plain",
            size_bytes=512,
            sha256="b" * 64,
            status="REVIEW_REQUIRED",
        )
        db_session.add(doc2)
        db_session.flush()

        c1 = EvidenceClaim(
            case_id=case.id,
            evidence_id=doc1.id,
            statement="임대인은 박정훈이다.",
            claim_type="PARTY_INFO",
            review_status="PENDING",
        )
        c2 = EvidenceClaim(
            case_id=case.id,
            evidence_id=doc2.id,
            statement="문서에는 임대인이 박정훈으로 기재되어 있다.",
            claim_type="PARTY_INFO",
            review_status="PENDING",
        )
        db_session.add_all([c1, c2])
        db_session.commit()

        process_evidence_review(db=db_session, claim_id=c1.id, action="APPROVE")
        process_evidence_review(db=db_session, claim_id=c2.id, action="APPROVE")
        assert db_session.query(Party).filter_by(case_id=case.id).count() == 1

        # c1만 반려 -> c2가 여전히 지지하므로 박정훈(임대인) Party 유지
        process_evidence_review(db=db_session, claim_id=c1.id, action="REJECT")
        parties = db_session.query(Party).filter_by(case_id=case.id).all()
        assert len(parties) == 1
        assert (parties[0].name, parties[0].role) == ("박정훈", "임대인")

    def test_t12_manual_party_and_event_protection(self, db_session):
        """T12. 수동 Party / Event 보호: 사용자가 직접 등록한 MANUAL 데이터는 동기화 시 삭제·덮어쓰기되지 않는다."""
        case, _ = _create_case_with_doc(db_session)
        manual_party = Party(
            case_id=case.id,
            name="김변호사",
            role="소송대리인",
            notes="수동 입력 메모",
            source_type="MANUAL",
        )
        manual_event = Event(
            case_id=case.id,
            title="1차 조정기일 출석",
            event_date="2026-11-20",
            event_type="법원 기일",
            source_type="MANUAL",
        )
        fact = Fact(
            case_id=case.id,
            statement="임대인은 박정훈이다.",
            fact_type="PARTY_INFO",
        )
        db_session.add_all([manual_party, manual_event, fact])
        db_session.commit()

        synchronize_case_entities(db_session, case.id, dry_run=False, queue_graph_sync=False)
        db_session.commit()

        parties = db_session.query(Party).filter_by(case_id=case.id).all()
        assert {(p.name, p.role) for p in parties} == {
            ("김변호사", "소송대리인"),
            ("박정훈", "임대인"),
        }
        events = db_session.query(Event).filter_by(case_id=case.id).all()
        assert len(events) == 1
        assert events[0].title == "1차 조정기일 출석"
        assert events[0].source_type == "MANUAL"

    def test_t13_idempotency_verification(self, db_session):
        """T13. 멱등성 검증: 동기화 및 복구 함수를 3회 이상 반복 실행해도 Party와 Event가 중복 누적되지 않는다."""
        case, _ = _create_case_with_doc(db_session)
        facts = [
            Fact(case_id=case.id, statement="임대인은 박정훈이다.", fact_type="PARTY_INFO"),
            Fact(case_id=case.id, statement="임차인은 이수현이다.", fact_type="PARTY_INFO"),
            Fact(
                case_id=case.id,
                statement="임대차 기간은 2022년 3월 1일부터 2024년 2월 28일까지이다.",
                fact_type="DATE_INFO",
            ),
        ]
        db_session.add_all(facts)
        db_session.commit()

        for _ in range(3):
            synchronize_case_entities(db_session, case.id, dry_run=False, queue_graph_sync=False)
            db_session.commit()

        assert db_session.query(Party).filter_by(case_id=case.id).count() == 2
        assert db_session.query(Event).filter_by(case_id=case.id).count() == 2

    @patch("ai_legal_helper.database.graph_sync_worker.queue_sync_task")
    def test_t14_rebuild_case_entities_backfill_and_dry_run(self, mock_queue, db_session):
        """T14. 기존 사건 복구(rebuild_case_entities) 검증: dry_run 미리보기 후 실제 반영이 정확히 동작한다."""
        case, _ = _create_case_with_doc(db_session)
        db_session.add_all([
            Fact(case_id=case.id, statement="임대인은 박정훈이다.", fact_type="PARTY_INFO"),
            Fact(case_id=case.id, statement="임차인은 이수현이다.", fact_type="PARTY_INFO"),
            Fact(case_id=case.id, statement="계약금 지급기일은 2022년 2월 20일이다.", fact_type="DATE_INFO"),
        ])
        db_session.commit()

        # dry_run=True 실행 시 DB는 변경되지 않아야 함
        preview = rebuild_case_entities(db_session, case.id, dry_run=True)
        assert preview["before"] == {"facts": 3, "parties": 0, "events": 0}
        assert preview["after"] == {"facts": 3, "parties": 2, "events": 1}
        assert db_session.query(Party).filter_by(case_id=case.id).count() == 0
        assert db_session.query(Event).filter_by(case_id=case.id).count() == 0

        # dry_run=False 실행 시 실제 DB 반영
        applied = rebuild_case_entities(db_session, case.id, dry_run=False)
        assert applied["after"] == {"facts": 3, "parties": 2, "events": 1}
        assert db_session.query(Party).filter_by(case_id=case.id).count() == 2
        assert db_session.query(Event).filter_by(case_id=case.id).count() == 1

    def test_t15_t16_case_detail_schema_serialization_and_consistency(self, db_session):
        """T15 & T16. CaseDetailSchema 직렬화 및 Overview/Facts 데이터 일관성 검증."""
        case, _ = _create_case_with_doc(db_session)
        db_session.add_all([
            Fact(case_id=case.id, statement="임대인은 박정훈이다.", fact_type="PARTY_INFO"),
            Fact(case_id=case.id, statement="임차인은 이수현이다.", fact_type="PARTY_INFO"),
            Fact(case_id=case.id, statement="주택 인도 예정일은 2022년 3월 1일이다.", fact_type="DATE_INFO"),
        ])
        db_session.commit()
        synchronize_case_entities(db_session, case.id, dry_run=False, queue_graph_sync=False)
        db_session.commit()
        db_session.refresh(case)

        detail = CaseDetailSchema.model_validate(case)
        assert len(detail.facts) == 3
        assert len(detail.parties) == 2
        assert len(detail.events) == 1
        assert detail.events[0].occurrence_status == "SCHEDULED"
        assert detail.events[0].event_type == "인도 예정일"

    def test_t17_neo4j_snapshot_includes_parties_and_events(self, db_session):
        """T17. Neo4j 그래프 동기화 스냅샷에 생성된 Party, Event, event_fact_links, event_order가 반영된다."""
        case, _ = _create_case_with_doc(db_session)
        db_session.add_all([
            Fact(case_id=case.id, statement="임대인은 박정훈이다.", fact_type="PARTY_INFO"),
            Fact(case_id=case.id, statement="계약금 지급기일은 2022년 2월 20일이다.", fact_type="DATE_INFO"),
            Fact(case_id=case.id, statement="잔금 지급기일은 2022년 3월 1일이다.", fact_type="DATE_INFO"),
        ])
        db_session.commit()
        synchronize_case_entities(db_session, case.id, dry_run=False, queue_graph_sync=False)
        db_session.commit()

        snap = collect_case_snapshot(db_session, case.id)
        assert snap is not None
        assert len(snap["parties"]) == 1
        assert snap["parties"][0]["name"] == "박정훈"
        assert len(snap["events"]) == 2
        assert len(snap["event_fact_links"]) == 2
        assert len(snap["event_order"]) == 1

    def test_t18_cross_domain_generalization_without_hardcoding(self, db_session):
        """T18. 범용성 검증: 주택임대차 외 근로계약·민사소송(법인 당사자 포함)에서도 정상 동작한다."""
        case, _ = _create_case_with_doc(db_session, title="근로 및 손해배상 분쟁")
        db_session.add_all([
            Fact(
                case_id=case.id,
                statement="원고는 김민준이고 피고는 주식회사 한빛테크이다.",
                fact_type="PARTY_INFO",
            ),
            Fact(
                case_id=case.id,
                statement="근로계약 기간은 2025년 1월 1일부터 2025년 12월 31일까지이다.",
                fact_type="DATE_INFO",
            ),
        ])
        db_session.commit()
        synchronize_case_entities(db_session, case.id, dry_run=False, queue_graph_sync=False)
        db_session.commit()

        parties = db_session.query(Party).filter_by(case_id=case.id).all()
        assert {(p.name, p.role) for p in parties} == {
            ("김민준", "원고"),
            ("주식회사 한빛테크", "피고"),
        }
        events = db_session.query(Event).filter_by(case_id=case.id).all()
        assert len(events) == 2
        assert {e.event_date for e in events} == {"2025-01-01", "2025-12-31"}
