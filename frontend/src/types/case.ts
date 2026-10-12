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
