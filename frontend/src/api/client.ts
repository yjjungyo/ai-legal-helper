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

/**
 * HILT 법령 원문 검색 승인/거절 결정을 서버로 전송한다.
 *
 * @param requestId 대상 상담 요청 ID
 * @param approved 사용자 승인 여부 (true: 승인, false: 거절)
 * @param reason 승인 또는 거절 사유 메모
 * @returns 갱신된 상담 응답 객체
 */
export async function approveStatuteSearch(
  requestId: string,
  approved: boolean,
  reason?: string
): Promise<ConsultationResponse> {
  const res = await apiFetch(`/consultations/${requestId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved, reason })
  });
  if (!res.ok) throw new Error('Failed to submit statute search approval decision');
  return res.json();
}




