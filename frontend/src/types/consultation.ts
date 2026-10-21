/**
 * 표준 RAG 근거 출처 인터페이스 (법령, 판례, 사건 증거, 일반 문서 통합)
 */
export interface Source {
  file: string;
  page?: string | null;

  // 표준 공통 필드
  source_id?: string | null;
  source_type?: 'STATUTE' | 'PRECEDENT' | 'CASE_EVIDENCE' | 'DOCUMENT' | string | null;
  document_id?: string | null;
  title?: string | null;
  content?: string | null;
  retrieval_method?: string | null;
  chunk_id?: string | null;
  source_url?: string | null;
  version_date?: string | null;
  retrieved_at?: string | null;

  // 법령(STATUTE) 전용 필드 (P1-02 보강)
  law_id?: string | null;
  statute_name?: string | null;
  article?: string | null;
  promulgation_date?: string | null;
  promulgation_number?: string | null;
  effective_date?: string | null;
  version_id?: string | null;

  // 판례(PRECEDENT) 전용 필드
  court?: string | null;
  case_number?: string | null;
  decision_date?: string | null;

  // 사건 증거(CASE_EVIDENCE) 및 일반 문서(DOCUMENT) 전용 필드
  evidence_id?: string | null;
  filename?: string | null;
  category?: string | null;
}

export interface UsageSummary {
  total_calls: number;
  actual_calls: number;
  estimated_calls: number;
  unavailable_calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  agent_usage?: Record<string, number>;
}

export interface StatuteSearchApprovalRequest {
  type: string;
  case_id: string;
  thread_id: string;
  trace_id: string;
  approval_request_id: string;
  reason: string;
  explanation?: string;
  missing_issue: string;
  missing_legal_issues: string[];
  candidate_laws: string[];
  search_scope: string;
  approval_required: boolean;
}

export interface ConsultationResponse {
  request_id: string;
  trace_id: string;
  status: 'IN_PROGRESS' | 'SUCCESS' | 'ERROR' | 'APPROVAL_REQUIRED';
  // 3계층 상태 분리 (P1-05 Three-Tier Status Model)
  execution_status?: 'IN_PROGRESS' | 'APPROVAL_REQUIRED' | 'COMPLETED' | 'ERROR';
  verification_status?: 'PASS' | 'REVISE' | 'INSUFFICIENT' | 'UNVERIFIED' | string;
  answer_status?: 'DELIVERED' | 'WITHHELD' | 'CAUTIONARY' | 'REVISED' | string;
  routing_status?: 'CLASSIFIED' | 'NEEDS_CLARIFICATION' | 'ROUTER_ERROR' | string;
  answer?: string;
  sources: Source[];
  elapsed_ms?: number;
  usage_summary?: UsageSummary;
  warnings: string[];
  verification_result?: {
    status: string;
    reason_code?: string;
    candidate_laws?: string[];
    missing_legal_issues?: string[];
    recommended_action?: string;
    explanation?: string;
    claims: Array<{
      claim: string;
      source_ids: string[];
      grounding_status: string;
      reason: string;
    }>;
    missing_issues: string[];
    contradictions: string[];
    warnings: string[];
  };
  revision_count?: number;
  selected_agents?: string[];
  question?: string;
  case_id?: string;
  created_at?: string;
  approval_request?: StatuteSearchApprovalRequest | null;
}


