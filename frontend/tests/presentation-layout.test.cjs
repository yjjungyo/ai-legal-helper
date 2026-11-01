const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

const filename = path.resolve(__dirname, '../src/components/presentationLayout.ts');
const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true },
});
const mod = new Module(filename, module);
mod.paths = Module._nodeModulePaths(path.dirname(filename));
mod._compile(outputText, filename);
const { shouldCollapsePresentationBlock } = mod.exports;
const block = (title, kind = 'SECTION') => ({ title, kind });

test('핵심 결론과 주의·다음 행동은 기본으로 공개한다', () => {
  for (const title of ['핵심 결론', '미확인 사항 및 주의', '다음 행동', '권리 보전 조치']) {
    assert.equal(shouldCollapsePresentationBlock(block(title), 2), false, title);
  }
});
test('참고 근거와 장문 심층 분석은 사용자가 펼칠 수 있다', () => {
  for (const title of ['상세 법률 분석', '참고 자료', '법적 근거', '증거 출처 목록']) {
    assert.equal(shouldCollapsePresentationBlock(block(title), 2), true, title);
  }
});
test('첫 번째 블록은 상세 분석 제목이어도 감추지 않는다', () => {
  assert.equal(shouldCollapsePresentationBlock(block('상세 법률 분석'), 0), false);
});
test('원문에 없는 의미를 추측해 일반 섹션을 숨기지 않는다', () => {
  assert.equal(shouldCollapsePresentationBlock(block('현재 계약 상태'), 2), false);
});
