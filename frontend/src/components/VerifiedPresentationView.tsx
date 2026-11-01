/**
 * P2 구조화 답변 렌더러.
 * 백엔드가 검증된 원문의 연속 구간을 손실 없이 반환하며,
 * 각 블록을 정확히 한 번씩 표시한다. 기존 LegalAnswerView는 상세 서식 처리용으로 재사용한다.
 */
import React from 'react';
import type { ClaimCitation, ConsultationPresentation } from '../types/consultation';
import { LegalAnswerView } from './LegalAnswerView';
import type { CitationMeta } from './LegalAnswerView';

interface Props {
  presentation: ConsultationPresentation;
  claimCitations?: ClaimCitation[];
  onEvidenceClick?: (label: string, meta?: CitationMeta) => void;
}

export const VerifiedPresentationView: React.FC<Props> = ({ presentation, claimCitations, onEvidenceClick }) => {
  return (
    <div className="chat-presentation" data-presentation-version={presentation.schema_version}>
      {presentation.blocks.map((block) => (
        <section
          key={block.block_id}
          className={`chat-presentation-block chat-presentation-${block.kind.toLowerCase()}`}
          data-block-id={block.block_id}
        >
          <LegalAnswerView
            content={block.markdown}
            claimCitations={claimCitations}
            onEvidenceClick={onEvidenceClick}
          />
        </section>
      ))}
    </div>
  );
};
