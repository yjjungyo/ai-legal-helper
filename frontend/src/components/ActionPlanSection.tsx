/**
 * @fileoverview 법률 대응 행동 계획(Action Plan) 관리 섹션 컴포넌트
 * 사건의 현재 단계, 증거, 사실관계를 종합하여 단계별 법률 조치, 기한(시효),
 * 사전 필수 요건을 AI 기반으로 생성·추적하고, 요건 충족 체크 및 연관 서면 초안 생성을 지원합니다.
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  type LegalAction,
  getActionPlan,
  createActionPlan,
  updateActionStatus,
  updateRequirementStatus,
} from '../api/actionClient';
import { createDocument } from '../api/documentClient';

interface Props {
  /** 사건 식별자 UUID */
  caseId: string;
}

/**
 * 대응 행동 계획(Action Plan) 컴포넌트
 */
export const ActionPlanSection: React.FC<Props> = ({ caseId }) => {
  const navigate = useNavigate();
  const [actions, setActions] = useState<LegalAction[]>([]);
  const [loading, setLoading] = useState(false);
  const [creatingDocForActionId, setCreatingDocForActionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  /**
   * 등록된 대응 계획 목록 조회
   */
  const fetchActions = async () => {
    try {
      setLoading(true);
      const data = await getActionPlan(caseId);
      setActions(data);
    } catch (err: any) {
      setError(err.message || '대응 계획을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  /**
   * AI 에이전트를 통한 행동 계획 자동 수립 및 재평가 (EVT-025)
   */
  const handleGenerate = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await createActionPlan(caseId);
      setActions(data);
    } catch (err: any) {
      setError(err.message || '대응 계획 생성에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  /**
   * 대응 조치 진행 상태(PENDING <-> COMPLETED) 토글
   */
  const handleToggleActionStatus = async (action: LegalAction) => {
    const nextStatus = action.status === 'COMPLETED' ? 'PENDING' : 'COMPLETED';
    try {
      const updated = await updateActionStatus(caseId, action.id, nextStatus);
      setActions((prev) => prev.map((a) => (a.id === action.id ? updated : a)));
    } catch (err: any) {
      alert(err.message || '조치 상태 변경에 실패했습니다.');
    }
  };

  /**
   * 사전 필요 요건 충족 상태(SATISFIED <-> UNSATISFIED) 토글
   */
  const handleToggleRequirement = async (actionId: string, reqId: string, currentStatus: string) => {
    const nextStatus = currentStatus === 'SATISFIED' ? 'UNSATISFIED' : 'SATISFIED';
    try {
      const updatedReq = await updateRequirementStatus(caseId, actionId, reqId, nextStatus);
      setActions((prev) =>
        prev.map((a) =>
          a.id === actionId
            ? {
                ...a,
                requirements: a.requirements.map((r) => (r.id === reqId ? updatedReq : r)),
              }
            : a,
        ),
      );
    } catch (err: any) {
      alert(err.message || '요건 상태 변경에 실패했습니다.');
    }
  };

  /**
   * 해당 대응 조치(action_id)와 연결된 법률 서면 초안을 즉시 생성하고 문서 작성실로 이동
   */
  const handleCreateLinkedDocument = async (action: LegalAction) => {
    try {
      setCreatingDocForActionId(action.id);
      await createDocument(caseId, {
        document_type: action.title,
        title: `${action.title} 서면 초안`,
        action_id: action.id,
      });
      navigate('../documents');
    } catch (err: any) {
      alert(err.message || '연관 법률 서면 생성에 실패했습니다.');
    } finally {
      setCreatingDocForActionId(null);
    }
  };

  useEffect(() => {
    fetchActions();
  }, [caseId]);

  /**
   * 우선순위에 따른 배지 색상 지정
   */
  const getPriorityBadge = (priority: string) => {
    switch (priority?.toUpperCase()) {
      case 'HIGH':
        return <span className="badge badge-red">긴급 (HIGH)</span>;
      case 'MEDIUM':
        return <span className="badge badge-amber">보통 (MEDIUM)</span>;
      default:
        return <span className="badge badge-blue">{priority || 'LOW'}</span>;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* 1. 상단 타이틀 및 액션 버튼 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '1.4em', fontWeight: 700, margin: '0 0 4px 0' }}>📋 법률 대응 행동 계획 (Action Plan)</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.88em' }}>
            사건 분석 결과를 바탕으로 권장되는 법률 조치, 법정 기한 및 필요 서류 요건을 관리합니다.
          </p>
        </div>
        <button
          onClick={handleGenerate}
          disabled={loading}
          className="btn btn-primary"
        >
          {loading ? 'AI 분석 및 계획 수립 중...' : '⚡ Action Plan AI 자동 생성/재평가'}
        </button>
      </div>

      {/* 2. 에러 알림 */}
      {error && (
        <div style={{ padding: '14px 18px', backgroundColor: 'var(--danger-bg)', color: 'var(--danger)', borderRadius: 'var(--radius-md)', border: '1px solid var(--danger-border)', fontSize: '0.9em' }}>
          ⚠️ 오류: {error}
        </div>
      )}

      {/* 3. 로딩 상태 */}
      {loading && actions.length === 0 && (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          대응 계획 데이터를 불러오는 중입니다...
        </div>
      )}

      {/* 4. 빈 상태 */}
      {!loading && actions.length === 0 && (
        <div className="card empty-state">
          <div style={{ fontSize: '2.5em', marginBottom: '12px' }}>📝</div>
          <h3 style={{ fontSize: '1.15em', fontWeight: 600, marginBottom: '8px' }}>수립된 대응 계획이 없습니다</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9em', marginBottom: '20px' }}>
            우측 상단의 "Action Plan AI 자동 생성/재평가" 버튼을 눌러 사건에 맞는 맞춤형 조치 계획을 생성해보세요.
          </p>
          <button onClick={handleGenerate} className="btn btn-primary">
            ⚡ 첫 대응 계획 생성하기
          </button>
        </div>
      )}

      {/* 5. 대응 계획 카드 목록 */}
      {!loading && actions.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {actions.map((action) => {
            const isCompleted = action.status === 'COMPLETED';
            return (
              <div key={action.id} className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {getPriorityBadge(action.priority)}
                    <h3
                      style={{
                        fontSize: '1.1em',
                        fontWeight: 700,
                        margin: 0,
                        color: 'var(--text-main)',
                        textDecoration: isCompleted ? 'line-through' : 'none',
                      }}
                    >
                      {action.title}
                    </h3>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className={isCompleted ? 'badge badge-green' : 'badge badge-gray'}>
                      상태: {action.status}
                    </span>
                    <button
                      onClick={() => handleToggleActionStatus(action)}
                      className={isCompleted ? 'btn btn-outline btn-sm' : 'btn btn-secondary btn-sm'}
                    >
                      {isCompleted ? '↩ 진행대기로 변경' : '✓ 완료 처리'}
                    </button>
                    <button
                      onClick={() => handleCreateLinkedDocument(action)}
                      disabled={creatingDocForActionId === action.id}
                      className="btn btn-primary btn-sm"
                    >
                      {creatingDocForActionId === action.id ? '작성 중...' : '📄 관련 서면 초안 생성'}
                    </button>
                  </div>
                </div>

                <p style={{ color: 'var(--text-secondary)', fontSize: '0.92em', lineHeight: 1.5, marginBottom: '12px' }}>
                  {action.description}
                </p>

                {action.rationale && (
                  <div style={{ padding: '10px 14px', backgroundColor: 'var(--surface-alt)', borderRadius: 'var(--radius-md)', fontSize: '0.88em', marginBottom: '14px' }}>
                    <strong style={{ color: 'var(--primary)' }}>💡 추천 이유: </strong>
                    <span style={{ color: 'var(--text-secondary)' }}>{action.rationale}</span>
                  </div>
                )}

                {/* 기한 정보 */}
                {action.deadlines && action.deadlines.length > 0 && (
                  <div style={{ padding: '12px 14px', backgroundColor: 'var(--warning-bg)', border: '1px solid var(--warning-border)', borderRadius: 'var(--radius-md)', marginBottom: '12px' }}>
                    <strong style={{ color: 'var(--warning)', fontSize: '0.9em', display: 'block', marginBottom: '6px' }}>
                      ⏰ 법정·권장 기한 정보
                    </strong>
                    <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.85em', color: 'var(--text-secondary)' }}>
                      {action.deadlines.map((dl) => (
                        <li key={dl.id} style={{ marginBottom: '4px' }}>
                          <strong>{dl.deadline_type}</strong>: {dl.deadline_date ? new Date(dl.deadline_date).toLocaleDateString() : '미정'}
                          {dl.calculation_basis && <span style={{ color: 'var(--text-muted)', marginLeft: '6px' }}>({dl.calculation_basis})</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* 필요 요건 (클릭 시 충족 상태 토글) */}
                {action.requirements && action.requirements.length > 0 && (
                  <div style={{ borderTop: '1px solid var(--border)', paddingTop: '12px' }}>
                    <strong style={{ fontSize: '0.88em', color: 'var(--text-main)', display: 'block', marginBottom: '8px' }}>
                      📋 사전 필요 요건 및 서류 (클릭하여 준비 완료 체크)
                    </strong>
                    <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.85em', color: 'var(--text-secondary)', listStyle: 'none' }}>
                      {action.requirements.map((req) => {
                        const isSatisfied = req.satisfaction_status === 'SATISFIED';
                        return (
                          <li
                            key={req.id}
                            onClick={() => handleToggleRequirement(action.id, req.id, req.satisfaction_status)}
                            style={{
                              marginBottom: '6px',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '8px',
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={isSatisfied}
                              onChange={() => {}}
                              style={{ cursor: 'pointer' }}
                            />
                            <span
                              className={isSatisfied ? 'badge badge-green' : 'badge badge-amber'}
                              style={{ fontSize: '0.75em' }}
                            >
                              {isSatisfied ? '충족 (SATISFIED)' : req.satisfaction_status}
                            </span>
                            <span style={{ textDecoration: isSatisfied ? 'line-through' : 'none' }}>
                              {req.description}
                            </span>
                            <span style={{ color: 'var(--text-muted)' }}>({req.requirement_type})</span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

