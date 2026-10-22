/**
 * @fileoverview 법률 상담 실행 및 사건별 대화 이력 조회를 관리하는 커스텀 Hook 모듈
 * 
 * [개선 사항 - Phase 1: Context-Aware Multi-turn Conversation]
 * 1. `activeConversationId` 대화 세션 상태 관리:
 *    - 연속 질문 시 동일 conversation_id를 서버로 전달하여 이전 질의응답 맥락을 복원합니다.
 *    - `startNewConversation()` 호출 시 대화 세션을 초기화하여 완전히 새로운 대화를 시작할 수 있습니다.
 * 2. 활성 상담(Active Consultation)과 완료된 상담 이력(History)의 엄격한 분리:
 *    - IN_PROGRESS / APPROVAL_REQUIRED 상태의 상담은 `result`(활성 상담) 상태로만 관리하고,
 *    - `history`에는 최종 완료(SUCCESS / ERROR)된 과거 상담 기록만 필터링하여 보관합니다.
 * 3. 브라우저 새로고침(F5) 시 세션 연속성 복원:
 *    - 페이지 재진입 시 서버 DB에서 최신 미완료 상담을 감지하여 `result`로 자동 복원하고,
 *      진행 중인 경우 폴링을 자동 재개합니다.
 * 4. HILT 승인/거절 시 단일화된 폴링 및 낙관적 상태 전이 처리.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import type { ConsultationResponse } from '../types/consultation';
import { startConsultation, getConsultation, getCaseConsultations, approveStatuteSearch } from '../api/client';

/**
 * 법률 상담 실행 및 사건별 대화 이력 조회를 관리하는 Hook.
 *
 * @param caseId 현재 작업 중인 사건 식별자 UUID
 * @returns 상담 입력값, 완료된 이력 목록, 현재 활성 상담 결과, 대화 세션 ID, 로딩 및 오류 상태, 실행 액션 함수들
 */
export function useConsultation(caseId?: string) {
  const [question, setQuestion] = useState('');
  /** 현재 활성화된 연속 대화 세션 식별자 (null인 경우 신규 대화 시작) */
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  /** 완료된 과거 상담 내역만 보관 (IN_PROGRESS, APPROVAL_REQUIRED 제외) */
  const [history, setHistory] = useState<ConsultationResponse[]>([]);
  /** 현재 진행 중이거나 사용자 승인 대기 중인 단일 활성 상담 객체 */
  const [result, setResult] = useState<ConsultationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /**
   * 실행 중인 상태 폴링 인터벌을 안전하게 해제한다.
   */
  const clearPollInterval = useCallback(() => {
    if (pollIntervalRef.current !== null) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  /**
   * 새로운 대화 세션을 시작하도록 현재 대화 ID와 입력을 초기화한다.
   */
  const startNewConversation = useCallback(() => {
    setActiveConversationId(null);
    setQuestion('');
    setResult(null);
  }, []);

  /**
   * 지정된 상담 요청 ID의 진행 상태를 2초 주기로 주기적 조회(Polling)한다.
   *
   * @param requestId 추적 대상 상담 요청 식별자
   */
  const startPolling = useCallback(
    (requestId: string) => {
      clearPollInterval();
      setLoading(true);

      pollIntervalRef.current = setInterval(async () => {
        try {
          const current = await getConsultation(requestId);
          setResult(current);

          // conversation_id 동기화
          if (current.conversation_id) {
            setActiveConversationId(current.conversation_id);
          }

          // 1. HILT 추가 법령 검색 승인 대기 상태로 전이된 경우: 폴링 일시중지 후 사용자 입력 대기
          if (current.status === 'APPROVAL_REQUIRED') {
            clearPollInterval();
            setLoading(false);
          } else if (current.status === 'SUCCESS' || current.status === 'ERROR') {
            // 2. 최종 완료(SUCCESS) 또는 오류(ERROR) 상태 도달 시: 폴링 종료 및 이력 목록 갱신
            clearPollInterval();
            setLoading(false);
            setQuestion('');

            if (caseId) {
              const records = await getCaseConsultations(caseId);
              // 완료된 기록만 history에 보관
              const completedRecords = records.filter(
                (r) => r.status !== 'IN_PROGRESS' && r.status !== 'APPROVAL_REQUIRED'
              );
              setHistory(completedRecords);
            }
            // 활성 작업 완료 -> 활성 카드 닫고 상담 이력 최상단에 완료된 답변으로 표시
            setResult(null);
          }
        } catch (err) {
          clearPollInterval();
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      }, 2000);
    },
    [caseId, clearPollInterval]
  );

  /**
   * 사건의 상담 내역을 조회하고, 활성 상담과 완료 이력을 분리하여 상태를 동기화한다.
   * 새로고침(F5) 시 진행 중이던 상담이 있을 경우 자동으로 활성 영역으로 복원하고 폴링을 재개한다.
   */
  const loadHistory = useCallback(async () => {
    if (!caseId) return;
    try {
      const records = await getCaseConsultations(caseId);

      // 최신 레코드 중 미완료(진행 중이거나 승인 대기) 건 탐색
      const activeRecord = records.find(
        (r) => r.status === 'IN_PROGRESS' || r.status === 'APPROVAL_REQUIRED'
      );

      if (activeRecord) {
        // 활성 작업 복원 및 폴링 재개
        setResult(activeRecord);
        if (activeRecord.conversation_id) {
          setActiveConversationId(activeRecord.conversation_id);
        }
        if (activeRecord.status === 'IN_PROGRESS') {
          startPolling(activeRecord.request_id);
        }
      } else {
        setResult(null);
        // 가장 최근에 완료된 대화가 있다면 해당 대화 세션을 기본 활성 대화로 지정
        if (records.length > 0 && records[0].conversation_id) {
          setActiveConversationId(records[0].conversation_id);
        }
      }

      // 완료된 기록만 과거 이력(history)에 반영
      const completedRecords = records.filter(
        (r) => r.status !== 'IN_PROGRESS' && r.status !== 'APPROVAL_REQUIRED'
      );
      setHistory(completedRecords);
    } catch (err) {
      console.warn('Failed to load consultation history:', err);
    }
  }, [caseId, startPolling]);

  // 마운트 및 caseId 변경 시 이력 조회 및 미완료 작업 복원
  useEffect(() => {
    loadHistory();
    return () => {
      clearPollInterval();
    };
  }, [loadHistory, clearPollInterval]);

  /**
   * 신규 또는 후속 법률 상담 요청을 서버에 전송하고 실시간 진행 상태 추적을 시작한다.
   */
  const submit = async () => {
    if (!question.trim() || !caseId) return;
    clearPollInterval();
    setLoading(true);
    setError(null);

    try {
      const initial = await startConsultation(
        question,
        caseId,
        activeConversationId || undefined
      );

      if (initial.conversation_id) {
        setActiveConversationId(initial.conversation_id);
      }

      // 활성 상담 상태로 등록하고 폴링 시작
      setResult(initial);
      startPolling(initial.request_id);
    } catch (err) {
      clearPollInterval();
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  /**
   * HILT 법령 원문 검색 승인 또는 거절 결정을 서버로 전송하고 재개 상태를 폴링한다.
   *
   * @param requestId 대상 상담 요청 ID
   * @param approved 사용자 승인 여부 (true: 승인 후 공식 법령 검색 진행, false: 거절 후 판단 유보)
   * @param reason 승인 또는 거절 사유 메모
   */
  const respondApproval = async (requestId: string, approved: boolean, reason?: string) => {
    clearPollInterval();
    setLoading(true);
    setError(null);

    // 1. 낙관적(Optimistic) UI 업데이트: 활성 상담의 상태를 IN_PROGRESS로 즉시 전이
    setResult((prev) =>
      prev && prev.request_id === requestId
        ? {
            ...prev,
            status: 'IN_PROGRESS',
            execution_status: 'IN_PROGRESS',
            answer_status: 'WITHHELD',
          }
        : prev
    );

    try {
      // 2. 서버에 승인 결정 전달 및 재개된 워크플로우 폴링 시작
      await approveStatuteSearch(requestId, approved, reason);
      startPolling(requestId);
    } catch (err) {
      clearPollInterval();
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  return {
    question,
    setQuestion,
    activeConversationId,
    setActiveConversationId,
    startNewConversation,
    history,
    loadHistory,
    submit,
    respondApproval,
    result,
    loading,
    error,
  };
}
