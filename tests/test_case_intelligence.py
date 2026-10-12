# -*- coding: utf-8 -*-
"""
Case Intelligence 파이프라인 통합 테스트 (P2.2)

주택임대차 분쟁 시나리오를 바탕으로 사건 생성부터 진술 추가, 
타임라인 생성, 법률 쟁점 추출, 그리고 마지막으로 Supervisor 연동까지 검증한다.
"""
import sys
import os
import json
import asyncio

# src 경로를 sys.path에 추가하여 패키지를 임포트 가능하게 함
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import Case, Fact, Event, Party
from ai_legal_helper.api.schemas.case import CaseCreateRequest
from ai_legal_helper.case_intelligence.manager import process_new_statement
from ai_legal_helper.observability.context import set_case_id, set_request_id, set_trace_id, reset_case_id, reset_request_id, reset_trace_id
from ai_legal_helper.workflows.legal_workflow import run_legal_consultation

async def run_scenario():
    print("=== [P2.2 테스트] 주택임대차 분쟁 시나리오 ===")
    db = SessionLocal()
    
    # 1. 사건 생성
    new_case = Case(title="주택임대차 분쟁 (보증금 미반환)", case_type="주택임대차")
    db.add(new_case)
    db.commit()
    db.refresh(new_case)
    case_id = new_case.id
    print(f"[1] 사건 생성됨: ID={case_id}, 제목={new_case.title}")
    
    try:
        # 시나리오 진술
        statements = [
            "2022년 3월 1일에 보증금 2억원으로 2년 전세계약을 체결했습니다.",
            "2024년 3월 1일에 계약이 묵시적으로 갱신되었습니다.",
            "그런데 직장을 옮기게 되어 2024년 5월 초에 집주인에게 문자로 계약 해지를 통지했습니다.",
            "집주인이 다음 세입자를 구하기 전까지는 보증금을 돌려줄 수 없다고 거절했습니다.",
            "제가 5월 통지 시에 보낸 문자 메시지 캡처본이 증거로 있습니다."
        ]
        
        for i, stmt in enumerate(statements, 2):
            print(f"\n[{i}] 진술 추가: {stmt}")
            process_new_statement(db, case_id, stmt)
            
            # DB 갱신 반영
            db.commit()
        
        # 사건 데이터 검증
        db.refresh(new_case)
        facts = db.query(Fact).filter(Fact.case_id == case_id).all()
        events = db.query(Event).filter(Event.case_id == case_id).order_by(Event.event_date).all()
        parties = db.query(Party).filter(Party.case_id == case_id).all()
        
        print("\n=== [추출 결과 확인] ===")
        print(f"사건 버전: {new_case.version}")
        print("\n당사자:")
        for p in parties:
            print(f" - {p.name} ({p.role})")
            
        print("\n사실관계:")
        for f in facts:
            print(f" - [{f.fact_type}] {f.occurred_at}: {f.statement}")
            
        print("\n타임라인:")
        for e in events:
            print(f" - {e.event_date} ({e.date_precision}): {e.title}")
            
        # 10. Supervisor 재분석 (LangGraph 연동)
        print("\n[10] Supervisor 재분석 실행 (Case ID 연동)")
        
        # Set Context
        c_tok = set_case_id(case_id)
        r_tok = set_request_id("test-p2-2-req")
        t_tok = set_trace_id("test-p2-2-trace")
        
        question = "지금 상황에서 제가 언제 보증금을 돌려받을 수 있으며, 만약 계속 안 주면 임차권등기명령을 신청할 수 있나요?"
        print(f"질문: {question}")
        
        result = await run_legal_consultation(question, thread_id="test-p2-2-thread")
        
        reset_case_id(c_tok)
        reset_request_id(r_tok)
        reset_trace_id(t_tok)
        
        print("\n=== [최종 답변] ===")
        print(result["answer"])
        
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_scenario())

