import { useState, useEffect, useCallback } from 'react';
import type { ConsultationResponse } from '../types/consultation';
import { startConsultation, getConsultation, getCaseConsultations } from '../api/client';

/**
 * 법률 상담 실행 및 사건별 대화 이력 조회를 관리하는 Hook.
 *
 * 주요 처리:
 * 1. 사건(caseId)이 주어지면 영구 저장된 과거 상담 내역(history)을 서버에서 자동 조회한다.
 * 2. 신규 상담 요청을 전송하고 비동기 폴링을 통해 완료 시까지 상태를 추적한다.
 * 3. 상담이 완료되면 이력 목록을 새로고침하고 입력창을 초기화한다.
 *
 * 주의사항:
 * - 컴포넌트 마운트 해제 시 폴링 인터벌을 정리한다.
 * - 네트워크 오류 발생 시 에러 메시지를 UI에 전달한다.
 */
export function useConsultation(caseId?: string) {
  const [question, setQuestion] = useState('');
  const [history, setHistory] = useState<ConsultationResponse[]>([]);
  const [result, setResult] = useState<ConsultationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    if (!caseId) return;
    try {
      const records = await getCaseConsultations(caseId);
      setHistory(records);
    } catch (err) {
      console.warn("Failed to load consultation history:", err);
    }
  }, [caseId]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const submit = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    
    try {
      const initial = await startConsultation(question, caseId);
      setResult(initial);
      
      // Poll until finished
      const interval = setInterval(async () => {
        try {
          const current = await getConsultation(initial.request_id);
          setResult(current);
          if (current.status !== 'IN_PROGRESS') {
            clearInterval(interval);
            setLoading(false);
            setQuestion('');
            loadHistory();
          }
        } catch (err) {
          clearInterval(interval);
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
          loadHistory();
        }
      }, 2000);
      
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  return { question, setQuestion, history, loadHistory, submit, result, loading, error };
}

