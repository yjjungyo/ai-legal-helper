import { apiFetch } from './apiFetch';

export const getCaseGraph = async (caseId: string): Promise<any> => {
  const res = await apiFetch(`/cases/${caseId}/graph`);
  if (!res.ok) throw new Error('Failed to fetch case graph');
  return res.json();
};

export const getGraphAnalysis = async (caseId: string): Promise<any> => {
  const res = await apiFetch(`/cases/${caseId}/graph/analysis`);
  if (!res.ok) throw new Error('Failed to fetch graph analysis');
  return res.json();
};
