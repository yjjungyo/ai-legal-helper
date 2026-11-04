"""부분 수정은 지정된 원문만 변경하며 그 외 초안은 바이트 단위로 보존한다."""
import json
import pytest

from ai_legal_helper.agents.document_answer import apply_verified_draft_patches


def test_only_targeted_text_changes():
    draft = "### 계약 종료\n계약은 종료되었습니다.\n\n### 손해배상\n손해는 무조건 배상됩니다.\n\n### 대응\n내용증명을 준비하세요."
    patch = {"patches": [{"old_text": "손해는 무조건 배상됩니다.",
                          "new_text": "손해배상은 요건과 입증 여부에 따라 달라집니다."}]}
    revised = apply_verified_draft_patches(draft, json.dumps(patch, ensure_ascii=False))
    assert revised == draft.replace("손해는 무조건 배상됩니다.", patch["patches"][0]["new_text"])


@pytest.mark.parametrize("patches", [
    [{"old_text": "없던 문장", "new_text": "수정"}],
    [{"old_text": "반복", "new_text": "수정"}],
    [{"old_text": "반복", "new_text": "수정"}, {"old_text": "반복", "new_text": "다른 수정"}],
    [],
])
def test_ambiguous_or_empty_patches_fail_closed(patches):
    with pytest.raises(ValueError):
        apply_verified_draft_patches("반복 그리고 반복", json.dumps({"patches": patches}, ensure_ascii=False))


def test_overlapping_patches_fail_closed():
    with pytest.raises(ValueError, match="OVERLAPPING"):
        apply_verified_draft_patches("abcdef", json.dumps({"patches": [
            {"old_text": "abcd", "new_text": "X"},
            {"old_text": "cdef", "new_text": "Y"},
        ]}))
