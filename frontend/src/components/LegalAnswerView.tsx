/**
 * @fileoverview 법률 상담 답변 구조화 및 안전한 마크다운 렌더러 컴포넌트
 * 원시 마크다운 기호를 파괴적으로 제거하지 않고, 안전한 인라인 마크다운(볼드, 이탤릭, 인라인 코드) 및
 * 지시서 P2-03의 8대 권장 구성요소(사건 요약, 확인된 사실, 법률 쟁점, 적용 법령 및 근거, 분석 결과,
 * 불확실/추가확인 사항, 다음 행동, 검증된 출처)를 가독성 높은 카드/섹션 양식으로 렌더링합니다.
 */

import React from 'react';

interface LegalAnswerViewProps {
  /** 렌더링할 법률 답변 텍스트 */
  content: string;
}

/**
 * 8대 권장 구성요소 분류 정보
 */
interface SectionCategoryConfig {
  icon: string;
  theme: 'summary' | 'facts' | 'issues' | 'statutes' | 'analysis' | 'uncertain' | 'action' | 'sources' | 'banner' | 'warning' | 'normal';
}

/**
 * 섹션 제목으로부터 8대 권장 구성요소 및 특수 블록 테마를 분류하는 함수
 * @param title 섹션 제목
 * @returns 해당 섹션의 아이콘 및 테마 설정
 */
function classifySectionTitle(title: string): SectionCategoryConfig {
  const t = title.toLowerCase();

  // 특수 시스템 배너 및 경고
  if (t.includes('insufficient') || t.includes('근거 불충분') || t.includes('검증 안내') || t.includes('판단 유보') || t.includes('withheld') || t.includes('안내:')) {
    return { icon: '🛡️', theme: 'banner' };
  }
  if (t.includes('미검증') || t.includes('초안 주의') || t.includes('주의사항') || t.includes('경고')) {
    return { icon: '⚠️', theme: 'warning' };
  }

  // 1. 핵심 결론
  if (t.includes('핵심 결론') || t.includes('사건 요약') || t.includes('상담 요약') || t.includes('개요')) {
    return { icon: '📋', theme: 'summary' };
  }
  // 2. 사건 사실관계 및 증거
  if (t.includes('사실관계') || t.includes('확인된 사실') || t.includes('사건 사실') || t.includes('증거 자료') || t.includes('기초 사실')) {
    return { icon: '🔍', theme: 'facts' };
  }
  // 3. 쟁점별 법률 분석
  if (t.includes('쟁점별 법률 분석') || t.includes('법률 분석') || t.includes('법적 근거 및 심층 분석') || t.includes('법률 쟁점') || t.includes('주요 쟁점') || t.includes('쟁점')) {
    return { icon: '⚖️', theme: 'issues' };
  }
  // 4. 우선순위별 다음 행동
  if (t.includes('우선순위') || t.includes('다음 행동') || t.includes('action plan') || t.includes('조치 사항') || t.includes('대응 방안') || t.includes('행동 가이드')) {
    return { icon: '🚀', theme: 'action' };
  }
  // 5. 추가 확인사항
  if (t.includes('추가 확인') || t.includes('확인사항') || t.includes('유의사항') || t.includes('입증 필요') || t.includes('불확실')) {
    return { icon: '⚠️', theme: 'uncertain' };
  }

  // 보조 분류 (기존 호환성)
  if (t.includes('적용 법령') || t.includes('관련 법령') || t.includes('법적 근거') || t.includes('관련 조문') || t.includes('판례')) {
    return { icon: '📜', theme: 'statutes' };
  }
  if (t.includes('분석 결과') || t.includes('법률 검토') || t.includes('종합 의견') || t.includes('판단 결과')) {
    return { icon: '💡', theme: 'analysis' };
  }
  if (t.includes('검증된 출처') || t.includes('참고 자료') || t.includes('출처 목록')) {
    return { icon: '📚', theme: 'sources' };
  }

  return { icon: '▪', theme: 'normal' };
}

/**
 * 인라인 마크다운(볼드, 이탤릭, 인라인 코드)을 안전하게 React 노드 배열로 변환하는 함수
 * XSS 위험이 전혀 없도록 정규식 분할 후 안전한 JSX 엘리먼트를 반환합니다.
 * @param text 한 줄의 텍스트
 * @returns React 노드 배열
 */
export function renderInlineMarkdown(text: string): React.ReactNode[] {
  if (!text) return [];

  // 토큰 분할 정규식: **볼드**, `인라인코드`, *이탤릭*
  const tokenRegex = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  const parts = text.split(tokenRegex);

  return parts.map((part, index) => {
    if (!part) return null;

    // 볼드: **text**
    if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
      return (
        <strong key={index} style={{ fontWeight: 700, color: 'var(--text-main, #0f172a)' }}>
          {part.slice(2, -2)}
        </strong>
      );
    }

    // 인라인 코드: `code`
    if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
      return (
        <code
          key={index}
          style={{
            backgroundColor: 'var(--surface-alt, #f1f5f9)',
            border: '1px solid var(--border, #e2e8f0)',
            borderRadius: '4px',
            padding: '1px 5px',
            fontSize: '0.88em',
            fontFamily: 'monospace',
            color: '#0969da',
            margin: '0 2px',
          }}
        >
          {part.slice(1, -1)}
        </code>
      );
    }

    // 이탤릭: *text*
    if (part.startsWith('*') && part.endsWith('*') && part.length >= 2) {
      return (
        <em key={index} style={{ fontStyle: 'italic' }}>
          {part.slice(1, -1)}
        </em>
      );
    }

    // 일반 텍스트
    return <span key={index}>{part}</span>;
  });
}

/**
 * 개별 줄의 서식(불릿, 번호 목록, 일반 문장, 빈 줄)에 따라 깔끔한 스타일 적용
 */
function renderFormattedLine(line: string, index: number): React.ReactNode {
  const trimmed = line.trim();
  if (!trimmed) {
    return <div key={index} style={{ height: '6px' }} />;
  }

  // 1. 불릿 목록 (- 또는 • 또는 *)
  if (trimmed.startsWith('- ') || trimmed.startsWith('• ') || trimmed.startsWith('* ')) {
    const textContent = trimmed.substring(2);
    return (
      <div
        key={index}
        style={{
          display: 'flex',
          gap: '8px',
          alignItems: 'flex-start',
          margin: '3px 0 3px 6px',
        }}
      >
        <span style={{ color: 'var(--primary, #3b82f6)', fontWeight: 'bold' }}>•</span>
        <span style={{ flex: 1, lineHeight: 1.6 }}>{renderInlineMarkdown(textContent)}</span>
      </div>
    );
  }

  // 2. 번호 목록 (1., 2), 가., (1) 등)
  const numMatch = trimmed.match(/^(\d+[.)]|\([0-9]+\)|[가-힣][.)])\s*(.+)$/);
  if (numMatch) {
    return (
      <div
        key={index}
        style={{
          display: 'flex',
          gap: '8px',
          alignItems: 'flex-start',
          margin: '3px 0 3px 6px',
        }}
      >
        <span style={{ color: 'var(--text-muted, #64748b)', fontWeight: 600, minWidth: '20px' }}>
          {numMatch[1]}
        </span>
        <span style={{ flex: 1, lineHeight: 1.6 }}>{renderInlineMarkdown(numMatch[2])}</span>
      </div>
    );
  }

  // 3. 인용구 (> text)
  if (trimmed.startsWith('>')) {
    const quoteText = trimmed.replace(/^>\s*/, '');
    return (
      <div
        key={index}
        style={{
          borderLeft: '3px solid var(--border-focus, #3b82f6)',
          paddingLeft: '10px',
          margin: '4px 0',
          color: 'var(--text-secondary, #475569)',
          fontStyle: 'italic',
        }}
      >
        {renderInlineMarkdown(quoteText)}
      </div>
    );
  }

  // 4. 일반 문장
  return (
    <div key={index} style={{ margin: '2px 0', lineHeight: 1.6 }}>
      {renderInlineMarkdown(line)}
    </div>
  );
}

/**
 * 구조화된 법률의견서 및 마크다운 텍스트를 섹션별 UI 요소로 파싱하여 렌더링하는 컴포넌트
 */
export const LegalAnswerView: React.FC<LegalAnswerViewProps> = ({ content }) => {
  if (!content) return null;

  // 줄바꿈 단위로 분할하여 파싱
  const rawLines = content.split('\n');

  // 섹션 단위로 그룹화
  const sections: Array<{
    type: SectionCategoryConfig['theme'];
    title?: string;
    icon?: string;
    lines: string[];
  }> = [];

  let currentSection: {
    type: SectionCategoryConfig['theme'];
    title?: string;
    icon?: string;
    lines: string[];
  } = { type: 'normal', lines: [] };

  for (const line of rawLines) {
    const trimmed = line.trim();

    // 구분선 감지 (=================== 또는 -------------------)
    if (/^={10,}$/.test(trimmed) || /^-{3,}$/.test(trimmed)) {
      if (currentSection.lines.length > 0 || currentSection.title) {
        sections.push(currentSection);
      }
      sections.push({ type: 'normal', title: '__DIVIDER__', lines: [] });
      currentSection = { type: 'normal', lines: [] };
      continue;
    }

    // 섹션 헤더 감지: [제목...] 형태 또는 ### 제목 또는 ## 제목
    let detectedTitle: string | null = null;
    const bracketMatch = trimmed.match(/^\[(.+)\]$/);
    const mdHeaderMatch = trimmed.match(/^#{1,4}\s*(.+)$/);

    if (bracketMatch) {
      detectedTitle = bracketMatch[1];
    } else if (mdHeaderMatch) {
      detectedTitle = mdHeaderMatch[1].replace(/^\*\*|\*\*$/g, ''); // 볼드 감싸진 헤더 정제
    }

    if (detectedTitle) {
      if (currentSection.lines.length > 0 || currentSection.title) {
        sections.push(currentSection);
      }
      const cat = classifySectionTitle(detectedTitle);
      currentSection = {
        type: cat.theme,
        title: detectedTitle,
        icon: cat.icon,
        lines: [],
      };
      continue;
    }

    // 빈 줄이 아니고 현재 섹션이 있는 경우 내용 누적
    currentSection.lines.push(line);
  }

  if (currentSection.lines.length > 0 || currentSection.title) {
    sections.push(currentSection);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', lineHeight: 1.65 }}>
      {sections.map((sec, idx) => {
        // 1. 구분선
        if (sec.title === '__DIVIDER__') {
          return (
            <div
              key={idx}
              style={{
                borderTop: '1px dashed var(--border, #e2e8f0)',
                margin: '8px 0',
              }}
            />
          );
        }

        // 첫 번째 본문 행이 섹션 제목(sec.title)과 완전히 중복되는 경우(예: [1. 핵심 결론] 바로 아래 "1. 핵심 결론" 또는 "**1. 핵심 결론**" 재출력) 필터링하여 이중 제목 노출 방지
        const normalizeTitle = (t: string) => t.replace(/[*#_`~[\]]/g, '').trim().toLowerCase();
        const normSecTitle = sec.title ? normalizeTitle(sec.title) : '';
        const linesToRender: string[] = [];
        let skippedDuplicate = false;

        for (const l of sec.lines) {
          const normL = normalizeTitle(l);
          if (!skippedDuplicate && normSecTitle && (normL === normSecTitle || normL === normSecTitle.replace(/^[0-9.]+\s*/, ''))) {
            skippedDuplicate = true;
            continue;
          }
          linesToRender.push(l);
        }

        // 2. 검증 실패 / 불충분 근거 안내 배너
        if (sec.type === 'banner') {
          return (
            <div
              key={idx}
              style={{
                backgroundColor: 'var(--warning-bg, #fffbeb)',
                border: '1px solid var(--warning-border, #fef3c7)',
                borderLeft: '4px solid var(--warning, #f59e0b)',
                borderRadius: 'var(--radius-md, 6px)',
                padding: '14px 16px',
                color: 'var(--text-main, #1e293b)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontWeight: 700,
                  fontSize: '0.98em',
                  color: 'var(--warning-dark, #b45309)',
                  marginBottom: '8px',
                }}
              >
                <span>{sec.icon || '🛡️'}</span>
                <span>{sec.title}</span>
              </div>
              <div style={{ fontSize: '0.9em', color: 'var(--text-main)' }}>
                {linesToRender.map((l, lIdx) => renderFormattedLine(l, lIdx))}
              </div>
            </div>
          );
        }

        // 3. 미검증 초안 / 불확실성 주의 경고 박스
        if (sec.type === 'warning' || sec.type === 'uncertain') {
          return (
            <div
              key={idx}
              style={{
                backgroundColor: '#fff7ed',
                border: '1px solid #fed7aa',
                borderLeft: '4px solid #ea580c',
                borderRadius: 'var(--radius-md, 6px)',
                padding: '12px 14px',
                color: 'var(--text-main, #1e293b)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontWeight: 700,
                  fontSize: '0.94em',
                  color: '#c2410c',
                  marginBottom: '6px',
                }}
              >
                <span>{sec.icon || '⚠️'}</span>
                <span>{sec.title}</span>

              </div>
              <div style={{ fontSize: '0.89em', color: 'var(--text-secondary, #475569)' }}>
                {linesToRender.map((l, lIdx) => renderFormattedLine(l, lIdx))}
              </div>
            </div>
          );
        }

        // 4. 다음 행동 권장 조치 카드 (산뜻한 블루 카드)
        if (sec.type === 'action') {
          return (
            <div
              key={idx}
              style={{
                backgroundColor: '#f0fdf4',
                border: '1px solid #bbf7d0',
                borderLeft: '4px solid #16a34a',
                borderRadius: 'var(--radius-md, 6px)',
                padding: '12px 14px',
                color: 'var(--text-main, #1e293b)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontWeight: 700,
                  fontSize: '0.94em',
                  color: '#15803d',
                  marginBottom: '6px',
                }}
              >
                <span>{sec.icon || '🚀'}</span>
                <span>{sec.title}</span>

              </div>
              <div style={{ fontSize: '0.91em', color: 'var(--text-main)' }}>
                {linesToRender.map((l, lIdx) => renderFormattedLine(l, lIdx))}
              </div>
            </div>
          );
        }

        // 5. 일반 본문 및 8대 권장 구성요소 카드
        return (
          <div
            key={idx}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
              padding: sec.title ? '4px 0' : '0',
            }}
          >
            {sec.title && (
              <div
                style={{
                  fontWeight: 700,
                  fontSize: '0.96em',
                  color: 'var(--primary, #2563eb)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  marginTop: '4px',
                }}
              >
                <span>{sec.icon || '▪'}</span>
                <span>{sec.title}</span>

              </div>
            )}
            <div style={{ fontSize: '0.92em', color: 'var(--text-main)' }}>
              {linesToRender.map((l, lIdx) => renderFormattedLine(l, lIdx))}
            </div>
          </div>
        );
      })}
    </div>
  );
};
