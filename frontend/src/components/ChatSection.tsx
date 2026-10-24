/**
 * @fileoverview 사건 문맥 기반 AI 법률 상담 섹션 컴포넌트
 * 사건의 확정 사실(Facts)과 증거 문맥을 자동 반영하여 법률 질의응답을 수행하며,
 * 상담 내역 데이터베이스 영구 저장 및 질문의 사건 사실관계(Fact) 1-클릭 등록을 지원합니다.
 */

import { useState, useRef } from 'react';
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

function renderIntentBadge(intent?: string) {
  if (!intent) return null;
  switch (intent) {
    case 'FOLLOWUP_ACTION':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#ecfdf5', color: '#047857', border: '1px solid #a7f3d0', fontSize: '0.78em' }}
        >
          🚀 후속 조치
        </span>
      );
    case 'FOLLOWUP_QUESTION':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe', fontSize: '0.78em' }}
        >
          🔍 세부 질의
        </span>
      );
    case 'FACT_CLARIFICATION':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#fffbeb', color: '#b45309', border: '1px solid #fde68a', fontSize: '0.78em' }}
        >
          📝 사실 정정
        </span>
      );
    case 'DOCUMENT_REQUEST':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#f5f3ff', color: '#6d28d9', border: '1px solid #ddd6fe', fontSize: '0.78em' }}
        >
          📄 서식 초안
        </span>
      );
    case 'GENERAL_CONVERSATION':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#f1f5f9', color: '#475569', border: '1px solid #cbd5e1', fontSize: '0.78em' }}
        >
          💬 일반 대화
        </span>
      );
    case 'NEW_LEGAL_ANALYSIS':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#fdf2f8', color: '#be185d', border: '1px solid #fbcfe8', fontSize: '0.78em' }}
        >
          ⚖️ 심층 분석
        </span>
      );
    default:
      return null;
  }
}

function renderStatusBadge(item: ConsultationResponse) {
  if (item.routing_status === 'NEEDS_CLARIFICATION') {
    return (
      <span
        className="badge"
        style={{
          backgroundColor: '#eff6ff',
          color: '#1d4ed8',
          border: '1px solid #bfdbfe',
          fontWeight: 600,
        }}
      >
        ℹ️ 추가 정보 필요
      </span>
    );
  }
  if (item.routing_status === 'ROUTER_ERROR') {
    return (
      <span
        className="badge"
        style={{
          backgroundColor: '#fef2f2',
          color: '#b91c1c',
          border: '1px solid #fecaca',
          fontWeight: 600,
        }}
      >
        ⚠️ 시스템 오류
      </span>
    );
  }
  if (item.status === 'ERROR') {
    return <span className="badge badge-red">오류</span>;
  }
  if (item.status === 'APPROVAL_REQUIRED') {
    return <span className="badge badge-blue">추가 검색 승인 대기</span>;
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
        공식 법령 조회 및 재분석 중
      </span>
    );
  }

  // 고객 친화적 답변 상태 배지 (내부 Verifier 디버그 상태 노출 제거)
  if (item.answer_status === 'WITHHELD') {
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
        🛡️ 판단 유보
      </span>
    );
  }
  if (item.answer_status === 'CAUTIONARY') {
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

  return <span className="badge badge-green">✓ 답변 완료</span>;
}

/**
 * 사건 작업 공간 내 AI 법률 상담 컴포넌트
 */
export function ChatSection({ caseId }: ChatSectionProps) {
  const {
    question,
    setQuestion,
    activeConversationId,
    startNewConversation,
    history,
    loadHistory,
    submit,
    respondApproval,
    result,
    loading,
    error,
  } = useConsultation(caseId);
  const [registering, setRegistering] = useState<string | null>(null);
  const [showOnlyActiveConversation, setShowOnlyActiveConversation] = useState<boolean>(true);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);


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
          ref={textareaRef}
          placeholder="법률 상담 질문이나 새로운 분쟁 상황을 입력하세요 (예: 임대차 계약이 만료되었는데 임대인이 보증금을 돌려주지 않습니다. 내용증명 발송과 임차권등기명령 절차가 어떻게 되나요?)"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={4}
          disabled={loading}
          className="form-control"
          style={{ resize: 'vertical', lineHeight: 1.5 }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '0.82em', color: 'var(--text-muted)' }}>
              {activeConversationId ? '🔗 이전 대화 맥락이 연결되어 있습니다.' : '💡 새로운 대화 세션입니다.'}
            </span>
            {activeConversationId && (
              <button
                type="button"
                onClick={startNewConversation}
                className="btn btn-secondary btn-sm"
                style={{ fontSize: '0.78em', padding: '2px 8px' }}
                title="이전 대화 맥락을 끊고 새로운 주제로 대화를 시작합니다"
              >
                + 새 대화 시작
              </button>
            )}
          </div>
          <button
            onClick={submit}
            disabled={loading || !question.trim()}
            className="btn btn-primary"
          >
            {loading ? 'AI 분석 및 상담 진행 중...' : (activeConversationId ? '💬 이어서 질문하기' : '🚀 상담 요청하기')}
          </button>
        </div>
      </div>

      {/* 4. 오류 메시지 */}
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

      {/* 5. 현재 진행 중인 상담 (Active Consultation) 단일 전용 작업 공간 */}
      {(result || loading) && (
        <div
          className="card"
          style={{
            border: result?.status === 'APPROVAL_REQUIRED' ? '2px solid #3b82f6' : '1px solid #bfdbfe',
            backgroundColor: result?.status === 'APPROVAL_REQUIRED' ? '#eff6ff' : '#f8fafc',
            boxShadow: result?.status === 'APPROVAL_REQUIRED' ? '0 4px 14px rgba(59, 130, 246, 0.15)' : 'none',
            padding: '20px 22px',
          }}
        >
          {/* 상단 헤더: 제목 및 통합 상태 배지 */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '12px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '1.25em' }}>
                {result?.status === 'APPROVAL_REQUIRED' ? '⚖️' : '🔄'}
              </span>
              <strong
                style={{
                  fontSize: '1.05em',
                  color: result?.status === 'APPROVAL_REQUIRED' ? '#1e40af' : '#1e293b',
                }}
              >
                {result?.status === 'APPROVAL_REQUIRED'
                  ? '공식 법령 원문 추가 검색 승인 요청 (Human-in-the-Loop)'
                  : '현재 진행 중인 법률 상담 분석'}
              </strong>
            </div>
            <div>
              {result ? (
                renderStatusBadge(result)
              ) : (
                <span className="badge badge-blue">
                  <span
                    className="spinner"
                    style={{ width: '10px', height: '10px', display: 'inline-block', marginRight: '4px' }}
                  />
                  분석 준비 중
                </span>
              )}
            </div>
          </div>

          {/* 의뢰인 질문 표시 (진행 맥락 인지 지원) */}
          {(result?.question || question) && (
            <div
              style={{
                marginBottom: '14px',
                padding: '10px 14px',
                backgroundColor: '#ffffff',
                borderRadius: '6px',
                border: '1px solid #e2e8f0',
                fontSize: '0.9em',
                color: '#334155',
              }}
            >
              <strong style={{ color: '#0f172a', marginRight: '6px' }}>👤 의뢰인 질문:</strong>
              <span>{result?.question || question}</span>
            </div>
          )}

          {/* 상황 A: HILT 승인 대기 상태 */}
          {result?.status === 'APPROVAL_REQUIRED' && (
            <div>
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

          {/* 상황 B: 분석 또는 공식 법령 재분석 진행 중 상태 (단일 프로그레스 배너) */}
          {(loading || result?.status === 'IN_PROGRESS') && result?.status !== 'APPROVAL_REQUIRED' && (
            <div
              style={{
                padding: '16px 18px',
                backgroundColor: '#ffffff',
                borderRadius: '6px',
                border: '1px solid #e2e8f0',
              }}
            >
              {result?.approval_request ? (
                // HILT 승인 후 공식 법령 조회 및 재분석 단계
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                    <span
                      className="spinner"
                      style={{
                        width: '14px',
                        height: '14px',
                        borderColor: '#93c5fd',
                        borderTopColor: '#16a34a',
                      }}
                    />
                    <strong style={{ color: '#15803d', fontSize: '0.96em' }}>
                      공식 법령 원문 검색 및 AI 재분석 진행 중입니다...
                    </strong>
                  </div>
                  <p style={{ fontSize: '0.86em', color: '#166534', margin: 0, lineHeight: 1.5 }}>
                    국가법령정보공동활용(open.law.go.kr) 공식 API에서 최신 법령 조문을 조회하여 법률검증 및 답변을 재작성하고 있습니다. (약 10~20초 소요)
                  </p>
                </div>
              ) : (
                // 1차 법률 상담 분석 단계
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                    <span
                      className="spinner"
                      style={{
                        width: '14px',
                        height: '14px',
                        borderColor: '#93c5fd',
                        borderTopColor: '#1d4ed8',
                      }}
                    />
                    <strong style={{ color: '#1d4ed8', fontSize: '0.96em' }}>
                      법률 전문 Agent가 사건 문맥을 검토하여 분석 중입니다...
                    </strong>
                  </div>
                  <p style={{ fontSize: '0.86em', color: '#475569', margin: 0, lineHeight: 1.5 }}>
                    등록된 사건 사실관계와 판례·법령 데이터베이스를 대조하고 증거 관계를 검증하여 맞춤 답변을 생성하고 있습니다.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 7. 영구 저장된 상담 내역 목록 */}
      <div style={{ marginTop: '10px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h3 style={{ fontSize: '1.1em', fontWeight: 700, margin: 0 }}>
            {showOnlyActiveConversation && activeConversationId
              ? `💬 현재 연속 상담 대화 (${history.filter(i => i.conversation_id === activeConversationId).length}턴)`
              : `📋 전체 상담 이력 (${history.length}건)`}
          </h3>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {activeConversationId && (
              <button
                type="button"
                onClick={() => setShowOnlyActiveConversation(!showOnlyActiveConversation)}
                className="btn btn-outline btn-sm"
                style={{
                  fontSize: '0.82em',
                  borderColor: showOnlyActiveConversation ? '#2563eb' : '#cbd5e1',
                  color: showOnlyActiveConversation ? '#2563eb' : '#64748b',
                  fontWeight: 600,
                }}
              >
                {showOnlyActiveConversation ? '📋 전체 이력 보기' : '💬 현재 대화만 보기'}
              </button>
            )}
            <button onClick={loadHistory} className="btn btn-secondary btn-sm">
              새로고침
            </button>
          </div>
        </div>

        {history.length === 0 && !loading && (
          <div className="card" style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
            아직 저장된 법률 상담 내역이 없습니다.<br />위 입력창을 통해 첫 질문을 남겨보세요!
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {(
            showOnlyActiveConversation && activeConversationId
              ? history
                  .filter((i) => i.conversation_id === activeConversationId)
                  .sort((a, b) => (a.turn_index || 1) - (b.turn_index || 1))
              : history
          ).map((item: ConsultationResponse) => (
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
                  {item.turn_index && (
                    <span
                      style={{
                        fontSize: '0.75em',
                        backgroundColor: '#f1f5f9',
                        color: '#475569',
                        padding: '1px 6px',
                        borderRadius: '4px',
                        fontWeight: 600,
                        border: '1px solid #cbd5e1',
                      }}
                    >
                      Turn {item.turn_index}
                    </span>
                  )}
                  {renderIntentBadge(item.intent)}
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

              {/* 5. 상태별 UI 카드 분리: 추가 정보 필요(파랑), 시스템 오류(빨강), 근거 부족 판단 유보(노랑) (P0-02/Router v2.0) */}
              {item.routing_status === 'NEEDS_CLARIFICATION' ? (
                /* 1. NEEDS_CLARIFICATION: 파란색 계열 카드 */
                <div
                  style={{
                    padding: '20px 22px',
                    backgroundColor: '#eff6ff',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid #bfdbfe',
                    borderLeft: '4px solid #2563eb',
                    marginBottom: '14px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                    <span style={{ fontSize: '1.2em' }}>ℹ️</span>
                    <strong style={{ color: '#1d4ed8', fontSize: '1.02em' }}>
                      원활한 법률 상담을 위해 추가 정보가 필요합니다
                    </strong>
                  </div>
                  <div style={{ color: '#1e3a8a', fontSize: '0.92em', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                    {item.answer || '질문 내용만으로는 핵심 법률 쟁점을 파악하기 어렵습니다.'}
                  </div>
                  <div style={{ marginTop: '14px', display: 'flex', gap: '8px' }}>
                    <button
                      onClick={() => {
                        if (item.question) {
                          setQuestion(item.question + '\n[추가 정보]: ');
                        }
                        textareaRef.current?.focus();
                      }}
                      className="btn btn-primary btn-sm"
                      style={{ backgroundColor: '#2563eb', borderColor: '#1d4ed8' }}
                    >
                      ✏️ 질문 보완하여 다시 상담하기
                    </button>
                  </div>
                </div>
              ) : item.routing_status === 'ROUTER_ERROR' ? (
                /* 2. ROUTER_ERROR: 빨간색 계열 카드 */
                <div
                  style={{
                    padding: '20px 22px',
                    backgroundColor: '#fef2f2',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid #fecaca',
                    borderLeft: '4px solid #dc2626',
                    marginBottom: '14px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                    <span style={{ fontSize: '1.2em' }}>⚠️</span>
                    <strong style={{ color: '#b91c1c', fontSize: '1.02em' }}>
                      일시적 시스템 오류 안내
                    </strong>
                  </div>
                  <div style={{ color: '#991b1b', fontSize: '0.92em', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                    {item.answer || '법률 분야 분류 중 기술적 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.'}
                  </div>
                  <div style={{ marginTop: '14px', display: 'flex', gap: '8px' }}>
                    <button
                      onClick={() => {
                        if (item.question) {
                          setQuestion(item.question);
                        }
                        textareaRef.current?.focus();
                      }}
                      className="btn btn-secondary btn-sm"
                      style={{ borderColor: '#f87171', color: '#b91c1c' }}
                    >
                      🔄 다시 시도하기
                    </button>
                  </div>
                </div>
              ) : item.answer_status === 'WITHHELD' ? (
                /* 3. WITHHELD: 기존 노란색/주황색 주의 카드 유지 (법률적 근거 부족) */
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

              {/* 7. 쟁점별 검증 현황 뱃지 (Issue-Level Verification v1.0) */}
              {item.status !== 'IN_PROGRESS' && item.issue_results && item.issue_results.length > 0 && (
                <div
                  style={{
                    marginTop: '10px',
                    marginBottom: '8px',
                    padding: '8px 12px',
                    backgroundColor: 'var(--surface-alt)',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    flexWrap: 'wrap',
                    fontSize: '0.82em',
                  }}
                >
                  <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>⚖️ 쟁점별 검증 현황:</span>
                  {item.issue_results.map((iss, iIdx) => {
                    let badgeClass = 'badge badge-blue';
                    let statusLabel = '검증완료';
                    if (iss.status === 'VERIFIED') {
                      badgeClass = 'badge badge-green';
                      statusLabel = '검증완료';
                    } else if (iss.status === 'CONDITIONAL') {
                      badgeClass = 'badge badge-purple';
                      statusLabel = '조건부 검증';
                    } else if (iss.status === 'NEEDS_EVIDENCE') {
                      badgeClass = 'badge badge-yellow';
                      statusLabel = '증거 보완필요';
                    } else if (iss.status === 'BLOCKED') {
                      badgeClass = 'badge badge-red';
                      statusLabel = '답변 제한';
                    }
                    return (
                      <span key={iIdx} className={badgeClass} style={{ fontSize: '0.82em', fontWeight: 500 }}>
                        {iss.title}: {statusLabel}
                      </span>
                    );
                  })}
                </div>
              )}

              {/* 8. 고객용 참고 법령 및 사건 증거 목록 (심플 뱃지 안내) */}
              {item.status !== 'IN_PROGRESS' && item.sources && item.sources.length > 0 && (
                <div
                  style={{
                    marginTop: '8px',
                    padding: '8px 12px',
                    backgroundColor: 'var(--surface-alt)',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    flexWrap: 'wrap',
                    fontSize: '0.82em',
                  }}
                >
                  <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>📚 확인된 출처 및 증거:</span>
                  {Array.from(
                    new Map(
                      item.sources.map((s) => [
                        s.source_type === 'CASE_EVIDENCE'
                          ? `evidence_${s.evidence_label || s.file}`
                          : `statute_${s.statute_name || s.title}_${s.article || ''}`,
                        s,
                      ])
                    ).values()
                  ).slice(0, 10).map((s, sIdx) => (
                    <span
                      key={sIdx}
                      className={s.source_type === 'CASE_EVIDENCE' ? 'badge badge-green' : 'badge badge-blue'}
                      style={{ fontSize: '0.85em', fontWeight: 500 }}
                    >
                      {s.source_type === 'CASE_EVIDENCE'
                        ? `📁 ${s.evidence_label ? `[${s.evidence_label}] ` : ''}${s.file || s.title}`
                        : `📜 ${s.statute_name || s.title}${s.article ? ` ${s.article}` : ''}`}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
