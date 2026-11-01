/**
 * P3: 검증된 원문 블록을 순서 그대로 표시한다.
 * 결론·주의·행동은 펼친 상태, 선택적인 상세 근거는 접근성 있는 버튼으로 접는다.
 * 문자열 재요약·재배치·상태 재판정은 이 컴포넌트에서 하지 않는다.
 */
import { useState } from 'react';
import type { ClaimCitation, ConsultationPresentation } from '../types/consultation';
import { LegalAnswerView } from './LegalAnswerView';
import type { CitationMeta } from './LegalAnswerView';
import { shouldCollapsePresentationBlock } from './presentationLayout';

interface Props {
  presentation: ConsultationPresentation;
  claimCitations?: ClaimCitation[];
  onEvidenceClick?: (label: string, meta?: CitationMeta) => void;
}

export const VerifiedPresentationView = ({ presentation, claimCitations, onEvidenceClick }: Props) => {
  const [opened, setOpened] = useState<Record<string, boolean>>({});

  return (
    <div className="chat-presentation" data-presentation-version={presentation.schema_version}>
      {presentation.blocks.map((block, index) => {
        const collapsible = shouldCollapsePresentationBlock(block, index);
        const expanded = !collapsible || (opened[block.block_id] ?? false);
        const toggle = () => setOpened((prev) => ({ ...prev, [block.block_id]: !expanded }));
        const panelId = `presentation-panel-${block.block_id}`;
        return (
          <section
            key={block.block_id}
            className={`chat-presentation-block chat-presentation-${block.kind.toLowerCase()}`}
            data-block-id={block.block_id}
          >
            {collapsible && !expanded && (
              <button
                type="button"
                className="chat-presentation-disclosure"
                aria-expanded={false}
                aria-controls={panelId}
                onClick={toggle}
              >
                <span className="chat-presentation-disclosure-name">{block.title || '상세 내용'}</span>
                <span className="chat-presentation-disclosure-action">상세 보기 ▾</span>
              </button>
            )}
            {collapsible && expanded && (
              <div className="chat-presentation-collapse-row">
                <button
                  type="button"
                  className="chat-presentation-collapse-button"
                  aria-expanded={true}
                  aria-controls={panelId}
                  onClick={toggle}
                >
                  상세 접기 ▴
                </button>
              </div>
            )}
            <div id={panelId} hidden={!expanded}>
              {expanded && (
                <>
                  <LegalAnswerView
                    content={block.markdown}
                    claimCitations={claimCitations}
                    onEvidenceClick={onEvidenceClick}
                  />
                </>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
};
