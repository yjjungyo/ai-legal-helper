export interface Party {
  id: string;
  name: string;
  role?: string;
  party_relationship?: string;
  notes?: string;
}

export interface Fact {
  id: string;
  statement: string;
  fact_type?: string;
  confidence?: number;
  source_type: string;
  occurred_at?: string;
  verification_status: string;
}

export interface Event {
  id: string;
  title: string;
  description?: string;
  event_date?: string;
  date_precision: string;
  event_type?: string;
}

export interface LegalIssue {
  id: string;
  title: string;
  description?: string;
  status: string;
}

export interface CaseBase {
  id: string;
  title: string;
  case_type?: string;
  description?: string;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface CaseDetail extends CaseBase {
  parties: Party[];
  facts: Fact[];
  events: Event[];
  legal_issues: LegalIssue[];
}

export interface NextAction {
  title: string;
  description: string;
  tab_id: string;
}

export interface WorkflowStats {
  facts_count: number;
  parties_count: number;
  events_count: number;
  issues_count: number;
  evidences_count: number;
  claims_pending_count: number;
  claims_approved_count: number;
  conflicts_count: number;
  actions_count: number;
  documents_count: number;
  consultations_count: number;
}

export interface WorkflowSummary {
  case_id: string;
  title: string;
  case_type?: string;
  status: string;
  created_at: string;
  updated_at: string;
  stage_code: string;
  stage_name: string;
  next_action: NextAction;
  stats: WorkflowStats;
  consultation_preview?: {
    total_count: number;
    last_question: string;
    last_answer_snippet: string;
    last_consulted_at?: string;
  };
  recent_evidences: Array<{ id: string; filename: string; status: string; uploaded_at?: string }>;
  recent_claims: Array<{ id: string; statement: string; claim_type?: string; status: string }>;
  recent_actions: Array<{ id: string; title: string; priority: string; risk_level: string; action_type: string; status: string }>;
  recent_documents: Array<{ id: string; title: string; doc_type: string; status: string }>;
  issues_preview: Array<{ id: string; title: string; status: string }>;
  timeline_preview: Array<{ id: string; title: string; event_date?: string }>;
  recent_activities: Array<{ type: string; title: string; time?: string; tab_id: string }>;
}
