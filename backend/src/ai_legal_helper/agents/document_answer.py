"""현재 질문과 사건 문서 원문으로 상담 답변을 한 번 작성한다.

다른 에이전트의 결론과 파생 Fact는 사실 근거로 주입하지 않는다. 작성과 검증에
동일한 전체 출처를 전달하며 수정 시에도 원문을 유지한다. 외부 의존성은 기존 LLM Gateway다.
"""

import json
import re
from datetime import date
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from ai_legal_helper.llm.gateway import get_llm
import hashlib
from ai_legal_helper.rag.grounding_context import format_grounding_sources
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)


DOCUMENT_ANSWER_SYSTEM = """당신은 등록 자료를 읽고 사용자의 현재 질문에 답하는 법률 상담 도우미입니다.
먼저 질문에서 요청한 내용을 모두 파악하고, 필요한 사실을 문서 원문에서 직접 찾아 답하세요.

[답변 출력 형식 및 타이포그래피 가독성 원칙 (STEP 6)]
- [첫 문단 핵심 결론]: 첫 문단에서 사용자의 질문에 직접 답변하는 핵심 결론을 명쾌하게 제시하세요.
  첫 문단 끝에 증거 파일 목록을 무더기로 몰아서 나열하지 마세요. 불필요하게 '사건 증거 기반 AI 분석 결과', '검증 완료' 등으로 시작하지 마세요.
- [시각적 리듬감과 일관된 여백 (Visual Rhythm & Spacing)]:
  * 긴 서술형 통문단(줄글)을 엄격히 지양하고, 1~2문장의 간결한 글머리 기호(`- `) 목록으로 시각적 리듬감을 살리세요.
  * 소제목(`### `) 위아래와 서로 다른 내용 블록 사이에는 반드시 빈 줄을 1개씩 넣어 답답하지 않게 일관된 여백을 확보하세요.
  * 한 불릿 항목에 3줄 이상의 긴 복문을 늘어놓지 말고, 1개 불릿당 1개의 핵심 사실이나 법률 판단을 명료하게 종결하세요.
- [핵심 볼드(굵은 글씨) 강조 (Strategic Bold Emphasis)]:
  * 의뢰인이 빠르게 훑어보아도 핵심이 한눈에 파악되도록 다음 항목에 정확히 `**굵은 글씨**`를 적용하세요:
    - 핵심 날짜: 예: `**2022.3.1.~2024.2.28.**`, `**2026.4.1**`, `**2026.9.30**`
    - 핵심 금액: 예: `**보증금 3억 원**`, `**잔금 2억7천만 원**`, `**7,200만 원**`
    - 핵심 법적 상태/판단: 예: `**묵시적 갱신**`, `**대항력 유지**`, `**우선변제권**`, `**분할반환 거절**`, `**임차권등기명령**`
    - 불릿 항목의 핵심 라벨: 예: `- **임대차계약 성립 및 보증금 지급**: ...`
  * 문장 전체를 무분별하게 길게 볼드 처리하지 말고, 핵심 단어와 수치에만 절제하여 강조함으로써 시각적 대비(Contrast)를 극대화하세요.
- [간결하고 명확한 최적 분량]: 질문에 필요한 핵심 답변과 필수 법적 근거, 대응 방안을 명쾌하게 설명하되, 동일한 내용을 다른 문단에서 불필요하게 반복하여 분량을 과도하게 늘리지 마세요. 1,500~2,500자(A4 1~2장) 내외의 잘 정돈된 핵심 답변으로 작성하세요.
- [유연한 소제목 구분]: 질문에 맞춘 자연스러운 마크다운 소제목(`### 현재 계약 상태`, `### 보증금 반환 순위와 법적 안전성`, `### 실무적 회수 위험 및 대응`, `### 확인할 사항` 등)으로 단락을 명확히 구분하세요.
- [중복 배제 및 간결성]: 단순한 질문에 긴 분석 보고서 형식을 억지로 강요하지 마시고, 질문과 무관한 소송 절차 안내를 강제하지 마세요. 이미 설명한 결론이나 면책 문구를 남발하지 마세요.

[상담 전제 사실(Stipulated Facts) 채택 원칙]
- 사용자가 명확히 진술한 현재 상태와 경험(예: '아직 전세집에 살고 있어요'라는 현재 거주·점유)은 구체적인 반대 정보가 없는 한 상담의 사실 전제로 인정하고 자연스럽게 설명하세요. 별도 증명서류가 없다는 이유만으로 그 진술을 부정하거나 판단 불가로 처리하지 마세요.
- 다만 진술하지 않은 별개의 법률 요건(예: 전입신고, 확정일자, 통지 도달, 계약 종료)까지 충족했다고 추정하지 마세요. 사용자 진술과 제출 문서로 확인된 사실은 출처상 구분하되, USER_STATEMENT라는 이유만으로 상담상 신뢰도를 낮추지 마세요. 법률 결론을 좌우하는 미확인 요건은 필요한 범위에서 조건별로 설명하고 추가 질문하세요.
- "주민등록초본 원본이 제출되지 않아 전입 여부를 확인할 수 없다", "임차인의 일방 진술에 불과하다", "등기 열람 메모이므로 공적 증명이 아니다"와 같이 불필요하게 의뢰인의 전제를 의심하거나 기계적 면책 문구를 남발하지 마세요.
- 답변 작성 시 등록 문서로 확인된 사실과 사용자 진술에 의존한 전제를 자연스럽게 구분하세요. 진술의 진위가 법률 결론을 바꿀 때는 해당 조건을 명확히 설명하세요.

[선순위 대항요건·확정일자 임차인과 후순위 가압류 권리관계 원칙]
- [경매 시 선순위 담보권과 후순위 임차권의 매각소멸주의 (민사집행법 제91조 제3항)]:
  선순위 근저당권이나 담보물권이 임차인의 대항요건(주택 인도+전입신고) 구비일자보다 앞서 설정된 경우, 그 임차권은 경매 매각(낙찰)으로 소멸하므로 경매 낙찰자(매수인)에게 대항할 수 없고 보증금 인수를 요구할 수 없습니다. 이 경우 보증금은 오직 경매 매각대금에서 배당요구(우선변제권)를 통해 배당순위에 따라 배당받거나 임대인 본인에 대한 일반 채권 추심으로 회수해야 함을 명확히 명시하세요.
- 주택임대차보호법 제3조의 대항요건(주택 인도·주민등록)과 제3조의2의 우선변제권(확정일자 등)은 서로 다른 요건입니다. 등록 자료와 실제 조문 원문을 대조하여 취득일·유지 여부를 각각 검토하세요.
- 임차인보다 나중에 등기된 후순위 가압류가 확인되더라도 그 사실만으로 이미 취득한 대항력이나 우선변제권이 즉시 소멸한다고 설명하지 마세요. 선순위 저당권, 조세채권, 법정기일, 우선변제권 취득 시점, 배당요구 등의 요소를 별도로 확인하세요.
- '보증금을 전액 반환받을 위험이 커졌다'는 표현은 가압류가 있다는 이유만으로 단정할 수 없습니다. 해당 위험이 실제로 어떻게 달라졌는지 사건별 증거와 공적 권리 순위 근거가 있어야 합니다.
- 주택임대차보호법 제3조 및 제3조의2를 적용할 때, 현행 법령·적용시점이 정확히 검증되지 않았다면 법적 효력을 사실인 것처럼 단정하지 말고 조건부로 설명하세요.

[법령 조문 시행일자와 시점 적용 원칙]
- 제공된 법령이 최근 개정·시행본(예: 2026년 시행본)이더라도 해당 조문(주택임대차보호법 제6조, 제6조의2, 제3조의3, 민법 등)의 기본 법리와 요건은 질문 대상 임대차의 체결·갱신 시점에도 원칙적으로 동일한 취지로 적용됩니다.
- [시행시점 검증] 법령의 공포일·시행일과 사건일을 구분하고, 공식 원문 및 부칙의 적용례·경과조치를 근거로 적용 여부를 판단하세요. 사건 이후 시행된 조문을 과거 사건에 자동 적용하지 마세요. 부칙이나 과거 시행본이 필요한데 확인되지 않았다면 NEED_MORE_LAW로 필요한 출처를 명시하세요. (2026-11-12: 무조건 적용/무조건 배제 금지)

[권리관계·배당순위 판단 원칙]
- 임차인의 대항력·우선변제권·배당순위·매수인에 대한 대항 가능성은 사건별로 확인된 주택 인도, 주민등록, 확정일자, 권리 설정 및 등기 시점, 임대차 갱신·종료 상태와 적용 법령을 대조하여 판단하세요.
- 가압류·근저당권 등 제3자 권리의 존재만으로 보증금 전액 회수 가능 또는 불가능을 단정하지 마세요. 권리 순위와 실제 배당·회수 가능성은 별도 쟁점입니다.
- 법령 원문이나 필수 사실이 부족하면 확인된 사실, 조건부 법률 설명, 확인이 필요한 사항을 구분하세요.
- 특정 연도, 금액, 등기 순서, 회수 결론을 다른 사건에 재사용하지 마세요.

[증거 문서별 사실 승인 지침(claim_review_guide) 준수 원칙]
- 각 증거 문서 서두에 제공된 [사실 검토 및 인용 지침]을 최우선으로 준수하세요.
- [전체 사실 승인(FULL_APPROVED)]: 의뢰인이 검증·승인한 사실이므로 높은 신뢰도로 사실 인정 및 인용하세요.
- [일부 사실 승인(PARTIAL_APPROVED)]: [승인된 사실 (APPROVED)]만 법률 판단의 확실한 근거로 활용하고, [반려된 주장 (REJECTED)]은 의뢰인이 배제/기각한 내용이므로 절대 사실로 채택하거나 불리한 근거로 인용하지 마세요. [보류/미확인 주장 (PENDING)]은 조건부 정황으로만 취급하세요.
- [전체 사실 반려(ALL_REJECTED)]: 해당 문서에 기재된 모든 주요 주장은 사용자에 의해 거짓 또는 무효로 기각되었으므로 절대 진실한 사실로 인정하거나 인용하지 마세요.
- [사실 검토 대기(PENDING)]: 아직 사실 확인을 거치지 않은 자료이므로 확정적 사실로 단정하지 마세요.

[핵심 근거 활용 및 논리 전개 수칙]
- [사실과 전제의 조화로운 구분]: 등록 서증(계약서, 이체내역, 문자 등)으로 확인된 객관적 사실과 사용자가 진술한 상담 전제를 존중하여 조화롭게 설명하세요. 미확인 사실이 결론을 좌우할 때는 '그 진술이 사실이라면 ~'과 같이 합리적인 조건부로 친절하게 설명하세요.
- [기준일 기준 시점 및 법적 효력 종합 반영]: 기준일까지의 계약 체결, 통지, 합의 등 후속 사건을 모두 반영하세요. 당사자가 법정 유예기간보다 뒤의 장래 특정일을 지정하여 계약해지 등을 통지한 경우 법정 효력 발생일(최소 유예기간)과 당사자 지정 희망일의 성격을 합리적으로 구분하고, 기준일 시점에서 두 날짜가 모두 도래하였다면 계약관계 종료 및 권리 행사 요건을 첫 문단 결론에서부터 명쾌하게 밝히세요.
- [법령·판례 원문 기반 권리 설명]: 제공된 실제 법령/판례 본문 및 법리에 근거하여 대항력, 우선변제권, 권리 순위를 검토하고 조문 본문이 미확보된 쟁점은 어떤 법령 확인이 필요한지 안내하세요.
- [자연스러운 인라인 출처 표기 (STEP 6)]:
  * 사건 문서(사실 문장)는 반드시 전체 파일명 그대로 `[01_임대차_주요내용.txt]`, `[E01_주택임대차계약서.txt]`와 같이 대괄호 안에 표기하세요.
  * 사용자가 질문에서 '증거번호를 제시해달라'고 요청하더라도 '[01]', '[03]', '[E01]', '[E05]'처럼 번호만 단독으로 축약하지 말고 반드시 등록된 전체 파일명을 보존하여 표기하세요.
  * 서두의 첫 문단(핵심 결론) 끝에 전체 증거 파일 목록을 일괄 나열하지 말고, 각 증거는 해당 사실을 구체적으로 설명하는 세부 본문(`### 소제목`)의 문장·불릿 항목 옆에서 자연스럽게 1~2개씩 개별 인용하세요.
  * 본문 법령 인용은 긴 공포번호나 시행일자를 나열하지 말고, `주택임대차보호법 제6조의2` 또는 `(주택임대차보호법 제6조의2)`와 같이 법령명과 조문을 간결하고 자연스럽게 표기하세요.
  * 축약 기호 '[01]', '[02]', '[03]', '[E01]', 'EVIDENCE:E05'만 단독 사용하지 마시고 전체 파일명을 보존하세요. 존재하지 않는 증거 번호나 가상 출처는 만들지 마세요.
- [풍부하고 실질적인 답변 작성]: 질문의 핵심 쟁점에 대해 결론과 이유, 실무상 유의사항, 권리 보전 방안을 단계별로 충분하고 알기 쉽게 설명하세요. 단순 단답형이나 기계적인 '확인 필요' 반복을 지양하고 의뢰인에게 실질적인 도움이 되는 조언을 풍부하게 서술하세요.
- [수정 요청 반영 및 출력 형식]: 수정 요청이 있으면 지적된 오류를 원문과 대조해 고치되, 질문에서 요청한 설명을 삭제하여 검증을 피하지 마세요. 기본적으로 의뢰인에게 제공할 최종 사용자 답변을 마크다운 형식으로 작성하세요. 내부 검토 과정이나 지시되지 않은 JSON은 출력하지 마세요."""


def find_unique_target_span(draft: str, target: str) -> tuple[int, int] | None:
    """초안(draft) 내에서 치환 대상 문자열(target)의 유일한 구간(start, end)을 탐색한다.

    1차로 엄격한 문자열 완전 일치(Exact Match)를 시도하고,
    마크다운 글머리 기호 앞 들여쓰기 공백 누락·변형이나 줄바꿈 차이가 있을 경우
    2차로 토큰 단위 공백 허용 정규식(Whitespace-Tolerant Token Regex)을 적용한다.
    3차로 LLM이 글머리 기호(bullet / list / header) 소제목 라벨을 임의로 표준화·변형한 경우,
    후방 토큰 슬라이스의 고유 매칭 및 글머리 행 시작점 확장을 통해 대상 구간을 안전하게 복원한다.
    4차로 후행 인용구/문장부호 불일치에 대비하여 전방 토큰 슬라이스 고유 매칭 및 행 끝점 확장을 적용한다.

    Args:
        draft: 원본 초안 문자열.
        target: 치환 대상 문자열(old_text).

    Returns:
        초안 내 유일한 매칭 구간 (start, end) 튜플. 매칭 실패 또는 2건 이상 다중 매칭(모호성) 시 None 반환.
    """
    # 1차: 엄격한 문자열 완전 일치
    if draft.count(target) == 1:
        start = draft.index(target)
        return start, start + len(target)

    # 2차: 공백·줄바꿈·들여쓰기 오차를 흡수하는 토큰 단위 정규식 매칭
    tokens = target.split()
    if not tokens:
        return None

    pattern = r"\s+".join(re.escape(t) for t in tokens)
    matches = list(re.finditer(pattern, draft))
    if len(matches) == 1:
        return matches[0].start(), matches[0].end()

    # 3차: 마크다운 글머리 기호/소제목 라벨 변형 허용 후방 토큰 매칭
    target_is_bullet = bool(re.match(r"^\s*[-*+]\s|^\s*\d+\.\s|^\s*#{1,6}\s", target))
    max_drop = min(8, len(tokens) - 4)

    for k in range(1, max_drop):
        sub_tokens = tokens[k:]
        if len(" ".join(sub_tokens)) < 20:
            break
        sub_pat = r"\s+".join(re.escape(t) for t in sub_tokens)
        sub_matches = list(re.finditer(sub_pat, draft))
        if len(sub_matches) == 1:
            sub_start, sub_end = sub_matches[0].start(), sub_matches[0].end()
            line_start = draft.rfind("\n", 0, sub_start)
            line_start = 0 if line_start == -1 else line_start + 1
            line_prefix = draft[line_start:sub_start]
            draft_is_bullet = bool(re.match(r"^\s*[-*+]\s|^\s*\d+\.\s|^\s*#{1,6}\s", line_prefix))
            if target_is_bullet and draft_is_bullet:
                return line_start, sub_end

    # 4차: 후행 인용구/출처 표기 차이 허용 전방 토큰 매칭
    for k in range(1, max_drop):
        sub_tokens = tokens[:-k]
        if len(" ".join(sub_tokens)) < 20:
            break
        sub_pat = r"\s+".join(re.escape(t) for t in sub_tokens)
        sub_matches = list(re.finditer(sub_pat, draft))
        if len(sub_matches) == 1:
            sub_start, sub_end = sub_matches[0].start(), sub_matches[0].end()
            line_end = draft.find("\n", sub_end)
            line_end = len(draft) if line_end == -1 else line_end
            if target_is_bullet:
                return sub_start, line_end

    return None


def apply_verified_draft_patches(previous_draft: str, raw_response: str) -> str:
    """모델이 지정한 원문 구간만 치환한다. 불일치·중복·겹침은 전체 재작성을 막는다.

    Args:
        previous_draft: 수정 전 초안 본문.
        raw_response: 모델이 반환한 JSON 패치 응답 문자열.

    Returns:
        부분 패치가 정확하게 적용된 수정 후 초안 본문.

    Raises:
        ValueError: JSON 형식이 올바르지 않거나, 유효한 패치가 하나도 없거나 패치 구간이 겹치는 경우.
    """
    try:
        patch_text = raw_response.strip()
        if "{" in patch_text and "}" in patch_text:
            patch_text = patch_text[patch_text.index("{"):patch_text.rindex("}") + 1]
        parsed = json.loads(patch_text, strict=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("INVALID_PARTIAL_REVISION_FORMAT") from exc
    patches = parsed.get("patches") if isinstance(parsed, dict) else None
    if not isinstance(patches, list) or not patches or len(patches) > 12:
        raise ValueError("INVALID_PARTIAL_REVISION_PATCHES")
    spans = []
    failed_count = 0
    for patch in patches:
        if not isinstance(patch, dict):
            raise ValueError("INVALID_PARTIAL_REVISION_PATCH")
        old, new = patch.get("old_text"), patch.get("new_text")
        if not isinstance(old, str) or not old.strip() or not isinstance(new, str) or not new.strip():
            raise ValueError("INVALID_PARTIAL_REVISION_PATCH")
        if old == new:
            continue
        span = find_unique_target_span(previous_draft, old)
        if span is None:
            failed_count += 1
            logger.warning("[PARTIAL_REVISION] 치환 대상 고유 구간 탐색 실패(패치 생략): %.60s", old)
            continue
        spans.append((span[0], span[1], new))
    if not spans:
        raise ValueError("AMBIGUOUS_PARTIAL_REVISION_TARGET")
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError("OVERLAPPING_PARTIAL_REVISION_PATCHES")
    revised = previous_draft
    for start, end, new in reversed(spans):
        revised = revised[:start] + new + revised[end:]
    return revised


def write_document_answer(
    question: str, sources: List[Dict[str, Any]], *,
    user_history: List[str] | None = None, previous_draft: str = "",
    verification: Dict[str, Any] | None = None,
    as_of_date: str | None = None,
    preserved_points: List[str] | None = None,
    limited: bool = False,
    rag_only_notice: bool = False,
    allow_need_more_law: bool = True,
) -> Dict[str, Any]:
    """원문 전체와 현재 질문으로 초안 또는 검증 지적을 반영한 답변을 작성한다.

    Args:
        question: 재해석으로 대체하지 않은 현재 사용자 질문.
        sources: 사건 문서와 실제 검색 법률 자료의 공통 레지스트리.
        user_history: 지시어 이해를 위한 이전 사용자 발언. 객관적 사실 근거가 아니다.
        previous_draft: 수정 대상 답변. 사실 출처로 사용하지 않는다.
        verification: 검증 지적 및 누락 사항. 최초 작성 시 생략한다.
        as_of_date: 사건에서 지정한 검토 기준일. 없으면 실행일을 사용한다.
        preserved_points: 이전 검증에서 맞다고 확인한 설명. 원문과 재대조할 보존 대상이다.
        limited: 전체 답변을 확정하지 못한 경우 확인 가능한 범위만 새로 작성할지 여부.

    Returns:
        답변과 작성 모델에 실제 전달한 출처 명세.

    Raises:
        ValueError: 원문 예산 초과, 출처 충돌 또는 빈 응답인 경우.
    """
    logger.info(
        "[DOCUMENT_ANSWER] 답변 초안 작성 시작 (출처: %d건 | 제한모드=%s | 재작성=%s)",
        len(sources),
        limited,
        bool(previous_draft),
    )
    # [컨텍스트 다이어트: 토큰 비용 및 지연시간 대폭 압축]
    # LLM 프롬프트에 주입할 본문은 동일 조문 중복 제거 및 재작성 시 비인용 증거 축약을 거쳐 압축한다.
    from ai_legal_helper.rag.grounding_context import prune_sources_for_consultation
    diet_sources = prune_sources_for_consultation(
        sources,
        draft_answer=previous_draft,
        verification=verification,
    )
    context, _ = format_grounding_sources(diet_sources)
    # 최종 매니페스트는 검증 및 영속성 무결성 유지를 위해 전체 sources 기준으로 산출한다.
    _, manifest = format_grounding_sources(sources)
    # 감사 레지스트리의 본문을 수정 지적으로 다시 넣으면 원문이 중복되고 예산이 무의미해진다.
    # 작성자는 오류·누락 지적만 읽고 사실 판단은 항상 아래 공통 원문에서 다시 수행한다.
    review = verification or {}
    repair_notes = {key: review[key] for key in (
        "status", "reason_code", "missing_legal_issues", "candidate_laws", "missing_issues",
        "contradictions", "revision_instructions", "question_coverage", "consistency_checks",
    ) if key in review}
    repair_notes["지적된 주장"] = [c for c in review.get("claims", [])
                                  if c.get("grounding_status") in ("UNSUPPORTED", "UNCERTAIN")]
    unique_history = list(dict.fromkeys(user_history or []))
    payload = {"현재 질문": question, "검토 기준일": as_of_date or date.today().isoformat(),
               "이전 사용자 발언(미입증 진술)": unique_history,
               "수정 대상(사실 출처 아님)": previous_draft,
               "검증 지적": repair_notes,
               "수정 중 보존할 설명(원문과 재대조)": preserved_points or []}
    if rag_only_notice:
        payload["공식 법령 검색 결과"] = (
            "공식 OpenLaw에서 요청한 법령의 일부 또는 전부를 찾지 못했습니다. 확보된 공식 법령과 RAG 근거만으로 "
            "확인 가능한 범위에서 답변하세요. 답변 첫 부분에 공식 검색 미확인 사실을 명시하고, "
            "미확인 법령의 조문이나 시행일을 확정하지 마세요. 추가 공식 검색 요청을 반복하지 마세요."
        )
    elif verification and verification.get("reason_code") == "LEGAL_SOURCE_MISSING":
        payload["추가 확보된 법령 안내"] = (
            "이전 검증에서 부족하다고 지적된 법령 조문이 [전체 근거 원문]에 새로 추가되었습니다. "
            "단순히 주장을 삭제하거나 '단정하기 어렵다'고 후퇴하지 말고, 새로 추가된 법령 조문(법령명 제O조)과 "
            "사건 증거를 연결하여 질문에 대한 법리적 판단과 결론을 명확히 보강하세요."
        )
    if limited:
        # 미검증 초안을 잘라 공개하지 않고 새 제한 답변을 생성한 뒤 같은 검증기로 다시 대조한다.
        payload["답변 범위"] = (
            "제한 답변: 확인된 사실과 근거 있는 조건부 설명으로 현재 질문에 최대한 답하세요. "
            "확정할 수 없는 부분은 이유와 필요한 자료를 사용자에게 직접 설명하세요. "
            "내부 검토 지적을 복사하거나 확인 필요만 나열하지 마세요. "
            "근거 없는 법률 결론은 삭제하되 기존에 검증된 설명은 보존하세요."
        )
    # 최초 작성이며 공식 법령 검색이 아직 수행되지 않은 경우에만 동일 LLM 호출로 법령 충분성을 판단한다.
    # 공식 법령 검색이 이미 수행되었거나 재작성/제한 답변 단계에서는 근거 자료를 바탕으로 완성된 답변 초안을 직접 작성한다.
    integrated = allow_need_more_law and not previous_draft and not limited and verification is None and not rag_only_notice
    if integrated:
        payload["출력 규약"] = (
            "반드시 JSON 객체만 출력하세요. 법령 원문이 현재 질문의 핵심 쟁점에 부족하면 "
            '{"status":"NEED_MORE_LAW","missing_laws":[{"law_name":"법령명","issue":"쟁점",'
            '"question_part":"질문 원문","articles":[]}],"answer":""} '
            "형식으로 반환하세요. 부족한 법령은 추측하지 말고 실제로 필요한 것만 제안하세요. "
            "현재 근거로 답변 가능하면 "
            '{"status":"READY","missing_laws":[],"answer":"근거 기반 완성 답변"} '
            "형식으로 반환하세요. NEED_MORE_LAW일 때 답변 초안을 생성하지 마세요."
        )
    partial_repair = bool(previous_draft) and not limited
    if partial_repair:
        payload["부분 수정 출력 규약"] = (
            "기존 초안에서 검증 실패 또는 근거 부족으로 변경이 필요한 최소한의 연속된 원문 구간만 선택하세요. "
            "다른 문장, 제목, 검증 통과 부분은 절대 수정하지 마세요. "
            '반드시 JSON 객체 {"patches":[{"old_text":"기존 초안에서 정확히 복사한 유일한 원문",'
            '"new_text":"근거에 맞게 수정한 문장"}]} 하나만 출력하세요. '
            "old_text는 기존 초안에 정확히 한 번 나타나는 문자열이어야 합니다. "
            "검증 지적과 무관한 부분은 패치에 넣지 마세요. 기존 초안 전체를 출력하지 마세요."
        )
    response = get_llm(temperature=0.0).invoke([
        SystemMessage(content=DOCUMENT_ANSWER_SYSTEM + (
            "\n\n[최초 작성 구조화 출력 최우선 규약]\n"
            "이번 호출에서는 반드시 JSON 객체 한 개만 출력하세요. "
            "법령 근거가 충분하면 status=READY 및 answer 필드에 사용자용 마크다운 답변을 넣으세요. "
            "법령 원문이 핵심 쟁점에 부족하면 status=NEED_MORE_LAW, missing_laws 배열, answer 빈 문자열을 반환하세요."
        ) if integrated else (DOCUMENT_ANSWER_SYSTEM + (
            "\n\n[부분 수정 JSON 출력 규약]\n"
            "이번 호출에서는 최종 답변 대신 patches JSON 객체만 출력하세요."
        ) if partial_repair else "")),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False) + "\n\n[전체 근거 원문]\n" + context),
    ])
    answer = response.content
    if not isinstance(answer, str) or not answer.strip():
        logger.error("[DOCUMENT_ANSWER] LLM 답변 생성 결과가 비어 있습니다 (EMPTY_DOCUMENT_ANSWER)")
        raise ValueError("EMPTY_DOCUMENT_ANSWER")
    answer_text = answer.strip()
    if partial_repair:
        answer_text = apply_verified_draft_patches(previous_draft, answer_text)
    if rag_only_notice and not (partial_repair and previous_draft.startswith("**안내:**")):
        answer_text = ("**안내:** 공식 법령 검색에서 요청한 법령의 일부 또는 전부를 확인하지 못해, "
                       "현재 확보된 공식 법령 및 RAG 자료로 검토한 답변입니다. "
                       "법령의 최신성 및 적용 시점은 추가 확인이 필요합니다.\\n\\n"
                       + answer_text)
    if integrated:
        try:
            parsed = None
            if "{" in answer_text and "}" in answer_text:
                slice_text = answer_text[answer_text.index("{"):answer_text.rindex("}") + 1]
                try:
                    parsed = json.loads(slice_text, strict=False)
                except (json.JSONDecodeError, ValueError):
                    # RFC 8259 제어문자(줄바꿈 등) 또는 답변 본문 내 미이스케이프 따옴표 발생 시 정규식 유연 추출
                    m_status = re.search(r'"status"\s*:\s*"([^"]+)"', slice_text)
                    st = m_status.group(1) if m_status else ""
                    if st == "READY":
                        m_ans = re.search(r'"answer"\s*:\s*"(.*)"\s*\}\s*$', slice_text, re.DOTALL)
                        if m_ans:
                            raw_ans = m_ans.group(1)
                            ans_unescaped = (
                                raw_ans.replace('\\"', '"')
                                .replace('\\n', '\n')
                                .replace('\\t', '\t')
                                .replace('\\\\', '\\')
                            )
                            parsed = {"status": "READY", "missing_laws": [], "answer": ans_unescaped}
            if not isinstance(parsed, dict):
                raise ValueError("INVALID_SYNTHESIS_GATE")
            if parsed.get("status") == "NEED_MORE_LAW":
                missing = parsed.get("missing_laws") or []
                if not isinstance(missing, list) or not missing:
                    raise ValueError("INVALID_MISSING_LAWS")
                requests = []
                for item in missing[:4]:
                    if not isinstance(item, dict):
                        raise ValueError("INVALID_LAW_REQUEST")
                    name = item.get("law_name")
                    issue = item.get("issue")
                    articles = item.get("articles", [])
                    if not isinstance(name, str) or not name.strip() or not isinstance(issue, str) or not issue.strip() or not isinstance(articles, list) or not all(isinstance(a, str) for a in articles):
                        raise ValueError("INVALID_LAW_REQUEST")
                    requests.append({"law_name": name.strip(), "issue": issue.strip(),
                                     "question_part": question, "articles": articles})
                return {"draft_answer": "", "answer_source_manifest": manifest,
                        "answer_generation_error": None, "synthesis_law_gate": {
                            "status": "NEED_MORE_LAW", "legal_search_requests": requests,
                            "candidate_laws": list(dict.fromkeys(x["law_name"] for x in requests)),
                            "missing_legal_issues": [x["issue"] for x in requests]}}
            if parsed.get("status") != "READY" or not isinstance(parsed.get("answer"), str) or not parsed["answer"].strip():
                raise ValueError("INVALID_SYNTHESIS_GATE")
            answer_text = parsed["answer"].strip()
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("[DOCUMENT_ANSWER] 통합 구조화 응답 파싱 실패 (%s: %s)", type(exc).__name__, exc)
            raise ValueError("INVALID_SYNTHESIS_GATE") from exc

    # [Option B] LLM이 [01], [03], [E01] 등 축약 표기를 남겼더라도 실제 전체 등록 파일명으로 자동 복원/확장
    from ai_legal_helper.utils.text_formatter import expand_evidence_citations
    answer_text = expand_evidence_citations(answer_text, sources)

    draft_hash = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()[:16]
    logger.info(
        "[DOCUMENT_ANSWER] 답변 초안 작성 완료 (길이: %d자 | 해시: %s | 제한모드=%s)",
        len(answer_text),
        draft_hash,
        limited,
    )
    return {"draft_answer": answer_text, "answer_source_manifest": manifest,
            "answer_generation_error": None}
