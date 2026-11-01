/**
 * @fileoverview 법률 비서(Assistant) 메시지 렌더링 컴포넌트 (STEP 6)
 *
 * [주요 변경]
 * 1. 완료 상태 배지(✓ 검증 완료, ⚠️ 조건부 안내, 🛡️ 판단 유보) 기본 헤더에서 제거 (지시서 6.4 A).
 * 2. 6단계 검증 완료 카드는 상담 완료 후 숨기고, 진행 중일 때만 친절한 상태로 표시 (지시서 6.4 B).
 * 3. [ANSWER_UI] 진단 로그 출력 (지시서 6.6 - 민감 답변 전문 제외).
 * 4. 증거 원문 Drawer 상호작용 및 출처 중복 최소화 보존.
 */

import React, { useState, useEffect } from 'react';
import type { ConsultationResponse } from '../../types/consultation';
import { LegalAnswerView } from '../LegalAnswerView';
import { VerifiedPresentationView } from '../VerifiedPresentationView';
import { ConsultationProgress } from './ConsultationProgress';
import { ConsultationSources } from './ConsultationSources';

export interface AssistantMessageProps {
  /** 렌더링할 어시스턴트 메시지 데이터 */
  message: ConsultationResponse;
  /** 증거 태그/출처 클릭 콜백 (사이드바 원문 Drawer 열기) */
  onEvidenceClick: (label: string, meta?: any) => void;
  /** HILT 외부 법령 검색 승인 콜백 */
  onApprove: (requestId: string) => void;
  /** HILT 외부 법령 검색 거절 콜백 */
  onReject: (requestId: string) => void;
  /** HILT 버튼 처리 중 여부 */
  isActionLoading?: boolean;
}

/**
 * ISO 시간 문자열을 읽기 쉬운 오전/오후 형식으로 포맷팅
 */
function formatTime(isoString?: string): string {
  if (!isoString) return '';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('ko-KR', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    });
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

  // STEP 6: UI 진단 로그 (지시서 6.6 - 민감한 답변 전문은 제외하고 진단 메타데이터만 기록)
  useEffect(() => {
    if (message.answer && !isRunningOrApproval && !isFailed) {
      console.info('[ANSWER_UI] 최종 답변 수신', {
        requestId: message.request_id?.slice(0, 8),
        sourcesCount: message.sources?.length || 0,
        answerLength: message.answer.length,
        hasCitations: (message.claim_citations?.length || 0) > 0,
        mode: message.answer_mode || 'STANDARD_CONSULTATION',
      });
    }
  }, [message.request_id, message.answer, isRunningOrApproval, isFailed, message.sources, message.claim_citations, message.answer_mode]);

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
              {!isRunningOrApproval && !isFailed && renderDispositionBadge(message.final_disposition || message.answer_status)}
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

          {/* 콘텐츠 영역: 6단계 진행과정 추적 카드 (진행 중일 때는 실시간 단계별 진행 표시, 완료 시 접기/펼치기 카드로 보존) */}
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

          {/* 상태별 세부 결과 (오류 알림 또는 최종 완성된 법률 상담 답변) */}
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
                ⚠️ 상담 분석 중 일시적인 오류가 발생했습니다.
              </div>
              <p style={{ margin: 0, fontSize: '0.86em', color: '#b91c1c' }}>
                {message.detail || message.answer || '서버와의 통신이 원활하지 않습니다. 잠시 후 다시 질문해주세요.'}
              </p>
            </div>
          ) : message.answer ? (
            <div className="chat-assistant-card" style={{ padding: '4px 0' }}>
              {message.verification_status === 'PASS' && message.answer_status !== 'WITHHELD' && message.presentation?.schema_version === '1.0' && message.presentation.blocks.length > 0 && message.presentation.blocks.map((block) => block.markdown).join('') === message.answer ? (
                <VerifiedPresentationView
                  presentation={message.presentation}
                  onEvidenceClick={onEvidenceClick}
                  claimCitations={message.claim_citations || (message.verification_result as any)?.claim_citations}
                />
              ) : (
                <LegalAnswerView
                  content={message.answer || ''}
                  onEvidenceClick={onEvidenceClick}
                  claimCitations={message.claim_citations || (message.verification_result as any)?.claim_citations}
                />
              )}

              {message.sources && message.sources.length > 0 && (
                <ConsultationSources sources={message.sources} onEvidenceClick={onEvidenceClick} />
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};
