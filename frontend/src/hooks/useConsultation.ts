/**
 * @fileoverview 사건 중심 단일 지속 대화(Case-Centric Chat) 관리 커스텀 Hook 모듈
 * 
 * [개선 사항 - Case = One Persistent Conversation (P0-01, P0-02, P0-04, P0-05)]
 * 1. '새 대화 시작' 완전 제거: 사건 식별자(caseId)당 단일 대화 스트림(messages)으로 일원화.
 * 2. 메시지 배열 단일화 (messages):
 *    - 과거 이력과 진행 중인 상담을 분리하지 않고 시간순(ASC) 단일 배열로 관리.
 *    - 새 질문 전송 시 스트림 하단에 진행 상태(IN_PROGRESS) 카드가 추가되고 완료 시 인플레이스 전이.
 * 3. 브라우저 새로고침(F5) 시 영속성 복원:
 *    - 페이지 재진입 시 DB에서 사건의 전체 상담 이력을 시간순 복원하고,
 *      마지막 메시지가 IN_PROGRESS인 경우 자동으로 상태 폴링을 재개.
 * 4. HILT 승인/거절 인플레이스 제어:
 *    - 승인 시 실시간 공식 법령 검색 및 재분석 폴링 재개, 거절 시 현재 근거 기반 종결.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { ConsultationResponse } from '../types/consultation';
import {
  startConsultation,
  getConsultation,
  getCaseConsultations,
  approveStatuteSearch,
} from '../api/client';

/**
 * 사건 중심 단일 지속 대화 Hook
 * @param caseId 현재 작업 중인 사건 식별자 UUID
 */
export function useConsultation(caseId?: string) {
  const [question, setQuestion] = useState('');
  /** 사건의 단일 대화 세션 식별자 (서버의 Case.primary_conversation_id와 동기화) */
  const [conversationId, setConversationId] = useState<string | null>(null);
  /** 사건의 전체 상담 턴 목록 (시간순 ASC 정렬) */
  const [messages, setMessages] = useState<ConsultationResponse[]>([]);
  /** 상담 요청 전송 및 폴링 진행 중 여부 */
  const [loading, setLoading] = useState(false);
  /** HILT 승인/거절 액션 처리 중 여부 */
  const [actionLoading, setActionLoading] = useState(false);
  /** 오류 메시지 */
  const [error, setError] = useState<string | null>(null);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /**
   * 폴링 인터벌 해제
   */
  const clearPollInterval = useCallback(() => {
    if (pollIntervalRef.current !== null) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  /**
   * 단일 메시지 객체 업데이트 헬퍼
   */
  const updateMessageInList = useCallback((updated: ConsultationResponse) => {
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.request_id === updated.request_id);
      if (idx !== -1) {
        const copy = [...prev];
        copy[idx] = updated;
        return copy;
      }
      return [...prev, updated];
    });
  }, []);

  /**
   * 지정된 상담 요청 ID의 진행 상태를 1.5초 주기로 폴링
   */
  const startPolling = useCallback(
    (requestId: string) => {
      clearPollInterval();
      setLoading(true);

      pollIntervalRef.current = setInterval(async () => {
        try {
          const current = await getConsultation(requestId);
          updateMessageInList(current);

          if (current.conversation_id) {
            setConversationId(current.conversation_id);
          }

          // 1. HILT 승인 대기 상태 도달 시: 폴링 멈추고 사용자 승인 대기
          if (current.status === 'APPROVAL_REQUIRED') {
            clearPollInterval();
            setLoading(false);
          } else if (current.status === 'SUCCESS' || current.status === 'ERROR') {
            // 2. 최종 완료 상태 도달 시: 폴링 종료
            clearPollInterval();
            setLoading(false);
          }
        } catch (err) {
          clearPollInterval();
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      }, 1500);
    },
    [clearPollInterval, updateMessageInList]
  );

  /**
   * 사건의 전체 상담 이력을 조회하고 진행 중인 상담이 있다면 폴링을 자동 재개한다.
   */
  const loadCaseChat = useCallback(async () => {
    if (!caseId) return;
    try {
      const records = await getCaseConsultations(caseId);
      // 서버에서 ASC 정렬되어 오지만, 방어적으로 정렬 보장
      const sorted = [...records].sort((a, b) => {
        const tA = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tB = b.created_at ? new Date(b.created_at).getTime() : 0;
        return tA - tB;
      });
      setMessages(sorted);

      if (sorted.length > 0) {
        const lastMsg = sorted[sorted.length - 1];
        if (lastMsg.conversation_id) {
          setConversationId(lastMsg.conversation_id);
        }
        // 마지막 메시지가 진행 중이면 자동 폴링 복원
        if (lastMsg.status === 'IN_PROGRESS') {
          startPolling(lastMsg.request_id);
        }
      }
    } catch (err) {
      console.warn('[useConsultation] Failed to load case consultations:', err);
    }
  }, [caseId, startPolling]);

  // 마운트 및 caseId 변경 시 이력 로드
  useEffect(() => {
    loadCaseChat();
    return () => {
      clearPollInterval();
    };
  }, [loadCaseChat, clearPollInterval]);

  /**
   * 새 질문 전송
   */
  const sendQuestion = useCallback(
    async (questionText?: string, reanalysisOfRequestId?: string) => {
      const query = (questionText !== undefined ? questionText : question).trim();
      if (!query || !caseId || loading) return;

      clearPollInterval();
      setLoading(true);
      setError(null);
      setQuestion('');

      try {
        const initial = await startConsultation(
          query,
          caseId,
          conversationId || undefined,
          reanalysisOfRequestId
        );

        if (initial.conversation_id) {
          setConversationId(initial.conversation_id);
        }

        // 메시지 스트림에 즉시 추가
        updateMessageInList(initial);

        // 실시간 상태 추적 시작
        startPolling(initial.request_id);
      } catch (err) {
        clearPollInterval();
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      }
    },
    [question, caseId, loading, conversationId, clearPollInterval, updateMessageInList, startPolling]
  );

  /**
   * HILT 외부 법령 검색 승인 또는 거절 처리
   */
  const handleApproval = useCallback(
    async (requestId: string, approved: boolean) => {
      setActionLoading(true);
      setError(null);

      try {
        const updated = await approveStatuteSearch(requestId, approved);
        updateMessageInList(updated);

        if (approved) {
          // 승인 시 공식 법령 검색 및 재분석 진행되므로 폴링 재개
          startPolling(requestId);
        } else {
          // 거절 시 추가 검색 없이 현재 결과로 종결
          setLoading(false);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setActionLoading(false);
      }
    },
    [updateMessageInList, startPolling]
  );

  // 하위 호환성 (구 ChatSection 등에서 사용하는 프로퍼티 매핑)
  const activeRecord = messages.find(
    (m) => m.status === 'IN_PROGRESS' || m.status === 'APPROVAL_REQUIRED'
  );

  return {
    question,
    setQuestion,
    conversationId,
    messages,
    loading,
    actionLoading,
    error,
    sendQuestion,
    submit: () => sendQuestion(),
    handleApproval,
    refreshChat: loadCaseChat,
    reanalyze: (prior: ConsultationResponse) => sendQuestion(prior.question || '', prior.request_id),
    // 하위 호환 필드
    result: activeRecord || null,
    history: messages,
    startNewConversation: () => {
      // P0-01: 새 대화 시작 기능 제거, 호환용 no-op
      console.warn('startNewConversation is deprecated in Case-Centric chat.');
    },
  };
}
