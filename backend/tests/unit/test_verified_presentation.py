"""P2: 검증된 답변 구조화가 원문을 훼손하거나 잘못 연결하지 않는지 검사."""
import hashlib

from ai_legal_helper.presentation.builder import build_consultation_presentation


def render(answer, status="PASS", answer_status="DELIVERED", claims=None, sources=None, hash_override=None):
    v = {"status": status, "claims": claims or []}
    if hash_override is not None:
        v["verified_answer_sha256"] = hash_override
    return build_consultation_presentation(
        answer=answer, verification_result=v, verification_status=status,
        answer_status=answer_status, sources=sources or [],
    )


def test_lossless_sections_and_single_lead():
    answer = "네, 가능합니다.\n\n### 법률상 원칙\n민법 제6조에 따라 처리합니다.\n\n### 참고\n[E01_계약서.txt] 내용을 확인하세요."
    result = render(answer, hash_override=hashlib.sha256(answer.encode()).hexdigest())
    assert result is not None
    assert result.verification_binding == "HASH_MATCHED"
    assert result.direct_answer_block_id == "B001"
    assert "".join(b.markdown for b in result.blocks) == answer
    assert len(result.blocks) == 3
    assert [b.kind for b in result.blocks] == ["LEAD", "SECTION", "SECTION"]


def test_citation_line_is_not_section_heading():
    answer = "[E01_임대차계약서.txt]\n후속 내용"
    result = render(answer)
    assert result is not None
    assert len(result.blocks) == 1
    assert result.blocks[0].kind == "LEAD"


def test_verified_hash_mismatch_fails_closed():
    assert render("현재 답변", hash_override="bad-hash") is None


def test_not_pass_or_withheld_has_no_presentation():
    assert render("판단 유보", status="INSUFFICIENT") is None
    assert render("숨겨진 답변", answer_status="WITHHELD") is None


def test_supported_exact_claim_only_maps_known_source():
    answer = "계약이 종료되었습니다. 추가 확인이 필요합니다."
    claims = [
        {"claim": "계약이 종료되었습니다.", "grounding_status": "SUPPORTED",
         "source_ids": ["EV-01", "UNKNOWN-SOURCE"], "claim_type": "CASE_FACT"},
        {"claim": "추가 확인이 필요합니다.", "grounding_status": "UNSUPPORTED",
         "source_ids": ["EV-01"]},
        {"claim": "계약 종료됨", "grounding_status": "SUPPORTED", "source_ids": ["EV-01"]},
    ]
    sources = [{"source_id": "EV-01", "source_type": "CASE_EVIDENCE",
                "original_filename": "E01_계약서.txt", "evidence_id": "ev-uuid"}]
    result = render(answer, claims=claims, sources=sources)
    assert result is not None
    assert len(result.claims) == 1
    assert result.claims[0].source_refs == ["EV-01"]
    assert result.sources[0].document_name == "E01_계약서.txt"
    assert result.blocks[0].claim_refs == ["C001"]


def test_duplicate_claim_text_must_not_guess_occurrence():
    result = render("반환 필요. 반환 필요.", claims=[
        {"claim": "반환 필요.", "grounding_status": "SUPPORTED", "source_ids": ["x"]}
    ], sources=[{"source_id": "x", "source_type": "STATUTE", "statute_name": "민법"}])
    assert result is not None
    assert result.claims == []


def test_without_explicit_verification_pass_no_structured_result():
    from ai_legal_helper.presentation.builder import build_consultation_presentation
    assert build_consultation_presentation(
        answer="문장", verification_result={}, verification_status="PASS",
        answer_status="DELIVERED", sources=[],
    ) is None


def test_numbered_section_heading_splits_blocks_and_preserves_numbering():
    """번호형 섹션 소제목(1. 핵심 결론, 2. 지금 해야 할 일)이 정상 분할되고 일반 번호 목록과 구분되는지 검증."""
    answer = (
        "1. 핵심 결론 및 직접 답변\n"
        "지금 상황에서 가장 안전한 실행 순서는 아래와 같습니다.\n"
        "1. 보증금을 실제로 돌려받기 전에는 임의로 전출하지 마세요.\n"
        "2. 임차권등기명령을 먼저 신청하세요.\n\n"
        "2. 지금 해야 할 일\n"
        "내용증명을 발송하고 등기부등본을 확인하세요.\n\n"
        "3. 쟁점별 상세 법률 분석\n"
        "주택임대차보호법 제3조의3에 근거합니다."
    )
    result = render(answer, hash_override=hashlib.sha256(answer.encode()).hexdigest())
    assert result is not None
    assert "".join(b.markdown for b in result.blocks) == answer
    assert len(result.blocks) == 3
    assert [b.kind for b in result.blocks] == ["SECTION", "SECTION", "SECTION"]
    assert result.blocks[0].title == "1. 핵심 결론 및 직접 답변"
    assert result.blocks[1].title == "2. 지금 해야 할 일"
    assert result.blocks[2].title == "3. 쟁점별 상세 법률 분석"
