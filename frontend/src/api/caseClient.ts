/**
 * @fileoverview 사건(Case) 생성, 목록 조회, 상세 조회, 정보 수정, 진술 추가, 워크플로우 요약, 삭제 API 클라이언트
 */
import { apiFetch } from './apiFetch';
import type { CaseBase, CaseDetail, WorkflowSummary } from '../types/case';

/**
 * 사건 기본 정보 수정 요청 인터페이스 (EVT-006)
 */
export interface CaseUpdatePayload {
  title?: string;
  case_type?: string;
  description?: string;
  status?: string;
}

/**
 * 새로운 사건을 생성한다.
 * @param title 사건 제목
 * @param case_type 사건 유형 (예: 주택임대차, 민사, 노동 등)
 * @param description 사건 개요 설명
 * @returns 생성된 사건 기본 정보
 */
export async function createCase(title: string, case_type?: string, description?: string): Promise<CaseBase> {
  const res = await apiFetch(`/cases`, {
    method: 'POST',
    body: JSON.stringify({ title, case_type, description }),
  });
  if (!res.ok) throw new Error('Failed to create case');
  return res.json();
}

/**
 * 현재 사용자의 전체 사건 목록을 조회한다.
 * @returns 사건 기본 정보 배열
 */
export async function listCases(): Promise<CaseBase[]> {
  const res = await apiFetch(`/cases`);
  if (!res.ok) throw new Error('Failed to list cases');
  return res.json();
}

/**
 * 특정 사건의 상세 정보(당사자, 사실관계, 타임라인, 쟁점 포함)를 조회한다.
 * @param caseId 사건 식별자 UUID
 * @returns 사건 상세 정보
 */
export async function getCaseDetail(caseId: string): Promise<CaseDetail> {
  const res = await apiFetch(`/cases/${caseId}`);
  if (!res.ok) throw new Error('Failed to get case');
  return res.json();
}

/**
 * 특정 사건의 기본 정보(제목, 사건 유형, 설명, 상태)를 수정한다 (EVT-006).
 * @param caseId 수정할 사건 식별자 UUID
 * @param payload 수정할 필드 객체
 * @returns 수정이 반영된 사건 상세 정보
 */
export async function updateCase(caseId: string, payload: CaseUpdatePayload): Promise<CaseDetail> {
  const res = await apiFetch(`/cases/${caseId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '사건 정보 수정에 실패했습니다.');
  }
  return res.json();
}

/**
 * 사건에 새로운 사실관계 진술(Statement)을 추가하고 AI 추출 파이프라인을 실행한다.
 * @param caseId 사건 식별자 UUID
 * @param statement 추가할 진술 텍스트
 * @returns 갱신된 사건 상세 정보
 */
export async function addStatement(caseId: string, statement: string): Promise<CaseDetail> {
  const res = await apiFetch(`/cases/${caseId}/statements`, {
    method: 'POST',
    body: JSON.stringify({ statement }),
  });
  if (!res.ok) throw new Error('Failed to add statement');
  return res.json();
}

/**
 * 사건의 진행 단계(Derived State), 통계, 다음 권장 행동(Next Action) 요약을 조회한다.
 * @param caseId 사건 식별자 UUID
 * @returns 워크플로우 요약 정보
 */
export async function getWorkflowSummary(caseId: string): Promise<WorkflowSummary> {
  const res = await apiFetch(`/cases/${caseId}/workflow/summary`);
  if (!res.ok) throw new Error('Failed to get workflow summary');
  return res.json();
}

/**
 * 사건 및 연관된 모든 데이터(증거, 사실, 상담, 대응계획, 문서, 벡터, 그래프 등)를 영구 삭제한다.
 * @param caseId 삭제할 사건 식별자 UUID
 */
export async function deleteCase(caseId: string): Promise<{ status: string; deleted_id: string; title: string }> {
  const res = await apiFetch(`/cases/${caseId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '사건 삭제에 실패했습니다.');
  }
  return res.json();
}




