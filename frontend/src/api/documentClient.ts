import { apiFetch } from './apiFetch';

export interface DocumentCreateRequest {
    document_type: string;
    title: string;
    action_id?: string;
}

export interface LegalDocument {
    id: string;
    case_id: string;
    action_id?: string;
    document_type: string;
    title: string;
    status: string;
    current_revision_id?: string;
    created_at: string;
    updated_at: string;
    revisions: DocumentRevision[];
}

export interface DocumentRevision {
    id: string;
    document_id: string;
    revision_number: number;
    content?: string;
    structured_content?: any;
    generation_context_version?: number;
    verification_status: string;
    created_at: string;
}

export async function createDocument(caseId: string, req: DocumentCreateRequest): Promise<LegalDocument> {
    const response = await apiFetch(`/cases/${caseId}/documents`, { method: 'POST', body: JSON.stringify(req) });
    if (!response.ok) throw new Error('Failed to create document');
    return response.json();
}

export async function listDocuments(caseId: string): Promise<LegalDocument[]> {
    const response = await apiFetch(`/cases/${caseId}/documents`);
    if (!response.ok) throw new Error('Failed to list documents');
    return response.json();
}

export async function exportDocument(caseId: string, documentId: string, format: string = 'docx'): Promise<Blob> {
    const response = await apiFetch(`/cases/${caseId}/documents/${documentId}/export?format=${format}`, { method: 'POST' });
    if (!response.ok) throw new Error('Failed to export document');
    return response.blob();
}
