const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { parseReport, location } = require('../src/report');

const finding = {
  rule_id: 'agentskill-name',
  message: 'Use kebab-case.',
  severity: 'warning',
  file_path: 'skills/café notes/SKILL.md',
  line: 2,
};
function report(violations = [finding]) {
  return { version: '0.21.1', stats: {}, summary: { errors: 0, warnings: 1, info: 0 }, violations };
}

test('existing JSON fields, all severities, additive fields and line-only locations', () => {
  const data = report(
    ['error', 'warning', 'info'].map((severity) => ({
      ...finding,
      severity,
      fixable: true,
      future: {},
    })),
  );
  assert.deepEqual(parseReport(JSON.stringify(data)), data);
  const root = path.resolve('workspace');
  assert.deepEqual(location(root, finding), {
    file: path.join(root, finding.file_path),
    line: 1,
    message: finding.message,
  });
  assert.equal(location(root, { ...finding, line: null }).line, 0);
  assert.equal(
    location(root, { ...finding, file_path: 'outside-repo/publisher.md' }).file,
    path.join(root, 'outside-repo/publisher.md'),
  );
});

test('invalid structured output fails atomically, never becomes a clean report', () => {
  for (const invalid of [
    'not JSON',
    '[]',
    '{}',
    JSON.stringify({ ...report(), summary: null }),
    ...[
      { severity: 'fatal' },
      { line: 0 },
      { line: -2 },
      { line: 1.5 },
      { line: 2 ** 40 },
      { file_path: '' },
      { file_path: 'a\0b' },
      { message: 3 },
      { rule_id: null },
    ].map((change) => JSON.stringify(report([finding, { ...finding, ...change }]))),
  ])
    assert.throws(() => parseReport(invalid), /Invalid skillsaw JSON/);
});

test('redacted, absent and escaping paths stay workspace findings', () => {
  const root = path.resolve('workspace');
  for (const file_path of [
    null,
    '../other/file.md',
    path.resolve('/other/file.md'),
    'C:\\other\\file.md',
    'outside-repo/123abc456def-SKILL.md',
  ]) {
    const target = location(root, { ...finding, file_path });
    assert.equal(target.file, root);
    assert.equal(target.line, 0);
    assert.match(target.message, /location unavailable/);
  }
});

module.exports = { report, finding };
