const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { runCli } = require('../src/runner');
const { parseReport } = require('../src/report');

const executable =
  process.env.SKILLSAW_CLI ||
  path.resolve(
    __dirname,
    '../../../.venv',
    process.platform === 'win32' ? 'Scripts/skillsaw.exe' : 'bin/skillsaw',
  );
const fixture = path.resolve(__dirname, '../../../examples/editor-onboarding');

test('installed CLI: baselines suppress known findings while new violations still fail', async (t) => {
  const cwd = await fs.mkdtemp(path.join(os.tmpdir(), 'skillsaw baseline '));
  t.after(() => fs.rm(cwd, { recursive: true, force: true }));
  await fs.cp(fixture, cwd, { recursive: true });
  const skill = path.join(cwd, 'skills/release-notes/SKILL.md');
  const source = await fs.readFile(skill, 'utf8');
  await fs.writeFile(skill, source.replace('name: release-notes', 'name: Release_Notes'));
  await promisify(execFile)(executable, ['baseline', '.'], { cwd, timeout: 10000 });
  const lint = () =>
    runCli({ executable, cwd, timeoutMs: 10000, signal: new AbortController().signal });
  let result = await lint();
  assert.equal(result.code, 0);
  let report = parseReport(result.stdout);
  assert.deepEqual(report.violations, []);
  assert(report.summary.baseline_suppressed > 0);
  await fs.appendFile(
    path.join(cwd, 'handbook/publishing.md'),
    '\nRead the [missing checklist](absent.md).\n',
  );
  result = await lint();
  assert.equal(result.code, 1);
  report = parseReport(result.stdout);
  assert(report.violations.some((item) => item.rule_id === 'content-broken-internal-reference'));
  assert(report.violations.every((item) => item.rule_id !== 'agentskill-name'));
  assert(report.summary.baseline_suppressed > 0);
});

test('installed CLI: root config, severities, exclusions, extra content, fail level and config failure', async (t) => {
  const cwd = await fs.mkdtemp(path.join(os.tmpdir(), 'skillsaw CLI ; '));
  t.after(() => fs.rm(cwd, { recursive: true, force: true }));
  await fs.cp(fixture, cwd, { recursive: true });
  const lint = () =>
    runCli({ executable, cwd, timeoutMs: 10000, signal: new AbortController().signal });
  const clean = await lint();
  assert.equal(clean.code, 0);
  assert.deepEqual(parseReport(clean.stdout).violations, []);
  const skill = path.join('skills', 'release-notes', 'SKILL.md');
  const source = await fs.readFile(path.join(cwd, skill), 'utf8');
  const broken = source.replace('name: release-notes', 'name: Release_Notes');
  await fs.writeFile(path.join(cwd, skill), broken);
  await fs.mkdir(path.join(cwd, 'drafts/release-notes'), { recursive: true });
  await fs.writeFile(path.join(cwd, 'drafts/release-notes/SKILL.md'), broken);
  let result = await lint();
  assert.equal(result.code, 1);
  let findings = parseReport(result.stdout).violations;
  assert(
    findings.some(
      (item) =>
        item.file_path === skill &&
        item.rule_id === 'agentskill-name' &&
        item.line === 2 &&
        item.severity === 'error',
    ),
  );
  assert(findings.every((item) => !item.file_path?.startsWith(`drafts${path.sep}`)));
  const config = path.join(cwd, '.skillsaw.yaml');
  let settings = await fs.readFile(config, 'utf8');
  settings += '\nrules:\n  agentskill-name:\n    severity: warning\n';
  await fs.writeFile(config, settings);
  result = await lint();
  assert.equal(result.code, 1); // Config's fail-on: warning, not the default.
  assert(
    parseReport(result.stdout)
      .violations.filter((item) => item.rule_id === 'agentskill-name')
      .every((item) => item.severity === 'warning'),
  );
  await fs.writeFile(config, settings.replace('fail-on: warning', 'fail-on: error'));
  assert.equal((await lint()).code, 0); // Warnings must not become process errors.
  await fs.writeFile(path.join(cwd, skill), source);
  await fs.appendFile(
    path.join(cwd, 'handbook/publishing.md'),
    '\nRead the [missing checklist](absent.md).\n',
  );
  result = await lint();
  findings = parseReport(result.stdout).violations;
  assert(
    findings.some(
      (item) =>
        item.file_path === path.join('handbook', 'publishing.md') &&
        item.rule_id === 'content-broken-internal-reference',
    ),
  );
  await fs.writeFile(config, 'rules: [invalid\n');
  result = await lint();
  assert.equal(result.code, 1);
  assert.match(result.stderr, /config/i);
  assert.throws(() => parseReport(result.stdout), /Invalid skillsaw JSON/);
});
