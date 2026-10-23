/**
 * @fileoverview 증거 문서 관리 및 사실 추출/리뷰(Evidence Section) 컴포넌트
 * 사건 관련 계약서, 내용증명 등의 문서(PDF, DOCX, TXT)를 업로드하고,
 * AI가 추출한 사실(Claim/Fact)의 원문 출처(Spans)를 검토 및 승인/수정/반려 처리합니다.
 */

import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  uploadEvidence, 
  deleteEvidence,
  listEvidence, 
  extractEvidence, 
  getEvidenceClaims, 
  reviewEvidenceClaim, 
  getEvidenceConflicts 
} from '../api/evidenceClient';
import type { EvidenceDocument, EvidenceClaim } from '../types/evidence';

/**
 * 사실관계 유형(claim_type)을 띄어쓰기 없는 표준 한글 라벨로 변환하는 맵퍼 함수.
 * 
 * 영문 코드 및 공백 포함 레거시 라벨을 지원하여 9가지 표준 법률 카테고리로 변환합니다:
 * '목적물정보', '권리의무', '문서정보', '일자기한', '금액비용', '당사자정보', '법률행위', '계약조건', '일반서술'.
 * 
 * @param rawType 원본 주장 유형 문자열
 * @returns 공백 없는 표준 한글 라벨
 */
export const getClaimTypeLabel = (rawType?: string | null): string => {
  if (!rawType) return '일반서술';
  // 공백, 언더스코어(_), 하이픈(-)을 모두 제거하고 대문자로 정규화
  const key = rawType.trim().toUpperCase().replace(/[_\-\s]+/g, '');
  const map: Record<string, string> = {
    // 목적물정보
    PROPERTY: '목적물정보',
    PROPERTYINFO: '목적물정보',
    부동산: '목적물정보',
    목적물: '목적물정보',
    목적물정보: '목적물정보',

    // 권리의무
    RIGHTDUTY: '권리의무',
    RIGHTSDUTIES: '권리의무',
    OBLIGATION: '권리의무',
    RIGHT: '권리의무',
    권리의무: '권리의무',

    // 문서정보
    DOCINFO: '문서정보',
    DOCUMENTINFO: '문서정보',
    DOCUMENT: '문서정보',
    문서: '문서정보',
    문서정보: '문서정보',

    // 일자기한
    DATE: '일자기한',
    DATEINFO: '일자기한',
    일자: '일자기한',
    기한: '일자기한',
    일자기한: '일자기한',

    // 금액비용
    AMOUNT: '금액비용',
    PRICE: '금액비용',
    COST: '금액비용',
    금액: '금액비용',
    비용: '금액비용',
    금액비용: '금액비용',

    // 당사자정보
    PARTYINFO: '당사자정보',
    PARTY: '당사자정보',
    PARTIES: '당사자정보',
    당사자: '당사자정보',
    당사자정보: '당사자정보',

    // 법률행위
    ACTION: '법률행위',
    LEGALACTION: '법률행위',
    행위: '법률행위',
    법률행위: '법률행위',

    // 계약조건
    CONDITION: '계약조건',
    TERMS: '계약조건',
    조건: '계약조건',
    특약: '계약조건',
    계약조건: '계약조건',

    // 일반서술
    OTHER: '일반서술',
    GENERAL: '일반서술',
    STATEMENT: '일반서술',
    FACT: '일반서술',
    일반: '일반서술',
    서술: '일반서술',
    일반서술: '일반서술',
  };

  return map[key] || '일반서술';
};

/**
 * 카테고리별 시각적 구분을 위한 배지 CSS 클래스 반환
 * 
 * @param label 공백 없는 표준 한글 라벨
 * @returns 매핑된 배지 CSS 클래스명
 */
export const getClaimTypeBadgeClass = (label: string): string => {
  switch (label) {
    case '목적물정보':
      return 'badge-teal';
    case '권리의무':
      return 'badge-purple';
    case '문서정보':
      return 'badge-indigo';
    case '일자기한':
      return 'badge-blue';
    case '금액비용':
      return 'badge-green';
    case '당사자정보':
      return 'badge-blue';
    case '법률행위':
      return 'badge-amber';
    case '계약조건':
      return 'badge-rose';
    case '일반서술':
    default:
      return 'badge-gray';
  }
};

interface SpanItemProps {
  span: any;
}

/**
 * 증거 문서 내 본문 발췌 위치(Span) 표시 컴포넌트
 */
const SpanItem: React.FC<SpanItemProps> = ({ span }) => {
  const [expanded, setExpanded] = useState(false);
  const pageNum = span.page_number ?? span.page;
  const paraIdx = span.paragraph_index;
  const excerpt = span.text_excerpt || span.text || '(본문 발췌 없음)';
  const locText = pageNum ? `p.${pageNum}` : '';
  const paraText = paraIdx !== undefined ? `문단 ${paraIdx + 1}` : '';
  const locationTag = [locText, paraText].filter(Boolean).join(', ') || '문서 본문';

  const isLong = excerpt.length > 110;
  const displayText = (!expanded && isLong) ? excerpt.slice(0, 100) + '...' : excerpt;

  return (
    <li style={{ margin: '4px 0', lineHeight: 1.5, fontSize: '0.86em' }}>
      <span style={{ color: 'var(--primary)', fontWeight: 600, marginRight: '4px' }}>[{locationTag}]</span>
      <span style={{ color: 'var(--text-secondary)' }}>"{displayText}"</span>
      {isLong && (
        <button 
          onClick={() => setExpanded(!expanded)} 
          className="btn btn-secondary btn-sm"
          style={{ marginLeft: '6px', padding: '1px 6px', fontSize: '0.75em' }}
        >
          {expanded ? '접기' : '전체보기'}
        </button>
      )}
    </li>
  );
};

/**
 * 사실 검토(수정 승인 / 반려) 인라인 모달 인터페이스
 */
interface ReviewModalProps {
  isOpen: boolean;
  action: 'EDIT' | 'REJECT' | null;
  currentStatement: string;
  onClose: () => void;
  onSubmit: (data: { newStatement?: string; reason?: string }) => void;
}

/**
 * 사실 검토 인라인 모달 컴포넌트 (prompt 대체)
 */
function ReviewModal({ isOpen, action, currentStatement, onClose, onSubmit }: ReviewModalProps) {
  const [statement, setStatement] = useState(currentStatement);
  const [reason, setReason] = useState('');

  useEffect(() => {
    setStatement(currentStatement);
    setReason('');
  }, [currentStatement, isOpen]);

  if (!isOpen || !action) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (action === 'EDIT') {
      onSubmit({ newStatement: statement });
    } else {
      onSubmit({ reason: reason || undefined });
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 style={{ fontSize: '1.1em', fontWeight: 700, margin: 0 }}>
            {action === 'EDIT' ? '사실 내용 수정 후 승인' : '추출 사실 제외 (반려)'}
          </h3>
          <button 
            type="button" 
            onClick={onClose} 
            style={{ background: 'none', border: 'none', fontSize: '1.2em', cursor: 'pointer', color: 'var(--text-muted)' }}
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {action === 'EDIT' ? (
              <div className="form-group">
                <label htmlFor="edit-statement">수정할 사실 내용 *</label>
                <textarea
                  id="edit-statement"
                  className="form-control"
                  rows={4}
                  value={statement}
                  onChange={(e) => setStatement(e.target.value)}
                  autoFocus
                />
                <p style={{ fontSize: '0.82em', color: 'var(--text-muted)' }}>
                  수정된 내용은 사건의 공식 Fact로 등록됩니다.
                </p>
              </div>
            ) : (
              <div className="form-group">
                <label htmlFor="reject-reason">반려 사유 (선택 사항)</label>
                <input
                  id="reject-reason"
                  type="text"
                  className="form-control"
                  placeholder="예: 사건과 무관한 일반 문구, 오추출 등"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  autoFocus
                />
              </div>
            )}
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              취소
            </button>
            <button 
              type="submit" 
              className={action === 'EDIT' ? 'btn btn-primary' : 'btn btn-danger'}
            >
              {action === 'EDIT' ? '수정 승인' : '반려 확정'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface Props {
  /** 사건 식별자 UUID */
  caseId: string;
  /** 상위 사건 정보 새로고침 콜백 */
  onRefreshCase: () => void;
}

/**
 * 증거 자료 및 사실 추출 관리 컴포넌트
 */
export const EvidenceSection: React.FC<Props> = ({ caseId, onRefreshCase }) => {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<EvidenceDocument[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [claims, setClaims] = useState<EvidenceClaim[]>([]);
  const [conflicts, setConflicts] = useState<any[]>([]);
  const [conflictError, setConflictError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [showReanalyzePrompt, setShowReanalyzePrompt] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 리뷰 모달 상태
  const [modalState, setModalState] = useState<{
    isOpen: boolean;
    action: 'EDIT' | 'REJECT' | null;
    claimId: string;
    statement: string;
  }>({
    isOpen: false,
    action: null,
    claimId: '',
    statement: '',
  });

  useEffect(() => {
    loadEvidences();
    loadConflicts();
  }, [caseId]);

  useEffect(() => {
    if (selectedDocId) {
      loadClaims(selectedDocId);
    } else {
      setClaims([]);
    }
  }, [selectedDocId]);

  /**
   * 백그라운드 추출 중인 문서(EXTRACTING / UPLOADED)가 있을 때 자동 폴링하여
   * 추출 완료 시 문서 배지와 주장 목록을 자동 갱신합니다.
   */
  useEffect(() => {
    const hasExtracting = documents.some(
      (d) => d.status === 'EXTRACTING' || d.status === 'UPLOADED'
    );
    if (!hasExtracting) return;
    const timer = setInterval(async () => {
      await loadEvidences();
      if (selectedDocId) {
        await loadClaims(selectedDocId);
      }
      await loadConflicts();
    }, 2500);
    return () => clearInterval(timer);
  }, [documents, selectedDocId, caseId]);

  /**
   * 증거 문서 목록 로드
   */
  const loadEvidences = async () => {
    try {
      const docs = await listEvidence(caseId);
      setDocuments(docs);
      if (docs.length > 0) {
        setSelectedDocId((prev) => (prev && docs.some((d) => d.id === prev) ? prev : docs[0].id));
      } else {
        setSelectedDocId(null);
      }
    } catch (e) {
      console.error('증거 목록 로딩 실패:', e);
    }
  };

  /**
   * 증거 간 모순/상충 내역 로드
   * API 호출 실패 시 상충 0건으로 오인되지 않도록 명시적 오류 상태를 기록합니다.
   */
  const loadConflicts = async () => {
    try {
      setConflictError(null);
      const data = await getEvidenceConflicts(caseId);
      setConflicts(data.conflicts || []);
    } catch (e: any) {
      console.error('증거 모순 분석 로딩 실패:', e);
      setConflictError(e?.message || '증거 상충 분석 결과를 불러오지 못했습니다. 네트워크 또는 서버 상태를 확인해 주세요.');
    }
  };

  /**
   * 선택 문서 내 추출된 사실 주장(Claims) 로드
   */
  const loadClaims = async (docId: string) => {
    try {
      const data = await getEvidenceClaims(caseId, docId);
      setClaims(data);
    } catch (e) {
      console.error('추출 사실 로딩 실패:', e);
    }
  };

  /**
   * 파일 업로드 처리
   */
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await uploadEvidence(caseId, file);
      await loadEvidences();
      onRefreshCase();
    } catch (err: any) {
      alert(err.message || '업로드 실패 (PDF, DOCX, TXT 파일만 지원됩니다)');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  /**
   * 증거 문서 삭제
   */
  const handleDelete = async (docId: string, filename: string) => {
    if (!window.confirm(`'${filename}' 증거 문서를 삭제하시겠습니까?`)) return;
    try {
      await deleteEvidence(caseId, docId);
      if (selectedDocId === docId) {
        setSelectedDocId(null);
        setClaims([]);
      }
      await loadEvidences();
      onRefreshCase();
    } catch (err: any) {
      alert(err.message || '증거 삭제에 실패했습니다.');
    }
  };

  /**
   * 문서 본문 텍스트 분석 및 사실(Fact) 추출 트리거
   */
  const handleExtract = async (docId: string) => {
    try {
      await extractEvidence(caseId, docId);
      alert('사실관계 추출 작업이 요청되었습니다. 잠시 후 문서를 다시 선택해 확인해주세요.');
      loadEvidences();
      loadClaims(docId);
    } catch (err) {
      alert('추출 요청에 실패했습니다.');
    }
  };

  /**
   * 사실 주장(Claim) 승인 처리 및 문서 상태·재분석 안내 갱신 (EVT-023)
   */
  const handleApprove = async (claimId: string) => {
    if (!selectedDocId) return;
    try {
      await reviewEvidenceClaim(caseId, selectedDocId, claimId, { action: 'APPROVE' });
      await Promise.all([
        loadClaims(selectedDocId),
        loadEvidences(),
        loadConflicts(),
      ]);
      setShowReanalyzePrompt(true);
      onRefreshCase();
    } catch (err) {
      alert('승인 처리 실패');
    }
  };

  /**
   * 모달을 통한 수정 승인 / 반려 실행 및 문서 상태·재분석 안내 갱신 (EVT-023)
   */
  const handleModalSubmit = async ({ newStatement, reason }: { newStatement?: string; reason?: string }) => {
    if (!selectedDocId || !modalState.action) return;
    const currentAction = modalState.action;
    try {
      await reviewEvidenceClaim(caseId, selectedDocId, modalState.claimId, {
        action: currentAction,
        new_statement: newStatement,
        review_reason: reason,
      });
      setModalState({ isOpen: false, action: null, claimId: '', statement: '' });
      await Promise.all([
        loadClaims(selectedDocId),
        loadEvidences(),
        loadConflicts(),
      ]);
      if (currentAction === 'EDIT') {
        setShowReanalyzePrompt(true);
      }
      onRefreshCase();
    } catch (err) {
      alert('리뷰 처리에 실패했습니다.');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* 1. 상단 타이틀 및 업로드 액션 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '1.4em', fontWeight: 700, margin: '0 0 4px 0' }}>📁 증거 문서 자료실 (Evidence)</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.88em' }}>
            계약서, 영수증, 문자 내역 등 법률 증거를 업로드하고 AI로 사실관계를 추출 및 검토합니다.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            ref={fileInputRef}
            onChange={handleUpload}
            disabled={uploading}
            style={{ display: 'none' }}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="btn btn-primary"
          >
            {uploading ? '업로드 중...' : '＋ 증거 파일 업로드'}
          </button>
          <button onClick={loadEvidences} className="btn btn-secondary">
            새로고침
          </button>
        </div>
      </div>

      {/* EVT-023: 신규 증거 승인 후 AI 재분석 유도 배너 */}
      {showReanalyzePrompt && (
        <div
          className="card"
          style={{
            padding: '14px 18px',
            backgroundColor: 'var(--primary-light)',
            borderColor: 'var(--primary)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '12px',
            flexWrap: 'wrap',
          }}
        >
          <div>
            <strong style={{ color: 'var(--primary)', fontSize: '0.95em', display: 'block', marginBottom: '2px' }}>
              ✓ 새로운 증거 사실이 사건 사실관계(Facts)에 반영되었습니다.
            </strong>
            <span style={{ fontSize: '0.84em', color: 'var(--text-secondary)' }}>
              갱신된 증거를 바탕으로 AI 법률 상담을 다시 받거나 대응 계획(Action Plan)을 갱신할 수 있습니다.
            </span>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              onClick={() => navigate('../chat')}
              className="btn btn-primary btn-sm"
            >
              💬 AI 법률 상담(재분석) 이동
            </button>
            <button
              onClick={() => navigate('../action')}
              className="btn btn-secondary btn-sm"
            >
              📋 대응 계획 갱신 이동
            </button>
            <button
              onClick={() => setShowReanalyzePrompt(false)}
              className="btn btn-outline btn-sm"
            >
              닫기
            </button>
          </div>
        </div>
      )}

      {/* 2. 메인 2단 레이아웃 (좌측 문서 목록 / 우측 추출 사실 상세) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 1fr) 2fr', gap: '20px' }}>
        {/* 좌측: 등록된 증거 문서 목록 */}
        <div className="card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h3 style={{ fontSize: '1.05em', fontWeight: 700, margin: 0 }}>등록된 문서 ({documents.length})</h3>
          </div>

          {documents.length === 0 && (
            <p style={{ color: 'var(--text-muted)', fontSize: '0.88em', textAlign: 'center', padding: '30px 0' }}>
              등록된 증거 문서가 없습니다.<br />위 업로드 버튼을 눌러보세요.
            </p>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {documents.map((doc) => {
              const displayName = doc.original_filename || (doc as any).filename || '증거 문서';
              const isSelected = selectedDocId === doc.id;

              return (
                <div
                  key={doc.id}
                  onClick={() => setSelectedDocId(doc.id)}
                  style={{
                    padding: '12px',
                    borderRadius: 'var(--radius-md)',
                    border: isSelected ? '1.5px solid var(--primary)' : '1px solid var(--border)',
                    backgroundColor: isSelected ? 'var(--primary-light)' : 'var(--surface-alt)',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                    <strong style={{ fontSize: '0.92em', color: isSelected ? 'var(--primary)' : 'var(--text-main)', wordBreak: 'break-all' }}>
                      {displayName}
                    </strong>
                    <span
                      className={
                        doc.status === 'APPROVED'
                          ? 'badge badge-green'
                          : doc.status === 'REVIEW_REQUIRED'
                            ? 'badge badge-amber'
                            : doc.status === 'EXTRACTING'
                              ? 'badge badge-blue'
                              : doc.status === 'FAILED' || doc.status === 'EXTRACTION_UNAVAILABLE'
                                ? 'badge badge-red'
                                : 'badge badge-gray'
                      }
                      style={{ fontSize: '0.72em', whiteSpace: 'nowrap' }}
                    >
                      {doc.status === 'APPROVED'
                        ? 'APPROVED (검토완료)'
                        : doc.status === 'REVIEW_REQUIRED'
                          ? 'REVIEW_REQUIRED'
                          : doc.status}
                    </span>
                  </div>

                  <div style={{ display: 'flex', gap: '6px', marginTop: '8px' }}>
                    {(doc.status === 'UPLOADED' || doc.status === 'FAILED' || doc.status === 'REVIEW_REQUIRED' || doc.status === 'APPROVED') && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleExtract(doc.id);
                        }}
                        className="btn btn-outline btn-sm"
                        style={{ fontSize: '0.78em', padding: '2px 8px' }}
                      >
                        사실 추출
                      </button>
                    )}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(doc.id, displayName);
                      }}
                      className="btn btn-danger btn-sm"
                      style={{ fontSize: '0.78em', padding: '2px 8px' }}
                    >
                      삭제
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 우측: 추출된 사실(Claim/Fact) 목록 및 리뷰 */}
        <div className="card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h3 style={{ fontSize: '1.05em', fontWeight: 700, margin: 0 }}>
              추출된 사실 및 진술 {selectedDocId && `(${claims.length}건)`}
            </h3>
            {selectedDocId && (
              <button onClick={() => loadClaims(selectedDocId)} className="btn btn-secondary btn-sm">
                새로고침
              </button>
            )}
          </div>

          {!selectedDocId && (
            <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)' }}>
              좌측 목록에서 문서를 선택하면 추출된 사실 정보를 검토할 수 있습니다.
            </div>
          )}

          {selectedDocId && claims.length === 0 && (
            <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)' }}>
              추출된 사실 정보가 없습니다.<br />좌측 문서의 [사실 추출] 버튼을 눌러 AI 분석을 시작하세요.
            </div>
          )}

          {selectedDocId && claims.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {claims.map((claim: any) => {
                const claimId = claim.id || claim.claim_id;
                const rawType = claim.claim_type || claim.type;
                const typeLabel = getClaimTypeLabel(rawType);
                const badgeClass = getClaimTypeBadgeClass(typeLabel);
                const reviewStatus = claim.review_status || claim.status || 'PENDING';
                const confidence = claim.confidence !== undefined ? claim.confidence : '-';

                return (
                  <div
                    key={claimId}
                    style={{
                      padding: '14px',
                      borderRadius: 'var(--radius-md)',
                      border: '1px solid var(--border)',
                      backgroundColor: 'var(--surface)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span className={`badge ${badgeClass}`}>{typeLabel}</span>
                        <strong style={{ fontSize: '0.95em', color: 'var(--text-main)' }}>{claim.statement}</strong>
                      </div>
                      <span
                        className={
                          reviewStatus === 'APPROVED' || reviewStatus === 'EDITED'
                            ? 'badge badge-green'
                            : reviewStatus === 'REJECTED'
                            ? 'badge badge-red'
                            : 'badge badge-amber'
                        }
                      >
                        {reviewStatus === 'APPROVED'
                          ? '승인됨 (Fact)'
                          : reviewStatus === 'EDITED'
                          ? '수정 승인됨 (Fact)'
                          : reviewStatus === 'REJECTED'
                          ? '반려됨'
                          : '검토 대기'}
                      </span>
                    </div>

                    <div style={{ fontSize: '0.82em', color: 'var(--text-muted)', marginBottom: '8px' }}>
                      신뢰도: <strong>{confidence}</strong>
                    </div>

                    {/* 출처 원문 (Spans) */}
                    <div
                      style={{
                        padding: '10px 12px',
                        backgroundColor: 'var(--surface-alt)',
                        borderRadius: 'var(--radius-md)',
                        marginBottom: '10px',
                      }}
                    >
                      <strong style={{ fontSize: '0.82em', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>
                        출처 원문 (Spans):
                      </strong>
                      {!claim.spans || claim.spans.length === 0 ? (
                        <span style={{ fontSize: '0.82em', color: 'var(--text-muted)' }}>연결된 출처 발췌문이 없습니다.</span>
                      ) : (
                        <ul style={{ margin: 0, paddingLeft: '16px' }}>
                          {claim.spans.map((s: any, idx: number) => {
                            const spanId = s.id || s.span_id || `span-${idx}`;
                            return <SpanItem key={spanId} span={s} />;
                          })}
                        </ul>
                      )}
                    </div>

                    {/* 검토 액션 버튼 (PENDING 상태일 때) */}
                    {reviewStatus === 'PENDING' && (
                      <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
                        <button
                          onClick={() => handleApprove(claimId)}
                          className="btn btn-primary btn-sm"
                        >
                          ✓ 승인 (Fact 등록)
                        </button>
                        <button
                          onClick={() =>
                            setModalState({
                              isOpen: true,
                              action: 'EDIT',
                              claimId,
                              statement: claim.statement,
                            })
                          }
                          className="btn btn-secondary btn-sm"
                        >
                          ✎ 수정 승인
                        </button>
                        <button
                          onClick={() =>
                            setModalState({
                              isOpen: true,
                              action: 'REJECT',
                              claimId,
                              statement: claim.statement,
                            })
                          }
                          className="btn btn-danger btn-sm"
                        >
                          ✕ 반려
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* 3. 증거 상충(Conflicts) 조회 오류 배너 및 확정 상충 / 추가 확인 필요 분리 카드 */}
      {conflictError && (
        <div
          className="card"
          style={{
            borderColor: 'var(--danger-border)',
            backgroundColor: 'var(--danger-bg)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          <div>
            <strong style={{ color: 'var(--danger)', fontSize: '0.95em', display: 'block', marginBottom: '2px' }}>
              ⚠️ 증거 상충 분석 결과를 불러오지 못했습니다
            </strong>
            <span style={{ fontSize: '0.85em', color: 'var(--text-secondary)' }}>
              {conflictError}
            </span>
          </div>
          <button onClick={loadConflicts} className="btn btn-secondary btn-sm">
            다시 시도
          </button>
        </div>
      )}

      {!conflictError && conflicts.length > 0 && (() => {
        const confirmedConflicts = conflicts.filter(
          (c) => typeof c === 'string' || c?.status !== 'POTENTIAL_CONFLICT'
        );
        const potentialConflicts = conflicts.filter(
          (c) => typeof c === 'object' && c?.status === 'POTENTIAL_CONFLICT'
        );

        const formatSpanLocation = (item: any): string | null => {
          const parts: string[] = [];
          if (item?.page_number !== undefined && item?.page_number !== null) {
            parts.push(`p.${item.page_number}`);
          }
          if (item?.paragraph_index !== undefined && item?.paragraph_index !== null) {
            parts.push(`문단 ${Number(item.paragraph_index) + 1}`);
          }
          return parts.length > 0 ? parts.join(', ') : null;
        };

        const renderConflictCard = (c: any, idx: number, isPotential: boolean) => {
          if (typeof c === 'string') {
            return (
              <div
                key={idx}
                style={{
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  backgroundColor: 'var(--surface)',
                  border: '1px solid var(--danger-border)',
                  fontSize: '0.86em',
                  color: 'var(--danger)',
                }}
              >
                {c}
              </div>
            );
          }
          const explanation =
            c.explanation ||
            c.description ||
            (isPotential
              ? '추가 사실관계 또는 시점 확인이 필요한 잠재 상충 항목입니다.'
              : '증거 진술과 기존 사건 사실 간 상충이 감지되었습니다.');
          const spanLoc = formatSpanLocation(c);

          return (
            <div
              key={c.conflict_id || idx}
              style={{
                padding: '12px 14px',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: 'var(--surface)',
                border: isPotential ? '1px solid var(--border)' : '1px solid var(--danger-border)',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span className={isPotential ? 'badge badge-amber' : 'badge badge-red'}>
                  {isPotential ? '추가 확인 필요' : '확정 상충'}
                </span>
                <span
                  style={{
                    fontSize: '0.88em',
                    fontWeight: 600,
                    color: isPotential ? 'var(--text-main)' : 'var(--danger)',
                  }}
                >
                  {explanation}
                </span>
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                  gap: '8px',
                  fontSize: '0.84em',
                }}
              >
                {c.claim_statement && (
                  <div
                    style={{
                      padding: '8px 10px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: 'var(--bg-secondary)',
                      border: '1px solid var(--border-color)',
                    }}
                  >
                    <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                      📄 증거 문서 진술 {c.document_name ? `(${c.document_name})` : ''}
                      {spanLoc && (
                        <span style={{ marginLeft: '6px', color: 'var(--primary)' }}>
                          [{spanLoc}]
                        </span>
                      )}
                    </div>
                    <div style={{ color: 'var(--text-primary)' }}>{c.claim_statement}</div>
                  </div>
                )}
                {c.target_description && (
                  <div
                    style={{
                      padding: '8px 10px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: 'var(--bg-secondary)',
                      border: '1px solid var(--border-color)',
                    }}
                  >
                    <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                      📌 비교 대상 기존 사실 {c.target_document_name ? `(${c.target_document_name})` : ''}
                    </div>
                    <div style={{ color: 'var(--text-primary)' }}>{c.target_description}</div>
                  </div>
                )}
              </div>
            </div>
          );
        };

        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            {confirmedConflicts.length > 0 && (
              <div
                className="card"
                style={{
                  borderColor: 'var(--danger-border)',
                  backgroundColor: 'var(--danger-bg)',
                }}
              >
                <h4 style={{ margin: '0 0 6px 0', color: 'var(--danger)', fontSize: '1em', fontWeight: 700 }}>
                  ⚠️ 확정 상충 ({confirmedConflicts.length}건)
                </h4>
                <p style={{ fontSize: '0.86em', color: 'var(--text-secondary)', marginBottom: '12px' }}>
                  동일한 사실 대상·속성에 대해 서로 양립할 수 없는 진술이 확인되었습니다. 원문 출처와 경위를 확인해 주세요.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {confirmedConflicts.map((c, i) => renderConflictCard(c, i, false))}
                </div>
              </div>
            )}

            {potentialConflicts.length > 0 && (
              <div
                className="card"
                style={{
                  borderColor: 'var(--border)',
                  backgroundColor: 'var(--surface-alt)',
                }}
              >
                <h4 style={{ margin: '0 0 6px 0', color: 'var(--text-main)', fontSize: '1em', fontWeight: 700 }}>
                  🔎 추가 확인 필요 ({potentialConflicts.length}건)
                </h4>
                <p style={{ fontSize: '0.86em', color: 'var(--text-secondary)', marginBottom: '12px' }}>
                  시점·조건 또는 문맥에 따라 양립 가능 여부가 달라질 수 있는 진술입니다. 계약 변경이나 후속 합의 여부를 확인해 주세요.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {potentialConflicts.map((c, i) => renderConflictCard(c, i, true))}
                </div>
              </div>
            )}
          </div>
        );
      })()}

      {/* 사실 검토(수정 승인 / 반려) 인라인 모달 */}
      <ReviewModal
        isOpen={modalState.isOpen}
        action={modalState.action}
        currentStatement={modalState.statement}
        onClose={() => setModalState({ isOpen: false, action: null, claimId: '', statement: '' })}
        onSubmit={handleModalSubmit}
      />
    </div>
  );
};
