"""문서가 등록된 사건의 원문 작성·검증·확정 경로.

검색은 법률 자료 확보에만 사용하고 답변 작성자는 하나로 유지한다. 검증 실패 시
공식 법령 검색 또는 제한된 재작성을 거치며, 미통과 초안을 최종 조언으로 승격하지 않는다.
"""

import hashlib
import re
from datetime import date
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, HumanMessage

from ai_legal_helper.agents.document_answer import write_document_answer
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.rag.grounding_context import format_grounding_sources
from ai_legal_helper.workflows.document_search import pending_searches, search_is_approved

logger = get_logger(__name__)
DOCUMENT_MODE = "DOCUMENT_GROUNDED"

_INTERNAL_CRITIQUE_MARKERS = (
    "밝혔어야", "초안", "답변은", "답변이", "제시하지 않", "지적하지 않",
    "설명이 제한적", "검증", "claim", "passed", "grounding", "재작성",
)


def _sanitize_client_missing_items(items: List[str]) -> List[str]:
    """내부 검토자 피드백 문구를 걸러내고 고객 안내에 적합한 확인 항목만 정제한다."""
    cleaned_list: List[str] = []
    for raw in items:
        text = str(raw or "").strip()
        if not text:
            continue
        if any(marker in text for marker in _INTERNAL_CRITIQUE_MARKERS):
            continue
        text = re.sub(r"\s+", " ", text)
        if text not in cleaned_list:
            cleaned_list.append(text)
    return cleaned_list


def document_sources(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """승인된 현재 사건 원문과 검색 법률 자료를 작성·검증 공통 목록으로 만든다.

    Args:
        state: 사건 브리핑과 실제 검색 결과가 담긴 그래프 상태.

    Returns:
        파생 그래프 주장과 반려/미승인 문서 본문을 제외한 전체 출처.
    """
    sources = []
    for document in (state.get("case_evidence_briefing") or {}).get("source_documents", []):
        usable_content = document.get("content", "") if document.get("review_status") == "APPROVED" else ""
        # "E05", "EVIDENCE:E05" 같은 축약 별칭 대신 실제 전체 파일명(예: "E05_퇴거_및_보증금_반환_요청_문자.txt")을 출처 ID로 사용한다.
        full_doc_name = str(
            document.get("document_name") or document.get("filename") or document.get("evidence_id") or ""
        ).strip()
        doc_without_alias = {k: v for k, v in document.items() if k not in ("evidence_label", "label")}
        sources.append({
            **doc_without_alias,
            "content": usable_content,
            "source_id": full_doc_name,
            "source_type": "CASE_EVIDENCE",
            "title": full_doc_name,
            "document_name": full_doc_name,
            "filename": full_doc_name,
            "file_name": full_doc_name,
            "file": full_doc_name,
            "retrieval_method": "CASE_DOCUMENT_SPANS",
        })
    # 과거 그래프 Fact와 기존 증거 청크가 원문과 이중으로 들어가 결론을 오염시키지 않게 한다.
    seen_statute_sids: Dict[str, str] = {}
    for source in state.get("retrieved_sources") or []:
        sid = str(source.get("source_id") or "")
        if (source.get("source_type") not in ("CASE_EVIDENCE", "GRAPH")
                and not sid.startswith(("GRAPH:", "EVIDENCE:"))):
            src_copy = dict(source)
            content_str = str(src_copy.get("content") or src_copy.get("article_text") or "").strip()
            if sid and sid in seen_statute_sids and seen_statute_sids[sid] != content_str:
                chunk_tag = str(src_copy.get("chunk_id") or len(seen_statute_sids) + 1)
                sid = f"{sid} ({chunk_tag})"
                src_copy["source_id"] = sid
            if sid:
                seen_statute_sids[sid] = content_str
            sources.append(src_copy)
    return sources


def generate_answer(
    state: Dict[str, Any],
    *,
    repair: bool = False,
    increment_revision: bool = True,
) -> Dict[str, Any]:
    """최초 작성과 수정 모두 같은 작성자·원문·질문을 사용한다.

    Args:
        state: 현재 질문, 사건 원문, 법률 검색 결과 및 검증 상태.
        repair: 검증 지적을 반영하는 재작성 여부.
        increment_revision: 오류 수정 횟수(revision_count)를 차감할지 여부(법령 보강 직후 첫 재작성은 차감하지 않음).

    Returns:
        새 초안, 출처 명세, 오류 상태 및 재작성 횟수.
    """
    sources = document_sources(state)
    result: Dict[str, Any] = {"answer_mode": DOCUMENT_MODE, "retrieved_sources": sources}
    if repair and increment_revision:
        result["revision_count"] = (state.get("revision_count") or 0) + 1
    history = [m.content for m in (state.get("messages") or [])[:-1]
               if isinstance(m, HumanMessage) and isinstance(m.content, str)]
    ver_res = state.get("verification_result") or {}
    preserved = list(dict.fromkeys(
        list(state.get("preserved_points") or [])
        + list(ver_res.get("preserved_points") or [])
    ))
    logger.info(
        "[DOC_CONSULTATION] 답변 생성 시작 (모드=%s | 출처=%d건 | 이전초안길이=%d자)",
        "수정보강(repair)" if repair else "최초초안(initial)",
        len(sources),
        len(state.get("draft_answer", "")),
    )
    try:
        written = write_document_answer(
            state.get("question", ""), sources, user_history=history[-4:],
            previous_draft=state.get("draft_answer", "") if repair else "",
            verification=ver_res if repair else None,
            as_of_date=(state.get("case_evidence_briefing") or {}).get("as_of_date"),
            preserved_points=preserved if repair else None,
        )
        result.update(written)
        draft_out = result.get("draft_answer", "")
        logger.info(
            "[DOC_CONSULTATION] 답변 생성 완료 (초안길이=%d자 | 해시=%s)",
            len(draft_out),
            hashlib.sha256(draft_out.encode("utf-8")).hexdigest()[:16] if draft_out else "None",
        )
    except Exception as exc:
        # 모델 오류나 원문 누락을 성공 답변으로 바꾸지 않으며 상담 원문/예외 본문은 기록하지 않는다.
        logger.warning("문서 답변 작성 실패: %s", type(exc).__name__)
        result.update(draft_answer="", answer_generation_error=type(exc).__name__)
    return result


def validate_document_snapshot(state: Dict[str, Any]) -> None:
    """작성 도중 삭제·반려·재추출된 문서를 현재 유효한 근거로 확정하지 않는다.

    Args:
        state: 사건 ID 및 작성에 사용한 문서 버전이 포함된 브리핑.

    Raises:
        ValueError: 사건 소유, 승인 상태 또는 추출 버전이 변경된 경우.
    """
    from ai_legal_helper.database.models import EvidenceDocument
    from ai_legal_helper.database.session import SessionLocal

    briefing = state.get("case_evidence_briefing") or {}
    documents = [d for d in briefing.get("source_documents", [])
                 if d.get("review_status") == "APPROVED" and d.get("content")]
    with SessionLocal() as db:
        current = {d.id: d for d in db.query(EvidenceDocument).filter(
            EvidenceDocument.case_id == briefing.get("case_id"),
            EvidenceDocument.id.in_([d["evidence_id"] for d in documents]),
        ).all()}
        for snapshot in documents:
            document = current.get(snapshot["evidence_id"])
            if (not document or document.status != "APPROVED"
                    or document.original_filename != snapshot.get("document_name")
                    or document.sha256 != snapshot.get("sha256")
                    or document.extraction_version != snapshot.get("extraction_version")
                    or (str(document.extracted_at) if document.extracted_at else None) != snapshot.get("extracted_at")):
                raise ValueError("CASE_DOCUMENT_SNAPSHOT_CHANGED")


def verify_answer(state: Dict[str, Any]) -> Dict[str, Any]:
    """원문 전체로 질문 충족과 사실·법률 근거를 확인하고 검증한 초안 해시를 남긴다.

    Args:
        state: 작성 결과와 동일한 원문 및 검색 출처를 포함한 그래프 상태.

    Returns:
        전체 검증 결과와 실제 출처 목록. 오류는 INSUFFICIENT로 반환한다.
    """
    from ai_legal_helper.agents.verification import run_verification

    sources = document_sources(state)
    draft = state.get("draft_answer", "")
    logger.info(
        "[DOC_CONSULTATION] 원문 근거 검증 시작 (검증 대상 초안: %d자 | 참조 출처: %d건)",
        len(draft),
        len(sources),
    )
    try:
        if state.get("answer_generation_error") or not draft.strip():
            raise ValueError("ANSWER_GENERATION_FAILED")
        validate_document_snapshot(state)
        _, manifest = format_grounding_sources(sources)
        if manifest.get("content_sha256") != (state.get("answer_source_manifest") or {}).get("content_sha256"):
            raise ValueError("ANSWER_VERIFICATION_SOURCE_MISMATCH")
        # 원문은 출처 목록에 한 번만 담고, 파생 사건 요약을 진실의 기준으로 재주입하지 않는다.
        as_of = (state.get("case_evidence_briefing") or {}).get("as_of_date") or date.today().isoformat()
        context = (f"검토 기준일: {as_of}\n등록 문서의 원문은 전체 출처 목록에 있습니다. "
                   "검토 승인은 내용의 진실성 확인이 아닙니다.")
        # 검증 함수의 반환값은 추적 SDK가 비동기로 직렬화한다. 추적 중인 딕셔너리에
        # 해시·명세를 추가하면 순회 중 변경 오류로 관측값이 유실될 수 있어 새 객체를 만든다.
        result = {**run_verification(state.get("question", ""), draft, sources, context,
                                     require_question_coverage=True), "source_manifest": manifest}
    except Exception as exc:
        logger.warning("문서 원문 검증 실패: %s", type(exc).__name__)
        result = {"status": "INSUFFICIENT", "reason_code": "VERIFICATION_ERROR",
                  "claims": [], "warnings": ["등록 자료와 답변의 대조를 완료하지 못했습니다."],
                  "missing_issues": [], "revision_instructions": []}
    result["verified_answer_sha256"] = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    preserved = list(state.get("preserved_points") or [])
    for pt in result.get("preserved_points") or []:
        if isinstance(pt, str) and pt.strip() and pt.strip() not in preserved:
            preserved.append(pt.strip())
    if "발견" in state.get("question", "") and "발견" in draft and "접수일" in draft:
        role_note = "사용자 질문의 발견일(인지 시점)과 문서상 등기 접수일·열람 기준일의 역할 구분을 삭제하지 말고 유지할 것"
        if role_note not in preserved:
            preserved.append(role_note)
    result["preserved_points"] = preserved
    claims_list = result.get("claims") or []
    sup_count = sum(1 for c in claims_list if c.get("grounding_status") == "SUPPORTED")
    unsup_count = sum(1 for c in claims_list if c.get("grounding_status") in ("UNSUPPORTED", "UNCERTAIN"))
    logger.info(
        "[DOC_CONSULTATION] 원문 근거 검증 완료 (판정=%s | 사유=%s | 주장=%d건[지지=%d, 미흡=%d] | 후보법령=%s)",
        result.get("status"),
        result.get("reason_code"),
        len(claims_list),
        sup_count,
        unsup_count,
        result.get("candidate_laws", []),
    )
    return {"verification_result": result, "retrieved_sources": sources, "issue_results": [],
            "preserved_points": preserved,
            "verified_sources": result.get("citation_audit", {}).get("verified_sources", [])}


def next_verification_step(state: Dict[str, Any]) -> str:
    """검증 통과만 확정하고 누락 법령은 검색, 나머지 수정은 총 세 번까지 허용한다.

    Args:
        state: 검증 결과, 공식 검색 실행 여부, 재작성 횟수.

    Returns:
        finalize, statute_search_approval, execute_statute_search, revise 또는 insufficient 노드 이름.
    """
    result = state.get("verification_result") or {}
    target_node = "insufficient"
    route_reason = "기본 보류 종료"

    if state.get("answer_generation_error") or result.get("reason_code") == "VERIFICATION_ERROR":
        target_node = "insufficient"
        route_reason = "답변 생성 오류 또는 검증 기술 오류"
    elif result.get("status") == "PASS":
        target_node = "finalize"
        route_reason = "검증 통과(PASS)"
    else:
        requests = pending_searches(state)
        search_count = state.get("statute_search_count") or 0
        branched_statute = False
        if requests and search_count < 2:
            if search_is_approved(state, requests):
                target_node = "execute_statute_search"
                route_reason = f"승인된 신규 법령 요청({len(requests)}건) 즉시 검색"
                branched_statute = True
            elif not state.get("hilt_executed"):
                target_node = "statute_search_approval"
                route_reason = f"신규 법령({len(requests)}건) 사용자 승인(HILT) 요청"
                branched_statute = True

        if not branched_statute:
            if result.get("status") in ("REVISE", "INSUFFICIENT") and (state.get("revision_count") or 0) < 3:
                target_node = "revise"
                route_reason = f"답변 보강 재작성 ({state.get('revision_count', 0) + 1}/3회)"
            else:
                target_node = "insufficient"
                route_reason = f"재작성 한도 초과 또는 추가 근거 부재 ({result.get('status')}/{result.get('reason_code')})"

    logger.info(
        "[DOC_ROUTING] 검증 후 다음 실행 노드 결정: %s (사유: %s | 재작성=%d회 | 법령검색=%d회)",
        target_node,
        route_reason,
        state.get("revision_count", 0),
        state.get("statute_search_count", 0),
    )
    return target_node
    if result.get("status") == "PASS":
        return "finalize"
    requests = pending_searches(state)
    if requests and (state.get("statute_search_count") or 0) < 2:
        if search_is_approved(state, requests):
            return "execute_statute_search"
        if not state.get("hilt_executed"):
            # 법령명 하나가 검색되었다고 해당 법의 다른 누락 조문까지 확보된 것으로 보지 않는다.
            return "statute_search_approval"
    if result.get("status") in ("REVISE", "INSUFFICIENT") and (state.get("revision_count") or 0) < 3:
        return "revise"
    return "insufficient"


def finish_answer(state: Dict[str, Any]) -> Dict[str, Any]:
    """검증된 정확한 문장을 보존하여 반환하고 실패 시 검증된 범위의 제한 답변을 생성·대조한다.

    Args:
        state: 초안, 검증 상태, 검증 당시 초안 해시.

    Returns:
        최종 답변과 실제 인용된 출처, 검증 및 처분 상태.
    """
    from ai_legal_helper.agents.verification import run_verification

    result = dict(state.get("verification_result") or {})
    draft = state.get("draft_answer", "")
    sources_list = document_sources(state)
    snapshot_valid = (
        bool(draft.strip())
        and not state.get("answer_generation_error")
        and result.get("reason_code") != "VERIFICATION_ERROR"
        and result.get("verified_answer_sha256") == hashlib.sha256(draft.encode("utf-8")).hexdigest()
    )
    manifest = None
    if snapshot_valid:
        try:
            _, manifest = format_grounding_sources(sources_list)
            snapshot_valid = manifest.get("content_sha256") == (result.get("source_manifest") or {}).get("content_sha256")
        except ValueError:
            snapshot_valid = False
    if snapshot_valid:
        try:
            validate_document_snapshot(state)
        except Exception:
            snapshot_valid = False

    valid = snapshot_valid and result.get("status") == "PASS"
    limited_used = False

    # 전체 답변이 PASS에 이르지 못했으나 원문 스냅샷·검증 무결성이 유효한 경우,
    # 확인된 사실과 조건부 설명만 남긴 제한 답변을 새로 생성하고 동일 검증기로 재검증한다.
    if snapshot_valid and not valid and result.get("claims"):
        try:
            history = [m.content for m in (state.get("messages") or [])[:-1]
                       if isinstance(m, HumanMessage) and isinstance(m.content, str)]
            as_of = (state.get("case_evidence_briefing") or {}).get("as_of_date") or date.today().isoformat()
            preserved = list(dict.fromkeys(
                list(state.get("preserved_points") or [])
                + list(result.get("preserved_points") or [])
            ))
            limited_written = write_document_answer(
                state.get("question", ""),
                sources_list,
                user_history=history[-4:],
                previous_draft=draft,
                verification=result,
                as_of_date=as_of,
                preserved_points=preserved,
                limited=True,
            )
            limited_draft = limited_written.get("draft_answer", "")
            if limited_draft.strip():
                context = (
                    f"검토 기준일: {as_of}\n등록 문서의 원문은 전체 출처 목록에 있습니다. "
                    "검토 승인은 내용의 진실성 확인이 아닙니다."
                )
                limited_ver = run_verification(
                    state.get("question", ""),
                    limited_draft,
                    sources_list,
                    context,
                    require_question_coverage=True,
                    allow_partial_answer=True,
                )
                if limited_ver.get("status") == "PASS":
                    draft = limited_draft
                    result = {
                        **limited_ver,
                        "source_manifest": manifest,
                        "verified_answer_sha256": hashlib.sha256(limited_draft.encode("utf-8")).hexdigest(),
                    }
                    valid = True
                    limited_used = True
        except Exception as exc:
            logger.warning("제한 답변 생성 또는 검증 실패: %s", type(exc).__name__)

    if not valid:
        # 검증 결과나 그 이후의 원문 변경을 정형 성공 답변으로 덮어쓰지 않으며 내부 검토 문구 노출을 차단한다.
        result["status"] = "INSUFFICIENT"
        if result.get("reason_code") in (None, "NONE"):
            result["reason_code"] = "VERIFICATION_ERROR"
        raw_missing = list(dict.fromkeys(result.get("missing_legal_issues", []) + result.get("missing_issues", [])))
        missing = _sanitize_client_missing_items(raw_missing)
        detail = "\n" + "\n".join(f"- {item}" for item in missing) if missing else ""
        final = "질문에 대한 답변을 확정할 만큼 근거 확인을 마치지 못했습니다."
        if result.get("reason_code") == "VERIFICATION_ERROR":
            final += " 등록 자료와 답변을 대조하는 과정에 문제가 있어 다시 확인해야 합니다."
        elif detail:
            final += " 추가로 확인할 사항은 다음과 같습니다.\n" + detail
        else:
            final += " 등록 자료와 법률 근거를 다시 확인해야 합니다."
        sources = []
        disposition = "WITHHELD"
    else:
        final = draft
        cited_ids = {sid for claim in result.get("claims", [])
                     if claim.get("grounding_status") == "SUPPORTED" for sid in claim.get("source_ids", [])}
        sources = [s for s in sources_list if s.get("source_id") in cited_ids]
        disposition = "CAUTIONARY" if (limited_used or any(
            c.get("fact_status") in ("CONFLICTED", "EVIDENCE_NEEDED", "INFERENCE", "USER_STATEMENT")
            and c.get("claim_type") in ("CASE_FACT", "CASE_INFERENCE", "LEGAL_APPLICATION", "USER_STATEMENT")
            for c in result.get("claims", [])
        )) else "DELIVERED"
    logger.info(
        "[DOC_FINALIZE] 문서 상담 답변 확정 (처분=%s | 초안보존=%s | 제한답변사용=%s | 인용출처=%d건 | 최종답변길이=%d자)",
        disposition,
        valid and not limited_used,
        limited_used,
        len(sources),
        len(final),
    )
    return {"final_answer": final, "answer": final, "messages": [AIMessage(content=final)],
            "sources": sources, "cited_sources": sources, "claim_citations": [], "case_delta": None,
            "final_disposition": disposition, "verification_result": result,
            "warnings": list(dict.fromkeys((state.get("warnings") or []) + (result.get("warnings") or []))),
            "issue_results": []}
