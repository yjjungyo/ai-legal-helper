/**
 * @fileoverview 단일 사건 대화 스트림(ChatMessageList) 컴포넌트
 * 사건에 속한 모든 대화 턴을 시간순으로 연속 렌더링하고, 날짜가 바뀌는 지점에 일자 구분선(ChatDateDivider)을
 * 삽입하며, 신규 메시지 수신 및 진행 상태 갱신 시 부드러운 하단 자동 스크롤을 유지합니다.
 */

import React, { useRef, useEffect } from 'react';
import type { ConsultationResponse } from '../../types/consultation';
import { ChatDateDivider } from './ChatDateDivider';
import { ChatMessage } from './ChatMessage';
import type { CitationMeta } from '../LegalAnswerView';

export interface ChatMessageListProps {
  /** 시간순(ASC)으로 정렬된 전체 대화 턴 목록 */
  messages: ConsultationResponse[];
  /** 증거 번호 [E01] 클릭 핸들러 */
  onEvidenceClick: (label: string, meta?: CitationMeta) => void;
  /** HILT 법령 검색 승인 핸들러 */
  onApprove: (requestId: string) => void;
  /** HILT 법령 검색 거절 핸들러 */
  onReject: (requestId: string) => void;
  /** HILT 승인/거절 액션 로딩 상태 */
  isActionLoading?: boolean;
  onReanalyze?: (message: ConsultationResponse) => void;
  isReanalysisDisabled?: boolean;
  /** 추천 질문 칩 클릭 시 질문 입력창에 설정하는 콜백 */
  onSelectSampleQuestion?: (question: string) => void;
}

/**
 * 두 날짜 문자열이 서로 다른 날짜(로컬 기준)인지 판별한다.
 */
function isDifferentDay(d1Str?: string, d2Str?: string): boolean {
  if (!d1Str || !d2Str) return true;
  const d1 = new Date(d1Str);
  const d2 = new Date(d2Str);
  return (
    d1.getFullYear() !== d2.getFullYear() ||
    d1.getMonth() !== d2.getMonth() ||
    d1.getDate() !== d2.getDate()
  );
}

interface SampleQuestion {
  category: string;
  question: string;
}

const SAMPLE_QUESTIONS: SampleQuestion[] = [
  {
    category: '💰 보증금 반환',
    question: '보증금 전액 반환 가능성 및 대항력 유지 요건은 어떻게 되나요?',
  },
  {
    category: '📜 계약 해지',
    question: '임대차 계약 해지 통보의 유효성과 필요 절차를 검토해주세요.',
  },
  {
    category: '🛡️ 권리 보전',
    question: '임대인의 분할반환 제안 수용 시 안전한 권리 보전 방안은 무엇인가요?',
  },
  {
    category: '⚖️ 배당 및 경매',
    question: '현재 가압류 상황에서 경매 진행 시 임차인의 배당 순위는 어떻게 되나요?',
  },
];

/**
 * 대화 스트림 목록 컴포넌트
 * @param props 메시지 배열 및 이벤트 핸들러
 * @returns 스크롤 가능한 대화 스트림 JSX
 */
export const ChatMessageList: React.FC<ChatMessageListProps> = ({
  messages,
  onEvidenceClick,
  onApprove,
  onReject,
  isActionLoading,
  onReanalyze,
  isReanalysisDisabled = false,
  onSelectSampleQuestion,
}) => {
  const bottomAnchorRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isFollowingRef = useRef(true);
  const previousLastRequestRef = useRef<string | null>(null);

  const handleScroll = () => {
    const container = containerRef.current;
    if (!container) return;
    const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
    isFollowingRef.current = nearBottom;
  };

  // 사용자 스크롤을 존중: 답변을 읽고 있을 때 단계 폴링이 화면을 아래로 끌어내리지 않는다.
  useEffect(() => {
    const container = containerRef.current;
    const last = messages[messages.length - 1];
    const isNewRequest = Boolean(last?.request_id && previousLastRequestRef.current !== last.request_id);
    if (isNewRequest) {
      previousLastRequestRef.current = last.request_id;
      // 질문 제출 시에는 새 메시지를 보여주되, 기존 요청의 진행 단계 변경으로는 읽던 위치를 바꾸지 않는다.
      if (last.status === 'IN_PROGRESS') {
        isFollowingRef.current = true;
        setShowJump(false);
      }
    }
    if (isFollowingRef.current && container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'auto' });
    }
  }, [messages.length, messages[messages.length - 1]?.status, messages[messages.length - 1]?.progress?.current_step]);

  if (messages.length === 0) {
    return (
      <main className="case-chat-stream" ref={containerRef}>
        <div className="chat-empty-state">
          <div className="chat-empty-icon" aria-hidden="true">
            ⚖️
          </div>
          <h3 className="chat-empty-title">
            사건 중심 AI 법률 상담을 시작해보세요
          </h3>
          <p className="chat-empty-subtitle">
            등록된 사건 증거(계약서, 등기부등본, 진술 등)와 확정 사실관계를 바탕으로<br />
            실제 사실에 입각한 전문적인 법률 검토와 안전한 행동 가이드를 제공합니다.
          </p>

          <div className="chat-sample-grid">
            {SAMPLE_QUESTIONS.map((item, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => onSelectSampleQuestion?.(item.question)}
                className="chat-sample-card"
              >
                <span className="chat-sample-category">{item.category}</span>
                <span className="chat-sample-text">{item.question}</span>
              </button>
            ))}
          </div>
        </div>
        <div ref={bottomAnchorRef} />
      </main>
    );
  }

  return (
    <main className="case-chat-stream" ref={containerRef} onScroll={handleScroll} role="log" aria-label="사건 상담 대화 이력">
      <div className="case-chat-stream-inner">
        {messages.map((msg, index) => {
          const prevMsg = index > 0 ? messages[index - 1] : undefined;
          const previousConsultation = msg.reanalysis_of_request_id
            ? messages.find((record) => record.request_id === msg.reanalysis_of_request_id)
            : undefined;
          const showDateDivider =
            index === 0 || isDifferentDay(prevMsg?.created_at, msg.created_at);

          return (
            <React.Fragment key={msg.request_id || `msg-${index}`}>
              {showDateDivider && msg.created_at && (
                <ChatDateDivider date={msg.created_at} />
              )}
              <ChatMessage
                message={msg}
                onEvidenceClick={onEvidenceClick}
                onApprove={onApprove}
                onReject={onReject}
                isActionLoading={isActionLoading}
                onReanalyze={onReanalyze}
                isReanalysisDisabled={isReanalysisDisabled}
              />
              {previousConsultation?.answer && msg.status === 'SUCCESS' && msg.answer && (
                <details className="chat-answer-comparison">
                  <summary>이전 상담과 재분석 답변 원문 비교</summary>
                  <p>다음은 두 상담의 답변 원문입니다. 문장 차이만으로 법률 판단이 변경되었다고 단정하지 않습니다.</p>
                  <div className="chat-answer-comparison-grid">
                    <section>
                      <h4>이전 상담 (턴 {previousConsultation.turn_index || '-'})</h4>
                      <pre>{previousConsultation.answer}</pre>
                    </section>
                    <section>
                      <h4>재분석 상담 (턴 {msg.turn_index || '-'})</h4>
                      <pre>{msg.answer}</pre>
                    </section>
                  </div>
                  <p className="chat-comparison-note">
                    {previousConsultation.answer === msg.answer
                      ? '답변 원문이 동일합니다. 증거 검토 결과도 동일한지는 별도로 확인해야 합니다.'
                      : '답변 원문에 차이가 있습니다. 추가 증거와 각 상담의 근거를 비교해 주세요.'}
                  </p>
                </details>
              )}
            </React.Fragment>
          );
        })}
        <div ref={bottomAnchorRef} style={{ height: '4px' }} />
      </div>
    </main>
  );
};
