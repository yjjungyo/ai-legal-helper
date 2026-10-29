/**
 * @fileoverview LangGraph 6단계 법률 상담 진행 상태 추적 및 HILT 승인 인터랙션 컴포넌트
 * 사건 분석 의도 파악부터 증거 매핑, 법령 분석, 쟁점 교차 검증, 미보유 법령 승인, 최종 답변 종합까지
 * 실시간 상태(RUNNING, COMPLETED, WAITING_APPROVAL, SKIPPED, FAILED)를 시각화합니다.
 */

import React, { useState } from 'react';
import type { ConsultationProgress as IConsultationProgress, ConsultationStep, ApprovalRequest } from '../../types/consultation';

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
 * 기본 6단계 정의 (서버 프로그레스가 아직 없을 때 기본 템플릿으로 사용)
 */
const DEFAULT_STEPS: ConsultationStep[] = [
  { step_id: 'INTENT_ANALYSIS', title: '사건 의도 및 쟁점 파악', status: 'COMPLETED' },
  { step_id: 'FACT_RETRIEVAL', title: '등록 증거 및 사실관계 조회', status: 'RUNNING' },
  { step_id: 'LEGAL_RESEARCH', title: '법령·판례 및 전문 법률 분석', status: 'PENDING' },
  { step_id: 'VERIFICATION', title: '쟁점별 사실·법리 교차 검증', status: 'PENDING' },
  { step_id: 'STATUTE_APPROVAL', title: '미보유 법령 외부 검색 승인', status: 'PENDING' },
  { step_id: 'FINAL_SYNTHESIS', title: '최종 법률 조언 답변 종합', status: 'PENDING' },
];

/**
 * 단계 상태에 따른 상태 아이콘 및 레이블 반환
 * @param status 단계 상태 코드
 * @returns JSX 아이콘
 */
function renderStepIcon(status: string) {
  switch (status) {
    case 'COMPLETED':
      return <span style={{ color: '#16a34a', fontWeight: 'bold' }}>✓</span>;
    case 'RUNNING':
      return (
        <span
          className="spinner"
          style={{ width: '14px', height: '14px', borderTopColor: '#2563eb' }}
          aria-label="진행 중"
        />
      );
    case 'WAITING_APPROVAL':
      return <span style={{ color: '#d97706', fontWeight: 'bold' }}>⚠️</span>;
    case 'FAILED':
      return <span style={{ color: '#dc2626', fontWeight: 'bold' }}>✕</span>;
    case 'SKIPPED':
      return <span style={{ color: '#94a3b8' }}>—</span>;
    case 'PENDING':
    default:
      return <span style={{ color: '#cbd5e1' }}>○</span>;
  }
}

/**
 * 진행 상태 카드 컴포넌트
 * @param props 진행 상태 및 HILT 콜백
 * @returns 대화 스트림 내 진행 상태 추적 카드 JSX
 */
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
  // [P0-04/Gate 2] 상담 완료 시 6단계 검증 카드는 한 줄 요약 카드로 기본 자동 접기, 진행 중일 때는 펼침
  const [isExpanded, setIsExpanded] = useState(!completedMode);

  // 서버로부터 전달받은 단계 목록이 있으면 사용하고, 없으면 기본 목록에 상태 보정
  let steps = progress?.steps && progress.steps.length > 0 ? progress.steps : DEFAULT_STEPS;

  if (completedMode) {
    // 최종 완료 상태에서는 모든 단계가 완료된 상태로 단정하게 보이도록 보정
    steps = steps.map((s) => ({
      ...s,
      status: s.status === 'PENDING' || s.status === 'RUNNING' ? 'COMPLETED' : s.status,
    }));
  } else if (status === 'APPROVAL_REQUIRED') {
    // HILT 승인 대기 상태인 경우 5번째 단계를 WAITING_APPROVAL로 보정
    steps = steps.map((s) => {
      if (s.step_id === 'STATUTE_APPROVAL') {
        return { ...s, status: 'WAITING_APPROVAL' };
      }
      if (['INTENT_ANALYSIS', 'FACT_RETRIEVAL', 'LEGAL_RESEARCH', 'VERIFICATION'].includes(s.step_id)) {
        return { ...s, status: 'COMPLETED' };
      }
      return s;
    });
  }

  const isApprovalWaiting = status === 'APPROVAL_REQUIRED';

  return (
    <div
      className={`chat-progress-card ${completedMode ? 'completed' : ''} ${isExpanded ? 'expanded' : 'collapsed'}`}
      role="status"
      aria-live="polite"
    >
      {/* 카드 상단 헤더 */}
      <div className="chat-progress-header">
        <div className="chat-progress-title">
          {completedMode ? (
            <span style={{ color: '#16a34a', fontWeight: 'bold', fontSize: '1.05em' }}>✓</span>
          ) : (
            <span
              className="spinner"
              style={{
                width: '14px',
                height: '14px',
                borderTopColor: isApprovalWaiting ? '#d97706' : '#2563eb',
              }}
            />
          )}
          <span style={{ color: completedMode ? '#166534' : '#1e40af' }}>
            {completedMode
              ? '사건 증거 기반 AI 법률 상담 분석 및 6단계 검증 완료'
              : isApprovalWaiting
              ? '법률 조문 추가 검색 승인 대기 중'
              : '사건 증거 기반 AI 법률 상담 분석 진행 중...'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              fontSize: '0.78em',
              color: completedMode ? '#15803d' : '#64748b',
              fontWeight: completedMode ? 600 : 400,
            }}
          >
            {completedMode
              ? '6단계 완료'
              : progress?.current_step_name || progress?.current_step || (isApprovalWaiting ? 'HILT 법령 검색 승인' : '증거 교차 검증')}
          </span>

          {completedMode && (
            <button
              type="button"
              onClick={() => setIsExpanded(!isExpanded)}
              className="btn btn-secondary btn-sm"
              style={{ padding: '2px 8px', fontSize: '0.74em', color: '#475569' }}
              title={isExpanded ? '진행과정 접기' : '진행과정 펼치기'}
            >
              {isExpanded ? '▲ 진행과정 접기' : '▼ 진행과정 보기'}
            </button>
          )}
        </div>
      </div>

      {/* 6단계 진행 리스트 (펼침 상태이거나 분석 중일 때 렌더링) */}
      {(!completedMode || isExpanded) && (
        <div className="chat-progress-steps-list">
          {steps.map((step) => {
            const statusClass = step.status.toLowerCase();
            return (
              <div key={step.step_id} className={`chat-progress-step-item ${statusClass}`}>
                <div className="chat-step-left">
                  <div className="chat-step-icon">{renderStepIcon(step.status)}</div>
                  <span>{step.step_name || step.title}</span>
                </div>
                <div style={{ fontSize: '0.78em' }}>
                  {step.status === 'RUNNING' && <span style={{ color: '#2563eb' }}>분석 중...</span>}
                  {step.status === 'COMPLETED' && <span style={{ color: '#16a34a' }}>완료</span>}
                  {step.status === 'WAITING_APPROVAL' && <span style={{ color: '#d97706', fontWeight: 600 }}>승인 필요</span>}
                  {step.status === 'SKIPPED' && <span style={{ color: '#94a3b8' }}>건너뜀</span>}
                  {step.status === 'PENDING' && <span style={{ color: '#94a3b8' }}>대기</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 상황 A: HILT 승인 대기 인라인 액션 박스 */}
      {isApprovalWaiting && (
        <div className="chat-approval-box">
          <div className="chat-approval-desc">
            {approvalRequest?.explanation ||
              '현재 등록된 사건 자료만으로는 의뢰인의 쟁점을 검증할 수 없습니다. 국가법령정보공동활용 공식 API에서 원문 조문을 직접 검색하여 법률 재분석을 진행하시겠습니까?'}
          </div>

          {approvalRequest?.candidate_laws && approvalRequest.candidate_laws.length > 0 && (
            <div>
              <div style={{ fontSize: '0.8em', color: '#78350f', fontWeight: 600, marginBottom: '4px' }}>
                조회 예정 공식 법령:
              </div>
              <div className="chat-approval-laws">
                {approvalRequest.candidate_laws.map((law: string, idx: number) => (
                  <span key={idx} className="chat-approval-law-tag">
                    {law}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="chat-approval-actions">
            <button
              type="button"
              onClick={() => onReject(requestId)}
              disabled={isActionLoading}
              className="btn btn-secondary btn-sm"
              style={{ fontSize: '0.82em' }}
            >
              ✕ 검색 건너뛰기 (현재 근거로 종료)
            </button>
            <button
              type="button"
              onClick={() => onApprove(requestId)}
              disabled={isActionLoading}
              className="btn btn-primary btn-sm"
              style={{
                fontSize: '0.82em',
                backgroundColor: '#2563eb',
                fontWeight: 600,
              }}
            >
              ✓ 공식 법령 검색 승인 및 재분석
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

