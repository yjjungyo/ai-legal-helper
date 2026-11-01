const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

function loadTsx(relative) {
  const filename = path.resolve(__dirname, '../src/components/' + relative);
  const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  });
  const mod = new Module(filename, module);
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  mod._compile(outputText, filename);
  return mod.exports;
}

const { ConsultationProgress } = loadTsx('chat/ConsultationProgress.tsx');
const { LegalAnswerView } = loadTsx('LegalAnswerView.tsx');

const steps = [
  { step_id: '1', title: '사건 정보 조회', status: 'COMPLETED' },
  { step_id: '2', title: '법령 검증', status: 'SKIPPED' },
  { step_id: '3', title: '답변 작성', status: 'COMPLETED' },
];
const base = { progress: { steps }, requestId: 'request-1', onApprove() {}, onReject() {} };

test('완료한 상담의 진행 과정은 별도 작은 접힘 영역으로 시작한다', () => {
  const html = renderToStaticMarkup(React.createElement(ConsultationProgress, {
    ...base, status: 'SUCCESS', isCompleted: true,
  }));
  assert.match(html, /<details class="chat-progress-audit">/);
  assert.match(html, /상담 처리 과정 확인/);
  assert.doesNotMatch(html, /class="chat-progress-card"/);
  assert.doesNotMatch(html, /<details[^>]* open/);
  assert.match(html, /건너뜀/);
});

test('완료 상태여도 건너뛰거나 미완료된 단계를 완료로 조작하지 않는다', () => {
  const html = renderToStaticMarkup(React.createElement(ConsultationProgress, {
    ...base, status: 'SUCCESS', isCompleted: true,
  }));
  assert.match(html, /법령 검증/);
  assert.match(html, /건너뜀/);
  assert.doesNotMatch(html, /6단계 완료/);
});

test('분석 중에는 사용자가 진행 단계를 계속 확인할 수 있다', () => {
  const html = renderToStaticMarkup(React.createElement(ConsultationProgress, {
    ...base, status: 'IN_PROGRESS', isCompleted: false,
  }));
  assert.match(html, /chat-progress-card/);
  assert.match(html, /사건 정보 조회/);
});

test('문단형 답변은 빈 줄로 장식 블록을 만들지 않고 일반 법령 제목은 표시한다', () => {
  const html = renderToStaticMarkup(React.createElement(LegalAnswerView, {
    content: '네, 가능합니다.\n\n### 관련 법률\n민법 제6조를 확인하세요.',
  }));
  assert.match(html, /chat-legal-answer/);
  assert.match(html, /chat-legal-heading/);
  assert.match(html, /관련 법률/);
  assert.match(html, /민법 제6조/);
});

test('증거 파일만 적힌 인용 줄을 잘못된 법률 섹션 제목으로 분류하지 않는다', () => {
  const html = renderToStaticMarkup(React.createElement(LegalAnswerView, {
    content: '[E01_임대차계약서.pdf]\n이 증거의 기재 내용을 검토합니다.',
  }));
  assert.doesNotMatch(html, /chat-legal-heading/);
  assert.match(html, /E01_임대차계약서.pdf/);
});
