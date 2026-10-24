/**
 * @fileoverview 사건별 메인 워크스페이스(Workspace) 페이지
 * 좌측 사이드바(사건 정보, 네비게이션 탭, 빠른 진술 추가)와
 * 우측 메인 캔버스(종합 개요, AI 상담, 사실/타임라인, 증거 관리, 그래프, 대응 계획, 문서 작성)로 구성된
 * 2단 모던 B2B SaaS 레이아웃을 제공합니다.
 */

import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom';
import { getCaseDetail, addStatement, updateCase, getWorkflowSummary } from '../api/caseClient';
import type { CaseDetail, WorkflowSummary } from '../types/case';

import { ChatSection } from '../components/ChatSection';
import { EvidenceSection, getClaimTypeLabel, getClaimTypeBadgeClass } from '../components/EvidenceSection';
import { EvidenceGraph } from '../components/EvidenceGraph';
import { ActionPlanSection } from '../components/ActionPlanSection';
import { DocumentSection } from '../components/DocumentSection';

/**
 * 사건 기본 정보 수정 모달 인터페이스 (EVT-006)
 */
interface EditCaseModalProps {
  /** 모달 오픈 여부 */
  isOpen: boolean;
  /** 현재 사건 상세 데이터 */
  activeCase: CaseDetail;
  /** 닫기 콜백 */
  onClose: () => void;
  /** 수정 완료 시 상태 갱신 콜백 */
  onSuccess: (updatedCase: CaseDetail) => void;
}

/**
 * 사건 제목·유형·설명·진행 상태를 수정하는 모달 컴포넌트 (EVT-006)
 */
function EditCaseModal({ isOpen, activeCase, onClose, onSuccess }: EditCaseModalProps) {
  const [title, setTitle] = useState(activeCase.title);
  const [caseType, setCaseType] = useState(activeCase.case_type || '주택임대차');
  const [description, setDescription] = useState(activeCase.description || '');
  const [status, setStatus] = useState(activeCase.status || 'IN_PROGRESS');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    if (isOpen) {
      setTitle(activeCase.title);
      setCaseType(activeCase.case_type || '주택임대차');
      setDescription(activeCase.description || '');
      setStatus(activeCase.status || 'IN_PROGRESS');
      setErrorMsg('');
    }
  }, [isOpen, activeCase]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setErrorMsg('사건 제목을 입력해주세요.');
      return;
    }
    try {
      setIsSubmitting(true);
      setErrorMsg('');
      const updated = await updateCase(activeCase.id, {
        title: title.trim(),
        case_type: caseType.trim(),
        description: description.trim(),
        status,
      });
      onSuccess(updated);
      onClose();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : '사건 수정 중 오류가 발생했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 style={{ fontSize: '1.1em', fontWeight: 700, margin: 0 }}>사건 기본 정보 수정</h3>
          <button
            type="button"
            onClick={onClose}
            style={{ background: 'none', border: 'none', fontSize: '1.2em', cursor: 'pointer', color: 'var(--text-muted)' }}
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {errorMsg && (
              <div style={{ padding: '8px 12px', backgroundColor: 'var(--danger-bg)', color: 'var(--danger)', borderRadius: '6px', fontSize: '0.85em' }}>
                {errorMsg}
              </div>
            )}

            <div className="form-group">
              <label htmlFor="edit-case-title">사건 제목 *</label>
              <input
                id="edit-case-title"
                type="text"
                className="form-control"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="edit-case-type">사건 유형</label>
              <select
                id="edit-case-type"
                className="form-control"
                value={caseType}
                onChange={(e) => setCaseType(e.target.value)}
              >
                <option value="주택임대차">주택임대차</option>
                <option value="상가임대차">상가임대차</option>
                <option value="민사">민사</option>
                <option value="노동">노동</option>
                <option value="소비자">소비자</option>
                <option value="회사">회사</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="edit-case-status">진행 상태</label>
              <select
                id="edit-case-status"
                className="form-control"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="IN_PROGRESS">IN_PROGRESS (진행중)</option>
                <option value="REVIEW_REQUIRED">REVIEW_REQUIRED (검토필요)</option>
                <option value="CLOSED">CLOSED (종결)</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="edit-case-desc">사건 설명</label>
              <textarea
                id="edit-case-desc"
                className="form-control"
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={isSubmitting}>
              취소
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? '저장 중...' : '변경사항 저장'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/**
 * 신규 사실 및 진술 추가 인라인 모달 인터페이스
 */
interface AddStatementModalProps {
  /** 모달 오픈 여부 */
  isOpen: boolean;
  /** 사건 식별자 */
  caseId: string;
  /** 닫기 콜백 */
  onClose: () => void;
  /** 성공 시 사건 상세 정보 갱신 콜백 */
  onSuccess: (updatedCase: CaseDetail) => void;
}

/**
 * 사실/진술 추가 인라인 모달 컴포넌트
 * 기존 브라우저 기본 prompt()를 모던 다이얼로그로 대체합니다.
 */
function AddStatementModal({ isOpen, caseId, onClose, onSuccess }: AddStatementModalProps) {
  const [statement, setStatement] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!statement.trim()) {
      setErrorMsg('진술 또는 사실 내용을 입력해주세요.');
      return;
    }

    try {
      setIsSubmitting(true);
      setErrorMsg('');
      const updated = await addStatement(caseId, statement.trim());
      setStatement('');
      onSuccess(updated);
      onClose();
    } catch (err) {
      console.error('진술 추가 오류:', err);
      setErrorMsg('진술 추가 중 오류가 발생했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 style={{ fontSize: '1.1em', fontWeight: 700, margin: 0 }}>새 사실 / 진술 추가</h3>
          <button 
            type="button" 
            onClick={onClose} 
            style={{ background: 'none', border: 'none', fontSize: '1.2em', cursor: 'pointer', color: 'var(--text-muted)' }}
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {errorMsg && (
              <div style={{ padding: '8px 12px', backgroundColor: 'var(--danger-bg)', color: 'var(--danger)', borderRadius: '6px', fontSize: '0.85em', marginBottom: '14px' }}>
                {errorMsg}
              </div>
            )}

            <div className="form-group">
              <label htmlFor="stmt-text">사실관계 또는 진술 내용 *</label>
              <textarea
                id="stmt-text"
                className="form-control"
                rows={5}
                placeholder="예: 2023년 12월 1일 임대인에게 보증금 반환 내용증명을 발송하였으나 폐문부재로 반송됨."
                value={statement}
                onChange={(e) => setStatement(e.target.value)}
                autoFocus
              />
            </div>
            <p style={{ fontSize: '0.82em', color: 'var(--text-muted)' }}>
              입력된 진술은 사건의 사실관계(Facts) 및 AI 분석 파이프라인에 즉시 반영됩니다.
            </p>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={isSubmitting}>
              취소
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? '추가 중...' : '진술 등록'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/**
 * 사건 워크스페이스 최상위 컴포넌트
 */
export function CaseWorkspace() {
  const { caseId } = useParams<{ caseId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [activeCase, setActiveCase] = useState<CaseDetail | null>(null);
  const [isAddStmtOpen, setIsAddStmtOpen] = useState(false);
  const [isEditCaseOpen, setIsEditCaseOpen] = useState(false);

  const currentTab = location.pathname.split('/').pop() || 'overview';

  useEffect(() => {
    if (caseId && (!activeCase || activeCase.id !== caseId || currentTab === 'facts' || currentTab === 'overview')) {
      loadCase(caseId);
    }
  }, [caseId, currentTab]);

  /**
   * 사건 상세 데이터 조회
   * @param id 사건 ID
   */
  const loadCase = async (id: string) => {
    try {
      const detail = await getCaseDetail(id);
      setActiveCase(detail);
    } catch (e) {
      console.error('사건 조회 실패:', e);
      alert('사건을 불러올 수 없습니다.');
      navigate('/');
    }
  };

  if (!activeCase) {
    return (
      <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-muted)' }}>
        사건 워크스페이스를 불러오는 중입니다...
      </div>
    );
  }

  /**
   * 7대 핵심 워크스페이스 네비게이션 탭 구성
   */
  const tabs = [
    { id: 'overview', icon: '📊', label: '개요 (Overview)' },
    { id: 'chat', icon: '💬', label: 'AI 법률 상담 (Chat)' },
    { id: 'facts', icon: '⚖️', label: '사실 및 타임라인 (Facts)' },
    { id: 'evidence', icon: '📁', label: '증거 관리 (Evidence)' },
    { id: 'graph', icon: '🕸️', label: '증거 지식그래프 (Graph)' },
    { id: 'action', icon: '📋', label: '대응 계획 (Action Plan)' },
    { id: 'docs', icon: '📄', label: '법률 문서 (Documents)' },
  ];

  return (
    <div className="workspace-wrapper">
      {/* 1. 좌측 통합 사이드바 */}
      <aside className="workspace-sidebar">
        {/* 뒤로 가기 링크 */}
        <button 
          onClick={() => navigate('/')} 
          className="btn btn-secondary btn-sm"
          style={{ width: '100%', justifyContent: 'flex-start', color: 'var(--text-secondary)' }}
        >
          &larr; 사건 목록으로
        </button>

        {/* 사건 메타데이터 프로필 카드 */}
        <div style={{ padding: '12px', backgroundColor: 'var(--surface-alt)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '6px' }}>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              <span className="badge badge-blue">{activeCase.case_type || '주택임대차'}</span>
              <span className="badge badge-green">{activeCase.status || '진행중'}</span>
            </div>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              style={{ padding: '2px 8px', fontSize: '0.75em' }}
              onClick={() => setIsEditCaseOpen(true)}
            >
              ✏️ 수정
            </button>
          </div>
          <h2 style={{ fontSize: '1.05em', fontWeight: 700, margin: 0, color: 'var(--text-main)', wordBreak: 'break-word', lineHeight: 1.35 }}>
            {activeCase.title}
          </h2>
          <div style={{ fontSize: '0.78em', color: 'var(--text-muted)', marginTop: '6px' }}>
            ID: <span style={{ fontFamily: 'var(--font-mono)' }}>{activeCase.id.slice(0, 8)}...</span>
          </div>
        </div>

        {/* 네비게이션 메뉴 섹션 */}
        <div className="workspace-sidebar-section" style={{ flex: 1 }}>
          <div className="workspace-sidebar-title">Workspace Menu</div>
          {tabs.map((tab) => {
            const isActive = currentTab === tab.id;
            return (
              <Link
                key={tab.id}
                to={`/${activeCase.id}/workspace/${tab.id}`}
                className={`workspace-nav-item ${isActive ? 'active' : ''}`}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>{tab.icon}</span>
                  <span>{tab.label}</span>
                </span>
                {isActive && <span style={{ fontSize: '0.8em' }}>●</span>}
              </Link>
            );
          })}
        </div>

        {/* 사이드바 하단 빠른 액션 버튼 */}
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: '14px' }}>
          <button 
            className="btn btn-outline" 
            style={{ width: '100%', fontSize: '0.88em' }}
            onClick={() => setIsAddStmtOpen(true)}
          >
            ＋ 새 사실(Fact) 추가
          </button>
        </div>
      </aside>

      {/* 2. 우측 메인 캔버스 영역 (Chat 탭일 경우 풀블리드 전용 스타일 적용) */}
      <main className={`workspace-canvas ${currentTab === 'chat' ? 'workspace-canvas-chat' : ''}`}>
        <Routes>
          <Route
            path="overview"
            element={
              <OverviewTab
                activeCase={activeCase}
                onTabChange={(tabId) => navigate(`/${activeCase.id}/workspace/${tabId}`)}
              />
            }
          />
          <Route path="chat" element={<ChatSection caseId={activeCase.id} />} />
          <Route path="facts" element={<FactsTab activeCase={activeCase} />} />
          <Route
            path="evidence"
            element={<EvidenceSection caseId={activeCase.id} onRefreshCase={() => loadCase(activeCase.id)} />}
          />
          <Route path="graph" element={<EvidenceGraph caseId={activeCase.id} />} />
          <Route path="action" element={<ActionPlanSection caseId={activeCase.id} />} />
          <Route path="docs" element={<DocumentSection caseId={activeCase.id} />} />
          <Route path="*" element={<Navigate to="overview" replace />} />
        </Routes>
      </main>

      {/* 새 사실/진술 추가 인라인 모달 */}
      <AddStatementModal
        isOpen={isAddStmtOpen}
        caseId={activeCase.id}
        onClose={() => setIsAddStmtOpen(false)}
        onSuccess={(updated) => setActiveCase(updated)}
      />

      {/* 사건 기본 정보 수정 모달 (EVT-006) */}
      <EditCaseModal
        isOpen={isEditCaseOpen}
        activeCase={activeCase}
        onClose={() => setIsEditCaseOpen(false)}
        onSuccess={(updated) => setActiveCase(updated)}
      />
    </div>
  );
}

/**
 * 사건 종합 개요 (Overview) 대시보드 컴포넌트
 */
function OverviewTab({ activeCase, onTabChange }: { activeCase: CaseDetail; onTabChange: (tabId: string) => void }) {
  const [summary, setSummary] = useState<WorkflowSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadSummary();
  }, [activeCase.id, activeCase.updated_at]);

  /**
   * 워크플로우 통합 요약 데이터 로드
   */
  const loadSummary = async () => {
    try {
      setLoading(true);
      const data = await getWorkflowSummary(activeCase.id);
      setSummary(data);
    } catch (e) {
      console.error('워크플로우 요약 로딩 실패:', e);
    } finally {
      setLoading(false);
    }
  };

  const stages = [
    { code: 'CASE_CREATED', label: '1. 사건 접수' },
    { code: 'EVIDENCE_IN_REVIEW', label: '2. 증거·사실 검토' },
    { code: 'ANALYSIS_COMPLETED', label: '3. AI 법률 분석' },
    { code: 'ACTION_PLAN_READY', label: '4. 대응 계획' },
    { code: 'DOCUMENT_DRAFTED', label: '5. 문서 작성' },
  ];

  const getStageIndex = (code: string) => {
    switch (code) {
      case 'CASE_CREATED': return 0;
      case 'FACTS_IN_REVIEW':
      case 'EVIDENCE_IN_REVIEW': return 1;
      case 'READY_FOR_ANALYSIS':
      case 'ANALYSIS_COMPLETED': return 2;
      case 'ACTION_PLAN_READY': return 3;
      case 'DOCUMENT_DRAFTED': return 4;
      default: return 0;
    }
  };

  const currentIdx = summary ? getStageIndex(summary.stage_code) : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* 1. 상단 기본 정보 및 새로고침 헤더 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '1.4em', fontWeight: 700, margin: '0 0 4px 0' }}>사건 종합 대시보드 (Overview)</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.88em' }}>
            사건 유형: <strong style={{ color: 'var(--primary)' }}>{activeCase.case_type || '일반'}</strong> | 
            최근 업데이트: {new Date(activeCase.updated_at).toLocaleString()}
          </p>
        </div>
        <button onClick={loadSummary} className="btn btn-secondary btn-sm">
          🔄 새로고침
        </button>
      </div>

      {loading && !summary && (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          개요 정보를 집계하고 있습니다...
        </div>
      )}

      {summary && (
        <>
          {/* 2. 워크플로우 진행 단계 5-Step 인디케이터 */}
          <div className="card" style={{ padding: '16px' }}>
            <div style={{ fontSize: '0.88em', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '12px' }}>
              워크플로우 진행 상태: <span style={{ color: 'var(--primary)', fontSize: '1.05em' }}>{summary.stage_name}</span>
            </div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {stages.map((st, idx) => {
                const isPast = idx < currentIdx;
                const isCurrent = idx === currentIdx;
                return (
                  <div
                    key={st.code}
                    style={{
                      flex: 1,
                      minWidth: '120px',
                      padding: '10px 8px',
                      borderRadius: 'var(--radius-md)',
                      textAlign: 'center',
                      fontSize: '0.85em',
                      fontWeight: isCurrent ? 700 : 500,
                      backgroundColor: isCurrent ? 'var(--primary)' : isPast ? 'var(--primary-light)' : 'var(--surface-alt)',
                      color: isCurrent ? '#ffffff' : isPast ? 'var(--primary)' : 'var(--text-muted)',
                      border: isCurrent ? '1.5px solid var(--primary-hover)' : isPast ? '1px solid var(--primary-border)' : '1px solid var(--border)',
                      transition: 'all 0.2s ease',
                    }}
                  >
                    {isPast ? '✓ ' : ''}{st.label}
                  </div>
                );
              })}
            </div>
          </div>

          {/* 3. 다음 권장 조치 (Next Action) 배너 */}
          <div
            style={{
              backgroundColor: 'var(--primary-light)',
              border: '1.5px solid var(--primary-border)',
              borderRadius: 'var(--radius-lg)',
              padding: '16px 20px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              boxShadow: 'var(--shadow-xs)',
            }}
          >
            <div>
              <div style={{ fontSize: '0.8em', color: 'var(--primary-hover)', fontWeight: 700, marginBottom: '3px' }}>
                📌 다음 권장 액션 (Recommended Step)
              </div>
              <div style={{ fontSize: '1.1em', fontWeight: 700, color: 'var(--text-main)', marginBottom: '4px' }}>
                {summary.next_action.title}
              </div>
              <div style={{ fontSize: '0.88em', color: 'var(--text-secondary)' }}>
                {summary.next_action.description}
              </div>
            </div>
            <button
              onClick={() => onTabChange(summary.next_action.tab_id)}
              className="btn btn-primary"
              style={{ whiteSpace: 'nowrap', marginLeft: '16px' }}
            >
              해당 단계로 이동 &rarr;
            </button>
          </div>

          {/* 4. 영역별 종합 요약 카드 4분할 그리드 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
            {/* 4-1. 상담 현황 */}
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <strong style={{ fontSize: '0.95em', color: 'var(--text-main)' }}>💬 AI 법률 상담</strong>
                <span className="badge badge-blue">총 {summary.stats.consultations_count}회</span>
              </div>
              {summary.consultation_preview ? (
                <div style={{ fontSize: '0.85em', color: 'var(--text-secondary)', backgroundColor: 'var(--surface-alt)', padding: '10px', borderRadius: 'var(--radius-md)', marginBottom: '14px' }}>
                  <div style={{ fontWeight: 600, color: 'var(--primary)', marginBottom: '4px' }}>
                    Q: {summary.consultation_preview.last_question}
                  </div>
                  <div style={{ color: 'var(--text-muted)', lineHeight: '1.4' }}>
                    A: {summary.consultation_preview.last_answer_snippet}
                  </div>
                </div>
              ) : (
                <p style={{ fontSize: '0.85em', color: 'var(--text-muted)', margin: '14px 0' }}>진행된 상담 내역이 없습니다.</p>
              )}
              <button onClick={() => onTabChange('chat')} className="btn btn-secondary" style={{ width: '100%' }}>
                상담 이어하기 &rarr;
              </button>
            </div>

            {/* 4-2. 증거 및 사실관계 */}
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <strong style={{ fontSize: '0.95em', color: 'var(--text-main)' }}>📁 증거 및 사실관계</strong>
                <span className="badge badge-blue">증거 {summary.stats.evidences_count}건</span>
              </div>
              <div style={{ fontSize: '0.88em', margin: '10px 0', lineHeight: '1.7' }}>
                <div>• 확정 사실(Fact): <strong>{summary.stats.facts_count}건</strong></div>
                <div>• 검토 대기 주장: <strong style={{ color: summary.stats.claims_pending_count > 0 ? 'var(--warning)' : 'inherit' }}>{summary.stats.claims_pending_count}건</strong></div>
                <div>• 증거 상충(모순): <strong style={{ color: summary.stats.conflicts_count > 0 ? 'var(--danger)' : 'inherit' }}>{summary.stats.conflicts_count}건</strong></div>
              </div>
              {summary.recent_evidences.length > 0 && (
                <div style={{ fontSize: '0.8em', color: 'var(--text-muted)', borderTop: '1px dashed var(--border)', paddingTop: '8px', marginBottom: '12px' }}>
                  최근 등록: {summary.recent_evidences[0].filename} ({summary.recent_evidences[0].status})
                </div>
              )}
              <button onClick={() => onTabChange('evidence')} className="btn btn-secondary" style={{ width: '100%' }}>
                증거 관리 & 검토 &rarr;
              </button>
            </div>

            {/* 4-3. 법률 쟁점 및 타임라인 */}
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <strong style={{ fontSize: '0.95em', color: 'var(--text-main)' }}>⚖️ 쟁점 및 타임라인</strong>
                <span className="badge badge-blue">쟁점 {summary.stats.issues_count}건</span>
              </div>
              <div style={{ fontSize: '0.88em', margin: '10px 0' }}>
                {summary.issues_preview.length > 0 ? (
                  <ul style={{ margin: '6px 0', paddingLeft: '18px', color: 'var(--text-secondary)' }}>
                    {summary.issues_preview.map((iss) => (
                      <li key={iss.id} style={{ margin: '3px 0' }}>{iss.title}</li>
                    ))}
                  </ul>
                ) : (
                  <p style={{ color: 'var(--text-muted)', margin: '8px 0', fontSize: '0.85em' }}>도출된 법률 쟁점이 없습니다.</p>
                )}
                <div style={{ fontSize: '0.82em', color: 'var(--text-muted)', marginTop: '8px' }}>
                  • 타임라인 일정: <strong>{summary.stats.events_count}건</strong> | 당사자: <strong>{summary.stats.parties_count}명</strong>
                </div>
              </div>
              <button onClick={() => onTabChange('facts')} className="btn btn-secondary" style={{ width: '100%' }}>
                사실 & 타임라인 상세 &rarr;
              </button>
            </div>

            {/* 4-4. 대응 계획 및 문서 작성 */}
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <strong style={{ fontSize: '0.95em', color: 'var(--text-main)' }}>📋 대응 계획 & 법률 문서</strong>
                <span className="badge badge-blue">조치 {summary.stats.actions_count}건</span>
              </div>
              <div style={{ fontSize: '0.88em', margin: '10px 0' }}>
                {summary.recent_actions.length > 0 ? (
                  <ul style={{ margin: '6px 0', paddingLeft: '18px', color: 'var(--text-secondary)' }}>
                    {summary.recent_actions.map((act) => (
                      <li key={act.id} style={{ margin: '3px 0' }}>
                        <span style={{ color: act.priority === 'HIGH' ? 'var(--danger)' : 'var(--primary)', fontWeight: 600 }}>
                          [{act.action_type || act.priority}]
                        </span>{' '}
                        {act.title}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p style={{ color: 'var(--text-muted)', margin: '8px 0', fontSize: '0.85em' }}>수립된 대응 계획이 없습니다.</p>
                )}
                <div style={{ fontSize: '0.82em', color: 'var(--text-muted)', marginTop: '8px' }}>
                  • 작성된 법률 문서: <strong>{summary.stats.documents_count}건</strong>
                </div>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={() => onTabChange('action')} className="btn btn-secondary" style={{ flex: 1 }}>
                  대응 계획 &rarr;
                </button>
                <button onClick={() => onTabChange('docs')} className="btn btn-secondary" style={{ flex: 1 }}>
                  문서함 &rarr;
                </button>
              </div>
            </div>
          </div>

          {/* 5. 최근 활동 타임라인 피드 */}
          {summary.recent_activities.length > 0 && (
            <div className="card">
              <h4 style={{ margin: '0 0 12px 0', fontSize: '0.98em', fontWeight: 700, color: 'var(--text-main)' }}>
                🕒 최근 사건 활동 내역
              </h4>
              <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.88em', color: 'var(--text-secondary)' }}>
                {summary.recent_activities.map((act, i) => (
                  <li key={i} style={{ marginBottom: '8px' }}>
                    <span style={{ color: 'var(--text-muted)', marginRight: '8px' }}>
                      {act.time ? new Date(act.time).toLocaleDateString() : ''}
                    </span>
                    <strong
                      style={{ cursor: 'pointer', color: 'var(--primary)', textDecoration: 'underline' }}
                      onClick={() => onTabChange(act.tab_id)}
                    >
                      {act.title}
                    </strong>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/**
 * 사실관계 및 타임라인 탭 컴포넌트
 * 당사자, 사실관계, 타임라인 이벤트, 법률 쟁점을 2x2 카드 그리드로 시각화합니다.
 */
function FactsTab({ activeCase }: { activeCase: CaseDetail }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div>
        <h2 style={{ fontSize: '1.4em', fontWeight: 700, margin: '0 0 4px 0' }}>사실관계 및 사건 정보 (Facts & Timeline)</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.88em' }}>
          확정된 사실, 당사자 관계, 시간순 사건 흐름 및 법률적 쟁점을 종합적으로 정리합니다.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
        {/* 당사자 정보 */}
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h3 style={{ fontSize: '1.05em', fontWeight: 700, margin: 0 }}>👥 당사자 (Parties)</h3>
            <span className="badge badge-blue">{activeCase.parties.length}명</span>
          </div>
          {activeCase.parties.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.88em' }}>등록된 당사자 정보가 없습니다.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.9em', color: 'var(--text-main)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {activeCase.parties.map((p) => (
                <li key={p.id}>
                  <div>
                    <strong>{p.name}</strong>
                    {p.role && <span className="badge badge-gray" style={{ marginLeft: '6px' }}>{p.role}</span>}
                    {p.party_relationship && (
                      <span style={{ color: 'var(--text-secondary)', fontSize: '0.85em', marginLeft: '6px' }}>
                        ({p.party_relationship})
                      </span>
                    )}
                  </div>
                  {p.notes && (
                    <div style={{ fontSize: '0.8em', color: 'var(--text-muted)', marginTop: '2px' }}>
                      {p.notes}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* 확정 사실관계 */}
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h3 style={{ fontSize: '1.05em', fontWeight: 700, margin: 0 }}>📌 확정 사실 (Facts)</h3>
            <span className="badge badge-blue">{activeCase.facts.length}건</span>
          </div>
          {activeCase.facts.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.88em' }}>등록된 사실 정보가 없습니다.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.9em', color: 'var(--text-main)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {activeCase.facts.map((f) => {
                const factLabel = getClaimTypeLabel(f.fact_type);
                const factBadge = getClaimTypeBadgeClass(factLabel);
                return (
                  <li key={f.id}>
                    <span className={`badge ${factBadge}`} style={{ fontSize: '0.75em', marginRight: '6px' }}>{factLabel}</span>
                    <span>{f.statement}</span>
                    <span style={{ fontSize: '0.75em', color: 'var(--text-muted)', marginLeft: '6px' }}>신뢰도: {f.confidence}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* 타임라인 이벤트 */}
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h3 style={{ fontSize: '1.05em', fontWeight: 700, margin: 0 }}>📅 타임라인 (Timeline)</h3>
            <span className="badge badge-blue">{activeCase.events.length}건</span>
          </div>
          {activeCase.events.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.88em' }}>등록된 시간순 일정이 없습니다.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.9em', color: 'var(--text-main)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {activeCase.events.map((e) => {
                const occLabel =
                  e.occurrence_status === 'SCHEDULED'
                    ? '예정/기일'
                    : e.occurrence_status === 'REQUESTED'
                      ? '요청 기한'
                      : e.occurrence_status === 'NEEDS_VERIFICATION'
                        ? '확인 필요'
                        : '실제 발생';
                const occBadge =
                  e.occurrence_status === 'SCHEDULED'
                    ? 'badge-blue'
                    : e.occurrence_status === 'REQUESTED'
                      ? 'badge-orange'
                      : e.occurrence_status === 'NEEDS_VERIFICATION'
                        ? 'badge-red'
                        : 'badge-green';
                return (
                  <li key={e.id}>
                    <span style={{ fontWeight: 600, color: 'var(--primary)', marginRight: '6px' }}>
                      {e.event_date || '일자 미상'}
                    </span>
                    {e.event_type && (
                      <span className="badge badge-gray" style={{ fontSize: '0.75em', marginRight: '5px' }}>
                        {e.event_type}
                      </span>
                    )}
                    <span className={`badge ${occBadge}`} style={{ fontSize: '0.72em', marginRight: '6px' }}>
                      {occLabel}
                    </span>
                    <span>{e.title}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* 법률 쟁점 */}
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h3 style={{ fontSize: '1.05em', fontWeight: 700, margin: 0 }}>⚖️ 법률 쟁점 (Legal Issues)</h3>
            <span className="badge badge-blue">{activeCase.legal_issues.length}건</span>
          </div>
          {activeCase.legal_issues.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.88em' }}>도출된 법률 쟁점이 없습니다.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.9em', color: 'var(--text-main)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {activeCase.legal_issues.map((l) => (
                <li key={l.id}>
                  <strong style={{ color: 'var(--text-main)' }}>{l.title}</strong>
                  {l.description && <div style={{ fontSize: '0.85em', color: 'var(--text-secondary)', marginTop: '2px' }}>{l.description}</div>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
