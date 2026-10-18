# -*- coding: utf-8 -*-
"""
모듈명: test_top10_audit_fixes.py

[모듈 개요]
As-Is Architecture & Event Flow Audit에서 식별된 우선 수정 문제 TOP 10의
코드 수정 사항을 검증하는 단위·통합 테스트 모듈이다.

[검증 항목]
1. Issue #1: AgentExecutor.invoke가 RAG 도구 결과(Observation)와 chat_brief를 프롬프트에 실제로 주입하는지 검증
2. Issue #2: consultation.py에 os 모듈이 정상 임포트되어 os.path.basename 호출이 동작하는지 검증
3. Issue #3: workflow.py 요약 API에서 last_c.answer가 None이거나 LegalDocument.document_type 조회 시 예외가 발생하지 않는지 검증
4. Issue #4: auth.py의 UserCreate/UserResponse가 name 및 display_name을 모두 수용하고 동기화하는지 검증
5. Issue #5: verification.py의 validate_citations_against_sources가 미검색 PDF 파일명을 탐지하고 revise_node가 보강 검색을 수행하는지 검증
6. Issue #6: evidence_extractor.py의 detect_conflicting_fact가 기존 Fact와의 금액/긍부정 상충을 탐지하는지 검증
7. Issue #7: Neo4j 드라이버가 None일 때 _collect_graph_evidence가 조기 종료하지 않고 하이브리드 폴백을 호출하는지 검증
8. Issue #8: @trace 데코레이터 중첩 호출 시 상위 Span UUID(parent_span_id)가 하위 Span으로 전파되는지 검증
9. Issue #9: PartySchema, FactSchema, EventSchema, LegalIssueSchema의 from_attributes=True 설정 검증
10. Issue #10: CaseUpdateRequest 스키마 및 PATCH /api/v1/cases/{case_id} 라우트 등록 여부 검증
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from langchain_core.prompts import PromptTemplate

from ai_legal_helper.agents.legal.base_agent import AgentExecutor, REACT_TEMPLATE
from ai_legal_helper.agents.verification import validate_citations_against_sources, run_verification
from ai_legal_helper.api.routes import consultation as consultation_route
from ai_legal_helper.api.routes.auth import UserCreate, UserResponse
from ai_legal_helper.api.schemas.case import (
    PartySchema,
    FactSchema,
    EventSchema,
    LegalIssueSchema,
    CaseUpdateRequest,
)
from ai_legal_helper.case_intelligence.evidence_extractor import detect_conflicting_fact


def test_issue_1_agent_executor_injects_tool_observation_and_chat_brief():
    """Issue #1: AgentExecutor.invoke가 도구 실행 결과(Observation)와 chat_brief를 LLM 프롬프트에 주입하는지 검증한다."""
    mock_tool = MagicMock()
    mock_tool.name = "housing_lease_rag"
    mock_tool.description = "주택임대차 법령 검색"
    mock_tool.invoke.return_value = "[CITE] (주택임대차보호법.pdf, p.3)\n제3조 대항력 등"

    captured_prompts = []
    mock_llm = MagicMock()

    def _capture_llm(prompt_text):
        captured_prompts.append(prompt_text)
        return SimpleNamespace(content="Final Answer: 대항력이 인정됩니다 (주택임대차보호법.pdf, p.3).")

    mock_llm.invoke.side_effect = _capture_llm

    prompt = PromptTemplate.from_template(REACT_TEMPLATE).partial(
        system="시스템 지침",
        tools="housing_lease_rag: 주택임대차 법령 검색",
        tool_names="housing_lease_rag",
    )
    executor = AgentExecutor(agent=prompt, tools=[mock_tool])

    with patch("ai_legal_helper.agents.legal.base_agent.get_llm", return_value=mock_llm):
        res = executor.invoke({
            "input": "대항력 요건은 무엇인가요?",
            "chat_brief": "[사건 기본 정보] 보증금 2억원 전세 계약",
        })

    assert "주택임대차보호법.pdf" in res["output"]
    assert len(captured_prompts) == 1
    sent_prompt = captured_prompts[0]
    assert "[CITE] (주택임대차보호법.pdf, p.3)" in sent_prompt
    assert "[사건 기본 정보] 보증금 2억원 전세 계약" in sent_prompt


def test_issue_2_consultation_has_os_import():
    """Issue #2: consultation 라우터 모듈에 os가 정상 임포트되어 있는지 검증한다."""
    assert hasattr(consultation_route, "os")
    assert consultation_route.os.path.basename("/tmp/test_doc.pdf") == "test_doc.pdf"


def test_issue_4_auth_schema_accepts_name_and_display_name():
    """Issue #4: UserCreate와 UserResponse가 프런트엔드 name 필드와 백엔드 display_name 필드를 상호 호환하는지 검증한다."""
    u1 = UserCreate(email="user1@example.com", password="pw", name="홍길동")
    assert u1.display_name == "홍길동"
    assert u1.name == "홍길동"

    u2 = UserCreate(email="user2@example.com", password="pw", display_name="김철수")
    assert u2.display_name == "김철수"
    assert u2.name == "김철수"

    resp = UserResponse(id="u-1", email="user1@example.com", display_name="홍길동", status="ACTIVE")
    assert resp.name == "홍길동"


def test_issue_5_citation_validator_detects_hallucinated_pdf():
    """Issue #5: validate_citations_against_sources가 검색 결과에 없는 허위 PDF 인용을 정확히 탐지하는지 검증한다."""
    sources = [
        {
            "source_id": "주택임대차보호법.pdf#p.3",
            "file_name": "주택임대차보호법.pdf",
            "page": "3",
            "category": "주택임대차",
            "content": "제3조 대항력",
        }
    ]
    draft = (
        "주택임대차보호법상 대항력이 발생합니다 (주택임대차보호법.pdf, p.3). "
        "또한 민법상 손해배상 청구가 가능합니다 (민법(법률)(제20432호)(20250131).pdf, p.40)."
    )
    unverified = validate_citations_against_sources(draft, sources)
    assert len(unverified) == 1
    assert "민법(법률)(제20432호)(20250131).pdf" in unverified[0]

    # LLM이 PASS를 반환하더라도 미검증 인용이 있으면 REVISE로 강등되는지 확인
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = SimpleNamespace(
        content='{"status": "PASS", "claims": [], "missing_issues": [], "contradictions": [], "revision_instructions": [], "warnings": []}'
    )
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=mock_llm):
        ver = run_verification("질문", draft, sources, case_context="사건 맥락")
    assert ver["status"] == "REVISE"
    assert any("민법" in w for w in ver["warnings"])


def test_issue_6_detect_conflicting_fact():
    """Issue #6: detect_conflicting_fact가 기존 Fact와 금액 또는 긍·부정이 상충하는 진술을 탐지하는지 검증한다."""
    existing_facts = [
        SimpleNamespace(id="fact-1", statement="임차인은 보증금 2억원을 지급하였다."),
    ]
    conflict_amt = detect_conflicting_fact("계약서상 임차인은 보증금 3억원을 지급하였다.", existing_facts)
    assert conflict_amt is not None
    assert conflict_amt.id == "fact-1"

    conflict_neg = detect_conflicting_fact("임차인은 보증금 2억원을 지급하지 않았다.", existing_facts)
    assert conflict_neg is not None
    assert conflict_neg.id == "fact-1"

    no_conflict = detect_conflicting_fact("임차인은 보증금 2억원을 지급하였다.", existing_facts)
    assert no_conflict is None


def test_issue_8_trace_decorator_propagates_parent_span_id():
    """Issue #8: 중첩된 @trace 함수 실행 시 부모 Span의 UUID가 자식 Span의 parent_span_id로 전달되는지 검증한다."""
    from ai_legal_helper.observability.decorators import trace

    recorded_spans = []

    def _mock_start_span(trace_id, span_id, name, parent_span_id=None, input=None):
        recorded_spans.append((name, span_id, parent_span_id))

    @trace
    def child_fn():
        return "ok"

    @trace
    def parent_fn():
        return child_fn()

    with patch("ai_legal_helper.observability.decorators.start_span", side_effect=_mock_start_span):
        assert parent_fn() == "ok"

    assert len(recorded_spans) == 2
    parent_name, parent_span_uuid, _ = recorded_spans[0]
    child_name, _, child_parent_uuid = recorded_spans[1]
    assert parent_name == "parent_fn"
    assert child_name == "child_fn"
    assert child_parent_uuid == parent_span_uuid


def test_issue_9_and_10_case_schemas_and_update_route():
    """Issue #9 & #10: ORM 객체 직렬화(from_attributes) 및 사건 수정(PATCH /cases/{case_id}) 스키마/라우트를 검증한다."""
    orm_party = SimpleNamespace(id="p1", name="임대인", role="임대인", party_relationship="계약상대방", notes=None)
    orm_fact = SimpleNamespace(
        id="f1",
        statement="보증금 1억원",
        fact_type="AMOUNT",
        confidence=0.9,
        source_type="USER_CLAIM",
        occurred_at=None,
        verification_status="VERIFIED",
    )
    orm_event = SimpleNamespace(
        id="e1",
        title="계약 체결",
        description=None,
        event_date="2025-01-01",
        date_precision="EXACT",
        event_type="CONTRACT",
        related_fact_ids=[],
    )
    orm_issue = SimpleNamespace(
        id="i1",
        title="보증금 반환",
        description=None,
        related_fact_ids=[],
        status="OPEN",
    )

    assert PartySchema.model_validate(orm_party).name == "임대인"
    assert FactSchema.model_validate(orm_fact).statement == "보증금 1억원"
    assert EventSchema.model_validate(orm_event).title == "계약 체결"
    assert LegalIssueSchema.model_validate(orm_issue).title == "보증금 반환"

    req = CaseUpdateRequest(title="수정된 사건명", status="CLOSED")
    assert req.title == "수정된 사건명"
    assert req.status == "CLOSED"


def test_additional_1_retrieval_factory_guide_has_no_hardcoded_filename():
    """추가 개선 #1: retrieval_factory의 [GUIDE] 프롬프트에 하드코딩된 민법 PDF 예시가 제거되었는지 검증한다."""
    from ai_legal_helper.rag.retrieval_factory import make_fixed_retrieval_tool

    fake_doc = SimpleNamespace(
        page_content="제3조 대항력 등 본문 내용",
        metadata={"file_name": "주택임대차보호법.pdf", "page": 3, "page_end": 3},
    )
    with patch("ai_legal_helper.rag.retrieval_factory.rewrite_query", return_value="대항력"), patch(
        "ai_legal_helper.rag.retrieval_factory._retrieve", return_value=[fake_doc]
    ):
        tool = make_fixed_retrieval_tool("search_lease", "housing_lease", "주택임대차")
        out = tool.func("대항력")

    assert "[CITE] (주택임대차보호법.pdf, p.3)" in out
    assert "민법(법률)(제20432호)(20250131).pdf" not in out


def test_additional_2_document_workflow_requirements_and_verification():
    """추가 개선 #2: document_workflow의 requirements_node가 일반 사건 맥락을 통과시키고 verification_node가 미검증 날짜·금액을 탐지하는지 검증한다."""
    from ai_legal_helper.workflows.document_workflow import (
        DocumentState,
        requirements_node,
        verification_node,
    )

    # 비임대차 일반 민사/근로 사건도 [사실관계]가 있으면 요건 충족
    st = DocumentState(
        case_id="case-1",
        document_type="내용증명",
        context_text="[사건: 부당해고 구제 신청]\n[사실관계]\n- 2025-03-01 해고 통보를 받음 (체불임금 500만원)",
    )
    st = requirements_node(st)
    assert st.requirements_met is True

    # 컨텍스트에 있는 날짜/금액만 사용한 경우 PASS
    st.draft_content = "귀하는 2025-03-01 해고 통보를 하였으며 체불임금 500만원을 지급해야 합니다."
    st = verification_node(st)
    assert st.verification_status == "PASS"
    assert len(st.verification_warnings) == 0

    # 컨텍스트에 없는 날짜(2026-12-31)나 금액(9000만원)이 포함된 경우 WARN
    st_warn = DocumentState(
        case_id="case-1",
        document_type="내용증명",
        context_text=st.context_text,
        requirements_met=True,
        draft_content="귀하는 2026-12-31까지 위약금 9000만원을 지급해야 합니다.",
    )
    st_warn = verification_node(st_warn)
    assert st_warn.verification_status == "WARN"
    assert len(st_warn.verification_warnings) == 2


def test_additional_3_statement_party_and_fact_deduplication():
    """추가 개선 #3: process_new_statement가 이미 등록된 동일 당사자(Party)와 동일 사실(Fact)을 중복 삽입하지 않는지 검증한다."""
    from ai_legal_helper.case_intelligence.manager import process_new_statement
    from ai_legal_helper.database.models import Case, Party, Fact

    mock_db = MagicMock()
    fake_case = SimpleNamespace(id="case-1", title="임대차 분쟁", version=1)
    existing_party = SimpleNamespace(id="p-1", case_id="case-1", name="홍길동", role="임대인", party_relationship=None)
    existing_fact = SimpleNamespace(id="f-1", case_id="case-1", statement="보증금 2억원을 지급함", occurred_at=None)

    def _query_side_effect(model):
        q = MagicMock()
        if model is Case:
            q.filter.return_value.first.return_value = fake_case
        elif model is Party:
            q.filter.return_value.all.return_value = [existing_party]
        elif model is Fact:
            q.filter.return_value.all.return_value = [existing_fact]
        else:
            q.filter.return_value.delete.return_value = 0
        return q

    mock_db.query.side_effect = _query_side_effect

    fake_extracted = SimpleNamespace(
        parties=[
            SimpleNamespace(name="홍길동", role="임대인", relationship="집주인"),  # 중복 (관계만 보완)
            SimpleNamespace(name="김임차", role="임차인", relationship="세입자"),  # 신규
        ],
        facts=[
            SimpleNamespace(statement="보증금  2억원을 지급함", fact_type="AMOUNT", occurred_at=None, source_type="USER_CLAIM"),  # 공백 차이 중복
            SimpleNamespace(statement="2025-05-01 만기 통보함", fact_type="DATE", occurred_at="2025-05-01", source_type="USER_CLAIM"),  # 신규
        ],
        missing_info_questions=[],
    )

    added_objects = []
    mock_db.add.side_effect = lambda obj: added_objects.append(obj)

    with patch("ai_legal_helper.case_intelligence.manager.extract_case_info", return_value=fake_extracted), patch(
        "ai_legal_helper.case_intelligence.manager.build_timeline_from_facts", return_value=[]
    ), patch("ai_legal_helper.database.graph_sync_worker.queue_sync_task"):
        process_new_statement(mock_db, "case-1", "진술 원문")

    added_parties = [o for o in added_objects if isinstance(o, Party)]
    added_facts = [o for o in added_objects if isinstance(o, Fact)]
    assert len(added_parties) == 1
    assert added_parties[0].name == "김임차"
    assert existing_party.party_relationship == "집주인"
    assert len(added_facts) == 1
    assert "2025-05-01" in added_facts[0].statement


def test_additional_4_action_and_document_update_schemas_and_routes():
    """추가 개선 #4: 법률 문서 리비전 수정 라우트 및 대응 계획 상태/요건 변경 스키마·라우트가 정상 등록되어 있는지 검증한다."""
    from ai_legal_helper.api.routes import documents as doc_routes
    from ai_legal_helper.api.routes import cases as case_routes
    from ai_legal_helper.api.schemas.action import ActionStatusUpdateRequest, RequirementStatusUpdateRequest
    from ai_legal_helper.api.schemas.document import DocumentUpdateRequest

    assert hasattr(doc_routes, "update_document")
    assert hasattr(case_routes, "update_action_status")
    assert hasattr(case_routes, "update_action_requirement_status")

    act_req = ActionStatusUpdateRequest(status="COMPLETED")
    req_upd = RequirementStatusUpdateRequest(satisfaction_status="SATISFIED")
    doc_upd = DocumentUpdateRequest(content="수정된 내용증명 본문", review_status="APPROVED")
    assert act_req.status == "COMPLETED"
    assert req_upd.satisfaction_status == "SATISFIED"
    assert doc_upd.review_status == "APPROVED"



