const { test } = require('node:test');
const assert = require('node:assert/strict');
const { setTimeout: delay } = require('node:timers/promises');
const { Scheduler } = require('../src/scheduler');

function harness(t) {
  const runs = [],
    published = [],
    failed = [];
  const scheduler = new Scheduler(
    (options) => new Promise((resolve, reject) => runs.push({ ...options, resolve, reject })),
    (key, result) => published.push([key, result]),
    (key, error) => failed.push([key, error.message]),
  );
  t.after(() => scheduler.dispose());
  return { scheduler, runs, published, failed };
}

test('save bursts coalesce; only one workspace runs at a time', async (t) => {
  const { scheduler, runs, published } = harness(t);
  for (let i = 0; i < 10; i++) scheduler.request('a', { version: i }, 10);
  scheduler.request('b', {}, 10);
  await delay(30);
  assert.equal(runs.length, 1);
  assert.equal(runs[0].version, 9);
  runs[0].resolve('a report');
  await delay(0);
  assert.equal(runs.length, 2);
  runs[1].resolve('b report');
  await delay(0);
  assert.deepEqual(published, [
    ['a', 'a report'],
    ['b', 'b report'],
  ]);
});

test('late completion cannot replace a newer save; superseded errors stay silent', async (t) => {
  const { scheduler, runs, published, failed } = harness(t);
  scheduler.request('a', {}, 0);
  await delay(10);
  scheduler.request('a', {}, 0);
  await delay(10);
  assert.equal(runs[0].signal.aborted, true);
  assert.equal(runs.length, 1);
  runs[0].resolve('stale');
  await delay(0);
  runs[1].resolve('current');
  await delay(0);
  assert.deepEqual(published, [['a', 'current']]);
  scheduler.request('a', {}, 0);
  await delay(10);
  scheduler.invalidate('a');
  runs[2].reject(new Error('stale failure'));
  await delay(0);
  assert.deepEqual(failed, []);
});

test('removal, disposal, current errors and changed settings', async (t) => {
  const { scheduler, runs, published, failed } = harness(t);
  scheduler.request('removed', {}, 20);
  scheduler.invalidate('removed');
  scheduler.request('a', { executable: 'new-cli' }, 0);
  await delay(30);
  assert.equal(runs.length, 1);
  assert.equal(runs[0].executable, 'new-cli');
  runs[0].reject(new Error('missing'));
  await delay(0);
  assert.deepEqual(failed, [['a', 'missing']]);
  scheduler.request('a', {}, 0);
  await delay(10);
  scheduler.dispose();
  assert.equal(runs[1].signal.aborted, true);
  runs[1].resolve('late');
  await delay(0);
  assert.deepEqual(published, []);
});
