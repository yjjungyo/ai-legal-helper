"""답변 작성자와 검증기가 동일한 원문 출처를 보도록 컨텍스트를 구성한다.

출처 추가 순서에 따른 개수 제한이나 본문 앞부분 절단을 하지 않는다.
전체 예산을 넘으면 누락을 숨기는 대신 명시적으로 실패하여 검증 범위를 보존한다.
"""

import json
import hashlib
from typing import Any, Dict, List, Tuple


def format_grounding_sources(
    sources: List[Dict[str, Any]], max_chars: int = 120_000,
) -> Tuple[str, Dict[str, Any]]:
    """전체 출처 본문과 실제 전달 목록을 함께 반환한다.

    Args:
        sources: 이번 요청에서 확보한 사건 증거와 법령 레지스트리.
        max_chars: 출처 컨텍스트의 문자 예산. 초과 시 일부를 조용히 생략하지 않는다.

    Returns:
        원문 컨텍스트와 source_ids·char_count·complete를 포함한 전달 명세.

    Raises:
        ValueError: 본문 예산을 넘거나 동일 출처 ID의 본문이 충돌한 경우.
    """
    blocks = []
    seen = {}
    for source in sources or []:
        sid = str(source.get("source_id") or source.get("evidence_id") or "")
        content = str(source.get("content") or source.get("article_text") or "").strip()
        if sid and sid in seen:
            if seen[sid] != content:
                raise ValueError("SOURCE_ID_CONTENT_CONFLICT")
            continue
        if not sid:
            # 기존 메타데이터만 있는 출처도 표시하되 가공 ID를 만들어 인용 가능하게 하지 않는다.
            sid = ""
        else:
            seen[sid] = content
        meta = {key: source.get(key) for key in (
            "source_id", "source_type", "evidence_id", "filename", "file_name", "title",
            "statute_name", "article", "article_title", "paragraph_no", "part", "chapter", "section",
            "promulgation_number", "promulgation_date", "effective_date", "version_date",
            "page", "source_url", "retrieval_method", "review_status", "source_kind", "document_name",
        ) if source.get(key) is not None}
        blocks.append(json.dumps(meta, ensure_ascii=False) + "\n본문:\n" + (content or "(원문 본문 미확보)"))
    rendered = "\n\n".join(blocks) or "(검색된 출처 없음)"
    if len(rendered) > max_chars:
        raise ValueError("GROUNDING_CONTEXT_LIMIT_EXCEEDED")
    return rendered, {
        "source_ids": list(seen), "source_count": len(seen), "char_count": len(rendered),
        "content_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "complete": True, "omitted_source_ids": [],
    }
