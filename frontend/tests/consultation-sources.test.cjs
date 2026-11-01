const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const filename = path.resolve(__dirname, '../src/components/chat/ConsultationSources.tsx');
const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
});
const component = new Module(filename, module);
component.paths = Module._nodeModulePaths(path.dirname(filename));
component._compile(outputText, filename);
const { ConsultationSources, collectDisplaySources } = component.exports;

test('같은 파일의 중복 출처는 1회 표시하고 전체 파일명은 보존한다', () => {
  const sources = [
    { file: 'E10_HUG_관련_구상권_가압류_등기_열람_메모.txt', evidence_id: 'uuid-10', source_type: 'CASE_EVIDENCE' },
    { file: 'E10_HUG_관련_구상권_가압류_등기_열람_메모.txt', evidence_id: 'uuid-10', source_type: 'CASE_EVIDENCE' },
  ];
  const display = collectDisplaySources(sources);
  assert.equal(display.length, 1);
  assert.equal(display[0].label, 'E10_HUG_관련_구상권_가압류_등기_열람_메모.txt');
  const html = renderToStaticMarkup(React.createElement(ConsultationSources, { sources, onEvidenceClick() {} }));
  assert.match(html, /인용 근거 1건/);
  assert.match(html, /E10_HUG_관련_구상권_가압류_등기_열람_메모.txt/);
});
test('서로 다른 증거 UUID는 파일명이 같아도 합치지 않는다', () => {
  const sources = [
    { file: 'E01_계약서.txt', evidence_id: 'doc-a', source_type: 'CASE_EVIDENCE' },
    { file: 'E01_계약서.txt', evidence_id: 'doc-b', source_type: 'CASE_EVIDENCE' },
  ];
  assert.equal(collectDisplaySources(sources).length, 2);
});
test('법령 시행 버전이 다르면 하나의 법령으로 합치지 않는다', () => {
  const sources = [
    { file: '민법', source_type: 'STATUTE', statute_name: '민법', article: '제6조', effective_date: '2024-01-01' },
    { file: '민법', source_type: 'STATUTE', statute_name: '민법', article: '제6조', effective_date: '2026-01-01' },
  ];
  assert.equal(collectDisplaySources(sources).length, 2);
});
test('정확한 파일명이 없는 증거는 클릭 가능한 버튼으로 만들지 않는다', () => {
  const html = renderToStaticMarkup(React.createElement(ConsultationSources, {
    sources: [{file: 'EVIDENCE:uuid',source_type:'CASE_EVIDENCE'}],
    onEvidenceClick() { throw new Error('unexpected click'); },
  }));
  assert.match(html, /파일명 확인 필요/);
  assert.doesNotMatch(html, /chat-source-link/);
});
