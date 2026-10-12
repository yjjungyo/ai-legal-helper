import React, { useState, useEffect } from 'react';
import { type LegalDocument, listDocuments, createDocument, exportDocument } from '../api/documentClient';

interface Props {
  caseId: string;
}

export const DocumentSection: React.FC<Props> = ({ caseId }) => {
  const [documents, setDocuments] = useState<LegalDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      const data = await listDocuments(caseId);
      setDocuments(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async (docType: string) => {
    try {
      setLoading(true);
      setError(null);
      await createDocument(caseId, { document_type: docType, title: docType + ' 초안' });
      await fetchDocuments();
    } catch (err: any) {
      setError(err.message || 'Failed to generate document');
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async (docId: string, format: string = 'docx') => {
    try {
      setLoading(true);
      const blob = await exportDocument(caseId, docId, format);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'document_' + docId.substring(0, 8) + '.' + format;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      alert("Export failed: " + err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, [caseId]);

  if (loading && documents.length === 0) return <div>문서 로딩 중...</div>;

  return (
    <div className="box" style={{ marginTop: '20px', border: '2px solid #28a745' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3>법률 문서 (Legal Documents)</h3>
        <div>
            <button onClick={() => handleGenerate("임대차보증금 반환 요구 내용증명")} style={{ backgroundColor: '#28a745', color: 'white', marginRight: '5px' }}>
            내용증명 생성
            </button>
            <button onClick={() => handleGenerate("임대차계약 종료 통지서")} style={{ backgroundColor: '#28a745', color: 'white' }}>
            계약 종료 통지서 생성
            </button>
        </div>
      </div>
      
      {error && <div style={{ color: 'red' }}>Error: {error}</div>}
      
      {documents.length === 0 ? (
        <p>생성된 문서가 없습니다.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', marginTop: '10px' }}>
          {documents.map((doc) => (
            <div key={doc.id} style={{ border: '1px solid #ccc', padding: '10px', borderRadius: '5px' }}>
              <h4>{doc.title} <span style={{ fontSize: '0.8em', color: '#666' }}>({doc.status})</span></h4>
              
              <button onClick={() => handleExport(doc.id, 'docx')}>DOCX 다운로드</button>
              <button onClick={() => handleExport(doc.id, 'pdf')} style={{ marginLeft: '10px' }}>PDF 다운로드</button>
              
              {doc.revisions && doc.revisions.length > 0 && (
                <div style={{ marginTop: '10px', backgroundColor: '#f8f9fa', padding: '10px' }}>
                  <strong>최신 초안 내용:</strong>
                  <pre style={{ whiteSpace: 'pre-wrap', fontSize: '0.9em' }}>
                    {doc.revisions[doc.revisions.length - 1].content}
                  </pre>
                  <p><small>검증 상태: {doc.revisions[doc.revisions.length - 1].verification_status}</small></p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
