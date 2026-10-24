# -*- coding: utf-8 -*-
"""
테스트 모듈: test_manifest.py

[역할]
Evaluation Harness의 증거 매니페스트 빌더(build_evidence_manifest) 단위 테스트.
원문 증거 디렉토리의 파일 개수(18건), SHA-256 해시 생성 및 DB 대조 상태가 정확한지 검증한다.
"""

import pytest
from evaluation_harness.datasets.manifest import build_evidence_manifest


def test_build_evidence_manifest():
    """SC-001 원문 디렉토리의 18개 증거 파일에 대해 매니페스트가 올바르게 생성되어야 한다."""
    manifest = build_evidence_manifest()

    assert manifest.total_raw_files == 18
    assert len(manifest.files) == 18
    assert manifest.case_name == "SC-001_전세보증금미반환_사건자료"

    # E01 계약서 파일 메타데이터 검증
    e01_item = next((f for f in manifest.files if f.label == "E01"), None)
    assert e01_item is not None
    assert e01_item.filename == "E01_주택임대차계약서.txt"
    assert len(e01_item.sha256) == 64
    assert e01_item.size_bytes > 0
