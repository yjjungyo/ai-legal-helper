import { apiFetch } from './apiFetch';
import type { ConsultationResponse } from '../types/consultation';

export async function startConsultation(question: string, case_id?: string): Promise<ConsultationResponse> {
  const res = await apiFetch(`/consultations`, {
    method: 'POST',
    body: JSON.stringify({ question, case_id })
  });
  if (!res.ok) throw new Error('Failed to start consultation');
  return res.json();
}

export async function getConsultation(requestId: string): Promise<ConsultationResponse> {
  const res = await apiFetch(`/consultations/${requestId}`);
  if (!res.ok) throw new Error('Failed to fetch consultation status');
  return res.json();
}

/**
 * 특정 사건의 저장된 상담 내역 목록을 조회한다.
 *
 * @param caseId 조회할 사건 ID
 * @returns 상담 내역 목록
 */
export async function getCaseConsultations(caseId: string): Promise<ConsultationResponse[]> {
  const res = await apiFetch(`/cases/${caseId}/consultations`);
  if (!res.ok) throw new Error('Failed to fetch case consultations');
  return res.json();
}



