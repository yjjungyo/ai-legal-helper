import { useState } from 'react';
import { useConsultation } from '../hooks/useConsultation';
import { addStatement } from '../api/caseClient';
import type { ConsultationResponse } from '../types/consultation';

interface ChatSectionProps {
  caseId: string;
}

/**
 * 사건 작업 공간 내 AI 법률 상담 컴포넌트.
 *
 * 주요 기능:
 * 1. 사건 문맥(Fact, Evidence) 기반 AI 법률 상담 질문 전송 및 상태 추적.
 * 2. 상담 결과 및 대화 이력의 데이터베이스 영구 저장 및 자동 로드.
 * 3. 상담 내용(질문)을 사건의 공식 사실관계(진술)로 1클릭 등록하는 기능 제공.
 */
export function ChatSection({ caseId }: ChatSectionProps) {
  const { question, setQuestion, history, loadHistory, submit, result, loading, error } = useConsultation(caseId);
  const [registering, setRegistering] = useState<string | null>(null);

  const handleRegisterAsFact = async (stmt?: string) => {
    if (!stmt) return;
    try {
      setRegistering(stmt);
      await addStatement(caseId, stmt);
      alert("✅ 사건의 사실관계 및 타임라인에 성공적으로 등록되었습니다!\n'사실 & 타임라인' 탭에서 확인하실 수 있습니다.");
    } catch (err) {
      alert("사실관계 등록 중 오류가 발생했습니다: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setRegistering(null);
    }
  };

  return (
    <div className="chat-view" style={{ maxWidth: '900px', margin: '0 auto' }}>
      <div style={{ marginBottom: '20px', padding: '15px', backgroundColor: '#f0f7ff', borderRadius: '8px', border: '1px solid #cce3ff' }}>
        <h3 style={{ margin: '0 0 8px 0', color: '#0056b3' }}>💬 AI 법률 상담 (사건 문맥 적용)</h3>
        <p style={{ margin: 0, fontSize: '14px', color: '#495057' }}>
          질문이나 상황을 입력하시면 AI가 사건의 사실관계와 증거를 기반으로 분석 답변을 제공합니다.<br />
          <strong>모든 상담 내역은 자동으로 데이터베이스에 영구 저장</strong>되며, 상담 내용을 사건의 공식 <strong>사실관계(진술)</strong>로도 등록할 수 있습니다.
        </p>
      </div>

      <div className="input-section" style={{ marginBottom: '25px', padding: '15px', backgroundColor: '#fff', borderRadius: '8px', border: '1px solid #ddd' }}>
        <textarea 
          placeholder="상담할 질문이나 새로운 상황을 상세히 입력하세요 (예: 집주인이 보증금 반환을 거부하는데 어떻게 해야 하나요?)"
          value={question}
          onChange={e => setQuestion(e.target.value)}
          rows={4}
          disabled={loading}
          style={{ width: '100%', boxSizing: 'border-box', padding: '10px', fontSize: '15px', borderRadius: '6px', border: '1px solid #ccc' }}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '10px' }}>
          <button 
            onClick={submit} 
            disabled={loading || !question.trim()}
            style={{ 
              padding: '10px 24px', 
              fontSize: '15px', 
              fontWeight: 'bold', 
              backgroundColor: loading ? '#ccc' : '#1976d2', 
              color: '#fff', 
              border: 'none', 
              borderRadius: '6px', 
              cursor: loading ? 'not-allowed' : 'pointer' 
            }}
          >
            {loading ? '⏳ AI 분석 및 상담 중...' : '🚀 상담 시작'}
          </button>
        </div>
      </div>

      {loading && (
        <div style={{ padding: '15px', marginBottom: '20px', backgroundColor: '#fff9db', borderRadius: '6px', border: '1px solid #ffe066', textAlign: 'center' }}>
          <strong>🔄 법률 전문가 Agent가 분석 및 검증을 진행 중입니다...</strong>
          <p style={{ margin: '5px 0 0 0', fontSize: '13px', color: '#666' }}>약 10~15초 정도 소요될 수 있습니다. 완료 시 아래 이력에 자동으로 저장됩니다.</p>
        </div>
      )}

      {error && (
        <div className="error" style={{ padding: '12px', marginBottom: '20px', backgroundColor: '#ffe3e3', color: '#c92a2a', borderRadius: '6px', border: '1px solid #ffc9c9' }}>
          ⚠️ 오류 발생: {error}
        </div>
      )}

      {/* 실시간 단일 상담 결과 (진행 중이거나 방금 완료된 경우) */}
      {result && result.status === 'IN_PROGRESS' && (
        <div style={{ padding: '15px', marginBottom: '20px', backgroundColor: '#f8f9fa', borderRadius: '8px', border: '1px dashed #ced4da' }}>
          <h4>진행 중인 상담 (요청 ID: {result.request_id})</h4>
          <p>분석 및 법률 근거 대조 중입니다...</p>
        </div>
      )}

      {/* 영구 저장된 상담 이력 목록 */}
      <div className="history-section" style={{ marginTop: '30px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px', borderBottom: '2px solid #eee', paddingBottom: '8px' }}>
          <h3 style={{ margin: 0 }}>📋 저장된 상담 이력 ({history.length}건)</h3>
          <button onClick={loadHistory} style={{ padding: '4px 10px', fontSize: '13px', cursor: 'pointer' }}>새로고침</button>
        </div>

        {history.length === 0 && !loading && (
          <div style={{ padding: '30px', textAlign: 'center', color: '#888', backgroundColor: '#fafafa', borderRadius: '8px', border: '1px solid #eee' }}>
            아직 이 사건에 저장된 상담 내역이 없습니다.<br />위 입력창에 질문을 작성하여 첫 상담을 시작해 보세요!
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {history.map((item: ConsultationResponse) => (
            <div 
              key={item.request_id} 
              style={{ 
                padding: '18px', 
                backgroundColor: '#ffffff', 
                borderRadius: '8px', 
                border: '1px solid #e0e0e0',
                boxShadow: '0 2px 5px rgba(0,0,0,0.05)'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px', borderBottom: '1px solid #f0f0f0', paddingBottom: '8px' }}>
                <div style={{ flex: 1 }}>
                  <span style={{ fontSize: '12px', color: '#888', marginRight: '10px' }}>
                    {item.created_at ? new Date(item.created_at).toLocaleString() : '상담 기록'}
                  </span>
                  <span style={{ 
                    fontSize: '12px', 
                    fontWeight: 'bold', 
                    padding: '2px 8px', 
                    borderRadius: '4px',
                    backgroundColor: item.status === 'SUCCESS' ? '#e6fcf5' : item.status === 'ERROR' ? '#ffe3e3' : '#fff3bf',
                    color: item.status === 'SUCCESS' ? '#0ca678' : item.status === 'ERROR' ? '#f03e3e' : '#f59f00'
                  }}>
                    {item.status === 'SUCCESS' ? '답변 완료' : item.status === 'ERROR' ? '오류' : '처리 중'}
                  </span>
                </div>

                {item.question && (
                  <button
                    onClick={() => handleRegisterAsFact(item.question)}
                    disabled={registering === item.question}
                    style={{
                      padding: '4px 10px',
                      fontSize: '12px',
                      backgroundColor: '#2b8a3e',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer'
                    }}
                  >
                    {registering === item.question ? '등록 중...' : '📌 사건 사실관계(진술)로 등록'}
                  </button>
                )}
              </div>

              {item.question && (
                <div style={{ marginBottom: '12px', padding: '10px 12px', backgroundColor: '#f8f9fa', borderRadius: '6px' }}>
                  <strong style={{ color: '#333' }}>👤 질문: </strong>
                  <span style={{ whiteSpace: 'pre-wrap', color: '#212529' }}>{item.question}</span>
                </div>
              )}

              {item.answer ? (
                <div style={{ padding: '12px', backgroundColor: '#f1f8ff', borderRadius: '6px', borderLeft: '4px solid #1976d2' }}>
                  <strong style={{ color: '#1976d2' }}>🤖 AI 법률 답변:</strong>
                  <div style={{ whiteSpace: 'pre-wrap', marginTop: '8px', lineHeight: '1.6', color: '#333' }}>
                    {item.answer}
                  </div>
                </div>
              ) : (
                item.status === 'IN_PROGRESS' && <p style={{ color: '#888' }}>답변을 생성하는 중입니다...</p>
              )}

              {item.sources && item.sources.length > 0 && (
                <div style={{ marginTop: '12px', fontSize: '13px', color: '#555' }}>
                  <strong>📚 참고 법률 출처:</strong>
                  <ul style={{ margin: '5px 0 0 20px', padding: 0 }}>
                    {item.sources.map((s, idx) => (
                      <li key={idx}>{s.file} (p.{s.page})</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
