import React, { useState, useEffect } from 'react';
import { type LegalAction, getActionPlan, createActionPlan } from '../api/actionClient';

interface Props {
  caseId: string;
}

export const ActionPlanSection: React.FC<Props> = ({ caseId }) => {
  const [actions, setActions] = useState<LegalAction[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchActions = async () => {
    try {
      setLoading(true);
      const data = await getActionPlan(caseId);
      setActions(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load action plan');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await createActionPlan(caseId);
      setActions(data);
    } catch (err: any) {
      setError(err.message || 'Failed to generate action plan');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchActions();
  }, [caseId]);

  if (loading) return <div>Action Plan 로딩 중...</div>;
  if (error) return <div style={{ color: 'red' }}>Error: {error}</div>;

  return (
    <div className="box" style={{ marginTop: '20px', border: '2px solid #0056b3' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3>대응 행동 계획 (Action Plan)</h3>
        <button onClick={handleGenerate} style={{ backgroundColor: '#0056b3', color: 'white' }}>
          Action Plan AI 생성/재평가
        </button>
      </div>
      
      {actions.length === 0 ? (
        <p>아직 생성된 Action Plan이 없습니다.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
          {actions.map((action) => (
            <div key={action.id} style={{ border: '1px solid #ccc', padding: '10px', borderRadius: '5px' }}>
              <h4>{action.title} <span style={{ fontSize: '0.8em', color: '#666' }}>({action.priority} Priority)</span></h4>
              <p><strong>위험도:</strong> {action.risk_level} | <strong>상태:</strong> {action.status}</p>
              <p><strong>설명:</strong> {action.description}</p>
              <p><strong>추천 이유:</strong> {action.rationale}</p>
              
              {action.deadlines.length > 0 && (
                <div style={{ marginTop: '10px', backgroundColor: '#fff3cd', padding: '8px' }}>
                  <strong>기한 정보:</strong>
                  <ul>
                    {action.deadlines.map(dl => (
                      <li key={dl.id}>
                        {dl.deadline_type}: {dl.deadline_date ? new Date(dl.deadline_date).toLocaleDateString() : '미정'}
                        <br/><small>{dl.calculation_basis}</small>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              
              {action.requirements.length > 0 && (
                <div style={{ marginTop: '10px' }}>
                  <strong>필요 요건:</strong>
                  <ul>
                    {action.requirements.map(req => (
                      <li key={req.id}>
                        [{req.satisfaction_status}] {req.description} ({req.requirement_type})
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

