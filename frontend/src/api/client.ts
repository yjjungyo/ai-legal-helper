/**
 * @fileoverview 법률 상담 및 사건별 대화 API 통신 클라이언트 모듈
 */

import { apiFetch } from './apiFetch';
import type { ConsultationResponse, ConversationSummary, ConversationDetail } from '../types/consultation';

/**
 * 신규 법률 상담을 시작한다.
 *
 * @param question 사용자의 법률 질의 내용
 * @param case_id 관련 사건 식별자 (선택)
 * @param conversation_id 연속된 대화 세션 식별자 (선택, 미지정 시 신규 대화 시작)
 * @returns 초기 상담 응답 객체
 */
export async function startConsultation(
  question: string,
  case_id?: string,
  conversation_id?: string,
  reanalysis_of_request_id?: string
): Promise<ConsultationResponse> {
  const res = await apiFetch(`/consultations`, {
    method: 'POST',
    body: JSON.stringify({ question, case_id, conversation_id, reanalysis_of_request_id })
  });
  if (!res.ok) throw new Error('Failed to start consultation');
  return res.json();
}

/**
 * 특정 상담 요청의 현재 진행 상태를 조회한다.
 *
 * @param requestId 상담 요청 식별자
 * @returns 상담 진행 결과 객체
 */
export async function getConsultation(requestId: string): Promise<ConsultationResponse> {
  const res = await apiFetch(`/consultations/${requestId}`);
  if (!res.ok) throw new Error('Failed to fetch consultation status');
  return res.json();
}

/**
 * 특정 사건의 저장된 상담 내역 목록을 조회한다.
 *
 * @param caseId 조회할 사건 ID
 * @param conversationId 특정 대화 세션으로 필터링할 경우의 ID (선택)
 * @returns 상담 내역 목록
 */
export async function getCaseConsultations(
  caseId: string,
  conversationId?: string
): Promise<ConsultationResponse[]> {
  const url = conversationId
    ? `/cases/${caseId}/consultations?conversation_id=${encodeURIComponent(conversationId)}`
    : `/cases/${caseId}/consultations`;
  const res = await apiFetch(url);
  if (!res.ok) throw new Error('Failed to fetch case consultations');
  return res.json();
}

/**
 * 특정 사건 내의 모든 대화 세션 요약 목록을 조회한다.
 *
 * @param caseId 사건 식별자
 * @returns 대화 세션 요약 목록
 */
export async function getCaseConversations(caseId: string): Promise<ConversationSummary[]> {
  const res = await apiFetch(`/cases/${caseId}/conversations`);
  if (!res.ok) throw new Error('Failed to fetch case conversations');
  return res.json();
}

/**
 * 특정 대화 세션의 상세 질의응답 이력을 시간순으로 조회한다.
 *
 * @param caseId 사건 식별자
 * @param conversationId 대화 세션 식별자
 * @returns 대화 세션 상세 객체
 */
export async function getCaseConversationDetail(
  caseId: string,
  conversationId: string
): Promise<ConversationDetail> {
  const res = await apiFetch(`/cases/${caseId}/conversations/${conversationId}`);
  if (!res.ok) throw new Error('Failed to fetch case conversation detail');
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
