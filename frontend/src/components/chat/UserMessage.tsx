/**
 * @fileoverview 의뢰인(사용자) 질문 메시지 버블 컴포넌트
 * 오른쪽 정렬된 말풍선으로 의뢰인의 질문 내용을 렌더링하고,
 * 질문 발생 시각 및 대화 턴 번호를 보조 메타데이터로 표기합니다.
 */

import React from 'react';

export interface UserMessageProps {
  /** 의뢰인 질문 원문 */
  question: string;
  /** 질문 작성 일시 (ISO 형식) */
  createdAt?: string;
  /** 대화 턴 번호 (1부터 시작) */
  turnIndex?: number;
}

/**
 * ISO 일시 문자열을 오전/오후 시:분 형식으로 변환한다.
 * @param dateStr ISO 문자열
 * @returns 시간 표기 문자열
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
 * 의뢰인 질문 말풍선 컴포넌트
 * @param props 질문 내용 및 메타데이터
 * @returns 우측 정렬 사용자 메시지 JSX
 */
export const UserMessage: React.FC<UserMessageProps> = ({ question, createdAt }) => {
  const timeLabel = formatTime(createdAt);

  return (
    <div className="chat-user-row">
      <div className="chat-user-bubble-wrapper">
        <div className="chat-user-bubble">
          {question}
        </div>
        {timeLabel && (
          <div className="chat-user-meta">
            <span>{timeLabel}</span>
          </div>
        )}
      </div>
    </div>
  );
};

