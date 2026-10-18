/**
 * @fileoverview 사건 문맥 기반 AI 법률 상담 섹션 컴포넌트
 * 사건의 확정 사실(Facts)과 증거 문맥을 자동 반영하여 법률 질의응답을 수행하며,
 * 상담 내역 데이터베이스 영구 저장 및 질문의 사건 사실관계(Fact) 1-클릭 등록을 지원합니다.
 */

import { useState } from 'react';
import { useConsultation } from '../hooks/useConsultation';
import { addStatement } from '../api/caseClient';
import type { ConsultationResponse } from '../types/consultation';
import { LegalAnswerView } from './LegalAnswerView';

interface ChatSectionProps {
  /** 사건 식별자 UUID */
  caseId: string;
}

/**
 * 상담 결과 상태(실행 상태, 검증 상태, 답변 상태)에 따른 일관된 배지 렌더링 함수 (P2-03)
 * @param item 상담 응답 객체
 * @returns 상태에 부합하는 배지 JSX
 */
function renderStatusBadge(item: ConsultationResponse) {
  if (item.status === 'ERROR') {
    return <span className="badge badge-red">오류</span>;
  }
  if (item.status === 'APPROVAL_REQUIRED') {
    return <span className="badge badge-blue">승인 대기</span>;
  }
  if (item.status === 'IN_PROGRESS') {
    return (
      <span
        className="badge"
        style={{
          backgroundColor: '#eff6ff',
          color: '#1d4ed8',
          border: '1px solid #bfdbfe',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '5px',
          fontWeight: 600,
        }}
      >
        <span
          className="spinner"
          style={{
            width: '10px',
            height: '10px',
            borderWidth: '2px',
            borderColor: '#93c5fd',
            borderTopColor: '#1d4ed8',
          }}
        />
        법령 조회 및 재분석 중
      </span>
    );
  }

  // item.status === 'SUCCESS'인 경우 세부 answer_status 및 verification_status 판별
  if (item.answer_status === 'WITHHELD' || item.verification_status === 'FAIL') {
    return (
      <span
        className="badge"
        style={{
          backgroundColor: '#fffbeb',
          color: '#b45309',
          border: '1px solid #fef3c7',
          fontWeight: 600,
        }}
      >
        🛡️ 판단 유보 (근거 부족)
      </span>
    );
  }
  if (item.answer_status === 'CAUTIONARY' || item.verification_status === 'REVISE') {
    return (
      <span
        className="badge"
        style={{
          backgroundColor: '#f3e8ff',
          color: '#7e22ce',
          border: '1px solid #e9d5ff',
          fontWeight: 600,
        }}
      >
        ⚠️ 주의 안내 포함
      </span>
    );
  }
  if (item.verification_status === 'PASS' || item.answer_status === 'DELIVERED') {
    return (
      <span className="badge badge-green">
        ✓ 검증 완료 (답변)
      </span>
    );
  }

  return <span className="badge badge-green">답변 완료</span>;
}

/**
 * 사건 작업 공간 내 AI 법률 상담 컴포넌트
 */
export function ChatSection({ caseId }: ChatSectionProps) {
  const {
    question,
    setQuestion,
    history,
    loadHistory,
    submit,
    respondApproval,
    result,
    loading,
    error,
  } = useConsultation(caseId);
  const [registering, setRegistering] = useState<string | null>(null);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  // 클릭하여 펼쳐진 출처 상세(청크 본문 및 표준 메타데이터) 키 상태
  const [expandedSourceKey, setExpandedSourceKey] = useState<string | null>(null);
  // 요청별 AI 추론 및 근거 검증 인스펙터(Tier 2) 열림 상태
  const [expandedInspectorKeys, setExpandedInspectorKeys] = useState<Record<string, boolean>>({});

  /**
   * 출처 항목 클릭 시 원문 청크 및 상세 메타데이터 패널 토글
   */
  const toggleSourceDetail = (key: string) => {
    setExpandedSourceKey((prev) => (prev === key ? null : key));
  };

  /**
   * AI 추론 및 근거 검증 인스펙터(Tier 2) 패널 토글
   */
  const toggleInspector = (requestId: string) => {
    setExpandedInspectorKeys((prev) => ({
      ...prev,
      [requestId]: !prev[requestId],
    }));
  };

  /**
   * HILT 법령 원문 검색 승인/거절 처리
   */
  const handleApprovalDecision = async (requestId: string, approved: boolean) => {
    try {
      await respondApproval(requestId, approved);
      setNotification({
        type: 'success',
        message: approved
          ? '공식 법령 원문 검색을 승인하였습니다. 최신 조문을 조회하여 재분석을 진행합니다.'
          : '법령 검색을 거절하였습니다. 현재 근거를 바탕으로 판단을 유보하고 상담을 종료합니다.',
      });
      setTimeout(() => setNotification(null), 5000);
    } catch (err) {
      setNotification({
        type: 'error',
        message: '승인 처리 중 오류가 발생했습니다: ' + (err instanceof Error ? err.message : String(err)),
      });
      setTimeout(() => setNotification(null), 5000);
    }
  };

  /**
   * 상담 질문 내용을 사건의 공식 사실관계(진술)로 등록
   * @param stmt 등록할 진술 내용
   */
  const handleRegisterAsFact = async (stmt?: string) => {
    if (!stmt) return;
    try {
      setRegistering(stmt);
      await addStatement(caseId, stmt);
      setNotification({
        type: 'success',
        message: '사건의 사실관계(Facts) 및 타임라인에 등록되었습니다. \'사실 및 타임라인\' 탭에서 확인하실 수 있습니다.',
      });
      setTimeout(() => setNotification(null), 4000);
    } catch (err) {
      setNotification({
        type: 'error',
        message: '사실관계 등록 중 오류가 발생했습니다: ' + (err instanceof Error ? err.message : String(err)),
      });
      setTimeout(() => setNotification(null), 5000);
    } finally {
      setRegistering(null);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* 1. 상단 안내 헤더 */}
      <div>
        <h2 style={{ fontSize: '1.4em', fontWeight: 700, margin: '0 0 4px 0' }}>💬 AI 법률 상담 (Chat)</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.88em' }}>
          사건의 사실관계와 등록된 증거를 바탕으로 전문 법률 분석 및 조언을 제공합니다.
        </p>
      </div>

      {/* 2. 상태 알림 메시지 (토스트 배너) */}
      {notification && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            backgroundColor: notification.type === 'success' ? 'var(--success-bg)' : 'var(--danger-bg)',
            color: notification.type === 'success' ? 'var(--success)' : 'var(--danger)',
            border: `1px solid ${notification.type === 'success' ? 'var(--success-border)' : 'var(--danger-border)'}`,
            fontSize: '0.9em',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span>{notification.type === 'success' ? '✓ ' : '⚠️ '}{notification.message}</span>
          <button
            onClick={() => setNotification(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontWeight: 'bold' }}
          >
            ✕
          </button>
        </div>
      )}

      {/* 3. 질문 입력 카드 */}
      <div className="card">
        <textarea
          placeholder="법률 상담 질문이나 새로운 분쟁 상황을 입력하세요 (예: 임대차 계약이 만료되었는데 임대인이 보증금을 돌려주지 않습니다. 내용증명 발송과 임차권등기명령 절차가 어떻게 되나요?)"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={4}
          disabled={loading}
          className="form-control"
          style={{ resize: 'vertical', lineHeight: 1.5 }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '12px' }}>
          <span style={{ fontSize: '0.82em', color: 'var(--text-muted)' }}>
            💡 상담 내역은 데이터베이스에 안전하게 영구 보존됩니다.
          </span>
          <button
            onClick={submit}
            disabled={loading || !question.trim()}
            className="btn btn-primary"
          >
            {loading ? 'AI 분석 및 상담 진행 중...' : '🚀 상담 요청하기'}
          </button>
        </div>
      </div>

      {/* 4. 분석 진행 중 인디케이터 */}
      {loading && (
        <div
          style={{
            padding: '16px 20px',
            backgroundColor: 'var(--warning-bg)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--warning-border)',
            textAlign: 'center',
          }}
        >
          <strong style={{ color: 'var(--warning)', display: 'block', marginBottom: '4px' }}>
            🔄 법률 전문 Agent가 사건 문맥을 검토하여 분석 중입니다...
          </strong>
          <span style={{ fontSize: '0.85em', color: 'var(--text-secondary)' }}>
            판례 및 법령 대조, 증거 관계 검증을 거쳐 답변이 생성됩니다.
          </span>
        </div>
      )}

      {/* 5. 오류 메시지 */}
      {error && (
        <div
          style={{
            padding: '14px 18px',
            backgroundColor: 'var(--danger-bg)',
            color: 'var(--danger)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--danger-border)',
            fontSize: '0.9em',
          }}
        >
          ⚠️ 상담 진행 중 오류가 발생했습니다: {error}
        </div>
      )}

      {/* 6. 실시간 요청 진행 상태 (In-progress) */}
      {result && result.status === 'IN_PROGRESS' && (
        <div className="card" style={{ borderStyle: 'dashed' }}>
          <h4 style={{ margin: '0 0 6px 0', fontSize: '0.95em' }}>진행 중인 상담 (요청 ID: {result.request_id})</h4>
          <p style={{ fontSize: '0.88em', color: 'var(--text-secondary)' }}>법률 근거 및 판례 데이터베이스를 검색 중입니다...</p>
        </div>
      )}

      {/* 6.1 실시간 HILT 승인 대기 카드 */}
      {result && result.status === 'APPROVAL_REQUIRED' && (
        <div
          style={{
            padding: '18px 22px',
            backgroundColor: '#eff6ff',
            borderRadius: 'var(--radius-md)',
            border: '2px solid #3b82f6',
            boxShadow: '0 4px 12px rgba(59, 130, 246, 0.15)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
            <span style={{ fontSize: '1.3em' }}>⚖️</span>
            <strong style={{ color: '#1e40af', fontSize: '1.05em' }}>
              공식 법령 원문 추가 검색 승인 요청 (Human-in-the-Loop)
            </strong>
            <span
              style={{
                marginLeft: 'auto',
                backgroundColor: '#dbeafe',
                color: '#1d4ed8',
                padding: '3px 8px',
                borderRadius: '4px',
                fontSize: '0.78em',
                fontWeight: 600,
              }}
            >
              사용자 결정 대기
            </span>
          </div>

          <p style={{ fontSize: '0.92em', color: '#1e293b', lineHeight: 1.6, margin: '8px 0 14px 0' }}>
            {result.approval_request?.explanation ||
              '현재 검색된 법률 자료만으로는 의뢰인의 쟁점을 검증할 수 없습니다. 국가법령정보공동활용 공식 API에서 원문 조문을 직접 검색하여 법률 재분석을 진행하시겠습니까?'}
          </p>

          <div
            style={{
              backgroundColor: '#ffffff',
              padding: '12px 16px',
              borderRadius: '6px',
              fontSize: '0.88em',
              marginBottom: '16px',
              border: '1px solid #bfdbfe',
            }}
          >
            <div style={{ marginBottom: '6px' }}>
              <strong style={{ color: '#475569' }}>확인 필요 쟁점: </strong>
              <span style={{ color: '#0f172a', fontWeight: 600 }}>
                {result.approval_request?.missing_issue || '특별법 조문 확인 필요'}
              </span>
            </div>
            {result.approval_request?.candidate_laws && result.approval_request.candidate_laws.length > 0 && (
              <div style={{ marginBottom: '6px' }}>
                <strong style={{ color: '#475569' }}>조회 후보 법령: </strong>
                <span style={{ color: '#2563eb', fontWeight: 600 }}>
                  {result.approval_request.candidate_laws.join(', ')}
                </span>
              </div>
            )}
            <div>
              <strong style={{ color: '#475569' }}>검색 출처: </strong>
              <span style={{ color: '#64748b' }}>
                {result.approval_request?.search_scope || '공식 법령 원문 (open.law.go.kr)'}
              </span>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
            <button
              onClick={() => handleApprovalDecision(result.request_id, false)}
              disabled={loading}
              className="btn btn-secondary btn-sm"
            >
              ✕ 추가 검색 없이 종료 (판단 유보)
            </button>
            <button
              onClick={() => handleApprovalDecision(result.request_id, true)}
              disabled={loading}
              className="btn btn-primary btn-sm"
              style={{ backgroundColor: '#2563eb', borderColor: '#1d4ed8', fontWeight: 600 }}
            >
              ✓ 공식 법령 검색 승인 및 재분석
            </button>
          </div>
        </div>
      )}

      {/* 7. 영구 저장된 상담 내역 목록 */}
      <div style={{ marginTop: '10px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ fontSize: '1.1em', fontWeight: 700, margin: 0 }}>
            📋 상담 이력 ({history.length}건)
          </h3>
          <button onClick={loadHistory} className="btn btn-secondary btn-sm">
            새로고침
          </button>
        </div>

        {history.length === 0 && !loading && (
          <div className="card" style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
            아직 저장된 법률 상담 내역이 없습니다.<br />위 입력창을 통해 첫 질문을 남겨보세요!
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {history.map((item: ConsultationResponse) => (
            <div key={item.request_id} className="card">
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: '12px',
                  paddingBottom: '10px',
                  borderBottom: '1px solid var(--border)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontSize: '0.82em', color: 'var(--text-muted)' }}>
                    {item.created_at ? new Date(item.created_at).toLocaleString() : '상담 기록'}
                  </span>
                  {renderStatusBadge(item)}
                </div>

                {item.question && (
                  <button
                    onClick={() => handleRegisterAsFact(item.question)}
                    disabled={registering === item.question}
                    className="btn btn-outline btn-sm"
                  >
                    {registering === item.question ? '등록 중...' : '📌 사건 사실관계(Fact)로 등록'}
                  </button>
                )}
              </div>

              {item.question && (
                <div
                  style={{
                    marginBottom: '14px',
                    padding: '12px 14px',
                    backgroundColor: 'var(--surface-alt)',
                    borderRadius: 'var(--radius-md)',
                  }}
                >
                  <strong style={{ color: 'var(--text-main)', display: 'block', marginBottom: '4px', fontSize: '0.9em' }}>
                    👤 의뢰인 질문:
                  </strong>
                  <span style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)', fontSize: '0.92em', lineHeight: 1.5 }}>
                    {item.question}
                  </span>
                </div>
              )}

              {/* 5. 공식 법령 원문 추가 검색 HILT 승인 요청 박스 */}
              {item.status === 'APPROVAL_REQUIRED' && (
                <div
                  style={{
                    padding: '16px 20px',
                    backgroundColor: '#eff6ff',
                    borderRadius: 'var(--radius-md)',
                    border: '2px solid #3b82f6',
                    marginBottom: '14px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                    <span style={{ fontSize: '1.2em' }}>⚖️</span>
                    <strong style={{ color: '#1e40af', fontSize: '1.02em' }}>
                      공식 법령 원문 추가 검색 승인 요청 (Human-in-the-Loop)
                    </strong>
                  </div>
                  <p style={{ fontSize: '0.88em', color: '#1e293b', margin: '4px 0 10px 0' }}>
                    {item.approval_request?.explanation ||
                      '현재 검색된 자료만으로는 해당 법률 쟁점을 확정할 수 없습니다. 국가법령정보공동활용 공식 API에서 원문 조문을 검색하여 재분석할 수 있습니다.'}
                  </p>
                  <div style={{ fontSize: '0.84em', color: '#475569', marginBottom: '12px' }}>
                    <div><strong>확인 필요 쟁점: </strong>{item.approval_request?.missing_issue}</div>
                    {item.approval_request?.candidate_laws && item.approval_request.candidate_laws.length > 0 && (
                      <div><strong>조회 후보 법령: </strong>{item.approval_request.candidate_laws.join(', ')}</div>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                    <button
                      onClick={() => handleApprovalDecision(item.request_id, false)}
                      disabled={loading}
                      className="btn btn-secondary btn-sm"
                    >
                      ✕ 추가 검색 없이 종료
                    </button>
                    <button
                      onClick={() => handleApprovalDecision(item.request_id, true)}
                      disabled={loading}
                      className="btn btn-primary btn-sm"
                      style={{ backgroundColor: '#2563eb', borderColor: '#1d4ed8' }}
                    >
                      ✓ 공식 법령 검색 승인 및 재분석
                    </button>
                  </div>
                </div>
              )}

              {/* 5-1. 공식 법령 검색 승인 후 AI 재분석 진행 중 실시간 안내 배너 (P2-03) */}
              {item.status === 'IN_PROGRESS' && (
                <div
                  style={{
                    padding: '16px 20px',
                    backgroundColor: '#f0fdf4',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid #bbf7d0',
                    borderLeft: '4px solid #16a34a',
                    marginBottom: '14px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                    <span style={{ fontSize: '1.2em' }}>🔄</span>
                    <strong style={{ color: '#15803d', fontSize: '0.98em' }}>
                      공식 법령 원문 검색 및 AI 재분석 진행 중입니다...
                    </strong>
                  </div>
                  <p style={{ fontSize: '0.88em', color: '#166534', margin: 0, lineHeight: 1.5 }}>
                    국가법령정보공동활용(open.law.go.kr) 공식 API에서 최신 법령 조문을 조회하여 법률검증 및 답변을 재작성하고 있습니다. (약 10~20초 소요)
                  </p>
                </div>
              )}

              {/* 6. AI 법률 분석 및 조언 본문 또는 진행 중 / 판단 유보 상태 카드 (P0-02) */}
              {item.status === 'IN_PROGRESS' ? (
                <div
                  style={{
                    padding: '28px 24px',
                    backgroundColor: 'var(--surface)',
                    borderRadius: 'var(--radius-md)',
                    border: '1px dashed var(--primary)',
                    textAlign: 'center',
                    marginBottom: '14px',
                  }}
                >
                  <div style={{ fontSize: '2em', marginBottom: '10px' }}>⚖️</div>
                  <strong style={{ display: 'block', marginBottom: '6px', color: 'var(--primary)', fontSize: '1.02em' }}>
                    법률 전문 Agent가 공식 법령을 반영하여 답변을 다시 작성하고 있습니다
                  </strong>
                  <span style={{ fontSize: '0.88em', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                    국가법령 조문 대조, 입증 요건 재검토, 법률검증 Agent의 근거 검증을 마치는 대로 완성된 법률 의견서가 즉시 표시됩니다.
                  </span>
                </div>
              ) : item.answer_status === 'WITHHELD' || item.status === 'APPROVAL_REQUIRED' ? (
                /* WITHHELD: 미검증 법률 분석 초안은 노출하지 않고 판단 유보 카드 및 보강 안내문 표시 */
                <div
                  style={{
                    padding: '20px 22px',
                    backgroundColor: '#fffbeb',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid #fef3c7',
                    borderLeft: '4px solid #d97706',
                    marginBottom: '14px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                    <span style={{ fontSize: '1.2em' }}>🛡️</span>
                    <strong style={{ color: '#b45309', fontSize: '1.02em' }}>
                      법률적 근거 부족으로 인한 판단 유보 안내
                    </strong>
                  </div>
                  <div style={{ color: '#78350f', fontSize: '0.92em', lineHeight: 1.6 }}>
                    {item.answer ? (
                      <LegalAnswerView content={item.answer} />
                    ) : (
                      <p style={{ margin: 0 }}>
                        현재 확보된 법률 조문 또는 사건 증거 자료만으로는 확정적인 법률 판단을 내릴 수 없어 의뢰인의 권리 보호를 위해 답변 제공을 안전하게 유보합니다.
                      </p>
                    )}
                  </div>
                </div>
              ) : item.answer_status === 'CAUTIONARY' ? (
                /* CAUTIONARY: 조건부 안내 및 주의 배너가 포함된 답변 */
                <div
                  style={{
                    padding: '16px 18px',
                    backgroundColor: 'var(--surface)',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid #e9d5ff',
                    borderLeft: '4px solid #9333ea',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                    marginBottom: '14px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <strong style={{ color: '#7e22ce', fontSize: '0.98em' }}>
                      ⚠️ AI 법률 분석 및 조언 (주의 및 조건부 안내 포함)
                    </strong>
                  </div>
                  {item.answer && <LegalAnswerView content={item.answer} />}
                </div>
              ) : item.answer ? (
                /* DELIVERED: 정밀 검증 통과(PASS) 답변 */
                <div
                  style={{
                    padding: '16px 18px',
                    backgroundColor: 'var(--surface)',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                    marginBottom: '14px',
                  }}
                >
                  <strong style={{ color: 'var(--primary)', display: 'block', marginBottom: '12px', fontSize: '0.98em' }}>
                    ⚖️ AI 법률 분석 및 조언
                  </strong>
                  <LegalAnswerView content={item.answer} />
                </div>
              ) : null}

              {/* 7. 답변 요약 바 및 Tier 2 인스펙터 토글 */}
              {item.status !== 'IN_PROGRESS' && item.answer_status !== 'WITHHELD' && item.answer && (
                (() => {
                  const legalSources = Array.from(
                    new Map(
                      (item.sources || [])
                        .filter((s) => s.source_type !== 'CASE_EVIDENCE')
                        .map((s) => [s.statute_name && s.article ? `${s.statute_name}_${s.article}` : `${s.source_id}_${s.file}`, s])
                    ).values()
                  );

                  const evidenceSources = Array.from(
                    new Map(
                      (item.sources || [])
                        .filter((s) => s.source_type === 'CASE_EVIDENCE')
                        .map((s) => [`${s.file}_${s.page || '1'}`, s])
                    ).values()
                  );

                  const isInspectorOpen = !!expandedInspectorKeys[item.request_id];
                  const verStatus = item.verification_result?.status;

                  const renderSourceItem = (s: typeof item.sources[0], idx: number, prefix: string) => {
                    const key = `${item.request_id}-${prefix}-${idx}`;
                    const isExpanded = expandedSourceKey === key;
                    const pageDisplay = s.page ? (s.page.startsWith('p.') ? s.page : `p.${s.page}`) : (s.page || 'p.1');
                    const typeLabel =
                      s.source_type === 'STATUTE'
                        ? '법령'
                        : s.source_type === 'PRECEDENT'
                        ? '판례'
                        : s.source_type === 'CASE_EVIDENCE'
                        ? '사건 증거'
                        : '법률 문서';
                    const badgeClass =
                      s.source_type === 'STATUTE'
                        ? 'badge-blue'
                        : s.source_type === 'PRECEDENT'
                        ? 'badge-purple'
                        : s.source_type === 'CASE_EVIDENCE'
                        ? 'badge-green'
                        : 'badge-gray';

                    return (
                      <li
                        key={key}
                        style={{
                          marginBottom: '8px',
                          padding: '8px 12px',
                          backgroundColor: 'var(--surface)',
                          borderRadius: 'var(--radius-md)',
                          border: '1px solid var(--border)',
                          listStyle: 'none',
                        }}
                      >
                        <div
                          onClick={() => toggleSourceDetail(key)}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            cursor: 'pointer',
                            gap: '8px',
                            flexWrap: 'wrap',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                            <span className={`badge ${badgeClass}`} style={{ fontSize: '0.72em' }}>
                              {typeLabel}
                            </span>
                            <strong style={{ color: 'var(--text-main)', fontSize: '0.9em' }}>
                              {s.title || s.file}
                            </strong>
                            {pageDisplay && (
                              <span style={{ color: 'var(--text-muted)', fontSize: '0.82em' }}>
                                ({pageDisplay})
                              </span>
                            )}
                            {s.article && (
                              <span style={{ color: 'var(--primary)', fontSize: '0.82em', fontWeight: 600 }}>
                                [{s.article}]
                              </span>
                            )}
                            {s.case_number && (
                              <span style={{ color: 'var(--secondary)', fontSize: '0.82em', fontWeight: 600 }}>
                                [{s.court ? `${s.court} ` : ''}{s.case_number}]
                              </span>
                            )}
                          </div>
                          <span style={{ fontSize: '0.78em', color: 'var(--primary)', userSelect: 'none' }}>
                            {isExpanded ? '▲ 접기' : '▼ 원문 청크 / 메타데이터 확인'}
                          </span>
                        </div>

                        {/* 펼쳐졌을 때: 검증된 메타데이터 및 실제 검색된 본문 청크 */}
                        {isExpanded && (
                          <div
                            style={{
                              marginTop: '10px',
                              paddingTop: '8px',
                              borderTop: '1px dashed var(--border)',
                              fontSize: '0.82em',
                              color: 'var(--text-secondary)',
                            }}
                          >
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '6px', marginBottom: '8px' }}>
                              {s.source_id && <div><strong>출처 식별자:</strong> {s.source_id}</div>}
                              {s.retrieval_method && <div><strong>검색 경로:</strong> {s.retrieval_method}</div>}
                              {s.chunk_id && <div><strong>청크 ID:</strong> {s.chunk_id}</div>}
                              {s.effective_date && <div><strong>시행일:</strong> {s.effective_date}</div>}
                              {s.decision_date && <div><strong>선고일:</strong> {s.decision_date}</div>}
                              {s.evidence_id && <div><strong>증거 ID:</strong> {s.evidence_id}</div>}
                            </div>
                            {s.content ? (
                              <div
                                style={{
                                  padding: '8px 10px',
                                  backgroundColor: 'var(--surface-alt)',
                                  borderRadius: 'var(--radius-sm)',
                                  whiteSpace: 'pre-wrap',
                                  lineHeight: 1.5,
                                  color: 'var(--text-main)',
                                }}
                              >
                                <strong>📄 실제 검색된 원문 청크:</strong>
                                <div style={{ marginTop: '4px' }}>{s.content}</div>
                              </div>
                            ) : (
                              <div style={{ color: 'var(--text-muted)' }}>본문 청크 요약이 제공되지 않았습니다.</div>
                            )}
                          </div>
                        )}
                      </li>
                    );
                  };

                  return (
                    <div style={{ marginTop: '12px' }}>
                      {/* Tier 1 요약 바: 검증 배지, 핵심 법령 뱃지, 인스펙터 토글 버튼 */}
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          flexWrap: 'wrap',
                          gap: '8px',
                          padding: '10px 14px',
                          backgroundColor: 'var(--surface-alt)',
                          borderRadius: 'var(--radius-md)',
                          border: '1px solid var(--border)',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                          <span
                            className={
                              verStatus === 'PASS'
                                ? 'badge badge-green'
                                : verStatus === 'REVISE'
                                ? 'badge badge-amber'
                                : 'badge badge-gray'
                            }
                            style={{ fontSize: '0.78em', fontWeight: 600 }}
                          >
                            🛡️ 근거 검증 {verStatus === 'PASS' ? '완료 (PASS)' : verStatus || '진행됨'}
                          </span>

                          {legalSources.slice(0, 3).map((s, sIdx) => (
                            <span key={sIdx} className="badge badge-blue" style={{ fontSize: '0.75em' }}>
                              📜 {s.statute_name || s.title} {s.article || ''}
                            </span>
                          ))}
                          {legalSources.length > 3 && (
                            <span style={{ fontSize: '0.75em', color: 'var(--text-muted)' }}>
                              외 {legalSources.length - 3}개 조문
                            </span>
                          )}

                          {evidenceSources.length > 0 && (
                            <span className="badge badge-gray" style={{ fontSize: '0.75em' }}>
                              📁 사건 증거 {evidenceSources.length}건 대조
                            </span>
                          )}
                        </div>

                        <button
                          type="button"
                          onClick={() => toggleInspector(item.request_id)}
                          className="btn btn-outline btn-sm"
                          style={{
                            fontSize: '0.8em',
                            padding: '3px 8px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            backgroundColor: isInspectorOpen ? '#eff6ff' : 'transparent',
                            borderColor: isInspectorOpen ? '#3b82f6' : 'var(--border)',
                            color: isInspectorOpen ? '#1d4ed8' : 'var(--text-secondary)',
                          }}
                        >
                          <span>🔬 AI 추론 & 검증 증빙 인스펙터</span>
                          <span>{isInspectorOpen ? '▲ 접기' : '▼ 펼치기'}</span>
                        </button>
                      </div>

                      {/* Tier 2: AI 추론 및 근거 검증 인스펙터 패널 (마스터 과제 심사 / 변호사 검토용) */}
                      {isInspectorOpen && (
                        <div
                          style={{
                            marginTop: '10px',
                            padding: '16px 18px',
                            backgroundColor: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius-md)',
                            boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '14px',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border)', paddingBottom: '8px' }}>
                            <strong style={{ color: 'var(--primary)', fontSize: '0.92em' }}>
                              🔬 AI 추론 프로세스 & 검증 감사 리포트 (Evaluation Audit)
                            </strong>
                            <span style={{ fontSize: '0.78em', color: 'var(--text-muted)' }}>
                              요청 ID: {item.request_id}
                            </span>
                          </div>

                          {/* 1. Multi-Agent & 워크플로우 실행 메타 */}
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '8px', fontSize: '0.82em', backgroundColor: 'var(--surface-alt)', padding: '10px 12px', borderRadius: '6px' }}>
                            <div>
                              <strong>실행 에이전트:</strong> {item.selected_agents && item.selected_agents.length > 0 ? item.selected_agents.join(', ') : '민법/부동산 전문 에이전트'}
                            </div>
                            <div>
                              <strong>재분석(Revision) 횟수:</strong> {item.revision_count ?? 0}회
                            </div>
                            <div>
                              <strong>공식 법령 연동(HITL):</strong> {item.approval_request ? '승인 완료 (open.law.go.kr)' : '내부 RAG'}
                            </div>
                            <div>
                              <strong>답변 상태:</strong> {item.answer_status || 'DELIVERED'}
                            </div>
                          </div>

                          {/* 2. 검증된 법령/판례 출처 (중복 제거된 고유 목록) */}
                          {legalSources.length > 0 && (
                            <div>
                              <strong style={{ display: 'block', marginBottom: '6px', fontSize: '0.85em', color: 'var(--primary)' }}>
                                ⚖️ 검증된 법령 및 판례 출처 ({legalSources.length}건 고유):
                              </strong>
                              <ul style={{ margin: 0, padding: 0 }}>
                                {legalSources.map((s, idx) => renderSourceItem(s, idx, 'legal'))}
                              </ul>
                            </div>
                          )}

                          {/* 3. 참조된 사건 증거 자료 (중복 제거된 고유 목록) */}
                          {evidenceSources.length > 0 && (
                            <div>
                              <strong style={{ display: 'block', marginBottom: '6px', fontSize: '0.85em', color: 'var(--success)' }}>
                                📁 참조된 사건 증거 자료 ({evidenceSources.length}건 고유):
                              </strong>
                              <ul style={{ margin: 0, padding: 0 }}>
                                {evidenceSources.map((s, idx) => renderSourceItem(s, idx, 'evidence'))}
                              </ul>
                            </div>
                          )}

                          {/* 4. 유의사항 및 권고사항 */}
                          {(() => {
                            let combinedWarnings = Array.from(
                              new Set([...(item.warnings || []), ...(item.verification_result?.warnings || [])])
                            );
                            if (item.status === 'SUCCESS') {
                              combinedWarnings = combinedWarnings.filter(
                                (w) => !w.includes('INSUFFICIENT 처리되었습니다')
                              );
                            }
                            if (combinedWarnings.length === 0) return null;

                            return (
                              <div
                                style={{
                                  padding: '10px 12px',
                                  backgroundColor: '#fffbeb',
                                  border: '1px solid #fef3c7',
                                  borderRadius: '6px',
                                  fontSize: '0.82em',
                                  color: '#b45309',
                                }}
                              >
                                <strong style={{ display: 'block', marginBottom: '4px' }}>
                                  🛡️ 법률검증 Agent 실무 권고사항 및 소송상 유의사항:
                                </strong>
                                <ul style={{ margin: '0 0 0 16px', padding: 0 }}>
                                  {combinedWarnings.map((w, idx) => (
                                    <li key={idx} style={{ lineHeight: 1.5 }}>
                                      {w}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            );
                          })()}
                        </div>
                      )}
                    </div>
                  );
                })()
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
