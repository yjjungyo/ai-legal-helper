import { useEffect, useState } from 'react';
import { useParams, useNavigate, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import { getCaseDetail, addStatement } from '../api/caseClient';
import type { CaseDetail } from '../types/case';

import { ChatSection } from '../components/ChatSection';
import { EvidenceSection } from '../components/EvidenceSection';
import { EvidenceGraph } from '../components/EvidenceGraph';
import { ActionPlanSection } from '../components/ActionPlanSection';
import { DocumentSection } from '../components/DocumentSection';

export function CaseWorkspace() {
  const { caseId } = useParams<{ caseId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [activeCase, setActiveCase] = useState<CaseDetail | null>(null);

  useEffect(() => {
    if (caseId) {
      loadCase(caseId);
    }
  }, [caseId]);

  const loadCase = async (id: string) => {
    try {
      const detail = await getCaseDetail(id);
      setActiveCase(detail);
    } catch (e) {
      alert("사건 조회 실패");
      navigate('/');
    }
  };

  const handleAddStatement = async () => {
    if (!activeCase) return;
    const stmt = prompt("사건에 추가할 사실이나 진술을 입력하세요:");
    if (!stmt) return;
    try {
      const detail = await addStatement(activeCase.id, stmt);
      setActiveCase(detail);
    } catch (e) {
      alert("진술 추가 실패");
    }
  };

  if (!activeCase) return <div>Loading workspace...</div>;

  const tabs = [
    { id: 'overview', label: '개요 (Overview)' },
    { id: 'chat', label: '상담 (Chat)' },
    { id: 'facts', label: '사실 & 타임라인 (Facts)' },
    { id: 'evidence', label: '증거 관리 (Evidence)' },
    { id: 'graph', label: '증거 그래프 (Graph)' },
    { id: 'action', label: '대응 계획 (Action Plan)' },
    { id: 'docs', label: '문서 (Documents)' },
  ];

  const currentTab = location.pathname.split('/').pop();

  return (
    <div className="workspace">
      <div className="workspace-header">
        <button onClick={() => navigate('/')}>&larr; 목록으로</button>
        <h2>사건 작업 공간: {activeCase.title}</h2>
        <span className="case-statusBadge">상태: {activeCase.status}</span>
        <button onClick={handleAddStatement} style={{marginLeft: 'auto'}}>새 진술 추가</button>
      </div>

      <div className="workspace-nav">
        {tabs.map(tab => (
          <Link 
            key={tab.id} 
            to={`/${activeCase.id}/workspace/${tab.id}`}
            className={`nav-tab ${currentTab === tab.id ? 'active' : ''}`}
          >
            {tab.label}
          </Link>
        ))}
      </div>

      <div className="workspace-content">
        <Routes>
          <Route path="overview" element={<OverviewTab activeCase={activeCase} />} />
          <Route path="chat" element={<ChatSection caseId={activeCase.id} />} />
          <Route path="facts" element={<FactsTab activeCase={activeCase} />} />
          <Route path="evidence" element={<EvidenceSection caseId={activeCase.id} onRefreshCase={() => loadCase(activeCase.id)} />} />
          <Route path="graph" element={<EvidenceGraph caseId={activeCase.id} />} />
          <Route path="action" element={<ActionPlanSection caseId={activeCase.id} />} />
          <Route path="docs" element={<DocumentSection caseId={activeCase.id} />} />
          <Route path="*" element={<Navigate to="overview" replace />} />
        </Routes>
      </div>
    </div>
  );
}

function OverviewTab({ activeCase }: { activeCase: CaseDetail }) {
  return (
    <div className="tab-pane">
      <h3>사건 개요</h3>
      <p>유형: {activeCase.case_type}</p>
      <p>업데이트: {new Date(activeCase.updated_at).toLocaleString()}</p>
      <p>현재 단계 및 다음 추천 행동(준비중)</p>
    </div>
  );
}

function FactsTab({ activeCase }: { activeCase: CaseDetail }) {
  return (
    <div className="tab-pane detail-sections">
      <div className="box">
        <h3>당사자 (Parties)</h3>
        <ul>
          {activeCase.parties.map(p => (
            <li key={p.id}>{p.name} ({p.role}) - {p.party_relationship}</li>
          ))}
        </ul>
      </div>
      
      <div className="box">
        <h3>사실관계 (Facts)</h3>
        <ul>
          {activeCase.facts.map(f => (
            <li key={f.id}>[{f.fact_type}] {f.statement} (신뢰도: {f.confidence})</li>
          ))}
        </ul>
      </div>
      
      <div className="box">
        <h3>타임라인 (Events)</h3>
        <ul>
          {activeCase.events.map(e => (
            <li key={e.id}><strong>{e.event_date || '미상'}</strong>: {e.title}</li>
          ))}
        </ul>
      </div>
      
      <div className="box">
        <h3>법률 쟁점 (Legal Issues)</h3>
        <ul>
          {activeCase.legal_issues.map(l => (
            <li key={l.id}>{l.title} - {l.description}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

