# -*- coding: utf-8 -*-
"""상담 LangGraph 소스의 14 active nodes / 30 edges를 실제 방향 그래프에 반영."""
from pathlib import Path
import svgwrite,cairosvg,fitz
import build_deep_slides as base
from build_deep_slides import Art,BLUE,CYAN,TEAL,PURPLE,AMBER,WHITE,NAVY,MUTED
P=Path(__file__).resolve().parent

a=Art(3,'LangGraph · 상담 실행 그래프 (실제 Node / Edge)',
      '14개 활성 노드 · 30개 Edge. 정상 응답, 증거 부족 종료, 추가 법령검색, 수정·재검증 루프를 실제 연결 방향으로 표현합니다.',
      '근거: backend/src/ai_legal_helper/workflows/legal_workflow.py · build_legal_graph() (main 브랜치)')
# region background
a.rect(55,278,2288,280,'#F0F6FC','#C9DCEA',2,17)
a.rect(55,578,735,617,'#FBFCFF','#D7E2EC',2,18)
a.rect(811,578,1068,617,'#F9F7FD','#DCCFEA',2,18)
a.rect(1898,578,445,617,'#FFFDF8','#E5D7BA',2,18)
a.text(83,315,'01  정상 처리 · 왼쪽에서 오른쪽',27,BLUE,True)
a.text(86,616,'02  조기 종료 / 근거 확인 불가',26,BLUE,True)
a.text(840,616,'03  추가 검색 및 반복 검증',26,PURPLE,True)
a.text(1925,616,'04  최종 분기',27,AMBER,True)
# exact actual edge list is tracked separately; flow arrows draw some with intermediate segments.
E=[]
def add(s,t,pts,color=BLUE,sw=3,dash=False,opacity=.75):
    E.append((s,t))
    a.line(pts,color,sw,dashed=dash,arrow=True,opacity=opacity)
# main chain
mid=421
for s,t,pts in [
    ('START','supervisor_initialize',[(203,422),(237,422)]),
    ('supervisor_initialize','route',[(532,422),(562,422)]),
    ('route','run_agents',[(753,422),(779,422)]),
    ('run_agents','synthesize',[(1037,422),(1057,422)]),
    ('synthesize','verification',[(1287,422),(1310,422)]),
    ('verification','finalize',[(1581,422),(1763,422)]),
    ('finalize','END',[(1991,422),(2090,422)]),]:add(s,t,pts,BLUE,4,False,.96)
# early exit branches to a local END marker
add('supervisor_initialize','general_conversation',[(359,470),(359,555),(133,555),(133,676)],BLUE,2.6,False,.48)
add('supervisor_initialize','evidence_unavailable',[(424,470),(424,570),(151,570),(151,791)],BLUE,2.6,False,.48)
add('supervisor_initialize','routing_exit',[(463,470),(463,589),(557,589),(557,904)],BLUE,2.6,False,.48)
add('route','routing_exit',[(650,472),(650,874),(611,874),(611,903)],BLUE,2.4,False,.45)
for s,yy in [('general_conversation',713),('evidence_unavailable',826),('routing_exit',940)]:
    add(s,'END',[(490,yy),(556,yy)],TEAL,2.7,False,.8)
# synthesis / verification gating: all real condition destinations represented
add('synthesize','statute_search_approval',[(1142,473),(1142,550),(986,550),(986,688)],TEAL,2.9,False,.65)
add('synthesize','insufficient',[(1215,472),(1215,545),(2021,545),(2021,876)],AMBER,2.5,True,.62)
add('verification','statute_search_approval',[(1400,472),(1400,568),(1060,568),(1060,688)],TEAL,2.5,False,.55)
add('verification','execute_statute_search',[(1503,473),(1503,682)],TEAL,2.7,False,.6)
add('verification','revise',[(1548,472),(1548,846),(1633,846)],PURPLE,2.8,False,.6)
add('verification','insufficient',[(1570,472),(1570,587),(2068,587),(2068,876)],AMBER,2.3,True,.55)
# approval routes
add('statute_search_approval','execute_statute_search',[(1190,749),(1247,749)],TEAL,3.3,False,.9)
add('statute_search_approval','insufficient',[(1113,808),(1113,1107),(1930,1107),(1930,929),(1950,929)],AMBER,2.4,True,.48)
# search outcomes
add('execute_statute_search','run_agents',[(1292,807),(1292,1170),(890,1170),(890,471)],TEAL,2.8,True,.65)
add('execute_statute_search','re_analyze',[(1559,746),(1609,746)],PURPLE,3.3,False,.88)
add('execute_statute_search','revise',[(1509,807),(1509,827),(1633,827),(1633,896)],PURPLE,2.7,False,.7)
add('execute_statute_search','finalize',[(1535,686),(1535,535),(1863,535),(1863,473)],AMBER,2.6,True,.74)
add('execute_statute_search','insufficient',[(1485,807),(1485,1147),(2122,1147),(2122,952)],AMBER,2.4,True,.49)
# corrections / independent re-verification
add('re_analyze','verification',[(1734,687),(1734,512),(1455,512),(1455,471)],PURPLE,3,True,.64)
add('revise','verification',[(1758,873),(1758,493),(1498,493),(1498,471)],PURPLE,3,True,.66)
# two final terminal branches
add('insufficient','END',[(2135,954),(2135,1013)],AMBER,3.0,False,.9)
assert len(E)==30,len(E)
assert len({s for s,t in E}|{t for s,t in E})-2==14
# actual nodes over edges
# MAIN
p=[(80,160,'START',TEAL),(240,290,'supervisor_initialize',BLUE),(567,180,'route',BLUE),
   (783,250,'run_agents',BLUE),(1065,215,'synthesize',PURPLE),(1320,255,'verification',PURPLE),
   (1771,219,'finalize',BLUE),(2097,167,'END',TEAL)]
for x,w,name,col in p:
    if name in ('START','END'):a.pill(x,382,w,80,name,'#E8F7F2',TEAL,fs=28)
    else:
        d={'supervisor_initialize':'사건 맥락·대화 준비','route':'법률 분야 분기','run_agents':'법령 RAG · 분야 처리',
           'synthesize':'근거 기반 초안 생성','verification':'출처 · 날짜 · 주장 검증','finalize':'안전한 답변 확정'}[name]
        a.node(x,365,w,112,name,[d],col,WHITE,fs=25 if len(name)<21 else 22)
# EARLY
for yy,tt,desc in [(677,'general_conversation','법률 외 일반 질문'),(790,'evidence_unavailable','원문 증거 부족'),(903,'routing_exit','진행 불가 / 요청 종료')]:
    a.node(95,yy,395,76,tt,[],BLUE,WHITE,fs=23)
    a.pill(557,yy+13,155,49,'END',fill='#E8F7F2',fg=TEAL,fs=24)
    a.text(105,yy+69,desc,15,MUTED)
# SEARCH
for x,y,w,title,des,col in [
    (876,689,314,'statute_search_approval','HITL: 검색 대상 사용자 승인',TEAL),
    (1248,689,310,'execute_statute_search','로컬 검색 / 공식 API',TEAL),
    (1610,689,249,'re_analyze','새 근거로 답변 재분석',PURPLE),
    (1635,875,224,'revise','지적사항 수정',PURPLE)]:
    a.node(x,y,w,115,title,[des],col,WHITE,fs=22 if len(title)>=17 else 25)
# Response
for x,y,w,title,des,col in [(1960,876,360,'insufficient','근거 부족 · 판단 유보',AMBER)]:
    a.node(x,y,w,78,title,[],col,WHITE,fs=26)
    a.text(x+23,y+66,des,18,MUTED)
a.pill(2046,1017,190,58,'END',fill='#E8F7F2',fg=TEAL,fs=26)
# Caveat panels and directional legend inside zones
a.rect(844,994,1025,92,'#F0EAF9','#CFBFEA',1.6,13)
a.text(874,1030,'재분석(re_analyze)·수정(revise) → verification 재진입',24,PURPLE,True)
a.text(874,1068,'검색 결과 → run_agents / 재분석 / 수정 / finalize* / 판단 유보',20,MUTED)
a.rect(1930,654,382,163,'#FFF4E3','#E8CDA2',1.6,13)
a.multi(1951,694,['* 검색 0건이라도 기존 검증된','  claims가 있는 문서 모드만','  finalize 직접 이동 가능','  (finish_answer 안전검사)'],21,AMBER,35)
# Legend
for i,(label,col,dash) in enumerate([('주 경로',BLUE,False),('공식 검색',TEAL,False),('재분석 / 수정',PURPLE,True),('판단 유보·예외',AMBER,True)]):
    x=64+i*375
    a.line([(x,1240),(x+72,1240)],col,4,dashed=dash,arrow=True)
    a.text(x+84,1248,label,23,MUTED)
a.text(1580,1250,'범례: 같은 END를 여러 위치에 반복 표기 · 조건 판단은 상태에 따라 결정',18,MUTED)
# actual edge list dump for validation
(P/'langgraph_edges.csv').write_text('source,target\n'+'\n'.join(f'{s},{t}' for s,t in E)+'\n',encoding='utf-8')
a.save('03_LangGraph_상담처리흐름도.svg')
name='03_LangGraph_상담처리흐름도'
cairosvg.svg2pdf(url=str(P/f'{name}.svg'),write_to=str(P/f'{name}.pdf'),output_width=2400,output_height=1350)
cairosvg.svg2png(url=str(P/f'{name}.svg'),write_to=str(P/f'{name}.png'),output_width=2400,output_height=1350)
allp=fitz.open()
for num in ('01_사용자경험_서비스개념도','02_전체시스템_아키텍처','03_LangGraph_상담처리흐름도'):
    f=fitz.open(P/f'{num}.pdf');allp.insert_pdf(f);f.close()
allp.save(P/'AI_Legal_Helper_기술아키텍처_상세3장.pdf',garbage=4,deflate=True)
allp.close()
print('Graph edges:',len(E), '\n',E)