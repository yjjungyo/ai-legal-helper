/**
 * @fileoverview 단일 상담 턴(Turn) 통합 렌더러 컴포넌트
 * 의뢰인의 질문(UserMessage)과 AI 법률 비서의 진행/답변(AssistantMessage)을
 * 순차적인 대화 단위로 묶어 연속적인 채팅 스트림의 단일 아이템으로 표현합니다.
 */

import React from 'react';
import type { ConsultationResponse } from '../../types/consultation';
import { UserMessage } from './UserMessage';
import { AssistantMessage } from './AssistantMessage';
import type { CitationMeta } from '../LegalAnswerView';

export interface ChatMessageProps {
  /** 상담 레코드 객체 */
  message: ConsultationResponse;
  /** 증거 번호 [E01] 클릭 핸들러 */
  onEvidenceClick: (label: string, meta?: CitationMeta) => void;
  /** HILT 법령 검색 승인 핸들러 */
  onApprove: (requestId: string) => void;
  /** HILT 법령 검색 거절 핸들러 */
  onReject: (requestId: string) => void;
  /** HILT 승인/거절 액션 로딩 상태 */
  isActionLoading?: boolean;
}

/**
 * 단일 대화 턴 컴포넌트
 * @param props 메시지 데이터 및 인터랙션 핸들러
 * @returns 사용자 질문 및 비서 응답 묶음 JSX
 */
export const ChatMessage: React.FC<ChatMessageProps> = ({
  message,
  onEvidenceClick,
  onApprove,
  onReject,
  isActionLoading,
}) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {/* 1. 의뢰인 질문 */}
      {message.question && (
        <UserMessage
          question={message.question}
          createdAt={message.created_at}
          turnIndex={message.turn_index}
        />
      )}

      {/* 2. 법률 비서 답변 / 진행 상태 */}
      <AssistantMessage
        message={message}
        onEvidenceClick={onEvidenceClick}
        onApprove={onApprove}
        onReject={onReject}
        isActionLoading={isActionLoading}
      />
    </div>
  );
};

