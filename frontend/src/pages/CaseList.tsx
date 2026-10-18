/**
 * @fileoverview 사건 목록 대시보드 및 신규 사건 생성 페이지
 * 사용자가 등록한 법률 사건을 카드 그리드로 조회하고 신규 사건을 인라인 모달로 생성합니다.
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { listCases, createCase, deleteCase } from '../api/caseClient';
import type { CaseBase } from '../types/case';

/**
 * 신규 사건 생성 모달 프로퍼티 인터페이스
 */
interface CreateCaseModalProps {
  /** 모달 열림 여부 */
  isOpen: boolean;
  /** 모달 닫기 이벤트 핸들러 */
  onClose: () => void;
  /** 사건 생성 완료 후 콜백 */
  onSuccess: (newCaseId: string) => void;
}

/**
 * 신규 법률 사건 생성을 위한 인라인 모달 컴포넌트
 * 브라우저 prompt()를 대체하여 제목 및 유형을 입력받습니다.
 */
function CreateCaseModal({ isOpen, onClose, onSuccess }: CreateCaseModalProps) {
  const [title, setTitle] = useState('');
  const [caseType, setCaseType] = useState('주택임대차');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setErrorMessage('사건 제목을 입력해주세요.');
      return;
    }

    try {
      setIsSubmitting(true);
      setErrorMessage('');
      const newCase = await createCase(title.trim(), caseType);
      onSuccess(newCase.id);
    } catch (err) {
      console.error('Failed to create case:', err);
      setErrorMessage('사건 생성 중 오류가 발생했습니다. 다시 시도해주세요.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3 style={{ fontSize: '1.1em', fontWeight: 700, margin: 0 }}>새 법률 사건 등록</h3>
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
            {errorMessage && (
              <div style={{ padding: '8px 12px', backgroundColor: 'var(--danger-bg)', color: 'var(--danger)', borderRadius: '6px', fontSize: '0.85em', marginBottom: '14px' }}>
                {errorMessage}
              </div>
            )}

            <div className="form-group">
              <label htmlFor="case-title">사건 제목 *</label>
              <input
                id="case-title"
                className="form-control"
                type="text"
                placeholder="예: 보증금 반환 청구 및 임차권등기명령 사건"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                autoFocus
              />
            </div>

            <div className="form-group">
              <label htmlFor="case-type">사건 분류 (분쟁 유형)</label>
              <select
                id="case-type"
                className="form-control"
                value={caseType}
                onChange={(e) => setCaseType(e.target.value)}
              >
                <option value="주택임대차">주택임대차 (보증금/원상복구/계약갱신)</option>
                <option value="상가임대차">상가임대차 (권리금/임대료 분쟁)</option>
                <option value="대여금/채권">대여금 및 채권추심 (차용증/미수금)</option>
                <option value="손해배상">손해배상 청구 (불법행위/채무불이행)</option>
                <option value="근로/노동">근로 및 임금체불 (퇴직금/부당해고)</option>
                <option value="기타 민사">기타 일반 민사 분쟁</option>
              </select>
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={isSubmitting}>
              취소
            </button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? '생성 중...' : '사건 생성'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/**
 * 사건 영구 삭제 확인 인라인 모달 프로퍼티
 */
interface DeleteConfirmModalProps {
  /** 모달 오픈 여부 */
  isOpen: boolean;
  /** 삭제 대상 사건 정보 */
  caseItem: CaseBase | null;
  /** 닫기 핸들러 */
  onClose: () => void;
  /** 삭제 확정 실행 핸들러 */
  onConfirm: () => Promise<void>;
  /** 삭제 진행 중 여부 */
  isDeleting: boolean;
}

/**
 * 사건 영구 삭제 확인 인라인 모달
 * 사건과 연결된 모든 증거, 상담, 대응계획 데이터 영구 파기를 사용자에게 명시적으로 안내합니다.
 */
function DeleteConfirmModal({ isOpen, caseItem, onClose, onConfirm, isDeleting }: DeleteConfirmModalProps) {
  if (!isOpen || !caseItem) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '480px' }}>
        <div className="modal-header" style={{ borderBottomColor: 'var(--danger-border)' }}>
          <h3 style={{ fontSize: '1.1em', fontWeight: 700, margin: 0, color: 'var(--danger)' }}>
            ⚠️ 사건 영구 삭제 확인
          </h3>
          <button 
            type="button" 
            onClick={onClose} 
            disabled={isDeleting}
            style={{ background: 'none', border: 'none', fontSize: '1.2em', cursor: 'pointer', color: 'var(--text-muted)' }}
          >
            ✕
          </button>
        </div>

        <div className="modal-body">
          <p style={{ fontSize: '0.95em', fontWeight: 600, color: 'var(--text-main)', marginBottom: '10px' }}>
            '{caseItem.title}' 사건을 정말로 삭제하시겠습니까?
          </p>
          <div style={{ backgroundColor: 'var(--danger-bg)', border: '1px solid var(--danger-border)', borderRadius: 'var(--radius-md)', padding: '12px', fontSize: '0.85em', color: 'var(--danger)', lineHeight: 1.6 }}>
            <strong>주의: 삭제 시 복구할 수 없습니다!</strong>
            <ul style={{ margin: '6px 0 0 16px', padding: 0 }}>
              <li>업로드된 모든 증거 원본 파일 (PDF, DOCX) 및 추출 사실</li>
              <li>진행된 AI 법률 상담 대화 이력 전체</li>
              <li>수립된 법률 대응 행동 계획(Action Plan) 및 요건</li>
              <li>작성된 내용증명/법률 서면 초안 전체</li>
              <li>지식 그래프(Neo4j) 및 벡터 데이터베이스 임베딩</li>
            </ul>
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={isDeleting}>
            취소
          </button>
          <button 
            type="button" 
            className="btn btn-danger" 
            onClick={onConfirm} 
            disabled={isDeleting}
          >
            {isDeleting ? '모든 데이터 파기 중...' : '영구 삭제'}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * 사건 목록 대시보드 컴포넌트
 */
export function CaseList() {
  const [cases, setCases] = useState<CaseBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [caseToDelete, setCaseToDelete] = useState<CaseBase | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [toastMessage, setToastMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    loadCases();
  }, []);

  /**
   * 사건 목록 데이터를 백엔드 API로부터 조회
   */
  const loadCases = async () => {
    try {
      setLoading(true);
      const data = await listCases();
      setCases(data);
    } catch (e) {
      console.error('사건 목록 로딩 실패:', e);
    } finally {
      setLoading(false);
    }
  };

  /**
   * 사건 영구 삭제 실행
   */
  const handleDeleteCase = async () => {
    if (!caseToDelete) return;
    try {
      setIsDeleting(true);
      await deleteCase(caseToDelete.id);
      setToastMessage({
        type: 'success',
        text: `'${caseToDelete.title}' 사건 및 연관된 모든 데이터가 영구 삭제되었습니다.`,
      });
      setTimeout(() => setToastMessage(null), 4000);
      setCaseToDelete(null);
      await loadCases();
    } catch (err: any) {
      setToastMessage({
        type: 'error',
        text: '사건 삭제 실패: ' + (err.message || String(err)),
      });
      setTimeout(() => setToastMessage(null), 5000);
    } finally {
      setIsDeleting(false);
    }
  };

  /**
   * 상태 코드에 대응하는 배지 스타일 반환
   */
  const getStatusBadge = (status: string) => {
    switch (status?.toUpperCase()) {
      case 'OPEN':
      case 'ACTIVE':
        return <span className="badge badge-green">진행중</span>;
      case 'CLOSED':
        return <span className="badge badge-gray">종결</span>;
      case 'PENDING':
        return <span className="badge badge-amber">검토중</span>;
      default:
        return <span className="badge badge-blue">{status || '진행중'}</span>;
    }
  };

  return (
    <div className="page-container">
      {/* 1. 상단 타이틀 및 액션 바 */}
      <div className="case-list-header">
        <div>
          <h2 style={{ fontSize: '1.5em', fontWeight: 700, marginBottom: '4px' }}>내 사건 관리 대시보드</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9em' }}>
            진행 중인 법률 상담, 증거 수집 및 대응 계획 워크스페이스를 관리합니다.
          </p>
        </div>
        <button 
          className="btn btn-primary" 
          onClick={() => setIsModalOpen(true)}
          style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
        >
          <span>＋</span> 새 사건 등록
        </button>
      </div>

      {/* 알림 토스트 배너 */}
      {toastMessage && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            backgroundColor: toastMessage.type === 'success' ? 'var(--success-bg)' : 'var(--danger-bg)',
            color: toastMessage.type === 'success' ? 'var(--success)' : 'var(--danger)',
            border: `1px solid ${toastMessage.type === 'success' ? 'var(--success-border)' : 'var(--danger-border)'}`,
            fontSize: '0.9em',
            marginBottom: '20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span>{toastMessage.type === 'success' ? '✓ ' : '⚠️ '}{toastMessage.text}</span>
          <button
            onClick={() => setToastMessage(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontWeight: 'bold' }}
          >
            ✕
          </button>
        </div>
      )}

      {/* 2. 로딩 상태 */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)' }}>
          사건 목록을 불러오는 중입니다...
        </div>
      )}

      {/* 3. 빈 상태 (등록된 사건이 없는 경우) */}
      {!loading && cases.length === 0 && (
        <div className="empty-state">
          <div style={{ fontSize: '2.5em', marginBottom: '12px' }}>📂</div>
          <h3 style={{ fontSize: '1.15em', fontWeight: 600, marginBottom: '8px' }}>등록된 사건이 없습니다</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9em', marginBottom: '20px' }}>
            새로운 사건을 등록하고 AI 법률 조언, 증거 분석 및 법률 서면 작성을 시작해보세요.
          </p>
          <button className="btn btn-primary" onClick={() => setIsModalOpen(true)}>
            ＋ 첫 번째 사건 생성하기
          </button>
        </div>
      )}

      {/* 4. 사건 카드 그리드 */}
      {!loading && cases.length > 0 && (
        <div className="case-grid">
          {cases.map((c) => (
            <div 
              key={c.id} 
              className="case-card"
              onClick={() => navigate(`/${c.id}/workspace/overview`)}
            >
              <div>
                <div className="case-card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span className="badge badge-blue" style={{ fontSize: '0.75em' }}>
                      {c.case_type || '주택임대차'}
                    </span>
                    {getStatusBadge(c.status)}
                  </div>

                  {/* 사건 삭제 버튼 */}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setCaseToDelete(c);
                    }}
                    className="btn btn-danger btn-sm"
                    style={{ fontSize: '0.75em', padding: '2px 8px' }}
                    title="사건 및 연관 데이터 영구 삭제"
                  >
                    삭제
                  </button>
                </div>

                <div className="case-card-title">{c.title}</div>
                <div className="case-card-body">
                  <div style={{ fontSize: '0.82em', color: 'var(--text-muted)' }}>
                    사건 번호: <span style={{ fontFamily: 'var(--font-mono)' }}>{c.id.slice(0, 8)}...</span>
                  </div>
                </div>
              </div>

              <div className="case-card-footer">
                <span>
                  최근 갱신: {new Date(c.updated_at).toLocaleDateString()}
                </span>
                <span style={{ color: 'var(--primary)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '4px' }}>
                  작업 공간 이동 &rarr;
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 신규 사건 생성 인라인 모달 */}
      <CreateCaseModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={(newCaseId) => {
          setIsModalOpen(false);
          navigate(`/${newCaseId}/workspace/overview`);
        }}
      />

      {/* 사건 영구 삭제 확인 인라인 모달 */}
      <DeleteConfirmModal
        isOpen={!!caseToDelete}
        caseItem={caseToDelete}
        onClose={() => setCaseToDelete(null)}
        onConfirm={handleDeleteCase}
        isDeleting={isDeleting}
      />
    </div>
  );
}


