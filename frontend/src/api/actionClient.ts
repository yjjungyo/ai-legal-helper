import { apiFetch } from './apiFetch';

export interface ActionRequirement {
    id: string;
    requirement_type: string;
    description?: string;
    satisfaction_status: string;
    supporting_evidence_ids?: string[];
}

export interface ActionDeadline {
    id: string;
    deadline_type: string;
    deadline_date?: string;
    calculation_basis?: string;
    verification_status: string;
}

export interface ActionDependency {
    id: string;
    depends_on_action_id: string;
    dependency_type: string;
}

export interface LegalAction {
    id: string;
    action_type: string;
    title: string;
    description?: string;
    priority: string;
    status: string;
    rationale?: string;
    risk_level: string;
    requirements: ActionRequirement[];
    deadlines: ActionDeadline[];
    dependencies_out: ActionDependency[];
}

export async function getActionPlan(caseId: string): Promise<LegalAction[]> {
    const response = await apiFetch(`/cases/${caseId}/actions`);
    if (!response.ok) throw new Error('Failed to get action plan');
    return response.json();
}

export async function createActionPlan(caseId: string): Promise<LegalAction[]> {
    const response = await apiFetch(`/cases/${caseId}/actions/plan`, { method: 'POST' });
    if (!response.ok) throw new Error('Failed to create action plan');
    return response.json();
}
