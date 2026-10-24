/**
 * @fileoverview 법률 상담 관련 표준 TypeScript 타입 정의 모듈
 * (RAG 출처, 사용량 요약, 승인 요청, 상담 응답 및 대화 세션 모델)
 */

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
  evidence_label?: string | null;
  label?: string | null;
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

export type ApprovalRequest = StatuteSearchApprovalRequest;

/**
 * 상담 단계별 세부 실행 상태 열거형 (P0-05)
 */
export type ConsultationStepStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'COMPLETED'
  | 'SKIPPED'
  | 'WAITING_APPROVAL'
  | 'FAILED';

/**
 * 상담 진행 단계 세부 정보 모델 (P0-05)
 */
export interface ConsultationStep {
  step_id: string;
  title: string;
  step_name?: string;
  status: ConsultationStepStatus;
  started_at?: string;
  completed_at?: string;
  message?: string;
}

/**
 * 상담 전체 6단계 진행 상태 모델 (P0-05)
 */
export interface ConsultationProgress {
  request_id: string;
  current_step: string | null;
  current_step_name?: string | null;
  steps: ConsultationStep[];
  updated_at: string;
}


export interface ConsultationResponse {
  request_id: string;
  conversation_id?: string;
  turn_index?: number;
  trace_id: string;
  status: 'IN_PROGRESS' | 'SUCCESS' | 'ERROR' | 'APPROVAL_REQUIRED';
  detail?: string;
  final_disposition?: string;
  // 3계층 상태 분리 (P1-05 Three-Tier Status Model)
  execution_status?: 'IN_PROGRESS' | 'APPROVAL_REQUIRED' | 'COMPLETED' | 'ERROR';
  verification_status?: 'PASS' | 'REVISE' | 'INSUFFICIENT' | 'UNVERIFIED' | string;
  answer_status?: 'DELIVERED' | 'WITHHELD' | 'CAUTIONARY' | 'REVISED' | string;
  routing_status?: 'CLASSIFIED' | 'NEEDS_CLARIFICATION' | 'ROUTER_ERROR' | string;
  intent?: string;
  resolved_query?: string;
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
  // 쟁점별 검증 및 증거 근거 필드 (Issue-Level Verification v1.0)
  issue_results?: Array<{
    issue_id: string;
    issue_type: string;
    title: string;
    status: string;
    fact_grounding_status?: string;
    legal_grounding_status?: string;
    reason_code?: string;
    reason?: string;
    cited_evidence_labels?: string[];
    missing_evidence_categories?: string[];
  }>;
  verified_facts?: string[];
  missing_evidence?: string[];
  evidence_citations?: Source[];
  // 사건 중심 Chat v1.1 6단계 실시간 진행 상태 (P0-05)
  progress?: ConsultationProgress | null;
}

/**
 * 사건 내 개별 대화 세션 요약 인터페이스
 */
export interface ConversationSummary {
  conversation_id: string;
  case_id?: string;
  first_question: string;
  last_question: string;
  last_answer?: string | null;
  turns_count: number;
  last_status: string;
  last_answer_status?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * 특정 대화 세션의 상세 턴 이력 인터페이스
 */
export interface ConversationDetail {
  conversation_id: string;
  case_id?: string;
  turns: ConsultationResponse[];
}
