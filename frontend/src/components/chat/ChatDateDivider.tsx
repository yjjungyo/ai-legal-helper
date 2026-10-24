/**
 * @fileoverview 상담 대화 스트림 일자별 구분선 컴포넌트
 * 사건 중심 지속 대화(One Persistent Conversation)에서 날짜가 바뀌는 시점마다
 * 타임스탬프를 한국어 날짜 형식("YYYY년 MM월 DD일 요일")으로 중앙 정렬 배지로 표시합니다.
 */

import React from 'react';

export interface ChatDateDividerProps {
  /** ISO 날짜 문자열 또는 날짜 객체 */
  date: string | Date;
}

/**
 * 날짜 문자열을 한국어 표준 일자 서식으로 변환한다.
 * @param date ISO 날짜 문자열 또는 Date 객체
 * @returns 포맷팅된 한국어 일자 문자열
 */
function formatDateLabel(date: string | Date): string {
  try {
    const d = typeof date === 'string' ? new Date(date) : date;
    if (isNaN(d.getTime())) {
      return '상담 기록';
    }
    return new Intl.DateTimeFormat('ko-KR', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      weekday: 'long',
    }).format(d);
  } catch {
    return '상담 기록';
  }
}

/**
 * 채팅 대화 일자 구분선 컴포넌트
 * @param props 대상 일자
 * @returns 중앙 정렬 구분선 배지 JSX
 */
export const ChatDateDivider: React.FC<ChatDateDividerProps> = ({ date }) => {
  const formattedDate = formatDateLabel(date);

  return (
    <div className="chat-date-divider" role="separator" aria-label={formattedDate}>
      <div className="chat-date-divider-line" />
      <span className="chat-date-divider-pill">{formattedDate}</span>
    </div>
  );
};

