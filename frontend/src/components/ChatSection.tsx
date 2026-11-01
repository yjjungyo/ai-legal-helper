/**
 * @fileoverview 사건 중심 단일 지속 대화(Case-Centric Chat) 메인 컨테이너 컴포넌트
 * 
 * [P0 핵심 구현 요건]
 * 1. P0-01: '+ 새 대화 시작' 및 대화 분기/세션 리셋 UI를 완전히 제거하고 단일 지속 대화로 통합.
 * 2. P0-02 & P0-04: 사건당 1개의 대화 스트림(Case = One Persistent Conversation)을 시간순 렌더링.
 * 3. P0-03: 모듈화된 하위 컴포넌트(CaseChatHeader, ChatMessageList, ChatComposer, EvidenceSourceDrawer) 조립.
 * 4. P0-05: LangGraph 6단계 실시간 진행 상태 및 HILT 승인/거절 인플레이스 상호작용.
 * 5. P0-06: [E01], [E02] 증거 인용 클릭 시 우측 슬라이드오버 드로어를 통한 실시간 원문/발췌 확인.
 * 6. P0-07: 하단 고정형 대화 입력기 및 한글 조합 방어.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useConsultation } from '../hooks/useConsultation';
import { getCaseDetail } from '../api/caseClient';
import { listEvidence } from '../api/evidenceClient';
import type { CaseDetail } from '../types/case';
import type { EvidenceDocument } from '../types/evidence';

// 모듈화된 채팅 전용 컴포넌트 및 스타일 임포트
import './chat/chat.css';
import { CaseChatHeader } from './chat/CaseChatHeader';
import { ChatMessageList } from './chat/ChatMessageList';
import { ChatComposer } from './chat/ChatComposer';
import { EvidenceSourceDrawer } from './chat/EvidenceSourceDrawer';
import type { CitationMeta } from './LegalAnswerView';

export interface ChatSectionProps {
  /** 현재 작업 대상 사건 식별자 UUID */
  caseId: string;
}

/**
 * 사건 중심 단일 대화 메인 화면 컴포넌트
 * @param props 사건 식별자
 * @returns 사건 지속 대화 화면 JSX
 */
export const ChatSection: React.FC<ChatSectionProps> = ({ caseId }) => {
  const navigate = useNavigate();

  // 1. 단일 대화 훅 (Case = One Persistent Conversation)
  const {
    question,
    setQuestion,
    messages,
    loading,
    actionLoading,
    error,
    sendQuestion,
    handleApproval,
  } = useConsultation(caseId);

  // 2. 사건 메타데이터 및 등록 증거 목록 상태 관리
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [evidenceDocs, setEvidenceDocs] = useState<EvidenceDocument[]>([]);

  // 3. 우측 증거 출처 슬라이드오버 드로어 제어 상태
  const [activeEvidenceLabel, setActiveEvidenceLabel] = useState<string | null>(null);
  const [activeEvidenceId, setActiveEvidenceId] = useState<string | null>(null);
  const [activeClaimId, setActiveClaimId] = useState<string | null>(null);
  const [activeSpanId, setActiveSpanId] = useState<string | null>(null);
  const [historicalMode, setHistoricalMode] = useState(false);
  const [historicalExcerpt, setHistoricalExcerpt] = useState<string | null>(null);
  const [historicalFileName, setHistoricalFileName] = useState<string | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  /**
   * 사건 정보 및 등록 증거 목록 로드
   */
  const loadCaseMetadata = useCallback(async () => {
    if (!caseId) return;
    try {
      const [caseData, docs] = await Promise.all([
        getCaseDetail(caseId).catch(() => null),
        listEvidence(caseId).catch(() => []),
      ]);
      if (caseData) setCaseDetail(caseData);
      if (docs) setEvidenceDocs(docs);
    } catch (err) {
      console.warn('[ChatSection] Failed to load case metadata:', err);
    }
  }, [caseId]);

  useEffect(() => {
    loadCaseMetadata();
  }, [loadCaseMetadata]);

  /**
   * [E01], [E02] 등 증거 번호 클릭 핸들러
   */
  const handleEvidenceClick = useCallback((label: string, meta?: CitationMeta) => {
    setActiveEvidenceLabel(label);
    setActiveEvidenceId(meta?.evidenceId || null);
    setActiveClaimId(meta?.claimId || null);
    setActiveSpanId(meta?.spanId || null);
    setHistoricalMode(Boolean(meta?.historicalMode));
    setHistoricalExcerpt(meta?.historicalExcerpt || null);
    setHistoricalFileName(meta?.historicalFileName || null);
    setIsDrawerOpen(true);
  }, []);

  /**
   * 드로어 내 '증거 탭 이동' 버튼 클릭 시 네비게이션
   */
  const handleNavigateToEvidence = useCallback((evidenceId?: string) => {
    navigate(`/${caseId}/workspace/evidence${evidenceId ? `?selected=${evidenceId}` : ''}`);
  }, [caseId, navigate]);

  /**
   * HILT 추가 법령 검색 승인/거절 핸들러
   */
  const handleApprove = useCallback((requestId: string) => {
    handleApproval(requestId, true);
  }, [handleApproval]);

  const handleReject = useCallback((requestId: string) => {
    handleApproval(requestId, false);
  }, [handleApproval]);

  return (
    <div className="case-chat-layout" style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
      {/* 1. 상단 사건 헤더 (CaseChatHeader) - 동적 카운트 배지 */}
      <CaseChatHeader
        caseTitle={caseDetail?.title || '사건 법률 상담'}
        caseStatus={caseDetail?.status}
        caseType={caseDetail?.case_type}
        evidenceCount={evidenceDocs.length}
        factsCount={caseDetail?.facts?.length || 0}
        totalTurnsCount={messages.length}
      />

      {/* 상단 통신 오류 알림 바 (존재 시) */}
      {error && (
        <div
          style={{
            backgroundColor: '#fef2f2',
            borderBottom: '1px solid #fecaca',
            color: '#b91c1c',
            padding: '8px 24px',
            fontSize: '0.84em',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            zIndex: 10,
          }}
        >
          <span>⚠️ {error}</span>
          <button
            type="button"
            onClick={() => loadCaseMetadata()}
            className="btn btn-secondary btn-sm"
            style={{ fontSize: '0.75em', padding: '2px 8px' }}
          >
            새로고침
          </button>
        </div>
      )}

      {/* 2. 대화 메시지 스트림 (ChatMessageList) */}
      <ChatMessageList
        messages={messages}
        onEvidenceClick={handleEvidenceClick}
        onApprove={handleApprove}
        onReject={handleReject}
        isActionLoading={actionLoading}
        onSelectSampleQuestion={(q) => setQuestion(q)}
      />

      {/* 3. 하단 고정 입력기 (ChatComposer) */}
      <ChatComposer
        value={question}
        onChange={setQuestion}
        onSend={(text) => sendQuestion(text)}
        disabled={loading}
      />

      {/* 4. 우측 슬라이드오버 증거 원문 및 사실 확인 드로어 (EvidenceSourceDrawer) */}
      <EvidenceSourceDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        selectedLabel={activeEvidenceLabel}
        selectedEvidenceId={activeEvidenceId}
        selectedClaimId={activeClaimId}
        selectedSpanId={activeSpanId}
        historicalMode={historicalMode}
        historicalExcerpt={historicalExcerpt}
        historicalFileName={historicalFileName}
        caseId={caseId}
        evidenceDocuments={evidenceDocs}
        onNavigateToEvidence={handleNavigateToEvidence}
      />
    </div>
  );
};
export default ChatSection;
