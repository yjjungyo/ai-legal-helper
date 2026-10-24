/**
 * @fileoverview 법률 상담 답변 인용 증거([E01], [E02] 등) 상세 슬라이드오버 드로어 컴포넌트
 * 답변 내 증거 번호를 클릭하면 화면 우측에서 슬라이드로 열리며,
 * 원본 증거 문서명, 메타데이터, 추출된 주장(Claims), 텍스트 발췌(Spans)를 확인하고
 * 필요 시 증거 탭으로 즉시 이동할 수 있는 단축 링크를 제공합니다.
 */

import React, { useEffect, useState, useMemo } from 'react';
import type { EvidenceDocument, EvidenceClaim } from '../../types/evidence';
import { getEvidenceClaims } from '../../api/evidenceClient';

export interface EvidenceSourceDrawerProps {
  /** 드로어 열림 상태 */
  isOpen: boolean;
  /** 드로어 닫기 콜백 */
  onClose: () => void;
  /** 선택된 증거 라벨 식별자 (예: "E01", "E02") */
  selectedLabel: string | null;
  /** 현재 사건 식별자 UUID */
  caseId: string;
  /** 현재 사건에 등록된 증거 문서 목록 */
  evidenceDocuments: EvidenceDocument[];
  /** 증거 탭으로 이동하기 위한 콜백 핸들러 */
  onNavigateToEvidence?: (evidenceId: string) => void;
}

/**
 * 증거 번호 라벨과 증거 문서 객체를 매핑하는 헬퍼 함수
 * 1. 파일명 시작부에 'E01', 'E02' 등의 접두사가 있는 경우 우선 매핑
 * 2. 없는 경우 업로드 일시 및 ID 순서로 정렬하여 인덱스 기반 순차 매핑
 *
 * @param label 탐색할 증거 라벨 (예: "E01")
 * @param documents 등록된 증거 문서 목록
 * @returns 매칭된 증거 문서 또는 undefined
 */
function findDocumentByLabel(label: string | null, documents: EvidenceDocument[]): EvidenceDocument | undefined {
  if (!label || !documents || documents.length === 0) return undefined;
  const cleanLabel = label.trim().toUpperCase();

  // 1차: 파일명 접두사 일치 확인
  const prefixMatch = documents.find((doc) => {
    const fn = (doc.original_filename || '').trim().toUpperCase();
    return fn.startsWith(cleanLabel) || fn.includes(`[${cleanLabel}]`) || fn.includes(`(${cleanLabel})`);
  });
  if (prefixMatch) return prefixMatch;

  // 2차: 숫자 순서 기반 인덱스 확인 (E01 -> 1번째, E02 -> 2번째)
  const numMatch = cleanLabel.match(/^E(\d+)$/);
  if (numMatch) {
    const targetIdx = parseInt(numMatch[1], 10) - 1;
    // 생성일시 기준 오름차순 정렬 후 인덱스 참조
    const sorted = [...documents].sort((a, b) => {
      const tA = new Date(a.created_at).getTime();
      const tB = new Date(b.created_at).getTime();
      return tA - tB;
    });
    if (targetIdx >= 0 && targetIdx < sorted.length) {
      return sorted[targetIdx];
    }
  }

  return undefined;
}

/**
 * 증거 원문 및 발췌 확인 슬라이드오버 드로어 컴포넌트
 * @param props 드로어 제어 프로퍼티
 * @returns 슬라이드오버 패널 JSX
 */
export const EvidenceSourceDrawer: React.FC<EvidenceSourceDrawerProps> = ({
  isOpen,
  onClose,
  selectedLabel,
  caseId,
  evidenceDocuments,
  onNavigateToEvidence,
}) => {
  const [claims, setClaims] = useState<EvidenceClaim[]>([]);
  const [loadingClaims, setLoadingClaims] = useState(false);
  const [claimError, setClaimError] = useState<string | null>(null);

  // 대상 증거 문서 조회
  const matchedDoc = useMemo(
    () => findDocumentByLabel(selectedLabel, evidenceDocuments),
    [selectedLabel, evidenceDocuments]
  );

  // ESC 키로 닫기 핸들러 등록
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // 대상 문서가 확정되면 해당 문서의 추출 클레임 및 스팬 목록 조회
  useEffect(() => {
    if (!isOpen || !matchedDoc || !caseId) {
      setClaims([]);
      setClaimError(null);
      return;
    }

    let isMounted = true;
    setLoadingClaims(true);
    setClaimError(null);

    getEvidenceClaims(caseId, matchedDoc.id)
      .then((data) => {
        if (isMounted) {
          setClaims(data || []);
          setLoadingClaims(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          console.warn('[EvidenceSourceDrawer] Failed to fetch claims:', err);
          setClaimError('추출된 주장 및 사실관계를 불러오지 못했습니다.');
          setLoadingClaims(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, matchedDoc, caseId]);

  if (!isOpen && !selectedLabel) {
    return null;
  }

  return (
    <>
      {/* 배경 딤 오버레이 */}
      <div
        className={`evidence-drawer-backdrop ${isOpen ? 'open' : ''}`}
        onClick={onClose}
        aria-hidden={!isOpen}
      />

      {/* 우측 슬라이드 패널 */}
      <div
        className={`evidence-drawer-panel ${isOpen ? 'open' : ''}`}
        role="dialog"
        aria-labelledby="evidence-drawer-heading"
        aria-modal="true"
      >
        {/* 헤더 */}
        <div className="evidence-drawer-header">
          <div className="evidence-drawer-title-group">
            <span className="chat-evidence-tag" style={{ fontSize: '0.95em', padding: '2px 8px' }}>
              {selectedLabel || 'E00'}
            </span>
            <h3
              id="evidence-drawer-heading"
              style={{ margin: 0, fontSize: '1.05em', fontWeight: 700, color: '#0f172a' }}
            >
              증거 원문 및 사실 확인
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-secondary btn-sm"
            style={{ borderRadius: '50%', width: '28px', height: '28px', padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            aria-label="드로어 닫기"
          >
            ✕
          </button>
        </div>

        {/* 바디 본문 */}
        <div className="evidence-drawer-body">
          {matchedDoc ? (
            <>
              {/* 문서 메타데이터 카드 */}
              <div
                style={{
                  backgroundColor: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  borderRadius: '10px',
                  padding: '14px 16px',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: '0.95em', color: '#1e293b', marginBottom: '8px', wordBreak: 'break-all' }}>
                  📄 {matchedDoc.original_filename}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px', fontSize: '0.8em', color: '#64748b' }}>
                  <div>
                    <span style={{ fontWeight: 600 }}>상태: </span>
                    <span style={{ color: matchedDoc.status === 'COMPLETED' ? '#16a34a' : '#2563eb' }}>
                      {matchedDoc.status}
                    </span>
                  </div>
                  <div>
                    <span style={{ fontWeight: 600 }}>유형: </span>
                    <span>{matchedDoc.media_type || '문서'}</span>
                  </div>
                  <div>
                    <span style={{ fontWeight: 600 }}>크기: </span>
                    <span>{(matchedDoc.size_bytes / 1024).toFixed(1)} KB</span>
                  </div>
                  <div>
                    <span style={{ fontWeight: 600 }}>등록일: </span>
                    <span>{matchedDoc.created_at ? matchedDoc.created_at.slice(0, 10) : '-'}</span>
                  </div>
                </div>
              </div>

              {/* 추출된 사실 및 증거 발췌 목록 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                  <h4 style={{ margin: 0, fontSize: '0.92em', fontWeight: 700, color: '#334155' }}>
                    🔍 추출된 사실관계 및 원문 발췌 ({claims.length}건)
                  </h4>
                </div>

                {loadingClaims ? (
                  <div style={{ textAlign: 'center', padding: '24px 0', color: '#64748b', fontSize: '0.88em' }}>
                    <span className="spinner" style={{ width: '16px', height: '16px', borderTopColor: '#2563eb', display: 'inline-block', marginRight: '8px' }} />
                    증거 발췌 내용을 불러오고 있습니다...
                  </div>
                ) : claimError ? (
                  <div style={{ padding: '12px', backgroundColor: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', color: '#991b1b', fontSize: '0.84em' }}>
                    {claimError}
                  </div>
                ) : claims.length === 0 ? (
                  <div style={{ padding: '16px', backgroundColor: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: '8px', textAlign: 'center', color: '#64748b', fontSize: '0.86em' }}>
                    추출된 사실관계 또는 텍스트 발췌가 없습니다.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {claims.map((claim) => (
                      <div
                        key={claim.id}
                        style={{
                          backgroundColor: '#ffffff',
                          border: '1px solid #e2e8f0',
                          borderRadius: '8px',
                          padding: '12px 14px',
                          boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                          <span
                            style={{
                              fontSize: '0.72em',
                              fontWeight: 700,
                              padding: '2px 6px',
                              borderRadius: '4px',
                              backgroundColor: claim.claim_type === 'FACT' ? '#eff6ff' : '#f5f3ff',
                              color: claim.claim_type === 'FACT' ? '#1d4ed8' : '#6d28d9',
                              border: '1px solid #bfdbfe',
                            }}
                          >
                            {claim.claim_type}
                          </span>
                          <span style={{ fontSize: '0.88em', fontWeight: 600, color: '#0f172a' }}>
                            {claim.statement}
                          </span>
                        </div>

                        {/* 원문 발췌 스팬 */}
                        {claim.spans && claim.spans.length > 0 && (
                          <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                            {claim.spans.map((span) => (
                              <div key={span.id} className="evidence-excerpt-box">
                                <div style={{ fontSize: '0.74em', color: '#92400e', fontWeight: 600, marginBottom: '2px' }}>
                                  {span.page_number ? `[페이지 ${span.page_number}] ` : ''}원문 발췌:
                                </div>
                                <div style={{ fontStyle: 'italic' }}>
                                  "{span.text_excerpt}"
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div style={{ padding: '30px 16px', textAlign: 'center', color: '#64748b', fontSize: '0.9em' }}>
              <div style={{ fontSize: '2em', marginBottom: '8px' }}>📂</div>
              <p>증거 식별자 <strong>[{selectedLabel}]</strong>에 해당하는 문서를 찾을 수 없습니다.</p>
              <p style={{ fontSize: '0.84em', color: '#94a3b8' }}>증거 탭에서 최신 증거가 정상적으로 업로드되었는지 확인해주세요.</p>
            </div>
          )}
        </div>

        {/* 푸터 액션 */}
        <div className="evidence-drawer-footer">
          {matchedDoc && onNavigateToEvidence && (
            <button
              type="button"
              onClick={() => {
                onClose();
                onNavigateToEvidence(matchedDoc.id);
              }}
              className="btn btn-secondary btn-sm"
              style={{ fontWeight: 600 }}
            >
              📁 증거 탭에서 전체 확인
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="btn btn-primary btn-sm"
          >
            닫기
          </button>
        </div>
      </div>
    </>
  );
};

