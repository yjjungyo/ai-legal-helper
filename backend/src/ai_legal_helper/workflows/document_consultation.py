"""문서가 등록된 사건의 원문 작성·검증·확정 경로.

검색은 법률 자료 확보에만 사용하고 답변 작성자는 하나로 유지한다. 검증 실패 시
공식 법령 검색 또는 제한된 재작성(최대 3회)을 거치며, 재작성 한도 도달 시 지지된 근거(SUPPORTED)가 확인된 경우에만 기존 초안을 조건부 안내(CAUTIONARY)로 보존하고 그 외에는 판단 유보(WITHHELD)로 처리한다.
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


def consultation_question(state: Dict[str, Any]) -> str:
    """단일 진실 공급원(SSOT) 원칙에 따라 사용자 원문 질문을 최우선으로 보존하고 문맥 복원 질의를 병기한다.

    Args:
        state: 사용자 질문(question) 및 의도 분석 결과(resolved_query)가 포함된 상태 딕셔너리.

    Returns:
        str: 작성 및 검증 공통으로 사용할 단일 진실 질의 문자열.

    Notes:
        사용자 원문 질문은 의뢰인의 모든 법률 쟁점 요구가 담긴 유일한 진실 공급원(SSOT)이다.
        resolved_query가 존재하더라도 원문 질문을 절대로 덮어써서 버리지 않으며,
        두 값이 서로 다를 경우 원문 질문을 최상단에 배치하고 문맥 복원 질의를 함께 병기하여
        초안 작성기와 검증기 간의 정보 비대칭 및 쟁점 누락(Early Stop / REVISE)을 원천 차단한다.
    """
    orig_q = str(state.get("question") or "").strip()
    if orig_q in ("", "(질문 미확인)"):
        # state["messages"]의 마지막 HumanMessage에서 원문 질문 복원 시도
        for m in reversed(state.get("messages") or []):
            if isinstance(m, HumanMessage) and isinstance(m.content, str) and m.content.strip():
                orig_q = m.content.strip()
                break
            elif isinstance(m, dict) and m.get("type") in ("human", "user") and m.get("content"):
                orig_q = str(m.get("content")).strip()
                break
        if orig_q == "(질문 미확인)":
            orig_q = ""

    resolved_q = str(state.get("resolved_query") or "").strip()
    if resolved_q == "(질문 미확인)":
        resolved_q = ""

    # 원문 질문이 없는 경우 문맥 질의 반환
    if not orig_q:
        return resolved_q
    # 문맥 질의가 없거나 원문과 완전히 동일한 경우 원문 반환
    if not resolved_q or orig_q == resolved_q:
        return orig_q

    # 원문 질문과 문맥 질의가 모두 존재하며 상이한 경우:
    # 검증기의 진술 일치 검증(_norm_quote in question) 및 작성기의 전 쟁점 충족을 위해
    # 원문 질문을 최우선으로 두고 대화 맥락 해석을 보조로 결합한다.
    return (
        f"[의뢰인 질문 원문]\n{orig_q}\n\n"
        f"[대화 맥락 및 쟁점 해석]\n{resolved_q}"
    )


def document_sources(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """승인된 현재 사건 원문과 검색 법률 자료를 작성·검증 공통 목록으로 만든다.

    Args:
        state: 사건 브리핑과 실제 검색 결과가 담긴 그래프 상태.

    Returns:
        파생 그래프 주장과 반려/미승인 문서 본문을 제외한 전체 출처.
    """
    sources = []
    for document in (state.get("case_evidence_briefing") or {}).get("source_documents", []):
        usable_content = (document.get("content") or "").strip() if document.get("review_status") == "APPROVED" else ""
        # 본문 발췌가 비어있더라도 승인된 사실 목록(approved_claims)이 있으면 안전하게 대체 보강
        if not usable_content and document.get("review_status") == "APPROVED":
            approved_claims = document.get("approved_claims") or []
            if approved_claims:
                usable_content = "\n".join(approved_claims)
            elif document.get("claim_review_guide"):
                usable_content = str(document.get("claim_review_guide"))

        # "E05", "EVIDENCE:E05" 같은 축약 별칭 대신 실제 전체 파일명(예: "E05_퇴거_및_보증금_반환_요청_문자.txt")을 출처 ID로 사용한다.
        full_doc_name = str(
            document.get("document_name") or document.get("filename") or document.get("evidence_id") or ""
        ).strip()
        doc_without_alias = {
            k: v for k, v in document.items()
            if k not in ("evidence_label", "label", "filename", "file_name", "title", "file")
        }
        # 승인되지 않은 원문은 출처 레지스트리에도 포함하지 않는다.
        # 빈 내용의 문서가 인용 후보로 남으면 사실 근거로 오인될 수 있다.
        if not str(usable_content or "").strip():
            continue
        sources.append({
            **doc_without_alias,
            "content": usable_content,
            "source_id": full_doc_name,
            "source_type": "CASE_EVIDENCE",
            "document_name": full_doc_name,
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
    allow_need_more_law: bool | None = None,
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
    # 이전 작성 실패 상태가 성공한 재작성까지 차단하지 않도록 매 시도마다 초기화한다.
    result: Dict[str, Any] = {"answer_mode": DOCUMENT_MODE, "retrieved_sources": sources,
                              "answer_generation_error": None}
    if repair and increment_revision:
        result["revision_count"] = (state.get("revision_count") or 0) + 1
    raw_history = [
        m.content for m in (state.get("messages") or [])[:-1]
        if isinstance(m, HumanMessage) and isinstance(m.content, str) and m.content.strip()
    ]
    history = list(dict.fromkeys(raw_history))
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
        # 공식 법령 검색이 이미 수행되었거나 재작성인 경우 추가 법령 요청(NEED_MORE_LAW)을 차단하고 초안 작성을 강제한다.
        has_searched = bool(
            state.get("statute_search_status")
            or (state.get("statute_search_count") or 0) > 0
            or state.get("hitl_executed")
        )
        effective_allow_need_more_law = (not has_searched and not repair) if allow_need_more_law is None else allow_need_more_law

        written = write_document_answer(
            consultation_question(state), sources, user_history=history[-4:],
            previous_draft=state.get("draft_answer", "") if repair else "",
            verification=ver_res if repair else None,
            as_of_date=(state.get("case_evidence_briefing") or {}).get("as_of_date"),
            preserved_points=preserved if repair else None,
            issue_tasks=state.get("issue_tasks"),
            rag_only_notice=(state.get("statute_search_status") in ("NOT_FOUND", "PARTIAL_SUCCESS")),
            allow_need_more_law=effective_allow_need_more_law,
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
        logger.warning("문서 답변 작성 실패: %s (%s)", type(exc).__name__, exc)
        # 최초 초안 생성 실패(else 분기)는 answer_generation_error를 기록하여 판단 유보(WITHHELD)로 차단하되,
        # 수정보강(repair) 단계 실패 시에는 이미 생성된 기존 초안을 안전하게 보존한다.
        if repair and state.get("draft_answer"):
            # 수정보강(repair) 실패 시 이미 생성된 기존 초안을 안전하게 보존하고,
            # 전체 답변이 파기되는 치명적 보류(WITHHELD)로 빠지지 않도록 generation_error를 발생시키지 않는다.
            logger.warning("[DOC_CONSULTATION] 재작성(repair) 실패로 기존 초안을 보존하여 검증을 지속합니다: %s", type(exc).__name__)
            result.update(draft_answer=state["draft_answer"],
                          answer_source_manifest=state.get("answer_source_manifest"),
                          answer_generation_error=None)
        else:
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
        # 후속 실무 행동 질의(FOLLOWUP_ACTION)는 5단계 정밀 의견서 타임라인/의사표시 정합성 강제를 완화한다.
        is_followup = (
            state.get("intent") == "FOLLOWUP_ACTION"
            or (state.get("intent_decision") or {}).get("intent") == "FOLLOWUP_ACTION"
            or (state.get("intent_decision") or {}).get("requires_full_analysis") is False
        )
        require_coverage = not is_followup
        # 검증 함수의 반환값은 추적 SDK가 비동기로 직렬화한다. 추적 중인 딕셔너리에
        # 해시·명세를 추가하면 순회 중 변경 오류로 관측값이 유실될 수 있어 새 객체를 만든다.
        result = {**run_verification(consultation_question(state), draft, sources, context,
                                     require_question_coverage=require_coverage), "source_manifest": manifest}
    except Exception as exc:
        logger.warning("문서 원문 검증 실패: %s (%s)", type(exc).__name__, exc)
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
            else:
                # 과거 HITL 실행 여부가 아니라 이번 신규 검색 범위의 승인 여부로 판단한다.
                target_node = "statute_search_approval"
                route_reason = f"신규 법령({len(requests)}건) 사용자 승인(HITL) 요청"
                branched_statute = True

        if not branched_statute:
            if result.get("status") in ("REVISE", "INSUFFICIENT") and (state.get("revision_count") or 0) < 3:
                target_node = "revise"
                route_reason = f"답변 보강 재작성 ({state.get('revision_count', 0) + 1}/3회)"
            else:
                if state.get("draft_answer") and result.get("claims"):
                    target_node = "finalize"
                    route_reason = f"재작성 한도 도달 후 초안 보존 최종화 ({result.get('status')}/{result.get('reason_code')})"
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


def finish_answer(state: Dict[str, Any]) -> Dict[str, Any]:
    """검증된 정확한 문장을 보존(DRAFT_PRESERVED)하여 반환하고, 추가 LLM 호출이나 재검증 없이 결과를 확정한다.

    Args:
        state: 초안, 검증 상태, 검증 당시 초안 해시.

    Returns:
        최종 답변과 실제 인용된 출처, 검증 및 처분 상태.
    """

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

    search_status = state.get("statute_search_status")
    if search_status == "API_ERROR":
        # 공식 API 장애는 이전 PASS 스냅샷이 남아 있어도 상담을 종료한다.
        result["status"] = "INSUFFICIENT"
        result["reason_code"] = "OFFICIAL_STATUTE_API_ERROR"
        snapshot_valid = False
    notice = (
        "**안내:** 공식 법령 검색에서 요청한 법령의 일부 또는 전부를 확인하지 못했습니다. "
        "확보된 공식 법령 및 RAG 자료를 바탕으로 검토했으며, "
        "미확인 법령의 최신성 및 적용 시점은 추가 확인이 필요합니다."
    ) if search_status in ("NOT_FOUND", "PARTIAL_SUCCESS") else ""
    # 안내는 검증된 답변의 일부로 취급한다. 검증 이후 내용을 덧붙이지 않는다.
    if notice and snapshot_valid and not draft.startswith("**안내:**"):
        snapshot_valid = False
        result["reason_code"] = "SEARCH_DISCLOSURE_NOT_VERIFIED"

    temporal_blocked = (result.get("temporal_gate") or {}).get("status") == "BLOCK"
    valid = snapshot_valid and result.get("status") == "PASS" and not temporal_blocked
    limited_used = False

    # [FINALIZE-NO-LLM] finalize_node / finish_answer에서는 추가 LLM 재작성(write_document_answer)이나
    # run_verification 재검증을 일체 수행하지 않는다. (LLM 0회 및 DRAFT_PRESERVED 원칙 준수)
    # 5단계 verification_node에서 검증한 초안(draft)의 스냅샷이 유효하고 지지 주장(SUPPORTED)이 1건 이상 존재하는 경우,
    # 답변 전체를 폐기(WITHHELD)하지 않고 검증된 초안을 그대로 보존(DRAFT_PRESERVED)하여 CAUTIONARY로 승인한다.
    if snapshot_valid and not valid and result.get("claims") and not temporal_blocked and search_status != "API_ERROR":
        has_supported = any(c.get("grounding_status") == "SUPPORTED" for c in result.get("claims", []))
        # 핵심 법률 적용(LEGAL_APPLICATION/LEGAL_RULE) 중 미입증(UNSUPPORTED), 불확실(UNCERTAIN),
        # 필수 법률 근거 누락(missing_legal_issues/LEGAL_SOURCE_MISSING), 허위 인용,
        # 또는 결정론적 법률 위험 감지(legal_risk_passed=False)가 남아있다면 PASS로 승격하지 않고 엄격히 차단한다.
        has_legal_claims = any(
            c.get("claim_type") in ("LEGAL_RULE", "LEGAL_APPLICATION")
            for c in result.get("claims", [])
        )
        # [P0-DEFENSE] 초안 본문에 법률적 권리·효과 단정(대항력, 보증금 청구/반환, 경매 인수, 계약 해지 등)이 포함되어 있으나,
        # 검증 Claims 중 이를 뒷받침(SUPPORTED)하는 법률 주장(LEGAL_APPLICATION/LEGAL_RULE)이 단 1건도 존재하지 않는 경우
        # (검증기 추출 누락으로 인한 위험한 미검증 법률 결론 누출 차단)
        draft_legal_assertion_patterns = [
            re.compile(r"(?:낙찰자|매수인|경락인|임대인)(?:에게|를\s*상대로)?\s*(?:[^\r\n]{0,25})?(?:대항|청구|반환청구|요구)할\s*수\s*있"),
            re.compile(r"(?:낙찰자|매수인|경락인)(?:가|는|이)\s*(?:[^\r\n]{0,25})?인수해야\s*(?:합|한)"),
            re.compile(r"(?:소멸하지\s*않고|대항력을\s*유지하여)\s*(?:낙찰자|매수인|경락인)에게\s*인수"),
            re.compile(r"(?:계약|임대차)이?\s*(?:적법하게\s*)?(?:종료|해지)(?:되었|됐|된\s*것으로)"),
        ]
        has_unverified_draft_legal_assertion = (
            any(p.search(draft) for p in draft_legal_assertion_patterns)
            and not any(
                c.get("grounding_status") == "SUPPORTED"
                and c.get("claim_type") in ("LEGAL_RULE", "LEGAL_APPLICATION")
                for c in result.get("claims", [])
            )
        )
        has_fatal_legal_error = (
            any(
                c.get("grounding_status") in ("UNSUPPORTED", "UNCERTAIN")
                and c.get("claim_type") in ("LEGAL_RULE", "LEGAL_APPLICATION")
                for c in result.get("claims", [])
            )
            or bool(result.get("contradictions"))
            or (has_legal_claims and bool(result.get("missing_legal_issues")))
            or any(
                any(kw in ml for kw in ("법", "조", "판례", "소멸", "대항", "우선변제", "경매", "인수"))
                for ml in result.get("missing_legal_issues", [])
            )
            or result.get("reason_code") in ("LEGAL_SOURCE_MISSING", "LEGAL_SOURCE_INSUFFICIENT", "CITATION_INVALID")
            or (isinstance(result.get("qa_summary"), dict) and result.get("qa_summary", {}).get("legal_risk_passed") is False)
            or has_unverified_draft_legal_assertion
        )
        if has_supported and not has_fatal_legal_error:
            result["pre_fallback_status"] = result.get("status")
            result["status"] = "PASS"
            result["verified_answer_sha256"] = hashlib.sha256(str(draft).encode("utf-8")).hexdigest()
            valid = True
            limited_used = True

    if not valid:
        # 검증 결과나 그 이후의 원문 변경을 정형 성공 답변으로 덮어쓰지 않으며 내부 검토 문구 노출을 차단한다.
        result["status"] = "INSUFFICIENT"
        if result.get("reason_code") in (None, "NONE"):
            result["reason_code"] = "VERIFICATION_ERROR"
        raw_missing = list(dict.fromkeys(result.get("missing_legal_issues", []) + result.get("missing_issues", [])))
        missing = _sanitize_client_missing_items(raw_missing)
        detail = "\n" + "\n".join(f"- {item}" for item in missing) if missing else ""
        final = "질문에 대한 답변을 확정할 만큼 근거 확인을 마치지 못했습니다."
        if search_status == "API_ERROR":
            final = ("공식 법령 검색 API 호출 중 오류가 발생하여 법령 확인을 완료하지 못했습니다. "
                     "정확한 법률 판단을 위해 현재 상담을 종료합니다. 잠시 후 다시 시도해 주세요.")
        elif temporal_blocked:
            final += (" 계약 또는 사건 발생일에 적용되는 개정 법령의 시행일·부칙·적용례 "
                      "확인이 부족하여 단정적인 법률 판단을 보류합니다.")
        elif result.get("reason_code") == "VERIFICATION_ERROR":
            final += " 등록 자료와 답변을 대조하는 과정에 문제가 있어 다시 확인해야 합니다."
        elif detail:
            final += " 추가로 확인할 사항은 다음과 같습니다.\n" + detail
        else:
            final += " 등록 자료와 법률 근거를 다시 확인해야 합니다."
        sources = []
        disposition = "WITHHELD"
    else:
        from ai_legal_helper.utils.text_formatter import expand_evidence_citations, extract_all_registered_evidence_sources
        all_sources = extract_all_registered_evidence_sources(state) or sources_list
        final = expand_evidence_citations(draft, all_sources)
        cited_ids = {sid for claim in result.get("claims", [])
                     if claim.get("grounding_status") == "SUPPORTED" for sid in claim.get("source_ids", [])}
        sources = [s for s in sources_list if s.get("source_id") in cited_ids] or [
            s for s in sources_list if s.get("source_id") in draft or str(s.get("filename", "")) in draft
        ]
        # [P0-FINAL-DISPOSITION-NORMALIZATION]
        # DELIVERED vs CAUTIONARY 판정:
        # 1. 재작성 한도 도달 후 지지 주장(SUPPORTED)이 포함된 기존 초안을 폴백 보존했거나(limited_used),
        # 2. 사실관계 충돌(CONFLICTED) 또는 추가 증거 확인 필요(EVIDENCE_NEEDED) 상태의 주장이 존재하거나,
        # 3. SUPPORTED로 완전히 입증되지 않은 미확정 주장(UNCERTAIN 등)이 포함된 경우에만 CAUTIONARY로 분류한다.
        # 반면 정상 입증(SUPPORTED)된 사건 정황 추론(INFERENCE)이나 사용자 진술(USER_STATEMENT)은
        # 정상적인 법률 상담의 유효한 구성 요소이므로 DELIVERED(검증 완료)로 온전히 확정한다.
        has_cautionary_claims = any(
            c.get("fact_status") in ("CONFLICTED", "EVIDENCE_NEEDED")
            or c.get("grounding_status") not in ("SUPPORTED", "NOT_APPLICABLE")
            for c in result.get("claims", [])
        )
        disposition = "CAUTIONARY" if (limited_used or has_cautionary_claims) else "DELIVERED"
        # 최종 확장 답변(final)과 검증 해시를 동기화하여 Presentation 빌더 무결성 검증을 유지한다.
        result["verified_answer_sha256"] = hashlib.sha256(final.encode("utf-8")).hexdigest()
    draft_str = str(draft or "")
    final_str = str(final or "")
    draft_sha = hashlib.sha256(draft_str.encode("utf-8")).hexdigest()
    final_sha = hashlib.sha256(final_str.encode("utf-8")).hexdigest()
    has_changed = "있음" if draft_str.strip() != final_str.strip() else "없음"

    logger.info(
        "[FINALIZE] 최종 답변 작성 시작\n"
        "[FINALIZE] 답변 생성 방식: DRAFT_PRESERVED\n"
        "[FINALIZE] Verification 결과: %s\n"
        "[FINALIZE] 초안 SHA256: %s\n"
        "[FINALIZE] 최종 SHA256: %s\n"
        "[FINALIZE] 답변 내용 변경: %s\n"
        "[FINALIZE] 인용 출처: %d건\n"
        "[FINALIZE] 완료",
        result.get("status", "PASS"),
        draft_sha,
        final_sha,
        has_changed,
        len(sources),
    )
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
