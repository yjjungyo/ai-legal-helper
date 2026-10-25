export interface EvidenceDocument {
  id: string;
  case_id: string;
  original_filename: string;
  filename?: string;
  evidence_label?: string;
  media_type: string;
  size_bytes: number;
  status: string; // UPLOADED, EXTRACTING, REVIEW_REQUIRED, FAILED, COMPLETED
  source_kind?: string;
  error_code?: string;
  created_at: string;
  extracted_at?: string;
}

export interface EvidenceSpan {
  id: string;
  page_number?: number;
  paragraph_index?: number;
  text_excerpt: string;
}

export interface EvidenceClaim {
  id: string;
  statement: string;
  claim_type: string; // FACT, EVENT, ISSUE
  assertion_status?: string;
  confidence?: string;
  review_status: string; // PENDING, APPROVED, REJECTED, EDITED
  spans: EvidenceSpan[];
}

export interface ReviewRequest {
  action: 'APPROVE' | 'EDIT' | 'REJECT';
  new_statement?: string;
  review_reason?: string;
}

