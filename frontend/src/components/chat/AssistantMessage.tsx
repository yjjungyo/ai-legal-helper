/**
 * @fileoverview 법률 비서(Assistant) 응답 메시지 렌더러 컴포넌트
 * 진행 중(IN_PROGRESS / APPROVAL_REQUIRED)인 경우 ConsultationProgress 6단계 체크리스트를
 * 동일 위치에서 즉시 렌더링하고, 완료 시 LegalAnswerView 구조화 답변으로 부드럽게 인플레이스 전이합니다.
 */

import React, { useState } from 'react';
import type { ConsultationResponse } from '../../types/consultation';
import { LegalAnswerView, type CitationMeta } from '../LegalAnswerView';
import { ConsultationProgress } from './ConsultationProgress';

export interface AssistantMessageProps {
  /** 상담 응답 전체 데이터 객체 */
  message: ConsultationResponse;
  /** 증거 번호 [E01] 클릭 핸들러 */
  onEvidenceClick: (label: string, meta?: CitationMeta) => void;
  /** HILT 법령 검색 승인 핸들러 */
  onApprove: (requestId: string) => void;
  /** HILT 법령 검색 거절 핸들러 */
  onReject: (requestId: string) => void;
  /** HILT 액션 처리 진행 중 여부 */
  isActionLoading?: boolean;
}

/**
 * 시간 표기 헬퍼
 */
function formatTime(dateStr?: string): string {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '';
    return new Intl.DateTimeFormat('ko-KR', {
      hour: 'numeric',
      minute: 'numeric',
      hour12: true,
    }).format(d);
  } catch {
    return '';
  }
}

/**
 * 최종 검증 판정 배지 렌더러 (VERIFIED, CAUTIONARY, WITHHELD)
 */
function renderDispositionBadge(disposition?: string) {
  if (!disposition) return null;
  switch (disposition) {
    case 'VERIFIED':
    case 'DELIVERED':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#ecfdf5', color: '#047857', border: '1px solid #a7f3d0', fontSize: '0.76em', fontWeight: 600 }}
        >
          ✓ 검증 완료
        </span>
      );
    case 'CAUTIONARY':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#fffbeb', color: '#b45309', border: '1px solid #fde68a', fontSize: '0.76em', fontWeight: 600 }}
        >
          ⚠️ 조건부 안내
        </span>
      );
    case 'WITHHELD':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#fef2f2', color: '#b91c1c', border: '1px solid #fecaca', fontSize: '0.76em', fontWeight: 600 }}
        >
          🛡️ 판단 유보
        </span>
      );
    default:
      return null;
  }
}

/**
 * 법률 비서 답변 메시지 컴포넌트
 * @param props 메시지 및 상호작용 콜백
 * @returns 좌측 정렬 어시스턴트 메시지 컨테이너 JSX
 */
export const AssistantMessage: React.FC<AssistantMessageProps> = ({
  message,
  onEvidenceClick,
  onApprove,
  onReject,
  isActionLoading = false,
}) => {
  const [copied, setCopied] = useState(false);
  const isRunningOrApproval = message.status === 'IN_PROGRESS' || message.status === 'APPROVAL_REQUIRED';
  const isFailed = message.status === 'ERROR';
  const timeLabel = formatTime(message.created_at);

  const handleCopy = () => {
    if (!message.answer) return;
    navigator.clipboard.writeText(message.answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="chat-assistant-row">
      <div className="chat-assistant-container">
        {/* 아바타 아이콘 */}
        <div className="chat-assistant-avatar" aria-hidden="true">
          ⚖️
        </div>

        {/* 메시지 바디 */}
        <div className="chat-assistant-body">
          {/* 발신자 및 메타 정보 헤더 */}
          <div className="chat-assistant-header">
            <div className="chat-assistant-title-group">
              <span className="chat-assistant-author">AI 법률 비서</span>
              {message.intent && (
                <span
                  style={{
                    fontSize: '0.74em',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    backgroundColor: '#f1f5f9',
                    color: '#475569',
                    fontWeight: 600,
                  }}
                >
                  {message.intent}
                </span>
              )}
              {renderDispositionBadge(message.final_disposition || message.answer_status)}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {timeLabel && (
                <span style={{ fontSize: '0.74em', color: '#94a3b8' }}>
                  {timeLabel}
                </span>
              )}
              {message.answer && !isRunningOrApproval && (
                <button
                  type="button"
                  onClick={handleCopy}
                  className="btn btn-secondary btn-sm"
                  style={{ padding: '2px 8px', fontSize: '0.75em' }}
                  title="답변 복사"
                >
                  {copied ? '✓ 복사됨' : '📋 복사'}
                </button>
              )}
            </div>
          </div>

          {/* 콘텐츠 영역: 6단계 진행과정 보존 및 답변 렌더링 */}
          {/* 1. 진행 상태 추적 카드 (진행 중이거나 완료된 경우 항상 보존하여 상단에 렌더링) */}
          {(isRunningOrApproval || message.progress || message.status === 'SUCCESS' || message.answer) && !isFailed && (
            <ConsultationProgress
              progress={message.progress}
              status={message.status}
              approvalRequest={message.approval_request}
              onApprove={onApprove}
              onReject={onReject}
              requestId={message.request_id}
              isActionLoading={isActionLoading}
              isCompleted={!isRunningOrApproval && !isFailed}
            />
          )}

          {/* 2. 상태별 세부 결과 (오류 알림 또는 최종 완성된 법률의견서 카드) */}
          {isFailed ? (
            <div
              style={{
                padding: '16px 18px',
                backgroundColor: '#fef2f2',
                border: '1px solid #fecaca',
                borderRadius: '12px',
                color: '#991b1b',
                fontSize: '0.9em',
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: '4px' }}>
                ⚠️ 상담 분석 중 오류가 발생했습니다.
              </div>
              <p style={{ margin: 0, fontSize: '0.86em', color: '#b91c1c' }}>
                {message.detail || message.answer || '서버와의 통신이 원활하지 않습니다. 잠시 후 다시 질문해주세요.'}
              </p>
            </div>
          ) : message.answer ? (
            <div className="chat-assistant-card">
              <LegalAnswerView
                content={message.answer || ''}
                onEvidenceClick={onEvidenceClick}
                claimCitations={message.claim_citations || (message.verification_result as any)?.claim_citations}
              />

              {/* 하단 인용 출처 목록 배지 */}
              {message.sources && message.sources.length > 0 && (
                <div
                  style={{
                    marginTop: '16px',
                    paddingTop: '12px',
                    borderTop: '1px solid #f1f5f9',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    flexWrap: 'wrap',
                  }}
                >
                  <span style={{ fontSize: '0.76em', color: '#64748b', fontWeight: 600 }}>
                    📚 참고 출처:
                  </span>
                  {message.sources.map((s, idx) => {
                    const sid = s.source_id || s.document_id || s.file || `SRC-${idx + 1}`;
                    const evLabel = s.evidence_label || s.label || (sid.startsWith('E') ? sid : (s.file && s.file.startsWith('E') ? s.file.split('_')[0] : null));
                    const isEv = s.source_type === 'CASE_EVIDENCE' || Boolean(evLabel);
                    const displayName = s.original_filename || s.title || s.file || sid;
                    return (
                      <span
                        key={idx}
                        onClick={() => {
                          if (isEv) {
                            onEvidenceClick(displayName, {
                              evidenceId: s.evidence_id || undefined,
                              claimId: s.claim_id || undefined,
                              spanId: s.span_id || undefined,
                            });
                          }
                        }}
                        style={{
                          fontSize: '0.76em',
                          padding: '2px 8px',
                          borderRadius: '4px',
                          backgroundColor: isEv ? '#fef3c7' : '#eff6ff',
                          color: isEv ? '#92400e' : '#1e40af',
                          border: `1px solid ${isEv ? '#fde68a' : '#bfdbfe'}`,
                          cursor: isEv ? 'pointer' : 'default',
                        }}
                      >
                        {isEv ? `📄 ${displayName}` : displayName}
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};
