/**
 * @fileoverview 법률 상담 실행 및 사건별 대화 이력 조회를 관리하는 커스텀 Hook 모듈
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import type { ConsultationResponse } from '../types/consultation';
import { startConsultation, getConsultation, getCaseConsultations, approveStatuteSearch } from '../api/client';

/**
 * 법률 상담 실행 및 사건별 대화 이력 조회를 관리하는 Hook.
 *
 * 주요 처리:
 * 1. 사건(caseId)이 주어지면 영구 저장된 과거 상담 내역(history)을 서버에서 자동 조회한다.
 * 2. 신규 상담 요청을 전송하고 비동기 폴링을 통해 완료 시까지 상태를 추적한다.
 * 3. HILT 법령 검색 승인/거절 요청(respondApproval)을 처리하고 재개된 워크플로우를 폴링한다.
 * 4. 상담이 완료되면 이력 목록을 새로고침하고 입력창을 초기화한다.
 */
export function useConsultation(caseId?: string) {
  const [question, setQuestion] = useState('');
  const [history, setHistory] = useState<ConsultationResponse[]>([]);
  const [result, setResult] = useState<ConsultationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearPollInterval = useCallback(() => {
    if (pollIntervalRef.current !== null) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const loadHistory = useCallback(async () => {
    if (!caseId) return;
    try {
      const records = await getCaseConsultations(caseId);
      setHistory(records);
    } catch (err) {
      console.warn('Failed to load consultation history:', err);
    }
  }, [caseId]);

  useEffect(() => {
    loadHistory();
    return () => {
      clearPollInterval();
    };
  }, [loadHistory, clearPollInterval]);

  const submit = async () => {
    if (!question.trim()) return;
    clearPollInterval();
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const initial = await startConsultation(question, caseId);
      setResult(initial);

      // 비동기 상담 완료 시까지 2초 주기로 상태 폴링
      pollIntervalRef.current = setInterval(async () => {
        try {
          const current = await getConsultation(initial.request_id);
          setResult(current);
          if (current.status !== 'IN_PROGRESS') {
            clearPollInterval();
            setLoading(false);
            if (current.status === 'SUCCESS' || current.status === 'ERROR') {
              setQuestion('');
            }
            loadHistory();
          }
        } catch (err) {
          clearPollInterval();
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
          loadHistory();
        }
      }, 2000);
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

    try {
      const updated = await approveStatuteSearch(requestId, approved, reason);
      setResult(updated);

      // 재개된 워크플로우 완료 시까지 2초 주기로 상태 폴링
      pollIntervalRef.current = setInterval(async () => {
        try {
          const current = await getConsultation(requestId);
          setResult(current);
          if (current.status !== 'IN_PROGRESS' && current.status !== 'APPROVAL_REQUIRED') {
            clearPollInterval();
            setLoading(false);
            setQuestion('');
            loadHistory();
          }
        } catch (err) {
          clearPollInterval();
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
          loadHistory();
        }
      }, 2000);
    } catch (err) {
      clearPollInterval();
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  return {
    question,
    setQuestion,
    history,
    loadHistory,
    submit,
    respondApproval,
    result,
    loading,
    error,
  };
}



