"""P1 출처 API 계약과 원본 파일명·법령 조문 정보 보존 회귀 테스트."""
from ai_legal_helper.rag.source_schema import normalize_source_dict
from ai_legal_helper.api.schemas.consultation import Source


def test_evidence_source_api_preserves_exact_filename_and_ids():
    raw = {
        "source_id": "EVIDENCE:doc:SPAN:span",
        "source_type": "CASE_EVIDENCE",
        "evidence_id": "document-uuid",
        "claim_id": "claim-uuid",
        "span_id": "span-uuid",
        "filename": "internal-upload.txt",
        "original_filename": "E10_HUG_관련_구상권_가압류_등기_열람_메모.txt",
        "document_name": "E10_HUG_관련_구상권_가압류_등기_열람_메모.txt",
    }
    result = Source(**normalize_source_dict(raw)).model_dump()
    assert result["original_filename"] == raw["original_filename"]
    assert result["document_name"] == raw["document_name"]
    assert result["file"] == raw["original_filename"]
    assert result["evidence_id"] == "document-uuid"
    assert result["claim_id"] == "claim-uuid"
    assert result["span_id"] == "span-uuid"


def test_statute_api_preserves_article_and_version_details():
    raw = {
        "source_id": "LAW-6",
        "source_type": "STATUTE",
        "statute_name": "민법",
        "article": "제6조",
        "article_title": "처분을 허락한 재산",
        "paragraph_no": "제1항",
        "effective_date": "2026-01-01",
        "source_url": "https://www.law.go.kr",
    }
    result = Source(**normalize_source_dict(raw)).model_dump()
    assert result["article_title"] == "처분을 허락한 재산"
    assert result["paragraph_no"] == "제1항"
    assert result["effective_date"] == "2026-01-01"
    assert result["statute_name"] == "민법"
