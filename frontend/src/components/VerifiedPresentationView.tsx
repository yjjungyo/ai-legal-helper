/**
 * 모바일에서도 1화면 안에서 법률 판단의 방향과 다음 확인 항목을 읽도록 구성한다.
 * 안내 카드의 모든 문장은 검증을 통과한 최종 답변에서 그대로 발췌한다.
 * 인용 버튼은 기존의 정확한 evidenceId/claimId/spanId 매핑을 재사용한다.
 */
import type { ClaimCitation, ConsultationPresentation } from '../types/consultation';
import { LegalAnswerView, renderInlineMarkdown } from './LegalAnswerView';
import type { CitationMeta } from './LegalAnswerView';
import { buildConsultationDigest, splitAnswerForDisplay } from './consultationDigest';

interface Props {
  presentation?: ConsultationPresentation | null;
  answer?: string;
  isVerified?: boolean;
  claimCitations?: ClaimCitation[];
  onEvidenceClick?: (label: string, meta?: CitationMeta) => void;
}

export const VerifiedPresentationView = ({
  presentation, answer, isVerified = false, claimCitations, onEvidenceClick,
}: Props) => {
  // 현재 원문과 완전히 같은 verified presentation만 사용한다.
  // 조건부 상담이나 구 이력은 표시 전용 파서로 구간만 추출하며, 검증 데이터로 저장하지 않는다.
  const fullAnswer = answer ?? presentation?.blocks.map(b => b.markdown).join('') ?? '';
  const verifiedBlocks = presentation && presentation.blocks.map(b => b.markdown).join('') === fullAnswer
    ? presentation.blocks : null;
  const displayBlocks = verifiedBlocks || splitAnswerForDisplay(fullAnswer);
  const digest = buildConsultationDigest({blocks: displayBlocks});

  // 명시적인 결론/요약이 없는 답변에는 임의의 '핵심 결론'을 붙이지 않는다.
  if (!digest.lead && digest.sections.length === 0) {
    return (
      <div className="chat-verified-fallback">
        <LegalAnswerView content={digest.fullAnswer} claimCitations={claimCitations} onEvidenceClick={onEvidenceClick} />
      </div>
    );
  }

  return (
    <div className="chat-consultation-digest" data-presentation-version={verifiedBlocks ? presentation?.schema_version : 'display-only'}>
      {digest.lead && (
        <section className="chat-digest-lead" aria-label="상담 핵심 답변">
          <div className="chat-digest-eyebrow">
            <span className="chat-digest-eyebrow-dot" aria-hidden="true" />
            상담 핵심 답변
            <span className="chat-digest-original-note">{isVerified && verifiedBlocks ? '검증된 답변 원문 발췌' : '상담 답변 원문 발췌'}</span>
          </div>
          <div className="chat-digest-lead-text">
            <LegalAnswerView content={digest.lead} claimCitations={claimCitations} onEvidenceClick={onEvidenceClick} />
          </div>
        </section>
      )}

      {digest.sections.length > 0 && (
        <div className="chat-digest-grid" aria-label="상담 중요 항목">
          {digest.sections.map((section) => (
            <section className={`chat-digest-summary chat-digest-${section.kind}`} key={section.kind}>
              <h3 className="chat-digest-summary-title">{section.title}</h3>
              <ul className="chat-digest-summary-list">
                {section.items.map((item, index) => (
                  <li key={index}>
                    {renderInlineMarkdown(item, onEvidenceClick, claimCitations, item)}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      <details className="chat-digest-full-answer">
        <summary>
          <span className="chat-digest-expand-icon" aria-hidden="true">▸</span>
          <span className="chat-digest-expand-title">전체 법률 분석 자세히 보기</span>
          <span className="chat-digest-expand-hint">사실관계 · 법률 판단 · 증거별 근거</span>
        </summary>
        <div className="chat-digest-full-content">
          <LegalAnswerView
            content={digest.fullAnswer}
            claimCitations={claimCitations}
            onEvidenceClick={onEvidenceClick}
          />
        </div>
      </details>
    </div>
  );
};
