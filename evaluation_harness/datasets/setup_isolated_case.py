# -*- coding: utf-8 -*-
"""
모듈명: setup_isolated_case.py

[역할]
SC-001 평가 전용 격리 환경 구축 스크립트.
기존 운영/테스트 DB 데이터(fa8f..., 7234... 등)를 일체 변경하지 않고(Non-destructive Isolation),
`C:\myprjs\ai_master\SC-001_전세보증금미반환_사건자료\02_증거원문TXT`의 18건 전체 증거 파일을
신규 격리 평가 사건(`c18e0118-0000-4000-8000-000000000018`)에 온전히 적재하고 구조화한다.

[주요 기능]
1. `Case` 레코드 생성 (격리 ID: c18e0118-0000-4000-8000-000000000018)
2. E01 ~ E18 원본 파일 18건 로컬 스토리지 보관 및 `EvidenceDocument` 레코드 생성 (APPROVED)
3. 당사자(Parties: 이수현, 박정훈, 우리은행, HUG) 등록
4. 기초 사실관계(Facts) 및 확정(FactAdjudication: EVIDENCE_SUPPORTED) 구성
5. 타임라인 사건(Events: 임대차계약, 전입/확정일자, 해지통고, 가압류 등) 등록
"""

import os
import glob
import uuid
import hashlib
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List

from sqlalchemy.orm import Session
from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import (
    Case,
    EvidenceDocument,
    Party,
    Fact,
    FactAdjudication,
    Event,
)

logger = logging.getLogger(__name__)

ISOLATED_CASE_ID = "c18e0118-0000-4000-8000-000000000018"
RAW_EVIDENCE_DIR = Path(r"C:\myprjs\ai_master\SC-001_전세보증금미반환_사건자료\02_증거원문TXT")
STORAGE_DIR = Path("backend/storage/evidence")


def compute_sha256(filepath: Path) -> str:
    """파일의 SHA-256 해시를 계산한다."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def setup_isolated_case() -> Dict[str, Any]:
    """18건 전체 증거를 보유한 격리 평가 케이스를 DB에 구성한다."""
    db: Session = SessionLocal()
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Case 레코드 생성 또는 조회
        case = db.query(Case).filter(Case.id == ISOLATED_CASE_ID).first()
        if not case:
            case = Case(
                id=ISOLATED_CASE_ID,
                user_id="f83a07d3-7c9b-45fe-bf30-57efc0e9299d",
                title="SC-001 전세보증금 미반환 사건 (격리 평가 18건 전체 적재)",
                case_type="HOUSING_LEASE",
                description="SC-001 전세보증금 3억 원 미반환 사건 전체 18건 원문 증거 격리 적재 케이스",
                status="ACTIVE",
            )
            db.add(case)
            db.commit()
            logger.info(f"격리 Case 생성 완료: {ISOLATED_CASE_ID}")
        else:
            logger.info(f"기존 격리 Case 사용: {ISOLATED_CASE_ID}")

        # 2. 증거 파일 18건 적재
        raw_files = sorted(list(RAW_EVIDENCE_DIR.glob("*.txt")))
        doc_map: Dict[str, EvidenceDocument] = {}

        for rf in raw_files:
            filename = rf.name
            existing_doc = (
                db.query(EvidenceDocument)
                .filter(EvidenceDocument.case_id == ISOLATED_CASE_ID, EvidenceDocument.original_filename == filename)
                .first()
            )

            if existing_doc:
                doc_map[filename[:3]] = existing_doc
                continue

            file_hash = compute_sha256(rf)
            size_bytes = rf.stat().st_size
            storage_key = f"{uuid.uuid4().hex}.txt"
            target_storage_path = STORAGE_DIR / storage_key

            shutil.copy2(rf, target_storage_path)

            doc = EvidenceDocument(
                id=str(uuid.uuid4()),
                case_id=ISOLATED_CASE_ID,
                original_filename=filename,
                safe_storage_key=storage_key,
                media_type="text/plain",
                size_bytes=size_bytes,
                sha256=file_hash,
                status="APPROVED",
                source_kind="TXT",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            doc_map[filename[:3]] = doc
            logger.info(f"증거 파일 적재 완료: {filename} -> {doc.id}")

        # 3. 당사자(Parties) 등록
        existing_parties = db.query(Party).filter(Party.case_id == ISOLATED_CASE_ID).all()
        if not existing_parties:
            parties_data = [
                Party(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    name="이수현",
                    role="임차인",
                    party_relationship="임대차계약 당사자",
                    notes="연락처: 010-7254-9142 | 역할: 작성자/임차인",
                    verification_status="DOCUMENT_VERIFIED",
                ),
                Party(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    name="박정훈",
                    role="임대인",
                    party_relationship="임대차계약 당사자",
                    notes="연락처: 010-4826-1357 | 역할: 소유자/임대인",
                    verification_status="DOCUMENT_VERIFIED",
                ),
                Party(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    name="우리은행",
                    role="가압류채권자",
                    party_relationship="후순위 가압류 권리자",
                    notes="가압류 청구금액: 72,000,000원 (2026.08.10 등기)",
                    verification_status="DOCUMENT_VERIFIED",
                ),
                Party(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    name="주택도시보증공사(HUG)",
                    role="가압류채권자",
                    party_relationship="후순위 가압류 권리자",
                    notes="가압류 청구금액: 120,000,000원 (2026.09.15 등기)",
                    verification_status="DOCUMENT_VERIFIED",
                ),
            ]
            for p in parties_data:
                db.add(p)
            db.commit()
            logger.info("4인 당사자 등록 완료")

        # 4. 사실관계(Facts) 및 확정(FactAdjudication) 등록
        existing_facts = db.query(Fact).filter(Fact.case_id == ISOLATED_CASE_ID).all()
        if not existing_facts:
            facts_definitions = [
                ("임대차계약 체결일은 2022년 2월 20일이고, 보증금은 300,000,000원, 임대차 기간은 2022.03.01부터 2024.02.29까지 2년이다.", "CONTRACT", "E01"),
                ("임차인은 2022년 2월 20일 계약금 30,000,000원, 2022년 3월 1일 잔금 270,000,000원을 임대인 계좌로 전액 지급 완료하였다.", "PAYMENT", "E02"),
                ("임차인은 2022년 3월 1일 가람오피스텔 503호에 입주 및 전입신고를 마치고 확정일자를 부여받았다.", "RESIDENCE", "E03"),
                ("최초 임대차기간 만료 시점(2024.02.29) 전후로 당사자 간 갱신거절 통지가 없어 계약은 동일 조건으로 묵시적 갱신되었다.", "CONTRACT", "E04"),
                ("임차인은 2026년 4월 1일 임대인에게 2026년 9월 30일 퇴거 및 보증금 3억 원 전액 반환을 요청하는 해지통고 문자를 발송하여 도달하였다.", "NOTICE", "E05"),
                ("임대인은 2026년 5월 20일 신규 세입자가 들어오면 보증금 일부를 먼저 지급하고 잔금은 1년 뒤에 지급하겠다는 분할변제를 제안하였다.", "NEGOTIATION", "E06"),
                ("임차인은 2026년 5월 19일 및 9월 25일 임대인과의 통화에서 일방적 분할반환 제안을 거절하고 9월 30일 전액 일시반환을 확답 요구하였다.", "NEGOTIATION", "E07"),
                ("임대인은 2026년 8월 10일 대출을 통한 보증금 반환을 시도하였으나 추가 대출이 거절되었음을 통보하였다.", "NEGOTIATION", "E13"),
                ("해당 부동산에는 2026년 8월 10일 우리은행 7,200만 원, 2026년 9월 15일 HUG 1억 2,000만 원의 가압류가 설정되어 있다.", "ATTACHMENT", "E09"),
                ("임대인은 2026년 9월 30일 약정일이 지난 현재까지 보증금 3억 원 전액을 반환하지 않고 있다.", "BREACH", "E15"),
                ("임차인은 2026년 10월 15일 현재 503호의 출입카드와 열쇠를 소지하며 적법하게 점유 및 주민등록을 유지하고 있다.", "RESIDENCE", "E16"),
                ("임차인은 전세대출 보증보험(반환보증)에 가입되어 있지 않음을 거래은행을 통해 확인하였다.", "GENERAL", "E17"),
            ]

            for stmt, ftype, elabel in facts_definitions:
                doc_obj = doc_map.get(elabel)
                ref_id = doc_obj.id if doc_obj else None

                f_obj = Fact(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    statement=stmt,
                    fact_type=ftype,
                    confidence=1.0,
                    source_type="DOCUMENT",
                    source_ref=ref_id,
                    verification_status="VERIFIED",
                )
                db.add(f_obj)
                db.commit()
                db.refresh(f_obj)

                # FactAdjudication 추가 (EVIDENCE_SUPPORTED)
                adj = FactAdjudication(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    fact_id=f_obj.id,
                    adjudication_status="EVIDENCE_SUPPORTED",
                    supporting_evidence_ids=[ref_id] if ref_id else [],
                    adjudication_basis=f"증거 {elabel} 원문 증빙에 의해 직접 확인됨",
                )
                db.add(adj)
            db.commit()
            logger.info("핵심 사실관계 및 확정 레코드 등록 완료")

        # 5. 타임라인 사건(Events) 등록
        existing_events = db.query(Event).filter(Event.case_id == ISOLATED_CASE_ID).all()
        if not existing_events:
            events_data = [
                Event(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    title="임대차계약 체결",
                    description="가람오피스텔 503호 보증금 3억 원 전세계약 체결 (계약금 3,000만 원 지급)",
                    event_date="2022-02-20",
                    date_precision="DAY",
                    event_type="CONTRACT",
                    occurrence_status="OCCURRED",
                ),
                Event(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    title="잔금 지급, 입주, 전입신고 및 확정일자 부여",
                    description="잔금 2억 7,000만 원 지급 완료 후 전입신고 및 확정일자 취득 (대항력 효력발생: 2022-03-02 00:00)",
                    event_date="2022-03-01",
                    date_precision="DAY",
                    event_type="RESIDENCE",
                    occurrence_status="OCCURRED",
                ),
                Event(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    title="최초 임대차기간 만료 및 묵시적 갱신",
                    description="별도 통지 없이 종전 조건과 동일하게 2년 묵시적 갱신됨",
                    event_date="2024-02-29",
                    date_precision="DAY",
                    event_type="CONTRACT",
                    occurrence_status="OCCURRED",
                ),
                Event(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    title="임차인의 해지통고 및 보증금 반환 요청 문자 도달",
                    description="2026.09.30 퇴거 및 보증금 반환 요청 통고 (법정 해지효력: 2026.07.01)",
                    event_date="2026-04-01",
                    date_precision="DAY",
                    event_type="NOTICE",
                    occurrence_status="OCCURRED",
                ),
                Event(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    title="임대인의 무담보 분할변제 제안",
                    description="새 세입자 입주 시 일부 지급, 잔금 1년 뒤 지급 제안 수신 (임차인 거부)",
                    event_date="2026-05-20",
                    date_precision="DAY",
                    event_type="NEGOTIATION",
                    occurrence_status="OCCURRED",
                ),
                Event(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    title="주택임대차보호법 제6조의2 제2항에 따른 법정 해지 효력 발생",
                    description="해지통고 도달 후 3개월 경과로 계약 법정 종료",
                    event_date="2026-07-01",
                    date_precision="DAY",
                    event_type="LEGAL_EFFECT",
                    occurrence_status="OCCURRED",
                ),
                Event(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    title="우리은행 가압류 기입등기",
                    description="청구금액 72,000,000원의 가압류 설정",
                    event_date="2026-08-10",
                    date_precision="DAY",
                    event_type="ATTACHMENT",
                    occurrence_status="OCCURRED",
                ),
                Event(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    title="HUG 주택도시보증공사 가압류 기입등기",
                    description="청구금액 120,000,000원의 가압류 설정",
                    event_date="2026-09-15",
                    date_precision="DAY",
                    event_type="ATTACHMENT",
                    occurrence_status="OCCURRED",
                ),
                Event(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    title="약정 퇴거일 도래 및 임대인의 보증금 미반환 (이행지체 발생)",
                    description="임차인이 지정한 퇴거일 도래하였으나 3억 원 미반환으로 임대인 이행지체",
                    event_date="2026-09-30",
                    date_precision="DAY",
                    event_type="BREACH",
                    occurrence_status="OCCURRED",
                ),
                Event(
                    id=str(uuid.uuid4()),
                    case_id=ISOLATED_CASE_ID,
                    title="임차인의 대항력 유지 및 현재 점유 상태 확인",
                    description="503호 출입카드 소지 및 전입 유지 중",
                    event_date="2026-10-15",
                    date_precision="DAY",
                    event_type="RESIDENCE",
                    occurrence_status="OCCURRED",
                ),
            ]
            for ev in events_data:
                db.add(ev)
            db.commit()
            logger.info("타임라인 10개 핵심 사건 등록 완료")

        return {
            "case_id": ISOLATED_CASE_ID,
            "docs_count": db.query(EvidenceDocument).filter(EvidenceDocument.case_id == ISOLATED_CASE_ID).count(),
            "parties_count": db.query(Party).filter(Party.case_id == ISOLATED_CASE_ID).count(),
            "facts_count": db.query(Fact).filter(Fact.case_id == ISOLATED_CASE_ID).count(),
            "events_count": db.query(Event).filter(Event.case_id == ISOLATED_CASE_ID).count(),
        }

    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = setup_isolated_case()
    print("Isolated case setup finished:", res)

