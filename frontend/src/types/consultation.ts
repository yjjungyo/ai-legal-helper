export interface Source {
  file: string;
  page: string;
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

export interface ConsultationResponse {
  request_id: string;
  trace_id: string;
  status: 'IN_PROGRESS' | 'SUCCESS' | 'ERROR';
  answer?: string;
  sources: Source[];
  elapsed_ms?: number;
  usage_summary?: UsageSummary;
  warnings: string[];
  verification_result?: {
    status: string;
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
}

