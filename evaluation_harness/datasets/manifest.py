# -*- coding: utf-8 -*-
"""
모듈명: manifest.py

[모듈 개요]
SC-001 사건 원본 증거자료 디렉터리의 실제 파일 무결성을 검증하고,
PostgreSQL DB(EvidenceDocument)에 등록된 상태와의 정합성 및 불일치를 대조하는 매니페스트 빌더 모듈이다.
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Optional

from evaluation_harness.config import config
from evaluation_harness.datasets.schemas import EvidenceFileManifestItem, EvidenceManifest
from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import EvidenceDocument


def build_evidence_manifest(
    raw_dir: Optional[Path] = None,
    case_id: Optional[str] = None,
) -> EvidenceManifest:
    """원본 증거 디렉터리의 파일을 스캔하고 DB 등록 상태와 대조하여 매니페스트를 생성한다.

    Args:
        raw_dir: 증거 파일 디렉터리 경로 (미지정 시 config.raw_evidence_dir 사용).
        case_id: 대조할 PostgreSQL 사건 ID (미지정 시 config.default_case_id 사용).

    Returns:
        EvidenceManifest: 파일 무결성 해시 및 DB 대조 결과가 포함된 매니페스트 객체.
    """
    target_dir = raw_dir or config.raw_evidence_dir
    target_case_id = case_id or config.default_case_id

    if not target_dir.exists():
        raise FileNotFoundError(f"증거 원문 디렉터리를 찾을 수 없습니다: {target_dir}")

    # DB에서 등록된 증거 문서 목록 조회
    db_docs = {}
    if target_case_id:
        try:
            with SessionLocal() as db:
                docs = db.query(EvidenceDocument).filter_by(case_id=target_case_id).all()
                for d in docs:
                    db_docs[d.original_filename] = d
        except Exception:
            pass

    file_items = []
    missing_in_db = []
    db_registered_count = 0

    raw_files = sorted(os.listdir(target_dir))
    for fname in raw_files:
        fpath = target_dir / fname
        if not fpath.is_file():
            continue

        with open(fpath, "rb") as fp:
            data = fp.read()

        sha256 = hashlib.sha256(data).hexdigest()
        text = data.decode("utf-8", errors="replace")
        lines = len(text.splitlines())
        size = len(data)

        # 라벨 추출 (예: E01, E18)
        lbl_match = re.match(r"^(E\d+)", fname)
        label = lbl_match.group(1) if lbl_match else "UNKNOWN"

        is_in_db = fname in db_docs
        db_doc = db_docs.get(fname)
        db_id = db_doc.id if db_doc else None
        db_status = db_doc.status if db_doc else None

        if is_in_db:
            db_registered_count += 1
        else:
            missing_in_db.append(fname)

        preview = text[:200].replace("\n", " ").strip()

        item = EvidenceFileManifestItem(
            filename=fname,
            label=label,
            size_bytes=size,
            sha256=sha256,
            line_count=lines,
            is_in_db=is_in_db,
            db_document_id=db_id,
            db_status=db_status,
            preview=preview,
        )
        file_items.append(item)

    manifest = EvidenceManifest(
        case_name="SC-001_전세보증금미반환_사건자료",
        source_dir=str(target_dir),
        total_raw_files=len(file_items),
        db_case_id=target_case_id,
        db_registered_count=db_registered_count,
        missing_files_in_db=missing_in_db,
        files=file_items,
    )
    return manifest

