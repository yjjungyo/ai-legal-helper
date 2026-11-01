/** Summarize only verbatim claims supported by registry sources and bound to a verified answer SHA. */
import type { ConsultationPresentation } from '../types/consultation';

const labels: Record<string, string> = {
  FACT: '확인 사실',
  USER_STATEMENT: '당사자 진술',
  INFERENCE: '정황 추론',
  LEGAL_RULE: '법률 규칙',
  LEGAL_APPLICATION: '법률 적용',
  ACTION: '대응 행동',
  UNCERTAINTY: '확인 필요',
};
const order = ['FACT', 'USER_STATEMENT', 'LEGAL_RULE', 'LEGAL_APPLICATION', 'ACTION', 'INFERENCE', 'UNCERTAINTY'];

export function linkedSemanticCounts(presentation: ConsultationPresentation, blockClaimIds: string[]) {
  if (presentation.verification_binding !== 'HASH_MATCHED') return [];
  const ids = new Set(blockClaimIds);
  const counts: Record<string, number> = {};
  for (const claim of presentation.claims) {
    const type = claim.semantic_type || '';
    if (!ids.has(claim.claim_id) || !labels[type]) continue;
    if (claim.grounding_status !== 'SUPPORTED' || claim.source_binding !== 'SOURCE_LINKED') continue;
    if (!claim.source_refs?.length) continue;
    counts[type] = (counts[type] || 0) + 1;
  }
  return order.filter((type) => counts[type]).map((type) => ({type, label: labels[type], count: counts[type]}));
}
