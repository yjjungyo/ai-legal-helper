/**
 * @fileoverview 사건 중심 단일 상담 상단 헤더(CaseChatHeader) 컴포넌트
 * 현재 사건의 제목, 사건 진행 상태 배지, 실제 등록된 증거 건수, 확정된 사실관계 건수,
 * 누적 상담 턴 수를 시각화하여 사용자가 사건 문맥 속에서 상담을 진행하고 있음을 명확히 인지하도록 합니다.
 */

import React from 'react';

export interface CaseChatHeaderProps {
  /** 사건 명칭 */
  caseTitle: string;
  /** 사건 진행 상태 (OPEN, IN_PROGRESS, RESOLVED 등) */
  caseStatus?: string;
  /** 사건 유형 (주택임대차 등) */
  caseType?: string;
  /** 등록된 증거 문서 총 건수 */
  evidenceCount: number;
  /** 확정된 사실관계(Facts) 총 건수 */
  factsCount: number;
  /** 누적 상담 대화 턴 총 건수 */
  totalTurnsCount: number;
}

/**
 * 사건 상태 배지 렌더러
 */
function renderCaseStatusBadge(status?: string) {
  const s = status?.toUpperCase() || 'OPEN';
  switch (s) {
    case 'IN_PROGRESS':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe', fontSize: '0.74em' }}
        >
          진행 중
        </span>
      );
    case 'RESOLVED':
    case 'COMPLETED':
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#ecfdf5', color: '#047857', border: '1px solid #a7f3d0', fontSize: '0.74em' }}
        >
          해결 완료
        </span>
      );
    case 'OPEN':
    default:
      return (
        <span
          className="badge"
          style={{ backgroundColor: '#f1f5f9', color: '#475569', border: '1px solid #cbd5e1', fontSize: '0.74em' }}
        >
          진행 대기
        </span>
      );
  }
}

/**
 * 상단 사건 상담 헤더 컴포넌트
 * @param props 사건명 및 실시간 건수 통계
 * @returns 고정 상단 헤더 JSX
 */
export const CaseChatHeader: React.FC<CaseChatHeaderProps> = ({
  caseTitle,
  caseStatus,
  caseType,
  evidenceCount,
  factsCount,
  totalTurnsCount,
}) => {
  return (
    <header className="case-chat-header" role="banner">
      {/* 좌측: 사건 타이틀 및 상태 */}
      <div className="case-chat-header-left">
        <div className="case-chat-icon-badge" aria-hidden="true">
          ⚖️
        </div>
        <div className="case-chat-title-group">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h2 className="case-chat-title" title={caseTitle}>
              {caseTitle || '사건 법률 상담'}
            </h2>
            {renderCaseStatusBadge(caseStatus)}
          </div>
          <div className="case-chat-subtitle">
            <span>{caseType || '법률 상담'}</span>
            <span>•</span>
            <span>단일 지속 대화(One Persistent Conversation)</span>
          </div>
        </div>
      </div>

      {/* 우측: 실제 데이터 동적 카운트 배지들 */}
      <div className="case-chat-header-stats">
        <span className="chat-stat-pill evidence" title="사건에 등록된 증거 문서 수">
          📁 등록 증거 <strong>{evidenceCount}</strong>건
        </span>
        <span className="chat-stat-pill facts" title="증거로부터 확정된 사실관계 수">
          ⚖️ 확정 사실 <strong>{factsCount}</strong>건
        </span>
        <span className="chat-stat-pill turns" title="사건 전체 누적 상담 턴 수">
          💬 누적 상담 <strong>{totalTurnsCount}</strong>건
        </span>
      </div>
    </header>
  );
};

