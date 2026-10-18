import { apiFetch } from './apiFetch';
import type { EvidenceDocument, EvidenceClaim, ReviewRequest } from '../types/evidence';

export const uploadEvidence = async (caseId: string, file: File): Promise<EvidenceDocument> => {
  const formData = new FormData();
  formData.append('file', file);

  const response = await apiFetch(`/cases/${caseId}/evidence`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    const msg = errorData?.detail || `증거 업로드 실패 (HTTP ${response.status})`;
    throw new Error(msg);
  }
  return response.json();
};

export const deleteEvidence = async (caseId: string, evidenceId: string): Promise<any> => {
  const response = await apiFetch(`/cases/${caseId}/evidence/${evidenceId}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || '증거 삭제에 실패했습니다.');
  }
  return response.json();
};

export const listEvidence = async (caseId: string): Promise<EvidenceDocument[]> => {
  const response = await apiFetch(`/cases/${caseId}/evidence`);
  if (!response.ok) throw new Error('Failed to list evidence');
  return response.json();
};

export const extractEvidence = async (caseId: string, evidenceId: string): Promise<any> => {
  const response = await apiFetch(`/cases/${caseId}/evidence/${evidenceId}/extract`, { method: 'POST' });
  if (!response.ok) throw new Error('Failed to extract evidence');
  return response.json();
};

export const getEvidenceClaims = async (caseId: string, evidenceId: string): Promise<EvidenceClaim[]> => {
  const response = await apiFetch(`/cases/${caseId}/evidence/${evidenceId}/claims`);
  if (!response.ok) throw new Error('Failed to get claims');
  return response.json();
};

export const reviewEvidenceClaim = async (caseId: string, evidenceId: string, claimId: string, reviewReq: ReviewRequest): Promise<any> => {
  const response = await apiFetch(`/cases/${caseId}/evidence/${evidenceId}/claims/${claimId}/review`, {
    method: 'POST',
    body: JSON.stringify(reviewReq)
  });
  if (!response.ok) throw new Error('Failed to review claim');
  return response.json();
};

export const getEvidenceConflicts = async (caseId: string): Promise<any> => {
  const response = await apiFetch(`/cases/${caseId}/evidence/conflicts`);
  if (!response.ok) throw new Error('Failed to get conflicts');
  return response.json();
};

