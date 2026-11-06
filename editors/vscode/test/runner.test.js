const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');
const { runCli, LINT_ARGS } = require('../src/runner');

async function fake(t, body) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'skillsaw process ; '));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const executable = path.join(dir, 'fake cli');
  await fs.writeFile(executable, `#!${process.execPath}\n${body}`, { mode: 0o755 });
  return { cwd: dir, executable, timeoutMs: 2000, signal: new AbortController().signal };
}

test('missing executable and invalid executable settings are meaningful failures', async () => {
  const options = {
    executable: 'skillsaw-absent-6f8ce',
    cwd: os.tmpdir(),
    timeoutMs: 1000,
    signal: new AbortController().signal,
  };
  await assert.rejects(runCli(options), /Cannot find skillsaw executable/);
  await assert.rejects(runCli({ ...options, executable: '' }), /Set skillsaw.executable/);
});

// These fake entry points need POSIX shebang support. On Windows the pilot
// invokes the skillsaw.exe installed by pip instead.
test(
  'fixed argv and cwd survive spaces and shell metacharacters; exit 1 is a result',
  { skip: process.platform === 'win32' },
  async (t) => {
    const options = await fake(
      t,
      'console.log(JSON.stringify({argv:process.argv.slice(2),cwd:process.cwd()})); process.stderr.write("notice"); process.exitCode=1;',
    );
    const result = await runCli(options);
    assert.equal(result.code, 1);
    assert.deepEqual(JSON.parse(result.stdout), { argv: LINT_ARGS, cwd: options.cwd });
    assert.equal(result.stderr, 'notice');
  },
);

test(
  'usage errors, output limits, timeouts, signals and cancellation reject',
  { skip: process.platform === 'win32' },
  async (t) => {
    await assert.rejects(
      runCli(await fake(t, 'process.stderr.write("bad argument"); process.exitCode=2;')),
      /exit 2.*bad argument/,
    );
    await assert.rejects(
      runCli({ ...(await fake(t, 'process.stdout.write("x".repeat(4000));')), maxBytes: 100 }),
      /output exceeded/,
    );
    await assert.rejects(
      runCli({ ...(await fake(t, 'setInterval(()=>{},1000);')), timeoutMs: 100 }),
      /exceeded 100 ms/,
    );
    await assert.rejects(runCli(await fake(t, 'process.kill(process.pid,"SIGTERM");')), /SIGTERM/);
  },
);

async function ready(options, name = 'ready') {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    try {
      const contents = await fs.readFile(path.join(options.cwd, name), 'utf8');
      const pid = Number(contents);
      if (/^[1-9]\d*\n$/.test(contents) && validPid(pid)) return pid;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    await delay(10);
  }
  assert.fail('CLI did not become ready');
}

function validPid(pid) {
  return Number.isSafeInteger(pid) && pid > 1 && pid <= 2147483647;
}

function alive(pid) {
  assert(validPid(pid), 'refuse to signal an invalid PID or process group');
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error.code !== 'ESRCH') throw error;
    return false;
  }
}

test('installed CLI stops its Python interpreter on cancellation and timeout', async (t) => {
  const executable =
    process.env.SKILLSAW_CLI ||
    path.resolve(
      __dirname,
      '../../../.venv',
      process.platform === 'win32' ? 'Scripts/skillsaw.exe' : 'bin/skillsaw',
    );
  // On Windows this exercises pip's real console launcher and its Job Object.
  for (const reason of ['cancellation', 'timeout']) {
    await t.test(reason, async (t) => {
      const cwd = await fs.mkdtemp(path.join(os.tmpdir(), 'skillsaw interpreter ; '));
      let controller, outcome, pid;
      t.after(async () => {
        controller?.abort();
        await outcome;
        if (pid !== undefined && alive(pid)) process.kill(pid, 'SIGKILL');
        await fs.rm(cwd, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
      });
      await fs.cp(path.resolve(__dirname, '../../../examples/editor-onboarding'), cwd, {
        recursive: true,
      });
      await fs.copyFile(
        path.resolve(__dirname, '../../../tests/fixtures/editor-slow-rule/slow_rule.py'),
        path.join(cwd, 'slow_rule.py'),
      );
      await fs.appendFile(path.join(cwd, '.skillsaw.yaml'), '\ncustom-rules:\n  - slow_rule.py\n');
      // Repeated cancellation must not accumulate surviving interpreters.
      for (let attempt = 0; attempt < (reason === 'cancellation' ? 3 : 1); attempt++) {
        await fs.rm(path.join(cwd, 'ready'), { force: true });
        controller = new AbortController();
        outcome = runCli({
          executable,
          cwd,
          timeoutMs: reason === 'timeout' ? 5000 : 10000,
          signal: controller.signal,
        }).then(
          () => null,
          (error) => error,
        );
        pid = await ready({ cwd });
        assert(alive(pid), 'the custom rule must be running before cancellation');
        if (reason === 'cancellation') controller.abort();
        const error = await outcome;
        assert(error instanceof Error, 'the slow CLI must not complete normally');
        assert.match(error.message, reason === 'timeout' ? /exceeded 5000 ms/ : /cancelled/);
        assert.equal(alive(pid), false, 'the interpreter must exit before releasing the runner');
        pid = undefined;
      }
    });
  }
});

test('readiness waits for a complete valid PID and cleanup rejects process groups', async (t) => {
  const cwd = await fs.mkdtemp(path.join(os.tmpdir(), 'skillsaw readiness '));
  t.after(() => fs.rm(cwd, { recursive: true, force: true }));
  const marker = path.join(cwd, 'ready');
  await fs.writeFile(marker, '');
  let settled = false;
  const pending = ready({ cwd }).then((pid) => {
    settled = true;
    return pid;
  });
  for (const incomplete of ['', '0\n', '-1\n', '1\n', '123', '999999999999999999\n']) {
    await fs.writeFile(marker, incomplete);
    await delay(20);
    assert.equal(settled, false);
  }
  await fs.writeFile(`${marker}.tmp`, `${process.pid}\n`);
  await fs.rename(`${marker}.tmp`, marker);
  assert.equal(await pending, process.pid);
  for (const invalid of [0, -1, 1, NaN, 1.5, 2147483648])
    assert.throws(() => alive(invalid), /invalid PID/);
});

test(
  'cancellation forcibly terminates a ready CLI ignoring SIGTERM',
  {
    skip: process.platform === 'win32',
  },
  async (t) => {
    const controller = new AbortController();
    const options = await fake(
      t,
      `
    process.on('SIGTERM', () => {});
    require('node:fs').writeFileSync('ready.tmp', String(process.pid) + '\\n');
    require('node:fs').renameSync('ready.tmp', 'ready');
    setInterval(() => {}, 1000);
  `,
    );
    const pending = runCli({ ...options, timeoutMs: 10000, signal: controller.signal });
    const rejected = assert.rejects(pending, /cancelled/);
    const pid = await ready(options);
    t.after(() => {
      if (alive(pid)) process.kill(pid, 'SIGKILL');
    });
    assert(alive(pid));
    const start = Date.now();
    controller.abort();
    await rejected;
    assert(Date.now() - start < 2000, 'forced cancellation is bounded');
    assert.equal(alive(pid), false);
    await assert.rejects(runCli({ ...options, signal: controller.signal }), /cancelled/);
  },
);

test(
  'cancellation settles even when an exited CLI leaves inherited pipes open',
  {
    skip: process.platform === 'win32',
  },
  async (t) => {
    const controller = new AbortController();
    const options = await fake(
      t,
      `
    require('node:fs').writeFileSync('parent.tmp', String(process.pid) + '\\n');
    require('node:fs').renameSync('parent.tmp', 'parent');
    const child = require('node:child_process').spawn(process.execPath, ['-e',
      "require('node:fs').writeFileSync('ready.tmp', String(process.pid) + '\\\\n'); require('node:fs').renameSync('ready.tmp', 'ready'); setInterval(() => {}, 1000);"
    ], { stdio: 'inherit' });
    child.unref();
  `,
    );
    const pending = runCli({ ...options, timeoutMs: 10000, signal: controller.signal });
    const rejected = assert.rejects(pending, /cancelled/);
    const pid = await ready(options);
    t.after(() => {
      if (alive(pid)) process.kill(pid, 'SIGKILL');
    });
    const parent = await ready(options, 'parent');
    const deadline = Date.now() + 5000;
    while (alive(parent)) {
      assert(Date.now() < deadline, 'fake CLI should exit while descendant holds pipes');
      await delay(10);
    }
    const start = Date.now();
    controller.abort();
    await rejected;
    assert(Date.now() - start < 2000, 'inherited pipes cannot retain the scheduler slot');
    assert(alive(pid), 'detached descendants remain the trusted custom rule responsibility');
  },
);
