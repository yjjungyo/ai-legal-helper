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
  /** 해당 문서에서 추출된 주장/사실 전체 건수 */
  claim_count?: number;
  /** 사실 승인 범위 (FULL_APPROVED, PARTIAL_APPROVED, ALL_REJECTED, PENDING, NO_CLAIMS) */
  approval_scope?: 'FULL_APPROVED' | 'PARTIAL_APPROVED' | 'ALL_REJECTED' | 'PENDING' | 'NO_CLAIMS';
  /** 사실 승인 범위 표시용 한글 레이블 */
  approval_scope_label?: string;
  /** 승인된 사실 건수 */
  approved_claim_count?: number;
  /** 반려(기각)된 주장 건수 */
  rejected_claim_count?: number;
  /** 검토 대기 주장 건수 */
  pending_claim_count?: number;
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

