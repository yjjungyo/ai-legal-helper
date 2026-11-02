# -*- coding: utf-8 -*-
"""P7 — 공식 법령·부칙·시행일의 재현 가능한 Evidence Bundle.

검색된 법령 Source와 P5 판정 기록을 결합한다. LLM에 주입하는 digest만
길이를 제한하며, 원문 출처 자체는 수정/삭제/변환하지 않는다.

신법 시행예정 후보와 종전 시행 버전은 같은 법령이라도 별도 Source로
보존한다. 단순 검색 적중은 판정 PASS가 아니고, 법률/증거 근거의 혼합도 금지.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

_MAX_SOURCE_PREVIEW = 850
_MAX_DIGEST = 6500


@dataclass(frozen=True)
class LegalEvidenceItem:
    source_id: str
    law_id: str
    law_name: str
    article: str
    version_id: str
    version_relation: str
    article_effective_date: str | None
    rule_status: str
    rule_reason: str
    source_url: str | None
    preview: str

    def as_dict(self) -> dict[str, Any]:
        return vars(self).copy()


@dataclass
class LegalEvidenceBundle:
    items: list[LegalEvidenceItem] = field(default_factory=list)
    digest: str = ""
    warning_codes: list[str] = field(default_factory=list)
    source_count: int = 0
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": [it.as_dict() for it in self.items],
            "digest": self.digest,
            "warning_codes": list(self.warning_codes),
            "source_count": self.source_count,
            "truncated": self.truncated,
        }


def build_legal_evidence_bundle(
    sources: Iterable[Mapping[str, Any]] | None,
    *,
    temporal_resolution: Mapping[str, Any] | None = None,
    max_chars: int = _MAX_DIGEST,
) -> LegalEvidenceBundle:
    """법령별 버전 근거를 출처ID에 고정한 Prompt/Trace 번들로 생성한다.

    P5의 결정 목록을 source_id로 결합하며, 없는 판정은 모두 UNCONFIRMED로
    취급한다. LLM 분석이 필요하면 digest에 남긴 링크/버전 정보로 검증 가능.
    """
    decisions = (temporal_resolution or {}).get("decisions") or []
    by_source = {
        str(d.get("source_id")): d for d in decisions
        if isinstance(d, Mapping) and d.get("source_id")
    }
    recorded: set[str] = set()
    items: list[LegalEvidenceItem] = []
    warnings: set[str] = set()
    for source in sources or []:
        if not isinstance(source, Mapping) or source.get("source_type") != "STATUTE":
            continue
        sid = str(source.get("source_id") or "").strip()
        text = str(source.get("content") or "").strip()
        if not sid or not text or sid in recorded:
            continue
        recorded.add(sid)
        decision = by_source.get(sid) or {}
        status = str(decision.get("status") or "UNCONFIRMED")
        reason = str(decision.get("reason_code") or "NO_TEMPORAL_DECISION")
        relation = str(source.get("version_relation") or "UNCONFIRMED")
        if relation == "NEXT_EFFECTIVE_CANDIDATE":
            warnings.add("FUTURE_VERSION_NOT_CURRENT")
        if status == "UNCONFIRMED":
            warnings.add("TEMPORAL_APPLICABILITY_UNCONFIRMED")
        if not source.get("version_id") or not source.get("law_id"):
            warnings.add("SOURCE_VERSION_ID_UNCONFIRMED")
        item = LegalEvidenceItem(
            source_id=sid,
            law_id=str(source.get("law_id") or ""),
            law_name=str(source.get("statute_name") or ""),
            article=str(source.get("article") or ""),
            version_id=str(source.get("version_id") or ""),
            version_relation=relation,
            article_effective_date=str(source.get("article_effective_date")) if source.get("article_effective_date") else None,
            rule_status=status,
            rule_reason=reason,
            source_url=str(source.get("source_url")) if source.get("source_url") else None,
            preview=text[:_MAX_SOURCE_PREVIEW] + (" … [원문 생략]" if len(text) > _MAX_SOURCE_PREVIEW else ""),
        )
        items.append(item)

    # 시행 버전 본문과 부칙을 둘 다 포함한다. 미래 후보는 혼동 방지를 위해
    # 별도 레이블을 붙이고 현재 적용 근거로 단정하지 말 것을 분명히 한다.
    lines = [
        "[공식 법령 근거 — 원문 출처 기반]",
        "법령 시행일/적용례가 미확인인 경우 확정적 적용 판단을 하지 마세요.",
        "NEXT_EFFECTIVE_CANDIDATE는 차기 시행예정 후보이며 현재 적용 법령으로 단정하면 안 됩니다.",
        "법령명/조문/MST/출처ID를 임의로 변경하거나 없는 문구를 만들지 마세요.",
    ]
    truncated = False
    for item in items:
        line = (
            f"\n[LAW_SOURCE {item.source_id}]\n"
            f"법령: {item.law_name} {item.article} | law_id={item.law_id} "
            f"| MST={item.version_id} | 버전역할={item.version_relation} "
            f"| 조문시행일={item.article_effective_date or '미확인'} "
            f"| 적용례판정={item.rule_status} ({item.rule_reason})\n"
            f"공식페이지: {item.source_url or '미확인'}\n"
            f"원문: {item.preview}\n"
        )
        if len("\n".join(lines)) + len(line) > max_chars:
            truncated = True
            break
        lines.append(line)
    if truncated:
        lines.append("\n[알림] 일부 법령 원문은 길이 제한으로 생략되었습니다. Source Registry 전체 원문은 유지됩니다.")
        warnings.add("DIGEST_TRUNCATED")
    if not items:
        return LegalEvidenceBundle(source_count=0)
    return LegalEvidenceBundle(
        items=items, digest="\n".join(lines), warning_codes=sorted(warnings),
        source_count=len(items), truncated=truncated,
    )
