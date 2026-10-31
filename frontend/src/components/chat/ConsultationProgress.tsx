/**
 * @fileoverview 법률 상담 진행 상태 추적 및 HILT 승인 인터랙션 컴포넌트 (STEP 6)
 *
 * [주요 변경]
 * 1. 상담 완료 후에는 기본 화면에 6단계 처리 카드를 노출하지 않음 (지시서 6.4 B).
 * 2. 진행 중에는 '사건 자료 확인 중', '관련 법률 검토 중', '답변 정리 중' 등 직관적이고 친절한 안내만 노출.
 * 3. HILT 공식 법령 검색 승인 대기 시 사용자 선택 인터랙션 보존.
 */

import React from 'react';
import type { ConsultationProgress as IConsultationProgress, ApprovalRequest } from '../../types/consultation';

export interface ConsultationProgressProps {
  /** 백엔드 LangGraph 진행 상태 객체 */
  progress?: IConsultationProgress | null;
  /** 현재 상담 요청의 전체 상태 (IN_PROGRESS, APPROVAL_REQUIRED 등) */
  status: string;
  /** HILT 외부 법령 검색 승인 요청 세부 정보 */
  approvalRequest?: ApprovalRequest | null;
  /** 승인 버튼 클릭 콜백 */
  onApprove: (requestId: string) => void;
  /** 거절/건너뛰기 버튼 클릭 콜백 */
  onReject: (requestId: string) => void;
  /** 상담 요청 식별자 UUID */
  requestId: string;
  /** 승인/거절 액션 처리 중 여부 */
  isActionLoading?: boolean;
  /** 최종 분석 및 답변 완료 여부 (완료 시 보존 모드로 전환) */
  isCompleted?: boolean;
}

/**
 * 일반 사용자가 이해하기 쉬운 친절한 진행 메시지 (지시서 6.4 B)
 */
function getFriendlyProgressMessage(stepId?: string | null, isApprovalWaiting?: boolean): string {
  if (isApprovalWaiting) {
    return '추가 법령 원문 검색 승인이 필요합니다.';
  }
  if (!stepId || stepId === 'step_1' || stepId === 'INTENT_ANALYSIS' || stepId === 'FACT_RETRIEVAL') {
    return '사건 자료를 확인하고 있습니다...';
  }
  if (stepId === 'step_2' || stepId === 'step_3' || stepId === 'LEGAL_RESEARCH' || stepId === 'STATUTE_APPROVAL') {
    return '관련 법률을 살펴보고 있습니다...';
  }
  return '답변을 정리하고 있습니다...';
}

export const ConsultationProgress: React.FC<ConsultationProgressProps> = ({
  progress,
  status,
  approvalRequest,
  onApprove,
  onReject,
  requestId,
  isActionLoading = false,
  isCompleted = false,
}) => {
  const completedMode = isCompleted || status === 'SUCCESS';
  const isApprovalWaiting = status === 'APPROVAL_REQUIRED';

  // STEP 6: 상담 완료 후에는 기본 화면에 6단계 처리 카드를 노출하지 않음
  if (completedMode && !isApprovalWaiting) {
    return null;
  }

  const friendlyMsg = getFriendlyProgressMessage(progress?.current_step, isApprovalWaiting);

  return (
    <div
      className={`chat-progress-card ${isApprovalWaiting ? 'approval-waiting' : 'running'}`}
      role="status"
      aria-live="polite"
      style={{
        margin: '8px 0 14px 0',
        padding: '12px 16px',
        backgroundColor: isApprovalWaiting ? '#fffbeb' : '#f8fafc',
        border: isApprovalWaiting ? '1px solid #fde68a' : '1px solid #e2e8f0',
        borderRadius: '8px',
      }}
    >
      {/* 간결한 진행 안내 헤더 */}
      <div className="chat-progress-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div className="chat-progress-title" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span
            className="spinner"
            style={{
              width: '14px',
              height: '14px',
              borderTopColor: isApprovalWaiting ? '#d97706' : '#2563eb',
            }}
          />
          <span style={{ color: isApprovalWaiting ? '#b45309' : '#1e40af', fontWeight: 600, fontSize: '0.92em' }}>
            {friendlyMsg}
          </span>
        </div>
      </div>

      {/* 상황 A: HILT 승인 대기 인라인 액션 박스 */}
      {isApprovalWaiting && (
        <div className="chat-approval-box" style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid #fef3c7' }}>
          <div className="chat-approval-desc" style={{ fontSize: '0.88em', color: '#92400e', marginBottom: '8px', lineHeight: 1.5 }}>
            {approvalRequest?.explanation ||
              '보다 정확한 법률 검토를 위해 공식 법령 조문 검색이 필요합니다. 국가법령정보 공식 검색을 진행하시겠습니까?'}
          </div>

          {approvalRequest?.candidate_laws && approvalRequest.candidate_laws.length > 0 && (
            <div style={{ marginBottom: '10px' }}>
              <div style={{ fontSize: '0.8em', color: '#78350f', fontWeight: 600, marginBottom: '4px' }}>
                조회 대상 법령:
              </div>
              <div className="chat-approval-laws" style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {approvalRequest.candidate_laws.map((law: string, idx: number) => (
                  <span
                    key={idx}
                    className="chat-approval-law-tag"
                    style={{
                      backgroundColor: '#fef3c7',
                      color: '#92400e',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      fontSize: '0.78em',
                      border: '1px solid #fde68a',
                    }}
                  >
                    {law}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="chat-approval-actions" style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <button
              type="button"
              onClick={() => onReject(requestId)}
              disabled={isActionLoading}
              className="btn btn-secondary btn-sm"
              style={{ fontSize: '0.82em', padding: '4px 10px' }}
            >
              ✕ 건너뛰기 (현재 자료로 완료)
            </button>
            <button
              type="button"
              onClick={() => onApprove(requestId)}
              disabled={isActionLoading}
              className="btn btn-primary btn-sm"
              style={{
                fontSize: '0.82em',
                padding: '4px 12px',
                backgroundColor: '#2563eb',
                color: '#ffffff',
                fontWeight: 600,
                border: 'none',
                borderRadius: '4px',
              }}
            >
              ✓ 법령 검색 승인
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
