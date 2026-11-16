"""상담 프롬프트 압축에서 원문·반대 증거·인용 ID가 보존되는지 검증한다.

실제 모델 호출 없이 동일 본문 공유와 작성기 입력을 검사한다. 모델의 응답 품질이나
실행 시간 개선을 이 테스트의 통과만으로 보장하지 않는다.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from ai_legal_helper.rag.grounding_context import format_grounding_sources


def statute(source_id: str, **changes) -> dict:
    """다른 버전·본문과 구별되는 가상 조문 출처를 만든다."""
    return {"source_id": source_id, "source_type": "STATUTE", "statute_name": "가상법",
            "article": "제1조", "version_id": "v1", "effective_date": "2025-01-01",
            "content": "조건과 예외를 함께 설명하는 가상 원문입니다. " * 60, **changes}


def test_identical_statute_body_shared_without_losing_source_ids():
    """중복 본문만 한 번 전달하고 두 출처 ID와 원본 입력은 보존한다."""
    sources = [statute("source-a"), statute("source-b")]
    original = deepcopy(sources)
    full, _ = format_grounding_sources(sources)
    compact, manifest = format_grounding_sources(sources, compact_repeated_bodies=True)
    assert compact.count(sources[0]["content"].strip()) == 1
    assert '"body_source_id": "source-a"' in compact
    assert manifest["source_ids"] == ["source-a", "source-b"]
    assert manifest["complete"] is True
    assert len(compact) < len(full)
    assert sources == original


@pytest.mark.parametrize("changes", [
    {"content": "다른 단서와 예외가 있는 별도 청크입니다."},
    {"version_id": "v2"}, {"effective_date": "2026-01-01"},
    {"article": "제2조"}, {"addendum_id": "별도 부칙"},
])
def test_distinct_versions_and_chunks_are_not_shared(changes):
    """같은 조문명이라도 버전·시행일·부칙·본문이 다르면 둘 다 전달한다."""
    sources = [statute("a"), statute("b", **changes)]
    rendered, _ = format_grounding_sources(sources, compact_repeated_bodies=True)
    assert '"body_source_id"' not in rendered
    assert sources[0]["content"].strip() in rendered
    assert sources[1]["content"].strip() in rendered


def test_uncited_counter_evidence_and_review_guide_kept():
    """미인용 사건 자료의 말미 반대 사실과 반려 지침은 축약하지 않는다."""
    evidence = {"source_id": "문서.txt", "source_type": "CASE_EVIDENCE",
                "approval_scope": "PARTIAL_APPROVED", "claim_review_guide": "반려된 주장은 제외하세요.",
                "content": "배경 설명. " * 100 + "말미에 계약 종료 합의 철회 기록이 있습니다."}
    rendered, manifest = format_grounding_sources([evidence], compact_repeated_bodies=True)
    assert evidence["content"] in rendered
    assert evidence["claim_review_guide"] in rendered
    assert manifest["omitted_source_ids"] == []


def test_same_id_content_conflict_still_fails_closed():
    """압축 모드에서도 같은 출처 ID의 원문 충돌을 숨기지 않는다."""
    with pytest.raises(ValueError, match="SOURCE_ID_CONTENT_CONFLICT"):
        format_grounding_sources([statute("a"), statute("a", content="충돌 본문")],
                                 compact_repeated_bodies=True)


def test_writer_receives_scope_rules_and_does_not_truncate_output(monkeypatch):
    """질문별 작성 규칙을 전달하고 긴 응답의 말미 조건을 사후 절단하지 않는다."""
    from ai_legal_helper.agents.document_answer import write_document_answer

    captured = []
    answer = "분석 문장. " * 600 + "이 결론은 통지 도달이 확인된 경우에만 적용됩니다."

    class FakeLLM:
        """입력을 보관하고 고정 응답을 돌려주는 모델 대역."""

        def invoke(self, messages):
            """모델 호출 없이 실제 작성기 프롬프트를 수집한다."""
            captured.extend(messages)
            return SimpleNamespace(content=answer)

    monkeypatch.setattr("ai_legal_helper.agents.document_answer.get_llm", lambda **kw: FakeLLM())
    evidence = {"source_id": "evidence", "source_type": "CASE_EVIDENCE", "content": "반대 사실을 포함한 원문"}
    sources = [statute("a"), statute("b"), evidence]
    result = write_document_answer("앞선 답변의 조건만 설명해 주세요.", sources, allow_need_more_law=False)
    assert "후속 질문은 이번에 묻는 내용" in captured[0].content
    assert "상세 보고서·전체 검토" in captured[0].content
    assert "반대 사실을 포함한 원문" in captured[1].content
    assert '"body_source_id": "a"' in captured[1].content
    assert result["draft_answer"] == answer
    assert result["answer_source_manifest"] == format_grounding_sources(sources)[1]
