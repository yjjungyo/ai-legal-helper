/**
 * @fileoverview 실제 인라인 인용 렌더러의 증거 연결과 복사 가능한 파일명을 검증한다.
 * 기존 TypeScript·React와 Node 내장 테스트만 사용하며 새 테스트 의존성을 추가하지 않는다.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const test = require('node:test');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

// 실제 TSX를 메모리에서 변환하여 정규식 복제 대신 제품 렌더러를 실행한다.
const filename = path.resolve(__dirname, '../src/components/LegalAnswerView.tsx');
const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
});
const componentModule = new Module(filename, module);
componentModule.paths = Module._nodeModulePaths(path.dirname(filename));
componentModule._compile(compiled.outputText, filename);
const { renderInlineMarkdown, LegalAnswerView } = componentModule.exports;

test('빈 파일명의 다른 증거가 E02 인용에 연결되지 않는다', () => {
  let clicked;
  const citations = [
    { claim_text: '다른 사실', citation_tag: '[E01]', evidence_refs: [
      { evidence_id: 'wrong', evidence_label: 'E01', document_name: '' },
    ] },
    { claim_text: '지급 자료', citation_tag: '[E02]', evidence_refs: [
      { evidence_id: 'correct', evidence_label: 'E02', document_name: 'E02_지급내역.txt' },
    ] },
  ];
  const nodes = renderInlineMarkdown('[E02]', (name, meta) => { clicked = { name, meta }; }, citations);
  const button = nodes.find((node) => node && node.type === 'button');
  button.props.onClick({ stopPropagation() {} });
  assert.equal(clicked.meta.evidenceId, 'correct');
  assert.equal(clicked.name, 'E02_지급내역.txt');
});

test('출처 버튼을 제외한 텍스트에도 세 파일명이 남는다', () => {
  const names = ['E01_계약서.txt', 'E02_지급내역.txt', 'E03_거주기록.txt'];
  const content = '[6. 참고 법률 및 증거 출처]\n' + names.map(
    (name, index) => `- ${name} [E0${index + 1}] (TXT)`,
  ).join('\n');
  const markup = renderToStaticMarkup(React.createElement(LegalAnswerView, { content }));
  const copyText = markup.replace(/<button\b[^>]*>[\s\S]*?<\/button>/g, '').replace(/<[^>]*>/g, '');
  for (const name of names) assert.ok(copyText.includes(name), name);
});


test('일반 대괄호 제목은 증거 버튼으로 변환하지 않는다', () => {
  const nodes = renderInlineMarkdown('[잠정] [검증 완료] [1. 핵심 결론]');
  assert.equal(nodes.filter((node) => node && node.type === 'button').length, 0);
});

test('유사한 E01/E010 라벨을 오인하지 않는다', () => {
  let clicked;
  const citations = [
    { claim_text: 'E010 자료', citation_tag: '[E010]', evidence_refs: [
      { evidence_id: 'e010-id', evidence_label: 'E010', document_name: 'E010_등기.txt' },
    ] },
    { claim_text: 'E01 자료', citation_tag: '[E01]', evidence_refs: [
      { evidence_id: 'e01-id', evidence_label: 'E01', document_name: 'E01_계약서.txt' },
    ] },
  ];
  const nodes = renderInlineMarkdown('[E01]', (name, meta) => { clicked = { name, meta }; }, citations);
  const button = nodes.find((node) => node && node.type === 'button');
  assert.ok(button);
  button.props.onClick({ stopPropagation() {} });
  assert.equal(clicked.meta.evidenceId, 'e01-id');
  assert.equal(clicked.name, 'E01_계약서.txt');
});

test('매칭되지 않는 인용은 다른 문서의 ID로 연결하지 않는다', () => {
  const citations = [
    { claim_text: '다른 증거', citation_tag: '[E01]', evidence_refs: [
      { evidence_id: 'wrong-id', evidence_label: 'E01', document_name: 'E01_계약서.txt' },
    ] },
  ];
  const nodes = renderInlineMarkdown('[E02]', () => {}, citations);
  assert.equal(nodes.filter((node) => node && node.type === 'button').length, 0);
});

test('동일한 증거의 여러 claim이 모호하면 Claim/Span을 임의 지정하지 않는다', () => {
  const citations = [
    { claim_text: '서로 다른 주장 1', citation_tag: '[E02]', evidence_refs: [
      { evidence_id: 'same-document', evidence_label: 'E02', claim_id: 'claim-1', span_id: 'span-1', document_name: 'E02_입금.txt' },
    ] },
    { claim_text: '서로 다른 주장 2', citation_tag: '[E02]', evidence_refs: [
      { evidence_id: 'same-document', evidence_label: 'E02', claim_id: 'claim-2', span_id: 'span-2', document_name: 'E02_입금.txt' },
    ] },
  ];
  let clicked;
  const nodes = renderInlineMarkdown('[E02]', (name, meta) => { clicked = { name, meta }; }, citations);
  nodes.find((node) => node && node.type === 'button').props.onClick({ stopPropagation() {} });
  assert.equal(clicked.meta.evidenceId, 'same-document');
  assert.equal(clicked.meta.claimId, undefined);
  assert.equal(clicked.meta.spanId, undefined);
});
