const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

function transpileFile(relative, aliases = {}) {
  const filename = path.resolve(__dirname, '../src/components/' + relative);
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true, jsx: ts.JsxEmit.ReactJSX },
  });
  const mod = new Module(filename, module);
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const realRequire = mod.require.bind(mod);
  mod.require = (key) => Object.prototype.hasOwnProperty.call(aliases, key) ? aliases[key] : realRequire(key);
  mod._compile(compiled.outputText, filename);
  return mod.exports;
}

const { buildConsultationDigest, splitAnswerForDisplay } = transpileFile('consultationDigest.ts');

function sample() {
  const parts = [
    { block_id: 'B001', kind: 'LEAD', title: null, markdown: '현 상태에서는 보증금 회수를 확정할 수 없습니다. 먼저 최신 등기와 점유 상태를 확인해야 합니다.\n\n' },
    { block_id: 'B002', kind: 'SECTION', title: '이번에 새로 확인된 권리관계 변화',
      markdown: '### 이번에 새로 확인된 권리관계 변화\n- 신규 가압류 신청이 확인되었습니다. [E10_가압류_자료.pdf]\n- 등기 접수일은 아직 확인되지 않았습니다.\n- 서류를 더 확인합니다.\n' },
    { block_id: 'B003', kind: 'SECTION', title: '지금 바로 확인할 사항',
      markdown: '### 지금 바로 확인할 사항\n- 최신 등기사항증명서 확인\n- 실제 점유와 전입 상태 확인\n- 남은 서류도 확인\n' },
    { block_id: 'B004', kind: 'SECTION', title: '아직 단정할 수 없는 부분',
      markdown: '### 아직 단정할 수 없는 부분\n- 우선변제권 행사를 확정적으로 단정할 수 없습니다.\n' },
    { block_id: 'B005', kind: 'SECTION', title: '관련 법률',
      markdown: '### 관련 법률\n- 주택임대차보호법의 구체적 요건을 검토합니다.\n' },
  ];
  return {schema_version:'1.0',verification_binding:'HASH_MATCHED',blocks:parts,claims:[],sources:[]};
}

test('한눈에 보기는 실제 검증 원문을 재작성하지 않고 그대로 발췌한다', () => {
  const presentation = sample();
  const result = buildConsultationDigest(presentation);
  assert.equal(result.fullAnswer, presentation.blocks.map(b => b.markdown).join(''));
  assert.ok(presentation.blocks[0].markdown.includes(result.lead));
  assert.deepEqual(result.sections.map(s=>s.kind), ['change','action','caution']);
  assert.equal(result.sections[0].items[0], '신규 가압류 신청이 확인되었습니다. [E10_가압류_자료.pdf]');
  assert.equal(result.sections[0].items.length, 2);
  assert.equal(result.sections[1].items.length, 2);
  assert.ok(!JSON.stringify(result.sections).includes('주택임대차보호법의 구체적 요건'));
});

test('조건이나 미확인을 임의로 삭제하거나 확정 사실로 바꾸지 않는다', () => {
  const result = buildConsultationDigest(sample());
  assert.match(result.lead, /확정할 수 없습니다/);
  assert.match(result.sections[0].items[1], /확인되지 않았습니다/);
  assert.match(result.sections[2].items[0], /단정할 수 없습니다/);
});

test('임의의 결론이 없는 답변에 핵심 판단을 만들어내지 않는다', () => {
  const result = buildConsultationDigest({ ...sample(), blocks: [
    {block_id:'B001',kind:'SECTION',title:'관련 법률',markdown:'### 관련 법률\n민법 제6조의 적용 조건은 다음과 같습니다.'},
  ]});
  assert.equal(result.lead, null);
  assert.equal(result.sections.length, 0);
});

test('명시적 핵심 결론 제목이 있으면 해당 본문을 그대로 사용한다', () => {
  const result = buildConsultationDigest({ ...sample(), blocks: [
    {block_id:'B001',kind:'SECTION',title:'핵심 결론',markdown:'### 핵심 결론\n지금은 판단을 유보해야 합니다.'},
  ]});
  assert.equal(result.lead, '지금은 판단을 유보해야 합니다.');
});

test('증거 인용 단독 행을 핵심 판단 항목으로 승격하지 않는다', () => {
  const result = buildConsultationDigest({ ...sample(), blocks: [
    {block_id:'B001',kind:'LEAD',markdown:'추가 확인이 필요합니다.'},
    {block_id:'B002',kind:'SECTION',title:'지금 확인할 사항',markdown:'### 지금 확인할 사항\n- [E01]\n- 권리관계 확인이 필요합니다.'},
  ]});
  assert.deepEqual(result.sections[0].items, ['권리관계 확인이 필요합니다.']);
});

const mockLegal = {
  LegalAnswerView: ({content}) => React.createElement('p', {className:'fake-legal-view'}, content),
  renderInlineMarkdown: (t) => [t],
};
const { VerifiedPresentationView } = transpileFile('VerifiedPresentationView.tsx', {
  './LegalAnswerView': mockLegal,
  './consultationDigest': {buildConsultationDigest},
});

test('초기 화면은 요약을 표시하고 전체 분석은 기본 닫힘 details 안에 둔다', () => {
  const html = renderToStaticMarkup(React.createElement(VerifiedPresentationView, {presentation:sample()}));
  assert.match(html, /상담 핵심 답변/);
  assert.match(html, /이번 상담에서 달라진 점/);
  assert.match(html, /우선 확인할 사항/);
  assert.match(html, /판단 전 주의할 점/);
  assert.match(html, /<details class="chat-digest-full-answer">/);
  assert.doesNotMatch(html, /<details[^>]*\sopen=/);
  assert.match(html, /전체 법률 분석 자세히 보기/);
  assert.match(html, /주택임대차보호법의 구체적 요건/);
});

test('핵심 결론을 뽑을 수 없는 답변은 원문 전체를 그대로 렌더링한다', () => {
  const p = {...sample(),blocks:[{block_id:'B001',kind:'SECTION',title:'관련 법률',markdown:'### 관련 법률\n법률 내용.'}]};
  const html = renderToStaticMarkup(React.createElement(VerifiedPresentationView,{presentation:p}));
  assert.match(html,/chat-verified-fallback/);
  assert.doesNotMatch(html,/전체 법률 분석 자세히 보기/);
  assert.match(html,/법률 내용/);
});


test('조건부 상담에서도 원문을 훼손하지 않고 핵심/상세 레이아웃을 제공한다', () => {
  const answer = '조건부 판단입니다. 추가 확인이 필요합니다.\n\n### 지금 바로 확인할 사항\n- 최신 등기를 확인하세요.\n- 계약 자료를 확보하세요.\n';
  const blocks = splitAnswerForDisplay(answer);
  assert.equal(blocks.map(b => b.markdown).join(''), answer);
  assert.equal(blocks.length, 2);
  const html = renderToStaticMarkup(React.createElement(VerifiedPresentationView, {
    answer, isVerified: false,
  }));
  assert.match(html, /조건부 판단입니다/);
  assert.match(html, /우선 확인할 사항/);
  assert.match(html, /전체 법률 분석 자세히 보기/);
  assert.match(html, /상담 답변 원문 발췌/);
  assert.doesNotMatch(html, /검증된 답변 원문 발췌/);
});

test('조건부 답변에서 증거 파일명을 제목으로 오인하지 않는다', () => {
  const answer = '추가 검토해야 합니다.\n[E01_계약서.pdf]\n### 다음 행동\n- 자료 보완\n';
  const blocks = splitAnswerForDisplay(answer);
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0].kind, 'LEAD');
  assert.equal(blocks[1].title, '다음 행동');
  assert.equal(blocks.map(b => b.markdown).join(''), answer);
});
