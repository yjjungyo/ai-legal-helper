/**
 * 검증된 상담 답변의 표시용 '한눈에 보기'.
 *
 * LLM 재요약 / 추론 금지:
 * - 오직 answer 원문의 문자열을 그대로 발췌한다.
 * - 제목의 제한된 키워드는 배치에만 사용하며 의미/법적 효력을 새로 판정하지 않는다.
 * - 조건·예외가 탈락하지 않도록 발췌 항목은 문장 중간에서 자르지 않는다.
 * - 모든 원문은 항상 '전체 법률 분석'에서 순서 그대로 열람할 수 있다.
 */
import type { ConsultationPresentation, PresentationBlock } from '../types/consultation';

export interface PreviewSection {
  title: string;
  items: string[];
  kind: 'change' | 'action' | 'caution';
}
export interface ConsultationDigest {
  lead: string | null;
  sections: PreviewSection[];
  fullAnswer: string;
}

const CLASSIFIERS: Array<{kind: PreviewSection['kind']; test: RegExp; title: string}> = [
  {kind: 'change', test: /(?:새로.{0,12}확인|추가.{0,10}확인|변화|변동|새로운.{0,6}사실|달라진.{0,6}점)/i, title: '이번 상담에서 달라진 점'},
  {kind: 'action', test: /(?:지금.{0,8}확인|바로.{0,8}확인|확인할.{0,6}사항|우선.{0,8}(?:조치|행동|확인)|다음.{0,6}행동|필요한.{0,6}조치|실행.{0,6}계획|대응.{0,6}방안)/i, title: '우선 확인할 사항'},
  {kind: 'caution', test: /(?:아직.{0,12}단정|주의|미확인|불확실|추가.{0,6}확인.{0,6}필요|판단.{0,6}유보)/i, title: '판단 전 주의할 점'},
];

function getExactBulletLines(block: PresentationBlock): string[] {
  const lines = block.markdown.split(/\r?\n/);
  const items: string[] = [];
  for (const line of lines) {
    const match = line.match(/^\s*(?:[-*•]\s+|\d+[.)]\s+)(.+?)\s*$/);
    if (!match) continue;
    const content = match[1].trim();
    // 독립 인용태그만 존재하면 문장으로 재분류하지 않는다.
    if (!content || /^\[(?:E\d{1,3}[^\]]*)\]$/i.test(content)) continue;
    items.push(content);
    if (items.length >= 2) break;
  }
  return items;
}

/** 구조화 메타데이터가 없는 조건부/이전 상담용 표시 전용 블록 파서. DB에는 쓰지 않는다. */
export function splitAnswerForDisplay(answer: string): PresentationBlock[] {
  if (!answer) return [];
  const lines = answer.match(/[^\n]*\n|[^\n]+$/g) || [];
  const boundaries: number[] = [0];
  let offset = 0;
  const getHeading = (value: string): string | null => {
    const line = value.trim();
    const md = line.match(/^#{1,4}\s+(.+)$/);
    if (md) return md[1].replace(/^\*\*|\*\*$/g, '').trim();
    const bracket = line.match(/^\[([^\[\]\r\n]+)\]$/);
    if (!bracket) return null;
    const title = bracket[1].trim();
    if (/^E\d{1,3}(?:$|[_.\s-])/i.test(title) ||
        /\.(?:pdf|docx|txt|png|jpg|jpeg)$/i.test(title)) return null;
    return title;
  };
  for (const line of lines) {
    if (offset > 0 && getHeading(line)) boundaries.push(offset);
    offset += line.length;
  }
  if (offset !== answer.length) throw new Error('DISPLAY_BLOCK_TEXT_MISMATCH');
  boundaries.push(answer.length);
  const blocks: PresentationBlock[] = [];
  for (let i = 0; i < boundaries.length - 1; i += 1) {
    const start = boundaries[i], end = boundaries[i + 1];
    if (start >= end) continue;
    const markdown = answer.slice(start, end);
    const title = getHeading(markdown.split(/\r?\n/)[0]);
    blocks.push({
      block_id: `LOCAL-${i + 1}`, kind: title ? 'SECTION' : (blocks.length === 0 ? 'LEAD' : 'BODY'),
      start, end, title, markdown, claim_refs: [], source_refs: [],
    });
  }
  return blocks;
}


/** 입력 문자열과 정확히 동일한 전체 답변만 구성한다. */
export function buildConsultationDigest(presentation: Pick<ConsultationPresentation, 'blocks'>): ConsultationDigest {
  const blocks = presentation.blocks || [];
  const fullAnswer = blocks.map((b) => b.markdown).join('');
  const leadBlock = blocks.find((b) => b.kind === 'LEAD' && b.markdown.trim());
  let lead = leadBlock?.markdown.trim() || null;

  // 결론 제목으로 시작하는 답변은 그 섹션의 본문을 그대로 사용한다.
  if (!lead) {
    const explicit = blocks.find((b) =>
      b.kind === 'SECTION' && /(?:핵심\s*결론|최종\s*결론|상담\s*요지|핵심\s*답변)/i.test(b.title || '')
    );
    if (explicit) {
      const firstLineEnd = explicit.markdown.search(/\r?\n/);
      const body = firstLineEnd < 0 ? '' : explicit.markdown.slice(firstLineEnd).trim();
      lead = body || null;
    }
  }

  const sections: PreviewSection[] = [];
  const used = new Set<string>();
  for (const classifier of CLASSIFIERS) {
    const block = blocks.find((b) => b.kind === 'SECTION'
      && classifier.test.test(b.title || '') && !used.has(b.block_id) && getExactBulletLines(b).length > 0);
    if (!block) continue;
    used.add(block.block_id);
    sections.push({
      kind: classifier.kind,
      title: classifier.title,
      items: getExactBulletLines(block),
    });
  }
  return {lead, sections, fullAnswer};
}
