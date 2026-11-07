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

def test_whitespace_and_indentation_tolerant_matching():
    """LLM이 마크다운 하위 글머리 기호의 선행 들여쓰기 공백을 누락하더라도 고유 구간을 정확히 치환한다."""
    draft = (
        "### 추가공사 판단\n"
        "- **명확한 승인 증거가 없으면**, 청구는 약해집니다.\n"
        "  - 반대로 발주자가\n"
        "    - 변경 시공을 요청했고\n"
        "  - 계약은 엄격합니다.\n\n"
        "### 지체상금\n"
        "- 일당 8만 원입니다."
    )
    # old_text는 "  - 반대로 발주자가"와 "  - 계약은 엄격합니다." 앞의 2칸 들여쓰기 공백이 누락된 형태
    patch = {
        "patches": [
            {
                "old_text": (
                    "- **명확한 승인 증거가 없으면**, 청구는 약해집니다.\n"
                    "- 반대로 발주자가\n"
                    "    - 변경 시공을 요청했고\n"
                    "- 계약은 엄격합니다."
                ),
                "new_text": (
                    "- **계약서 문언상** 명확한 전자적 승인이 있어야 인정됩니다.\n"
                    "  - 추가 확인이 필요합니다."
                ),
            }
        ]
    }
    revised = apply_verified_draft_patches(draft, json.dumps(patch, ensure_ascii=False))
    assert "- **계약서 문언상** 명확한 전자적 승인이 있어야 인정됩니다." in revised
    assert "### 지체상금\n- 일당 8만 원입니다." in revised
    assert "- **명확한 승인 증거가 없으면**" not in revised

def test_bullet_header_variation_tolerant_matching():
    """LLM이 글머리 기호의 볼드 소제목을 임의 변형하더라도 본문 고유 매칭으로 행 전체를 치환한다."""
    draft = (
        "### 해제 효과\n\n"
        "- **해제가 유효하면**: 각 당사자는 원상회복의무를 지고, 받은 금전은 이자를 가산하여 반환해야 합니다(민법 제548조).\n\n"
        "### 손해배상\n- 청구가 가능합니다."
    )
    # LLM이 '- **해제가 유효하면**:' 대신 '- **법률상 구조**: 해제가 유효하면' 형태로 old_text를 지정한 경우
    patch = {
        "patches": [
            {
                "old_text": "- **법률상 구조**: 해제가 유효하면 각 당사자는 원상회복의무를 지고, 받은 금전은 이자를 가산하여 반환해야 합니다(민법 제548조).",
                "new_text": "- **법률상 구조**: 해제가 유효하면 각 당사자는 원상회복의무를 지되, 기시공분 정산 방식은 감정이 필요합니다.",
            }
        ]
    }
    revised = apply_verified_draft_patches(draft, json.dumps(patch, ensure_ascii=False))
    assert "기시공분 정산 방식은 감정이 필요합니다." in revised
    assert "- **해제가 유효하면**" not in revised
    assert "### 손해배상\n- 청구가 가능합니다." in revised


def test_partial_patch_resilience_when_some_patches_miss():
    """복수 패치 중 일부 대상이 누락·불일치하더라도 유효한 다른 패치는 안전하게 적용된다."""
    draft = (
        "### 쟁점 1\n"
        "- 첫 번째 문장입니다.\n\n"
        "### 쟁점 2\n"
        "- 두 번째 문장입니다."
    )
    patch = {
        "patches": [
            {"old_text": "- 첫 번째 문장입니다.", "new_text": "- 수정된 첫 번째 문장입니다."},
            {"old_text": "- 완전히 존재하지 않는 엉뚱한 문장입니다.", "new_text": "- 실패할 패치"},
        ]
    }
    revised = apply_verified_draft_patches(draft, json.dumps(patch, ensure_ascii=False))
    assert "- 수정된 첫 번째 문장입니다." in revised
    assert "- 두 번째 문장입니다." in revised
