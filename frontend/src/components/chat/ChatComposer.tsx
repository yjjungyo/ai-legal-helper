/**
 * @fileoverview 하단 고정 법률 상담 질의 입력기(ChatComposer) 컴포넌트
 * 자동 높이 조절 텍스트에어리어, Enter 즉시 전송, Shift+Enter 줄바꿈 및
 * 한글 IME 조합 중복 전송 방지(e.nativeEvent.isComposing)를 완벽히 지원합니다.
 */

import React, { useRef, useEffect } from 'react';

export interface ChatComposerProps {
  /** 현재 입력된 질문 텍스트 */
  value: string;
  /** 입력 텍스트 변경 이벤트 핸들러 */
  onChange: (val: string) => void;
  /** 질문 전송 핸들러 */
  onSend: (text: string) => void;
  /** 현재 상담 진행 또는 전송 비활성화 상태 */
  disabled?: boolean;
  /** 입력창 안내 문구 (선택 사항) */
  placeholder?: string;
}

/**
 * 하단 고정형 대화 입력기 컴포넌트
 * @param props 입력값, 변경 핸들러, 전송 핸들러 및 비활성화 플래그
 * @returns 대화 입력창 및 전송 버튼 JSX
 */
export const ChatComposer: React.FC<ChatComposerProps> = ({
  value,
  onChange,
  onSend,
  disabled = false,
  placeholder = '사건에 대해 추가로 궁금한 점을 질문하세요... (Enter: 전송, Shift+Enter: 줄바꿈)',
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 텍스트 내용 길이에 따라 textarea 높이를 동적으로 자동 조절 (최대 140px)
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const newHeight = Math.min(el.scrollHeight, 140);
    el.style.height = `${newHeight}px`;
  }, [value]);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
  };

  /**
   * 키보드 이벤트 핸들러: 한글 조합 방어 및 단축키 전송
   */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // 1. 한글 IME 조합 중에는 Enter 키로 전송되지 않도록 방어 (중복 전송 버그 원천 차단)
    if (e.nativeEvent.isComposing) {
      return;
    }

    // 2. Enter 키로 전송 (Shift+Enter는 일반 줄바꿈 허용)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const isSendDisabled = disabled || !value.trim();

  return (
    <footer className="case-chat-composer" role="region" aria-label="메시지 입력 영역">
      <div className="case-chat-composer-inner">
        <div className="chat-textarea-wrapper">
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder={
              disabled
                ? '현재 AI 분석이 진행 중입니다. 답변 완료 후 추가 질문이 가능합니다...'
                : placeholder
            }
            className="chat-textarea"
            aria-label="법률 상담 질문 입력"
          />

          <button
            type="button"
            onClick={handleSubmit}
            disabled={isSendDisabled}
            className="chat-send-btn"
            title="질문 전송 (Enter)"
            aria-label="질문 전송"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>

        <div className="chat-composer-hint">
          <span>
            {disabled
              ? '⏳ AI 변호사가 사건 증거와 법령을 검증하고 있습니다.'
              : 'Enter를 누르면 전송되며, Shift+Enter로 줄바꿈할 수 있습니다.'}
          </span>
          <span>{value.length > 0 && `${value.length}자`}</span>
        </div>
      </div>
    </footer>
  );
};

