/** P3: 순수 표시 정책. 원문을 재해석하거나 법률 판단을 변경하지 않는다. */
import type { PresentationBlock } from '../types/consultation';

const important = /(?:핵심|결론|주의|경고|추가\s*확인|미확인|불확실|위험|다음\s*행동|행동\s*가이드|대응|필요\s*조치|우선순위|권리\s*보전)/i;
const optionalDetail = /(?:상세|심층|세부|쟁점별\s*법률\s*분석|법률\s*분석|증거\s*목록|출처\s*목록|참고\s*(?:자료|출처|법률)|법적\s*근거|증거\s*출처)/i;

/**
 * 제목은 정보 표시 우선순위에만 사용한다. 원문을 이동, 생략하거나
 * 확인되지 않은 사실/법적 결론으로 재분류하지 않는다.
 */
export function shouldCollapsePresentationBlock(block: Pick<PresentationBlock, 'kind' | 'title'>, index: number): boolean {
  if (index === 0 || block.kind !== 'SECTION' || !block.title) return false;
  if (important.test(block.title)) return false;
  return optionalDetail.test(block.title);
}
