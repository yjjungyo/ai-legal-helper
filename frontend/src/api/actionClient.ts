/**
 * @fileoverview 법률 대응 행동 계획(LegalAction) 조회, AI 생성, 진행 상태 및 요건 충족 상태 변경 API 클라이언트 모듈
 */
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

/**
 * 특정 대응 조치(LegalAction)의 진행 상태(PENDING, IN_PROGRESS, COMPLETED)를 변경합니다.
 */
export async function updateActionStatus(
    caseId: string,
    actionId: string,
    status: string,
): Promise<LegalAction> {
    const response = await apiFetch(`/cases/${caseId}/actions/${actionId}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
    });
    if (!response.ok) throw new Error('Failed to update action status');
    return response.json();
}

/**
 * 특정 대응 조치의 사전 필요 요건(ActionRequirement) 충족 상태(SATISFIED / UNSATISFIED)를 변경합니다.
 */
export async function updateRequirementStatus(
    caseId: string,
    actionId: string,
    requirementId: string,
    satisfactionStatus: string,
): Promise<ActionRequirement> {
    const response = await apiFetch(
        `/cases/${caseId}/actions/${actionId}/requirements/${requirementId}`,
        {
            method: 'PATCH',
            body: JSON.stringify({ satisfaction_status: satisfactionStatus }),
        },
    );
    if (!response.ok) throw new Error('Failed to update requirement status');
    return response.json();
}

