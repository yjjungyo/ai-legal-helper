const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

const file = path.resolve(__dirname, '../src/components/presentationSemantics.ts');
const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true },
});
const mod = new Module(file, module);
mod.paths = Module._nodeModulePaths(path.dirname(file));
mod._compile(compiled.outputText, file);
const { linkedSemanticCounts } = mod.exports;

test('never show semantics without verified answer hash', () => {
  assert.deepEqual(linkedSemanticCounts({verification_binding:'STATUS_MATCHED',claims:[]}, []), []);
});
test('show only grounded exact claim types', () => {
  const record = {verification_binding:'HASH_MATCHED',claims:[
    {claim_id:'1',semantic_type:'FACT',grounding_status:'SUPPORTED',source_binding:'SOURCE_LINKED',source_refs:['source']},
    {claim_id:'2',semantic_type:'ACTION',grounding_status:'SUPPORTED',source_binding:'NOT_LINKED',source_refs:[]},
  ]};
  assert.deepEqual(linkedSemanticCounts(record, ['1','2']).map(x => x.type), ['FACT']);
});
