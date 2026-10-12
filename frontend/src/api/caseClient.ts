import { apiFetch } from './apiFetch';
import type { CaseBase, CaseDetail } from '../types/case';

export async function createCase(title: string, case_type?: string, description?: string): Promise<CaseBase> {
  const res = await apiFetch(`/cases`, {
    method: 'POST',
    body: JSON.stringify({ title, case_type, description })
  });
  if (!res.ok) throw new Error('Failed to create case');
  return res.json();
}

export async function listCases(): Promise<CaseBase[]> {
  const res = await apiFetch(`/cases`);
  if (!res.ok) throw new Error('Failed to list cases');
  return res.json();
}

export async function getCaseDetail(caseId: string): Promise<CaseDetail> {
  const res = await apiFetch(`/cases/${caseId}`);
  if (!res.ok) throw new Error('Failed to get case');
  return res.json();
}

export async function addStatement(caseId: string, statement: string): Promise<CaseDetail> {
  const res = await apiFetch(`/cases/${caseId}/statements`, {
    method: 'POST',
    body: JSON.stringify({ statement })
  });
  if (!res.ok) throw new Error('Failed to add statement');
  return res.json();
}


