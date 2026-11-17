# -*- coding: utf-8 -*-
"""AI Legal Helper main 소스 근거 발표용 SVG/PDF/PNG 제작 (상세 재설계)."""
import math, os, re, html
from pathlib import Path
import svgwrite
import cairosvg, fitz

OUT=Path(__file__).resolve().parent
W,H=2400,1350
NAVY='#102940'; DARK='#182F44'; BLUE='#2A638E'; CYAN='#138E9C'; TEAL='#08756F'; PURPLE='#6B54A2'; AMBER='#BB7C26'; RED='#AE5B54'; FG='#273F53'; MUTED='#586D7F'; LINE='#DCE5EE'; LIGHT='#F5F8FC'; WHITE='#FFFFFF'
FONT='Noto Sans CJK KR'

class Art:
    def __init__(self,n,title,subtitle,topnote):
        self.n=n; self.d=svgwrite.Drawing(size=(W,H),viewBox=f'0 0 {W} {H}',profile='full')
        self.d.add(self.d.rect(insert=(0,0),size=(W,H),fill=LIGHT))
        self.d.add(self.d.rect(insert=(0,0),size=(W,155),fill=NAVY))
        self.d.add(self.d.rect(insert=(0,155),size=(W,97),fill='#E6F2F5'))
        self.text(68,94,title,58,WHITE,True)
        self.text(2330,92,f'{n:02d} / 03',28,'#CCE3EF',anchor='end')
        self.text(72,215,subtitle,29,NAVY,True)
        self.text(72,1322,topnote,17,MUTED)
        self.text(2322,1322,'소스 기준: GitHub main · 2026-11-17',17,MUTED,anchor='end')
    def text(self,x,y,v,sz=24,fill=DARK,bold=False,anchor='start',family=None):
        self.d.add(self.d.text(str(v),insert=(x,y),fill=fill,style=f'font-family:"{family or FONT}",sans-serif;font-size:{sz}px;font-weight:{700 if bold else 400}',text_anchor=anchor))
    def multi(self,x,y,strings,sz=24,fill=MUTED,leading=36,bold=False,anchor='start'):
        for k,line in enumerate(strings):self.text(x,y+k*leading,line,sz,fill,bold,anchor)
    def rect(self,x,y,w,h,fill=WHITE,stroke=LINE,sw=2,rad=18):
        r=self.d.rect(insert=(x,y),size=(w,h),rx=rad,ry=rad,fill=fill,stroke=stroke,stroke_width=sw)
        self.d.add(r);return r
    def line(self,pts,color=BLUE,sw=3,dashed=False,arrow=True,opacity=1.0):
        kw={'fill':'none','stroke':color,'stroke_width':sw,'stroke_linecap':'round','stroke_linejoin':'round','opacity':opacity}
        if dashed:kw['stroke_dasharray']='10 8'
        self.d.add(self.d.polyline(pts,**kw))
        if arrow:
            a,b=pts[-2],pts[-1]; rad=math.atan2(b[1]-a[1],b[0]-a[0]); l=11+sw*.6
            points=[b,(b[0]-l*math.cos(rad-.42),b[1]-l*math.sin(rad-.42)),(b[0]-l*math.cos(rad+.42),b[1]-l*math.sin(rad+.42))]
            self.d.add(self.d.polygon(points,fill=color,opacity=opacity))
    def pill(self,x,y,w,h,title,fill='#EAF4FC',fg=BLUE,border=None,fs=20):
        self.rect(x,y,w,h,fill,border or fg,1.6,rad=h/2)
        self.text(x+w/2,y+h*.68,title,fs,fg,True,'middle')
    def node(self,x,y,w,h,title,desc='',color=BLUE,fill=WHITE,tag=None,fs=25):
        self.rect(x,y,w,h,fill,color,2.7,rad=18)
        self.d.add(self.d.rect(insert=(x,y),size=(9,h),fill=color,rx=4))
        self.text(x+23,y+38,title,fs,FG,True)
        if isinstance(desc,str):desc=[desc] if desc else []
        for i,item in enumerate(desc):self.text(x+24,y+76+i*30,item,20,MUTED)
        if tag:self.text(x+w-15,y+h-15,tag,17,color,False,'end')
    def save(self,path):self.d.saveas(str(OUT/path))

# ---------------------------------------------------------------------------
# 01: USER EXPERIENCE: six-step journey over two independent swimlanes.
# ---------------------------------------------------------------------------
a=Art(1,'사용자 경험 · 사건 중심 서비스 여정',
      '사용자가 사실을 확정하고 상담을 이어가며, 대응계획·문서 작성까지 동일한 사건 맥락을 활용합니다.',
      '근거: frontend/src/pages/CaseWorkspace.tsx · api/routes/evidence.py · api/routes/consultation.py · api/routes/documents.py')
# presentation legend
for j,(label,col) in enumerate([('사용자 행동',BLUE),('시스템 처리',PURPLE),('사건 단위 누적 정보',TEAL)]):
    a.pill(72+j*300,270,265,44,label,fill=WHITE,fg=col,fs=22)
cols=[70,470,870,1270,1670,2070]
headings=['사건 생성','증거 자료 등록','사실 검토·승인','AI 법률 상담','대응계획 검토','법률문서 작성']
sub=['사건 유형·당사자 입력','계약서·문자·이체내역','추출 사실 승인·수정','증거·맥락 반영 질문','다음 행동·기한 확인','초안 검토 및 수정']
process=[['사건 ID 부여','기본정보 저장'],['텍스트 추출','LLM 사실 후보 생성'],['사실·타임라인 갱신','관계 그래프 동기화'],['법령 검색·검증','상담 이력 저장'],['실행 항목 구성','우선순위·기한'],['별도 LangGraph','생성·검토·버전']]
for i,x in enumerate(cols):
    a.rect(x,350,325,154,'#F5F9FE',BLUE,2.8,18)
    a.pill(x+20,365,55,41,f'{i+1:02d}',fill=BLUE,fg=WHITE,fs=24)
    a.text(x+24,444,headings[i],31,NAVY,True)
    a.text(x+24,480,sub[i],20,MUTED)
    a.line([(x+160,505),(x+160,565)],CYAN,2.8)
    a.node(x,570,325,147,process[i][0],process[i][1],PURPLE,'#F8F5FF',fs=27)
    if i<5:
        a.line([(x+325,426),(x+393,426)],BLUE,5)
    a.line([(x+160,718),(x+160,800)],TEAL,3,arrow=False)
a.text(76,336,'① 사용자 행동 · 동일 사건 작업공간',23,BLUE,True)
a.text(76,553,'② 시스템이 각 행동을 지원',23,PURPLE,True)
a.rect(71,790,2253,345,'#F1F9F7',TEAL,3,22)
a.text(112,852,'③ 사건 단위로 누적되는 업무 데이터 · PostgreSQL 중심',31,TEAL,True)
records=[('사건 · 당사자','Case / Party'),('증거 · 사실','Evidence / Claim'),('사건 타임라인','Fact / Event'),('상담 이력','ConsultationRecord'),('대응 조치','LegalAction'),('문서 버전','DocumentRevision')]
for i,(t,model) in enumerate(records):
    x=115+i*371
    a.rect(x,893,336,105,WHITE,'#C8DEDA',2,15)
    a.text(x+20,936,t,26,NAVY,True)
    a.text(x+20,972,model,19,TEAL)
a.line([(2038,1120),(1170,1120),(1170,1180),(1350,1180)],TEAL,3,dashed=True)
a.rect(1360,1143,903,69,'#E9F3FE',BLUE,1.7,12)
a.text(1388,1188,'새 증거·사실 변경 → 이전 상담은 재검토 필요 상태로 안내',25,BLUE,True)
a.text(110,1085,'핵심 UX: “한 번 묻고 끝나는 챗봇”이 아니라 변경되는 사건을 계속 관리',29,TEAL,True)
a.save('01_사용자경험_서비스개념도.svg')

# ---------------------------------------------------------------------------
# 02: SYSTEM ARCHITECTURE. Deployment boundaries, real protocols, orchestration.
# ---------------------------------------------------------------------------
a=Art(2,'시스템 아키텍처 · 실행 구성과 데이터 흐름',
      'Docker Compose 기반 React/FastAPI, 업무별 AI 실행, PostgreSQL·Neo4j·ChromaDB, 외부 LLM·법령 API를 연결합니다.',
      '근거: docker-compose.yml · api/main.py · api/routes/*.py · llm/gateway.py · database/graph_sync_worker.py')
# Left client
x=58
a.rect(x,315,350,290,'#FFFFFF',BLUE,3,20)
a.rect(x,315,350,56,BLUE,BLUE,1,18)
a.text(83,353,'브라우저 / 프런트엔드',26,WHITE,True)
a.text(83,416,'React + TypeScript',31,NAVY,True)
a.multi(84,463,['사건별 Workspace','상담 상태 폴링 · 승인 UI','증거·그래프·문서 화면'],23,MUTED,39)
a.pill(104,547,261,40,'frontend 컨테이너',fill='#E9F2FC',fg=BLUE,fs=19)
# API + processing boundary
bx=462;by=307;bw=1226;bh=680
a.rect(bx,by,bw,bh,'#FFFFFF','#94B7D2',3,23)
a.rect(bx,by,bw,62,NAVY,NAVY,1,21)
a.text(493,348,'FastAPI 백엔드 컨테이너  |  Python · LangGraph · SQLAlchemy',29,WHITE,True)
a.rect(498,405,1152,100,'#EDF5FD',BLUE,2.2,13)
a.text(526,450,'REST API · 권한 / 사건 접근 제어',29,NAVY,True)
a.text(526,487,'/api/v1  |  상담 POST → BackgroundTasks  |  상태 GET 폴링  |  Trace ID',21,MUTED)
# internal modules
modules=[(498,'증거 파이프라인',['파일·문자 추출','LLM 사실 후보 → HITL'],BLUE),
         (793,'법률 상담 LangGraph',['14개 노드 · 30개 Edge','법령 검색 · 생성 · 검증'],PURPLE),
         (1088,'대응계획 엔진',['조치 생성 · 기한 계산','사건·법률 근거 이용'],CYAN),
         (1383,'문서 작성 LangGraph',['맥락→요건→생성','검증→저장 · 개정'],PURPLE)]
for x,title,details,col in modules:a.node(x,548,267,164,title,details,col,fill='#FBFDFF',fs=24)
# internal crosscuts
for x in [631,926,1221,1516]:a.line([(x,506),(x,544)],BLUE,2.5)
a.rect(498,758,1152,180,'#F0F6FA','#C4D7E5',2,13)
a.text(531,805,'실행 공통 기반',28,NAVY,True)
a.rect(533,825,326,88,WHITE,'#CADAE5',1.3,11)
a.text(552,857,'LLM Gateway',24,PURPLE,True)
a.text(552,889,'Token Tracking · Trace',19,MUTED)
a.rect(875,825,335,88,WHITE,'#CADAE5',1.3,11)
a.text(894,857,'PostgreSQL Checkpointer',21,PURPLE,True)
a.text(894,889,'LangGraph 상태 / HITL 복구',19,MUTED)
a.rect(1227,825,390,88,WHITE,'#CADAE5',1.3,11)
a.text(1246,857,'Graph Sync Worker',23,TEAL,True)
a.text(1246,889,'GraphSyncTask 폴링 → Neo4j',19,MUTED)
# endpoints and protocol paths
# browser -> API
a.line([(410,455),(492,455)],BLUE,4)
a.pill(417,399,76,34,'REST',fill=WHITE,fg=BLUE,fs=16)
# external boundary
ex=1745
a.rect(ex,307,599,680,'#FAFCFF','#A9BBCD',3,21)
a.rect(ex,307,599,62,'#314B64','#314B64',1,20)
a.text(1782,349,'외부·분리형 연동 서비스',30,WHITE,True)
externals=[('Azure OpenAI','HTTPS  |  채팅 LLM · 임베딩',PURPLE),
           ('국가법령정보 공동활용','HTTP(S)  |  법령·판례 원문',TEAL),
           ('Langfuse  (별도 서비스)','Trace · Token · 지연시간',BLUE)]
for i,(title,desc,col) in enumerate(externals):
    y=405+i*169
    a.rect(1778,y,530,142,WHITE,col,2.2,15)
    a.text(1806,y+49,title,30,NAVY,True)
    a.text(1806,y+95,desc,22,MUTED)
for y,col,label in [(475,PURPLE,'LLM'),(645,TEAL,'법령'),(815,BLUE,'Trace')]:
    a.line([(1688,y),(1773,y)],col,3.5,dashed=(label=='Trace'))
# data row beneath backend
stores=[(58,370,'PostgreSQL 17',['사건·증거·승인 사실','상담 기록·체크포인트'],BLUE),
        (445,370,'Neo4j 5.23',['사건 지식그래프','Bolt :7687'],TEAL),
        (832,370,'ChromaDB',['법령 벡터 인덱스','HTTP :8000'],PURPLE),
        (1219,370,'증거 파일 저장소',['원문·첨부파일','/app/storage'],AMBER)]
a.text(67,1050,'지속 저장 계층 · Compose 서비스 및 마운트 볼륨',26,NAVY,True)
for x,w,title,info,col in stores:
    a.rect(x,1080,w,164,WHITE,col,2.3,16)
    a.text(x+19,1128,title,27,NAVY,True)
    a.multi(x+19,1169,info,20,MUTED,32)
# accurate connectors to storage zone; row positions some go out-of-bound? top y1080, backend y987
for xx in [660,975,1540]:a.line([(xx,988),(xx,1069)],BLUE,2.5,arrow=False,opacity=.65)
a.line([(670,1065),(244,1065),(244,1076)],BLUE,2.5)
a.line([(1385,989),(1385,1057),(1002,1057),(1002,1076)],PURPLE,2.5)
a.line([(1516,913),(1516,1044),(632,1044),(632,1076)],TEAL,2.7,dashed=True)
a.pill(707,1005,345,38,'PostgreSQL → Neo4j 비동기 동기화',WHITE,TEAL,fs=17)
a.text(1762,1038,'외부 시스템은 이 Compose에 포함되지 않을 수 있음',20,MUTED)
a.save('02_전체시스템_아키텍처.svg')

# ---------------------------------------------------------------------------
# 03: Detailed LangGraph topology. Main+subflows with conditional destination
#     matrix, visually distinct from business journey and deployment diagram.
# ---------------------------------------------------------------------------
a=Art(3,'LangGraph · 법률 상담 상세 실행 흐름',
      'main의 build_legal_graph() : 활성 노드 14개 · 조건부 분기점 6곳 · Edge 30개 (START/END 포함).',
      '근거: backend/src/ai_legal_helper/workflows/legal_workflow.py · build_legal_graph() / 분기 함수')
# zones
a.rect(55,277,2290,313,'#F4F9FE','#CADAE9',2.5,22)
a.text(80,316,'A   정상 상담 경로 · 좌 → 우',29,BLUE,True)
# main nodes widths total approx 2080
main=[(78,128,'START','',TEAL),(251,276,'supervisor_initialize','사건·대화 상태 초기화',BLUE),
      (571,178,'route','법률 분야 분기',BLUE),(794,240,'run_agents','RAG · 전문 처리',BLUE),
      (1077,224,'synthesize','초안 작성',PURPLE),(1344,238,'verification','근거·시점 검증',PURPLE),
      (1760,215,'finalize','답변 안전 확정',BLUE),(2063,209,'END','',TEAL)]
for x,w,name,desc,col in main:
    if name in ['START','END']:a.pill(x,380,w,78,name,fill='#E9F8F3',fg=TEAL,fs=29)
    else:a.node(x,366,w,106,name,[desc],col,fill=WHITE,fs=27 if len(name)<20 else 23)
for x1,x2 in [(206,250),(527,570),(749,793),(1034,1076),(1301,1343),(1582,1759),(1976,2062)]:
    a.line([(x1,420),(x2,420)],BLUE,4.1)
a.pill(1588,362,163,43,'PASS → 확정',fill='#E5F7F0',fg=TEAL,fs=17)
# first exit panel
# x to fit 3 exit processes
A_y=640
a.rect(55,613,758,351,'#FBFCFF','#D1DEEA',2,19)
a.text(79,655,'B   초기 분기 · 별도 종료',28,BLUE,True)
for yy,n,short in [(678,'general_conversation','일반 안내'),(771,'evidence_unavailable','증거 원문 부족'),(864,'routing_exit','요청 종료')]:
    a.node(90,yy,432,73,n,[],BLUE,WHITE,fs=24)
    a.pill(562,yy+16,175,42,'→ END',fill='#E8F5F1',fg=TEAL,fs=19)
a.text(87,944,'supervisor_initialize → 일반/증거부족/종료/route',18,MUTED)
# middle law search zone
sx=846
a.rect(sx,613,1050,560,'#F9F7FD','#D9CCE9',2.3,20)
a.text(sx+28,655,'C   HITL 검색 · 보강 · 재검증',28,PURPLE,True)
# nodes with logical main flow
sp=[(875,705,312,'statute_search_approval','사용자 검색 승인',TEAL),
    (1237,705,326,'execute_statute_search','공식 법령·판례 검색',TEAL),
    (1605,705,265,'re_analyze','추가 근거 반영',PURPLE),
    (1605,838,265,'revise','답변 수정',PURPLE)]
for x,y,w,name,desc,col in sp:a.node(x,y,w,107,name,[desc],col,WHITE,fs=23)
a.line([(1188,761),(1232,761)],TEAL,4)
a.line([(1564,757),(1599,757)],PURPLE,3.5)
a.text(900,849,'approval 거절 → insufficient',22,AMBER,True)
a.text(900,889,'검색 결과에 따라 목적지 선택',22,MUTED)
a.pill(891,926,300,44,'run_agents / re_analyze',fill=WHITE,fg=PURPLE,fs=18)
a.pill(1211,926,306,44,'revise / finalize*',fill=WHITE,fg=PURPLE,fs=18)
a.pill(1539,926,326,44,'insufficient (근거 부족)',fill=WHITE,fg=AMBER,fs=18)
a.line([(1365,812),(1365,922)],TEAL,3)
a.line([(1733,813),(1733,835)],PURPLE,3)
a.line([(1731,946),(1731,984),(1375,984),(1375,1142)],PURPLE,3,dashed=True)
a.pill(1173,1044,548,52,'re_analyze / revise → verification 재진입',fill='#E9E2F6',fg=PURPLE,fs=21)
a.line([(1377,1073),(1377,1133)],PURPLE,3,dashed=True)
a.pill(913,1108,618,43,'* finalize 직접 연결은 문서 상담의 무진전 검색 조건에서만',fill='#FFF3DC',fg=AMBER,fs=19)
# footer finalization block
fx=1930
a.rect(fx,613,413,560,'#FFFCF7','#E7D1AE',2.2,21)
a.text(fx+26,655,'D   결과 분기',29,AMBER,True)
a.node(fx+20,702,368,100,'finalize',['검증된 답변 유지'],BLUE,WHITE,fs=27)
a.node(fx+20,826,368,100,'insufficient',['판단 유보 · 보완 안내'],AMBER,WHITE,fs=27)
a.pill(fx+74,965,264,52,'END',fill='#E9F8F3',fg=TEAL,fs=26)
a.line([(fx+196,804),(fx+196,820)],BLUE,0.01,arrow=False,opacity=0.0)
a.line([(fx+196,802),(fx+196,954)],TEAL,2.7,dashed=True,arrow=False)
a.line([(fx+196,927),(fx+196,955)],AMBER,3.2)
a.text(fx+25,1075,'조건부 검색·재작성 실패도',20,MUTED)
a.text(fx+25,1105,'근거 부족으로 종료 가능',20,MUTED)
# rule matrix below zone base, source: conditional branches 6
mx=68;my=1191
a.text(mx,my+34,'조건부 Edge 목적지: ',24,NAVY,True)
a.text(mx+235,my+34,'초기화 4 / 분야분기 2 / 초안 3 / 검증 5 / 검색승인 2 / 검색결과 5 = 총 21개',21,MUTED)
a.text(mx,my+75,'그 외 단일 연결 9개 포함 총 30개.  종료로 연결되는 END 표시는 동일 종료 노드를 가독성 위해 반복 표기.',18,MUTED)
a.save('03_LangGraph_상담처리흐름도.svg')

# Generate pdf/png (vector PDF retains text as selectable glyphs under CairoSVG)
paths=[]
for n in ('01_사용자경험_서비스개념도','02_전체시스템_아키텍처','03_LangGraph_상담처리흐름도'):
    svg=OUT/f'{n}.svg'; pdf=OUT/f'{n}.pdf'; png=OUT/f'{n}.png'
    cairosvg.svg2pdf(url=str(svg),write_to=str(pdf),output_width=W,output_height=H)
    cairosvg.svg2png(url=str(svg),write_to=str(png),output_width=W,output_height=H)
    paths.append(pdf)
combined=fitz.open()
for path in paths:
    p=fitz.open(path);combined.insert_pdf(p);p.close()
combined.save(OUT/'AI_Legal_Helper_기술아키텍처_상세3장.pdf',garbage=4,deflate=True)
combined.close()
print('Complete:',[(p.name,p.stat().st_size) for p in OUT.iterdir() if p.suffix in ['.png','.svg','.pdf']])