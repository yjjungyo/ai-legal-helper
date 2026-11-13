/**
 * @fileoverview LangGraph 6단계 법률 상담 진행 상태 추적 및 HITL 승인 인터랙션 컴포넌트
 * 사건 분석 의도 파악부터 증거 매핑, 법령 분석, 쟁점 교차 검증, 미보유 법령 승인, 최종 답변 종합까지
 * 실시간 상태(RUNNING, COMPLETED, WAITING_APPROVAL, SKIPPED, FAILED)를 단계별 체크리스트로 시각화합니다.
 * 특히 3단계(관련 법령 및 판례 검색)에서는 벡터DB 및 국가법령정보센터 2대 채널의 실시간 검색 진행과
 * 찾은 법령명·제목 결과를 계층형 트리(Tree) 구조로 상세 표시하며, 다른 단계의 중복 안내 문구는 배제합니다.
 */

import React from 'react';
import type { ConsultationProgress as IConsultationProgress, ConsultationStep, ApprovalRequest } from '../../types/consultation';

export interface ConsultationProgressProps {
  /** 백엔드 LangGraph 진행 상태 객체 */
  progress?: IConsultationProgress | null;
  /** 현재 상담 요청의 전체 상태 (IN_PROGRESS, APPROVAL_REQUIRED 등) */
  status: string;
  /** HITL 외부 법령 검색 승인 요청 세부 정보 */
  approvalRequest?: ApprovalRequest | null;
  /** 승인 버튼 클릭 콜백 */
  onApprove: (requestId: string) => void;
  /** 거절/건너뛰기 버튼 클릭 콜백 */
  onReject: (requestId: string) => void;
  /** 상담 요청 식별자 UUID */
  requestId: string;
  /** 승인/거절 액션 처리 중 여부 */
  isActionLoading?: boolean;
  /** 최종 분석 및 답변 완료 여부 (완료 시 보존 모드로 전환) */
  isCompleted?: boolean;
}

/**
 * 기본 6단계 정의 (서버 프로그레스가 아직 없을 때 기본 템플릿으로 사용)
 */
const DEFAULT_STEPS: ConsultationStep[] = [
  { step_id: 'INTENT_ANALYSIS', title: '사건 정보와 이전 상담 맥락 확인', status: 'PENDING' },
  { step_id: 'FACT_RETRIEVAL', title: '사실관계·타임라인·증거 조회', status: 'PENDING' },
  { step_id: 'LEGAL_RESEARCH', title: '관련 법령 및 판례 검색', status: 'PENDING' },
  { step_id: 'VERIFICATION', title: '법률 쟁점별 분석', status: 'PENDING' },
  { step_id: 'STATUTE_APPROVAL', title: '증거·법률 근거 검증', status: 'PENDING' },
  { step_id: 'FINAL_SYNTHESIS', title: '최종 상담 답변 작성', status: 'PENDING' },
];

/**
 * 법령 검색 채널 분류 타입 (로컬 Chroma 벡터DB, OpenLaw 공식 API, 둘 다 병행)
 */
export type StatuteSearchChannel = 'VECTOR_DB' | 'OPENLAW_API' | 'HYBRID' | null;

/**
 * 법령 검색 채널 파싱 세부 정보
 */
export interface StatuteChannelDetails {
  /** 자동 승인 모드 여부 */
  isAutoApproved: boolean;
  /** 검색 채널 분류 */
  channel: StatuteSearchChannel;
  /** 채널 시각화 텍스트 레이블 (예: '📦 로컬 벡터DB') */
  channelLabel: string;
  /** 접두사 및 법령목록을 제외한 본문 안내 메시지 */
  cleanMessage: string;
  /** 찾은 법령명 및 제목 목록 (예: ['주택임대차보호법 제3조 (대항력 등)']) */
  statuteItems: string[];
}

/**
 * 단계 안내 메시지로부터 자동 승인 여부, 검색 채널, 찾은 법령명 및 제목 목록을 추출한다.
 */
function parseStatuteChannelDetails(step: ConsultationStep): StatuteChannelDetails {
  const rawMsg = step.message || '';
  const isAutoApproved = rawMsg.includes('[자동승인]') || rawMsg.includes('자동승인');

  const hasVector =
    rawMsg.includes('벡터DB') ||
    rawMsg.includes('Chroma') ||
    rawMsg.includes('VECTOR_DB') ||
    rawMsg.includes('로컬');
  const hasOpenLaw =
    rawMsg.includes('OpenLaw') ||
    rawMsg.includes('공식 API') ||
    rawMsg.includes('OPENLAW_API') ||
    rawMsg.includes('국가법령');

  let channel: StatuteSearchChannel = null;
  let channelLabel = '';

  if (hasVector && hasOpenLaw) {
    channel = 'HYBRID';
    channelLabel = '⚡ 벡터DB + OpenLaw API';
  } else if (hasVector) {
    channel = 'VECTOR_DB';
    channelLabel = '📦 로컬 벡터DB';
  } else if (hasOpenLaw) {
    channel = 'OPENLAW_API';
    channelLabel = '🌐 OpenLaw API';
  }

  // 앞의 [자동승인] 접두사를 제거
  const text = rawMsg.replace(/^\[자동승인(?:\s*완료)?\]\s*/, '').trim();

  // '|' 기호가 포함된 경우 (예: "로컬 벡터DB에서 2건 확보 | 주택임대차보호법 제3조 (대항력 등) · 민법 제623조 (임대인의 의무)")
  let cleanMessage = text;
  const statuteItems: string[] = [];

  if (text.includes('|')) {
    const parts = text.split('|');
    cleanMessage = parts[0].trim();
    const itemsPart = parts.slice(1).join('|').trim();
    if (itemsPart) {
      itemsPart.split('·').forEach((item) => {
        const trimmed = item.trim();
        if (trimmed) statuteItems.push(trimmed);
      });
    }
  }

  return { isAutoApproved, channel, channelLabel, cleanMessage, statuteItems };
}

/**
 * 3단계(관련 법령 및 판례 검색)의 하위 검색 채널별(벡터DB, 국가법령정보센터) 세부 진행 모델
 */
export interface StatuteSearchTreeNode {
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'SKIPPED' | 'NOT_NEEDED';
  target?: string;
  statutes: string[];
  message: string;
}

export interface StatuteSearchTree {
  vectorDb: StatuteSearchTreeNode;
  openlaw: StatuteSearchTreeNode;
}

/**
 * step_3 안내 메시지(JSON 또는 텍스트)로부터 벡터DB와 국가법령정보센터 하위 트리를 생성한다.
 */
function parseStatuteSearchTree(step: ConsultationStep): StatuteSearchTree {
  const isRunning = step.status === 'RUNNING';
  const isCompleted = step.status === 'COMPLETED';

  const defaultTree: StatuteSearchTree = {
    vectorDb: {
      status: isRunning ? 'RUNNING' : isCompleted ? 'COMPLETED' : 'PENDING',
      statutes: [],
      message: isRunning ? '벡터DB에서 법령 찾는 중...' : '법령을 찾지 못했습니다.',
    },
    openlaw: {
      status: 'PENDING',
      statutes: [],
      message: '국가법령정보센터에서 법령 대기 중...',
    },
  };

  const raw = (step.message || '').trim();
  // 1. JSON 직렬화된 채널 상태 파싱 우선 지원
  if (raw.startsWith('{') && raw.endsWith('}')) {
    try {
      const parsed = JSON.parse(raw);
      if (parsed.vector_db || parsed.openlaw) {
        return {
          vectorDb: {
            status: isCompleted ? 'COMPLETED' : (parsed.vector_db?.status || defaultTree.vectorDb.status),
            target: parsed.vector_db?.target || '',
            statutes: Array.isArray(parsed.vector_db?.statutes) ? parsed.vector_db.statutes : [],
            message: parsed.vector_db?.message || defaultTree.vectorDb.message,
          },
          openlaw: {
            status: isCompleted ? 'COMPLETED' : (parsed.openlaw?.status || defaultTree.openlaw.status),
            target: parsed.openlaw?.target || '',
            statutes: Array.isArray(parsed.openlaw?.statutes) ? parsed.openlaw.statutes : [],
            message: parsed.openlaw?.message || defaultTree.openlaw.message,
          },
        };
      }
    } catch {
      // JSON 파싱 실패 시 아래 텍스트 호환 파서로 폴백
    }
  }

  // 2. 레거시 텍스트 메시지 및 진행 상태 호환 파싱
  const channelInfo = parseStatuteChannelDetails(step);
  const items = channelInfo.statuteItems;

  if (isRunning) {
    if (raw.includes('OpenLaw') || raw.includes('국가법령') || raw.includes('공식 API') || raw.includes('공식 법령')) {
      return {
        vectorDb: {
          status: 'COMPLETED',
          statutes: items.length > 0 ? items : [],
          message: items.length > 0 ? '법령을 찾았습니다.' : '법령을 찾지 못했습니다.',
        },
        openlaw: {
          status: 'RUNNING',
          statutes: [],
          message: '국가법령정보센터에서 법령 찾는 중...',
        },
      };
    }
    return {
      vectorDb: {
        status: 'RUNNING',
        statutes: items,
        message: '벡터DB에서 법령 찾는 중...',
      },
      openlaw: {
        status: 'PENDING',
        statutes: [],
        message: '국가법령정보센터에서 법령 대기 중...',
      },
    };
  }

  if (isCompleted) {
    if (channelInfo.channel === 'HYBRID') {
      const half = Math.ceil(items.length / 2);
      return {
        vectorDb: {
          status: 'COMPLETED',
          statutes: items.slice(0, half),
          message: items.length > 0 ? '법령을 찾았습니다.' : '법령을 찾지 못했습니다.',
        },
        openlaw: {
          status: 'COMPLETED',
          statutes: items.slice(half),
          message: items.slice(half).length > 0 ? '법령을 찾았습니다.' : '추가 조회가 필요하지 않아 생략되었습니다.',
        },
      };
    }
    if (channelInfo.channel === 'OPENLAW_API') {
      return {
        vectorDb: {
          status: 'COMPLETED',
          statutes: [],
          message: '로컬 벡터DB 조회를 생략했습니다.',
        },
        openlaw: {
          status: 'COMPLETED',
          statutes: items,
          message: items.length > 0 ? '법령을 찾았습니다.' : '법령을 찾지 못했습니다.',
        },
      };
    }
    // 기본 로컬 벡터DB 검색 성공 또는 기본 완료: OpenLaw는 추가 조회가 필요하지 않아 생략됨
    return {
      vectorDb: {
        status: 'COMPLETED',
        statutes: items,
        message: items.length > 0 ? '법령을 찾았습니다.' : '법령을 찾지 못했습니다.',
      },
      openlaw: {
        status: 'SKIPPED',
        statutes: [],
        message: '추가 조회가 필요하지 않아 생략되었습니다.',
      },
    };
  }

  return defaultTree;
}

/**
 * 단계 상태에 따른 상태 아이콘 및 레이블 반환
 * @param status 단계 상태 코드
 * @returns JSX 아이콘
 */
function renderStepIcon(status: string) {
  switch (status) {
    case 'COMPLETED':
      return <span style={{ color: '#16a34a', fontWeight: 'bold' }}>✓</span>;
    case 'RUNNING':
      return (
        <span
          className="spinner"
          style={{ width: '14px', height: '14px', borderTopColor: '#2563eb' }}
          aria-label="진행 중"
        />
      );
    case 'WAITING_APPROVAL':
      return <span style={{ color: '#d97706', fontWeight: 'bold' }}>⚠️</span>;
    case 'FAILED':
      return <span style={{ color: '#dc2626', fontWeight: 'bold' }}>✕</span>;
    case 'SKIPPED':
      return <span style={{ color: '#94a3b8' }}>—</span>;
    case 'PENDING':
    default:
      return <span style={{ color: '#cbd5e1' }}>○</span>;
  }
}

/**
 * 진행 상태 카드 컴포넌트
 * @param props 진행 상태 및 HITL 콜백
 * @returns 대화 스트림 내 진행 상태 추적 카드 JSX
 */
export const ConsultationProgress: React.FC<ConsultationProgressProps> = ({
  progress,
  status,
  approvalRequest,
  onApprove,
  onReject,
  requestId,
  isActionLoading = false,
  isCompleted = false,
}) => {
  const completedMode = isCompleted || status === 'SUCCESS';

  // 서버로부터 전달받은 단계 목록이 있으면 사용하고, 없으면 기본 목록에 상태 보정
  let steps = progress?.steps && progress.steps.length > 0 ? progress.steps : DEFAULT_STEPS;

  if (!completedMode && status === 'APPROVAL_REQUIRED') {
    // HITL 승인 대기 상태인 경우 3번째 또는 관련 단계를 WAITING_APPROVAL로 보정
    steps = steps.map((s) => {
      if (s.step_id === 'STATUTE_APPROVAL' || s.step_id === 'step_3') {
        return { ...s, status: 'WAITING_APPROVAL' };
      }
      return s;
    });
  }

  const isApprovalWaiting = status === 'APPROVAL_REQUIRED';
  const hasReportedSteps = Boolean(progress?.steps?.length);

  // 최종 완료된 상담: 간결한 감사 기록으로 변환
  if (completedMode) {
    return (
      <details className="chat-progress-audit">
        <summary>상담 처리 과정 확인 <span>{hasReportedSteps ? `${steps.length}개 단계` : '상세 기록 없음'}</span></summary>
        <div className="chat-progress-audit-steps">
          {hasReportedSteps && steps.map((step) => {
            const isStatuteSearchStep = step.step_id === 'step_3' || step.step_id === 'LEGAL_RESEARCH';
            const tree = isStatuteSearchStep ? parseStatuteSearchTree(step) : null;

            return (
              <div className="chat-progress-audit-step" key={step.step_id}>
                <span>{renderStepIcon(step.status)}</span>
                <span className="chat-progress-audit-title">{step.step_name || step.title}</span>

                {/* 3단계에서만 찾은 법령명 배지 목록을 노출하며, 다른 단계의 중복 문구는 일체 표시하지 않는다 */}
                {isStatuteSearchStep && tree && (
                  <div className="chat-audit-statute-tags">
                    {tree.vectorDb.statutes.map((item, idx) => (
                      <span key={`v-${idx}`} className="badge-statute-item" title={`벡터DB: ${item}`}>
                        <span className="badge-statute-icon">📦</span>
                        {item}
                      </span>
                    ))}
                    {tree.openlaw.statutes.map((item, idx) => (
                      <span key={`o-${idx}`} className="badge-statute-item" title={`국가법령정보센터: ${item}`}>
                        <span className="badge-statute-icon">🌐</span>
                        {item}
                      </span>
                    ))}
                  </div>
                )}

                <span className="chat-progress-audit-status">
                  {step.status === 'COMPLETED' ? '완료' :
                   step.status === 'SKIPPED' ? '건너뜀' :
                   step.status === 'FAILED' ? '실패' :
                   step.status === 'WAITING_APPROVAL' ? '승인 대기' :
                   step.status === 'RUNNING' ? '진행 중' : '대기'}
                </span>
              </div>
            );
          })}
        </div>
      </details>
    );
  }

  return (
    <div
      className="chat-progress-card"
      role="status"
      aria-live="polite"
    >
      {/* 카드 상단 헤더 */}
      <div className="chat-progress-header">
        <div className="chat-progress-title">
          {completedMode ? (
            <span style={{ color: '#16a34a', fontWeight: 'bold', fontSize: '1.05em' }}>✓</span>
          ) : (
            <span
              className="spinner"
              style={{
                width: '14px',
                height: '14px',
                borderTopColor: isApprovalWaiting ? '#d97706' : '#2563eb',
              }}
            />
          )}
          <span style={{ color: completedMode ? '#166534' : '#1e40af' }}>
            {completedMode
              ? '사건 증거 기반 AI 법률 상담 분석 및 6단계 검증 완료'
              : isApprovalWaiting
              ? '법률 조문 추가 검색 승인 대기 중'
              : 'AI 법률 상담 처리 중...'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              fontSize: '0.78em',
              color: completedMode ? '#15803d' : '#64748b',
              fontWeight: completedMode ? 600 : 400,
            }}
          >
            {completedMode
              ? '6단계 완료'
              : progress?.current_step_name || progress?.current_step || (isApprovalWaiting ? '법령 검색 승인 대기' : '서버 진행 정보 확인 중')}
          </span>
        </div>
      </div>

      {/* 6단계 진행 리스트 (단계별 시각화) */}
      {!completedMode && (
        <div className="chat-progress-steps-list">
          {!hasReportedSteps && <p className="chat-progress-pending-note">서버의 단계별 진행 기록을 기다리고 있습니다. 아래 단계는 예상 작업이며 완료 여부를 뜻하지 않습니다.</p>}
          {steps.map((step) => {
            const statusClass = step.status.toLowerCase();
            const isStatuteSearchStep = step.step_id === 'step_3' || step.step_id === 'LEGAL_RESEARCH';
            const tree = isStatuteSearchStep ? parseStatuteSearchTree(step) : null;
            const channelInfo = parseStatuteChannelDetails(step);

            return (
              <div key={step.step_id} className={`chat-progress-step-item ${statusClass}`}>
                <div className="chat-step-content-col">
                  <div className="chat-step-left">
                    <div className="chat-step-icon">{renderStepIcon(step.status)}</div>
                    <span className="chat-step-title">{step.step_name || step.title}</span>
                    {isStatuteSearchStep && channelInfo.isAutoApproved && (
                      <span className="badge-channel-auto" title="자동 승인 모드로 법령 검색 수행">
                        🤖 자동 승인
                      </span>
                    )}
                  </div>

                  {/* 세부 상태는 오직 3단계(관련 법령 및 판례 검색)에서만 벡터DB/국가법령정보센터 계층 트리로 노출 */}
                  {/* 다른 단계(1, 2, 4, 5, 6)는 제목과 중복되는 반복 문구를 일체 출력하지 않는다 */}
                  {isStatuteSearchStep && tree && step.status !== 'PENDING' && (
                    <div className="chat-statute-tree">
                      {/* 1. 벡터DB 검색 노드 */}
                      <div className="chat-statute-branch">
                        <div className="chat-statute-branch-head">
                          <span className="chat-statute-branch-icon">
                            {tree.vectorDb.status === 'RUNNING' ? (
                              <span className="spinner-sub" aria-label="벡터DB 검색 중" />
                            ) : tree.vectorDb.statutes.length > 0 ? (
                              <span className="icon-check">✓</span>
                            ) : (
                              <span className="icon-bullet">·</span>
                            )}
                          </span>
                          <span className="chat-statute-branch-label">
                            {tree.vectorDb.status === 'RUNNING'
                              ? (tree.vectorDb.target
                                  ? `벡터DB에서 '${tree.vectorDb.target}' 찾는 중...`
                                  : '벡터DB에서 법령 찾는 중...')
                              : (tree.vectorDb.target
                                  ? `벡터DB (${tree.vectorDb.target})`
                                  : '벡터DB')}
                          </span>
                        </div>
                        <div className="chat-statute-branch-body">
                          {tree.vectorDb.statutes.length > 0 ? (
                            <div className="chat-statute-found-row">
                              {tree.vectorDb.statutes.map((item, idx) => (
                                <span key={idx} className="badge-statute-item" title={item}>
                                  <span className="badge-statute-icon">📜</span>
                                  {item}
                                </span>
                              ))}
                              <span className="chat-statute-found-tail">을 찾았습니다.</span>
                            </div>
                          ) : tree.vectorDb.status === 'RUNNING' ? null : tree.vectorDb.target ? (
                            <span className="chat-statute-empty-text">법령을 찾지 못했습니다.</span>
                          ) : (
                            <span className="chat-statute-skipped-text">법령 조회가 필요하지 않은 질의입니다.</span>
                          )}
                        </div>
                      </div>

                      {/* 2. 국가법령정보센터 검색 노드 */}
                      <div className="chat-statute-branch">
                        <div className="chat-statute-branch-head">
                          <span className="chat-statute-branch-icon">
                            {tree.openlaw.status === 'RUNNING' ? (
                              <span className="spinner-sub" aria-label="국가법령정보센터 검색 중" />
                            ) : tree.openlaw.statutes.length > 0 ? (
                              <span className="icon-check">✓</span>
                            ) : (
                              <span className="icon-dash" style={{ color: '#94a3b8' }}>—</span>
                            )}
                          </span>
                          <span className="chat-statute-branch-label">
                            {tree.openlaw.status === 'RUNNING'
                              ? (tree.openlaw.target
                                  ? `국가법령정보센터에서 '${tree.openlaw.target}' 찾는 중...`
                                  : '국가법령정보센터에서 법령 찾는 중...')
                              : (tree.openlaw.target
                                  ? `국가법령정보센터 (${tree.openlaw.target})`
                                  : '국가법령정보센터')}
                          </span>
                        </div>
                        <div className="chat-statute-branch-body">
                          {tree.openlaw.statutes.length > 0 ? (
                            <div className="chat-statute-found-row">
                              {tree.openlaw.statutes.map((item, idx) => (
                                <span key={idx} className="badge-statute-item" title={item}>
                                  <span className="badge-statute-icon">📜</span>
                                  {item}
                                </span>
                              ))}
                              <span className="chat-statute-found-tail">을 찾았습니다.</span>
                            </div>
                          ) : tree.openlaw.status === 'RUNNING' ? null : (tree.openlaw.status === 'SKIPPED' || tree.openlaw.status === 'NOT_NEEDED' || !tree.openlaw.target) ? (
                            <span className="chat-statute-skipped-text">추가 조회가 필요하지 않아 생략되었습니다.</span>
                          ) : (
                            <span className="chat-statute-empty-text">법령을 찾지 못했습니다.</span>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
                <div className="chat-step-right" style={{ fontSize: '0.78em' }}>
                  {step.status === 'RUNNING' && <span style={{ color: '#2563eb' }}>분석 중...</span>}
                  {step.status === 'COMPLETED' && <span style={{ color: '#16a34a' }}>완료</span>}
                  {step.status === 'WAITING_APPROVAL' && <span style={{ color: '#d97706', fontWeight: 600 }}>승인 필요</span>}
                  {step.status === 'SKIPPED' && <span style={{ color: '#94a3b8' }}>건너뜀</span>}
                  {step.status === 'PENDING' && <span style={{ color: '#94a3b8' }}>대기</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 상황 A: HITL 승인 대기 인라인 액션 박스 */}
      {isApprovalWaiting && (
        <div className="chat-approval-box">
          <div className="chat-approval-desc">
            {approvalRequest?.explanation ||
              '현재 등록된 사건 자료만으로는 의뢰인의 쟁점을 검증할 수 없습니다. 국가법령정보공동활용 공식 API에서 원문 조문을 직접 검색하여 법률 재분석을 진행하시겠습니까?'}
          </div>

          {approvalRequest?.candidate_laws && approvalRequest.candidate_laws.length > 0 && (
            <div>
              <div style={{ fontSize: '0.8em', color: '#78350f', fontWeight: 600, marginBottom: '4px' }}>
                조회 예정 공식 법령:
              </div>
              <div className="chat-approval-laws">
                {approvalRequest.candidate_laws.map((law: string, idx: number) => (
                  <span key={idx} className="chat-approval-law-tag">
                    {law}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="chat-approval-actions">
            <button
              type="button"
              onClick={() => onReject(requestId)}
              disabled={isActionLoading}
              className="btn btn-secondary btn-sm"
              style={{ fontSize: '0.82em' }}
            >
              ✕ 검색 건너뛰기 (현재 근거로 종료)
            </button>
            <button
              type="button"
              onClick={() => onApprove(requestId)}
              disabled={isActionLoading}
              className="btn btn-primary btn-sm"
              style={{
                fontSize: '0.82em',
                backgroundColor: '#2563eb',
                fontWeight: 600,
              }}
            >
              ✓ 공식 법령 검색 승인 및 재분석
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
