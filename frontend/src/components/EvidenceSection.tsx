import React, { useState, useEffect, useRef } from 'react';
import { 
  uploadEvidence, 
  listEvidence, 
  extractEvidence, 
  getEvidenceClaims, 
  reviewEvidenceClaim, 
  getEvidenceConflicts 
} from '../api/evidenceClient';
import type { EvidenceDocument, EvidenceClaim } from '../types/evidence';

interface Props {
  caseId: string;
  onRefreshCase: () => void;
}

export const EvidenceSection: React.FC<Props> = ({ caseId, onRefreshCase }) => {
  const [documents, setDocuments] = useState<EvidenceDocument[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [claims, setClaims] = useState<EvidenceClaim[]>([]);
  const [conflicts, setConflicts] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const loadEvidences = async () => {
    try {
      const docs = await listEvidence(caseId);
      setDocuments(docs);
    } catch (e) {
      console.error("Failed to load evidence", e);
    }
  };

  const loadConflicts = async () => {
    try {
      const data = await getEvidenceConflicts(caseId);
      setConflicts(data.conflicts || []);
    } catch (e) {
      console.error("Failed to load conflicts", e);
    }
  };

  const loadClaims = async (docId: string) => {
    try {
      const data = await getEvidenceClaims(caseId, docId);
      setClaims(data);
    } catch (e) {
      console.error("Failed to load claims", e);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await uploadEvidence(caseId, file);
      await loadEvidences();
    } catch (err) {
      alert("업로드 실패 (PDF, DOCX, TXT 파일만 지원)");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleExtract = async (docId: string) => {
    try {
      await extractEvidence(caseId, docId);
      alert("추출이 시작되었습니다. 잠시 후 상태를 새로고침 하세요.");
      loadEvidences();
    } catch (err) {
      alert("추출 요청 실패");
    }
  };

  const handleReview = async (docId: string, claimId: string, action: 'APPROVE' | 'EDIT' | 'REJECT') => {
    let newStatement = undefined;
    let reason = undefined;

    if (action === 'EDIT') {
      newStatement = prompt("수정할 내용을 입력하세요:");
      if (!newStatement) return;
    }

    if (action === 'REJECT') {
      reason = prompt("반려 사유를 입력하세요 (선택):") || undefined;
    }

    try {
      await reviewEvidenceClaim(caseId, docId, claimId, { action, new_statement: newStatement, review_reason: reason });
      await loadClaims(docId);
      onRefreshCase();
    } catch (err) {
      alert("리뷰 처리 실패");
    }
  };

  return (
    <div className="evidence-section" style={{ marginTop: '20px', borderTop: '2px solid #ccc', paddingTop: '10px' }}>
      <h3>증거 자료 (Evidence)</h3>
      
      <div style={{ marginBottom: '10px' }}>
        <input 
          type="file" 
          accept=".pdf,.docx,.txt" 
          ref={fileInputRef} 
          onChange={handleUpload} 
          disabled={uploading} 
          style={{ display: 'none' }} 
        />
        <button onClick={() => fileInputRef.current?.click()} disabled={uploading}>
          {uploading ? "업로드 중..." : "증거 파일 업로드 (PDF, DOCX, TXT)"}
        </button>
        <button onClick={loadEvidences} style={{ marginLeft: '10px' }}>새로고침</button>
      </div>

      <div style={{ display: 'flex', gap: '20px' }}>
        <div style={{ flex: 1 }}>
          <h4>문서 목록</h4>
          <ul>
            {documents.map(doc => (
              <li key={doc.id} style={{ marginBottom: '5px', padding: '5px', background: selectedDocId === doc.id ? '#eee' : 'transparent' }}>
                <strong onClick={() => setSelectedDocId(doc.id)} style={{ cursor: 'pointer', textDecoration: 'underline' }}>
                  {doc.original_filename}
                </strong>
                {' '}
                ({doc.status})
                {' '}
                {doc.status === 'REVIEW_REQUIRED' && <button onClick={() => handleExtract(doc.id)}>재추출</button>}
                {(doc.status === 'UPLOADED' || doc.status === 'FAILED') && <button onClick={() => handleExtract(doc.id)}>내용/사실 추출</button>}
              </li>
            ))}
          </ul>
        </div>

        <div style={{ flex: 2, borderLeft: '1px solid #ccc', paddingLeft: '10px' }}>
          <h4>추출된 사실 정보 {selectedDocId && '(리뷰 필요)'}</h4>
          {!selectedDocId && <p>문서를 선택하여 추출된 정보를 확인하세요.</p>}
          {selectedDocId && claims.length === 0 && <p>추출된 정보가 없습니다.</p>}
          {claims.map(claim => (
            <div key={claim.id} style={{ border: '1px solid #aaa', padding: '10px', marginBottom: '10px' }}>
              <p><strong>{claim.claim_type}</strong>: {claim.statement}</p>
              <p style={{ fontSize: '0.9em', color: '#555' }}>신뢰도: {claim.confidence} | 상태: <strong>{claim.review_status}</strong></p>
              <div style={{ fontSize: '0.8em', backgroundColor: '#f9f9f9', padding: '5px', margin: '5px 0' }}>
                <strong>출처 (Spans):</strong>
                <ul>
                  {claim.spans?.map(s => (
                    <li key={s.id}>
                      {s.page_number ? `p.${s.page_number}` : ''} {s.paragraph_index ? `para.${s.paragraph_index}` : ''}: "{s.text_excerpt}"
                    </li>
                  ))}
                </ul>
              </div>
              {claim.review_status === 'PENDING' && (
                <div>
                  <button onClick={() => handleReview(selectedDocId!, claim.id, 'APPROVE')} style={{ marginRight: '5px' }}>승인 (Fact 등록)</button>
                  <button onClick={() => handleReview(selectedDocId!, claim.id, 'EDIT')} style={{ marginRight: '5px' }}>수정 승인</button>
                  <button onClick={() => handleReview(selectedDocId!, claim.id, 'REJECT')}>제외 (반려)</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {conflicts.length > 0 && (
        <div style={{ marginTop: '20px', padding: '10px', border: '1px solid red', backgroundColor: '#fff0f0' }}>
          <h4>충돌 정보 (모순 발생)</h4>
          <ul>
            {conflicts.map((c, i) => (
              <li key={i}>{JSON.stringify(c)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

