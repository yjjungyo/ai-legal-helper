/**
 * @fileoverview 법률 문서(Legal Documents) 생성, 직접 편집(새 리비전 저장) 및 서면 다운로드 섹션 컴포넌트
 * 내용증명, 계약해지통지서, 손해배상 청구서, 체불임금 최고장 등 법률 서면을 AI가 사실관계 및 대응계획에 맞춰 자동 작성하며,
 * 본문 직접 편집 후 DOCX / PDF 포맷으로 실시간 내보내기(Export)를 지원합니다.
 */

import React, { useState, useEffect } from 'react';
import { type LegalDocument, listDocuments, createDocument, updateDocument, exportDocument } from '../api/documentClient';

interface Props {
  /** 사건 식별자 UUID */
  caseId: string;
}

const PRESET_DOC_TYPES = [
  '임대차보증금 반환 요구 내용증명',
  '임대차계약 종료 통지서',
  '손해배상 청구 내용증명',
  '체불임금 지급 최고장',
  '계약 해지 및 원상회복 통지서',
  '고소장 초안',
];

/**
 * 법률 문서 관리 및 작성 컴포넌트
 */
export const DocumentSection: React.FC<Props> = ({ caseId }) => {
  const [documents, setDocuments] = useState<LegalDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [customDocType, setCustomDocType] = useState<string>(PRESET_DOC_TYPES[0]);

  // 인라인 서면 편집 상태
  const [editingDocId, setEditingDocId] = useState<string | null>(null);
  const [editingContent, setEditingContent] = useState<string>('');
  const [savingEdit, setSavingEdit] = useState(false);

  /**
   * 사건에 작성된 법률 문서 목록 조회
   */
  const fetchDocuments = async () => {
    try {
      setLoading(true);
      const data = await listDocuments(caseId);
      setDocuments(data);
    } catch (err: any) {
      setError(err.message || '문서 목록을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  /**
   * 지정된 유형의 법률 서면 자동 생성 (EVT-026)
   * @param docType 서면 유형 명칭
   */
  const handleGenerate = async (docType: string) => {
    const trimmed = docType.trim();
    if (!trimmed) return;
    try {
      setLoading(true);
      setError(null);
      await createDocument(caseId, { document_type: trimmed, title: trimmed + ' 초안' });
      await fetchDocuments();
    } catch (err: any) {
      setError(err.message || '문서 생성 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  /**
   * 서면 본문 편집 모드 시작
   */
  const handleStartEdit = (docId: string, currentContent: string) => {
    setEditingDocId(docId);
    setEditingContent(currentContent);
  };

  /**
   * 편집된 서면 본문을 새 리비전(DocumentRevision)으로 저장
   */
  const handleSaveEdit = async (docId: string, finalize: boolean = false) => {
    if (!editingContent.trim()) return;
    try {
      setSavingEdit(true);
      setError(null);
      await updateDocument(caseId, docId, {
        content: editingContent,
        review_status: finalize ? 'APPROVED' : undefined,
      });
      setEditingDocId(null);
      await fetchDocuments();
    } catch (err: any) {
      setError(err.message || '서면 수정 저장 중 오류가 발생했습니다.');
    } finally {
      setSavingEdit(false);
    }
  };

  /**
   * 서면 파일 다운로드 (DOCX / PDF) (EVT-027)
   * @param docId 문서 식별자
   * @param format 파일 포맷 ('docx' | 'pdf')
   */
  const handleExport = async (docId: string, format: string = 'docx') => {
    try {
      setLoading(true);
      const blob = await exportDocument(caseId, docId, format);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `document_${docId.substring(0, 8)}.${format}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert('파일 다운로드 실패: ' + (err.message || String(err)));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, [caseId]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* 1. 상단 타이틀 및 서면 템플릿/직접 입력 생성 액션 바 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h2 style={{ fontSize: '1.4em', fontWeight: 700, margin: '0 0 4px 0' }}>📄 법률 문서 작성실 (Legal Documents)</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.88em' }}>
            확정된 사실관계와 AI 분석 법리를 인용하여 내용증명·통지서·고소장 등을 작성, 편집하고 DOCX/PDF로 다운로드합니다.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          <select
            className="input"
            style={{ width: 'auto', minWidth: '210px' }}
            value={PRESET_DOC_TYPES.includes(customDocType) ? customDocType : ''}
            onChange={(e) => {
              if (e.target.value) setCustomDocType(e.target.value);
            }}
          >
            <option value="" disabled>
              서면 템플릿 선택...
            </option>
            {PRESET_DOC_TYPES.map((preset) => (
              <option key={preset} value={preset}>
                {preset}
              </option>
            ))}
          </select>
          <input
            type="text"
            className="input"
            style={{ width: '240px' }}
            placeholder="작성할 서면 명칭 직접 입력"
            value={customDocType}
            onChange={(e) => setCustomDocType(e.target.value)}
          />
          <button
            onClick={() => handleGenerate(customDocType)}
            disabled={loading || !customDocType.trim()}
            className="btn btn-primary"
          >
            {loading ? '작성 중...' : '＋ 서면 초안 AI 생성'}
          </button>
        </div>
      </div>

      {/* 2. 에러 알림 */}
      {error && (
        <div style={{ padding: '14px 18px', backgroundColor: 'var(--danger-bg)', color: 'var(--danger)', borderRadius: 'var(--radius-md)', border: '1px solid var(--danger-border)', fontSize: '0.9em' }}>
          ⚠️ 오류: {error}
        </div>
      )}

      {/* 3. 로딩 상태 */}
      {loading && documents.length === 0 && (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          법률 문서를 불러오는 중입니다...
        </div>
      )}

      {/* 4. 빈 상태 */}
      {!loading && documents.length === 0 && (
        <div className="card empty-state">
          <div style={{ fontSize: '2.5em', marginBottom: '12px' }}>📑</div>
          <h3 style={{ fontSize: '1.15em', fontWeight: 600, marginBottom: '8px' }}>작성된 법률 문서가 없습니다</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9em', marginBottom: '20px' }}>
            상단에서 원하는 서면 유형을 선택하거나 직접 입력한 뒤 "서면 초안 AI 생성" 버튼을 눌러보세요.
          </p>
          <button onClick={() => handleGenerate(customDocType || PRESET_DOC_TYPES[0])} className="btn btn-primary">
            ＋ 첫 서면 초안 생성하기
          </button>
        </div>
      )}

      {/* 5. 문서 목록 */}
      {!loading && documents.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {documents.map((doc) => {
            const latestRevision = doc.revisions && doc.revisions.length > 0 ? doc.revisions[doc.revisions.length - 1] : null;
            const isEditing = editingDocId === doc.id;

            return (
              <div key={doc.id} className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', borderBottom: '1px solid var(--border)', paddingBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <h3 style={{ fontSize: '1.1em', fontWeight: 700, margin: 0, color: 'var(--text-main)' }}>
                      {doc.title}
                    </h3>
                    <span className={doc.status === 'FINALIZED' ? 'badge badge-blue' : 'badge badge-green'}>
                      {doc.status}
                    </span>
                  </div>

                  <div style={{ display: 'flex', gap: '6px' }}>
                    {latestRevision && !isEditing && (
                      <button
                        onClick={() => handleStartEdit(doc.id, latestRevision.content || '')}
                        className="btn btn-secondary btn-sm"
                      >
                        ✎ 서면 내용 편집
                      </button>
                    )}
                    <button onClick={() => handleExport(doc.id, 'docx')} className="btn btn-outline btn-sm">
                      📥 DOCX 다운로드
                    </button>
                    <button onClick={() => handleExport(doc.id, 'pdf')} className="btn btn-outline btn-sm">
                      📥 PDF 다운로드
                    </button>
                  </div>
                </div>

                {/* 서면 미리보기 및 인라인 편집 영역 */}
                {latestRevision ? (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <span style={{ fontSize: '0.85em', fontWeight: 600, color: 'var(--text-secondary)' }}>
                        최신 초안 서면 (검증 상태:{' '}
                        <strong
                          style={{
                            color:
                              latestRevision.verification_status === 'WARN'
                                ? 'var(--warning)'
                                : latestRevision.verification_status === 'FAIL'
                                ? 'var(--danger)'
                                : 'var(--primary)',
                          }}
                        >
                          {latestRevision.verification_status || 'PASS'}
                        </strong>
                        )
                      </span>
                      <span style={{ fontSize: '0.8em', color: 'var(--text-muted)' }}>
                        버전 v{latestRevision.revision_number || 1} (총 {doc.revisions.length}개 리비전)
                      </span>
                    </div>

                    {isEditing ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        <textarea
                          className="textarea"
                          style={{ minHeight: '280px', fontFamily: 'var(--font-sans)', lineHeight: 1.7, fontSize: '0.92em' }}
                          value={editingContent}
                          onChange={(e) => setEditingContent(e.target.value)}
                        />
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                          <button
                            onClick={() => setEditingDocId(null)}
                            disabled={savingEdit}
                            className="btn btn-outline btn-sm"
                          >
                            취소
                          </button>
                          <button
                            onClick={() => handleSaveEdit(doc.id, false)}
                            disabled={savingEdit}
                            className="btn btn-secondary btn-sm"
                          >
                            {savingEdit ? '저장 중...' : '임시 저장 (새 리비전)'}
                          </button>
                          <button
                            onClick={() => handleSaveEdit(doc.id, true)}
                            disabled={savingEdit}
                            className="btn btn-primary btn-sm"
                          >
                            {savingEdit ? '확정 중...' : '✓ 최종본 확정 저장'}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div
                        style={{
                          padding: '16px 20px',
                          backgroundColor: 'var(--surface-alt)',
                          borderRadius: 'var(--radius-md)',
                          border: '1px solid var(--border)',
                          fontFamily: 'var(--font-sans)',
                          lineHeight: 1.7,
                          fontSize: '0.92em',
                          whiteSpace: 'pre-wrap',
                          color: 'var(--text-main)',
                        }}
                      >
                        {latestRevision.content}
                      </div>
                    )}
                  </div>
                ) : (
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.88em' }}>초안 내용이 비어 있습니다.</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

