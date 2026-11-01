/**
 * 최종 답변 인용 출처: 평소에는 간결한 개수만 표시하며 전체 파일명은 펼치면 그대로 보인다.
 * 모호하거나 매칭되지 않은 문서에는 근거 없는 연결 버튼을 만들지 않는다.
 */
import type { Source } from '../../types/consultation';
import type { CitationMeta } from '../LegalAnswerView';

interface Props {
  sources: Source[];
  onEvidenceClick: (label: string, meta?: CitationMeta) => void;
}

type DisplaySource = {
  key: string;
  label: string;
  kind: 'evidence' | 'law' | 'precedent' | 'other';
  evidenceId?: string;
  claimId?: string;
  spanId?: string;
  url?: string;
  linkLabel?: string;
};

function presentSource(s: Source): DisplaySource | null {
  const rawFilename = (s.original_filename || s.document_name || s.filename || s.file_name || s.file || '').trim();
  const fileName = /^(?:EVIDENCE:|GRAPH:|VECTOR:|UNKNOWN$|\?$)/i.test(rawFilename) ? '' : rawFilename;
  const isEvidence = s.source_type === 'CASE_EVIDENCE' || Boolean(s.evidence_id);
  const isStatute = s.source_type === 'STATUTE' || Boolean(s.statute_name);
  const isPrecedent = s.source_type === 'PRECEDENT' || Boolean(s.case_number);
  const kind: DisplaySource['kind'] = isEvidence ? 'evidence' : isStatute ? 'law' : isPrecedent ? 'precedent' : 'other';

  let label: string;
  if (kind === 'evidence') {
    label = fileName || '파일명 확인 필요';
  } else if (kind === 'law') {
    const law = (s.statute_name || s.title || fileName || '').split('[')[0].trim();
    const article = (s.article || '').trim();
    label = [law, article && !law.includes(article) ? article : ''].filter(Boolean).join(' ') || '법령명 확인 필요';
  } else if (kind === 'precedent') {
    label = [s.court, s.case_number].filter(Boolean).join(' ') || s.title || fileName || '판례명 확인 필요';
  } else {
    label = s.title || fileName || '출처명 확인 필요';
  }
  const id = (s.source_id || s.document_id || '').trim();
  const key = kind === 'evidence' ? `evidence:${s.evidence_id || fileName || id}` :
    `${kind}:${label}`;
  return {
    key, label, kind,
    evidenceId: s.evidence_id || undefined,
    claimId: s.claim_id || undefined,
    spanId: s.span_id || undefined,
    url: s.source_url || undefined,
  };
}

/** 같은 이름의 다른 증거 UUID가 있으면 각각 보존한다. */
export function collectDisplaySources(sources: Source[]): DisplaySource[] {
  const items: DisplaySource[] = [];
  const found = new Set<string>();
  for (const src of sources || []) {
    const item = presentSource(src);
    if (!item || found.has(item.key)) continue;
    found.add(item.key);
    items.push(item);
  }
  return items;
}

export const ConsultationSources = ({ sources, onEvidenceClick }: Props) => {
  const items = collectDisplaySources(sources);
  if (items.length === 0) return null;
  const evidenceCount = items.filter((item) => item.kind === 'evidence').length;
  const legalCount = items.filter((item) => item.kind === 'law' || item.kind === 'precedent').length;

  return (
    <details className="chat-sources-details">
      <summary className="chat-sources-summary">
        <span>인용 근거 {items.length}건</span>
        <span className="chat-sources-counts">
          {evidenceCount > 0 && `증거 ${evidenceCount}건`}
          {evidenceCount > 0 && legalCount > 0 && ' · '}
          {legalCount > 0 && `법령·판례 ${legalCount}건`}
        </span>
        <span className="chat-sources-chevron" aria-hidden="true">▾</span>
      </summary>
      <ul className="chat-sources-list">
        {items.map((item) => {
          const isEvidence = item.kind === 'evidence';
          const canOpenEvidence = isEvidence && Boolean(item.evidenceId || item.label !== '파일명 확인 필요');
          return (
            <li key={item.key} className="chat-source-item">
              <span className="chat-source-category">
                {isEvidence ? '증거' : item.kind === 'law' ? '법령' : item.kind === 'precedent' ? '판례' : '참고'}
              </span>
              {canOpenEvidence ? (
                <button
                  type="button"
                  className="chat-source-link"
                  onClick={() => onEvidenceClick(item.label, {
                    evidenceId: item.evidenceId,
                    claimId: item.claimId,
                    spanId: item.spanId,
                  })}
                >
                  {item.label}
                </button>
              ) : item.url && /^https:\/\//i.test(item.url) ? (
                <a className="chat-source-link" href={item.url} target="_blank" rel="noopener noreferrer">
                  {item.label}
                </a>
              ) : (
                <span className="chat-source-text">{item.label}</span>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
};
