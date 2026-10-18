/**
 * @fileoverview 법률 상담 답변 구조화 렌더러 컴포넌트
 * 원시 마크다운 기호(#, **, --- 등)를 배제하고, 정형화된 공문서 및 법률의견서 양식에 맞추어
 * 안내 배너, 섹션 카드, 불릿 목록, 경고 박스 등을 깔끔하게 시각화합니다.
 */

import React from 'react';

interface LegalAnswerViewProps {
  /** 렌더링할 법률 답변 텍스트 */
  content: string;
}

/**
 * 텍스트에 남아 있을 수 있는 원시 마크다운 기호를 프론트엔드 단에서도 방어적으로 정제
 * @param text 원시 텍스트
 * @returns 정제된 플레인 텍스트
 */
function cleanRawMarkdown(text: string): string {
  if (!text) return '';
  return text
    // 1. 수평선 제거 (---, *** 등)
    .replace(/^\s*[-*_]{3,}\s*$/gm, '')
    // 2. 마크다운 헤더 (#, ##, ### 등) -> [헤더]
    .replace(/^#{1,6}\s*(.+)$/gm, (_match, title) => {
      const t = title.trim();
      return t.startsWith('[') && t.endsWith(']') ? t : `[${t}]`;
    })
    // 3. 볼드 및 이탤릭 (**text**, *text*, __text__) 제거
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '$1')
    // 4. 인용구 (> text) 기호 제거
    .replace(/^>\s*/gm, '')
    // 5. 인라인 백틱 (`code`) 제거
    .replace(/`([^`\n]+)`/g, '$1')
    .trim();
}

/**
 * 정형화된 법률의견서 플레인 텍스트를 섹션별 UI 요소로 파싱하여 렌더링하는 컴포넌트
 */
export const LegalAnswerView: React.FC<LegalAnswerViewProps> = ({ content }) => {
  const cleanedText = cleanRawMarkdown(content);
  if (!cleanedText) return null;

  // 줄바꿈 단위로 분할하여 파싱
  const rawLines = cleanedText.split('\n');

  // 섹션 단위로 그룹화
  const sections: Array<{
    type: 'banner' | 'warning_box' | 'section' | 'divider' | 'text';
    title?: string;
    lines: string[];
  }> = [];

  let currentSection: {
    type: 'banner' | 'warning_box' | 'section' | 'divider' | 'text';
    title?: string;
    lines: string[];
  } = { type: 'text', lines: [] };

  for (const line of rawLines) {
    const trimmed = line.trim();

    // 구분선 감지 (===================)
    if (/^={10,}$/.test(trimmed)) {
      if (currentSection.lines.length > 0 || currentSection.title) {
        sections.push(currentSection);
      }
      sections.push({ type: 'divider', lines: [] });
      currentSection = { type: 'text', lines: [] };
      continue;
    }

    // 섹션 헤더 감지: [제목...] 형태
    const headerMatch = trimmed.match(/^\[(.+)\]$/);
    if (headerMatch) {
      if (currentSection.lines.length > 0 || currentSection.title) {
        sections.push(currentSection);
      }
      const title = headerMatch[1];
      const isBanner = title.includes('INSUFFICIENT') || title.includes('안내:') || title.includes('검증 안내');
      const isWarningBox = title.includes('미검증') || title.includes('주의') || title.includes('한계');

      currentSection = {
        type: isBanner ? 'banner' : isWarningBox ? 'warning_box' : 'section',
        title,
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
        if (sec.type === 'divider') {
          return (
            <div
              key={idx}
              style={{
                borderTop: '1px dashed var(--border)',
                margin: '8px 0',
              }}
            />
          );
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
                <span>🛡️</span>
                <span>{sec.title}</span>
              </div>
              <div style={{ fontSize: '0.9em', color: 'var(--text-main)' }}>
                {sec.lines.map((l, lIdx) => renderFormattedLine(l, lIdx))}
              </div>
            </div>
          );
        }

        // 3. 미검증 초안 주의 경고 박스
        if (sec.type === 'warning_box') {
          return (
            <div
              key={idx}
              style={{
                backgroundColor: 'var(--surface-alt, #f8fafc)',
                border: '1px solid var(--border, #e2e8f0)',
                borderLeft: '4px solid var(--danger, #ef4444)',
                borderRadius: 'var(--radius-md, 6px)',
                padding: '12px 14px',
                color: 'var(--text-main, #1e293b)',
              }}
            >
              <div
                style={{
                  fontWeight: 700,
                  fontSize: '0.93em',
                  color: 'var(--danger, #ef4444)',
                  marginBottom: '6px',
                }}
              >
                ⚠️ {sec.title}
              </div>
              <div style={{ fontSize: '0.88em', color: 'var(--text-secondary)' }}>
                {sec.lines.map((l, lIdx) => renderFormattedLine(l, lIdx))}
              </div>
            </div>
          );
        }

        // 4. 일반 본문 섹션
        return (
          <div key={idx} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
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
                <span>▪</span>
                <span>{sec.title}</span>
              </div>
            )}
            <div style={{ fontSize: '0.92em', color: 'var(--text-main)' }}>
              {sec.lines.map((l, lIdx) => renderFormattedLine(l, lIdx))}
            </div>
          </div>
        );
      })}
    </div>
  );
};

/**
 * 개별 줄의 형태(불릿, 번호 목록, 일반 문장, 빈 줄)에 따라 깔끔한 스타일 적용
 */
function renderFormattedLine(line: string, index: number): React.ReactNode {
  const trimmed = line.trim();
  if (!trimmed) {
    return <div key={index} style={{ height: '6px' }} />;
  }

  // 1. 불릿 목록 (- 또는 •)
  if (trimmed.startsWith('- ') || trimmed.startsWith('• ')) {
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
        <span style={{ flex: 1 }}>{textContent}</span>
      </div>
    );
  }

  // 2. 번호 목록 (1., 2), 가. 등)
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
        <span style={{ color: 'var(--text-muted, #64748b)', fontWeight: 600, minWidth: '18px' }}>
          {numMatch[1]}
        </span>
        <span style={{ flex: 1 }}>{numMatch[2]}</span>
      </div>
    );
  }

  // 3. 일반 문장
  return (
    <div key={index} style={{ margin: '2px 0' }}>
      {line}
    </div>
  );
}

