// One process across the window, one replaceable queued request per folder.
// A generation check is still necessary when cancellation races completion.
class Scheduler {
  constructor(run, publish, failed) {
    this.run = run;
    this.publish = publish;
    this.failed = failed;
    this.entries = new Map();
    this.active = null;
    this.disposed = false;
  }

  invalidate(key) {
    const entry = this.entries.get(key);
    if (entry) clearTimeout(entry.timer);
    this.entries.delete(key);
    if (this.active?.key === key) this.active.controller.abort();
  }

  request(key, options, delay) {
    this.invalidate(key);
    if (this.disposed) return;
    const entry = { key, options, ready: false };
    this.entries.set(key, entry);
    entry.timer = setTimeout(() => {
      entry.ready = true;
      this.drain();
    }, delay);
  }

  async drain() {
    if (this.active || this.disposed) return;
    const entry = [...this.entries.values()].find((item) => item.ready);
    if (!entry) return;
    const controller = new AbortController();
    this.active = { key: entry.key, controller };
    const current = () =>
      !this.disposed && !controller.signal.aborted && this.entries.get(entry.key) === entry;
    try {
      const result = await this.run({ ...entry.options, signal: controller.signal });
      if (current()) this.publish(entry.key, result);
    } catch (error) {
      if (current()) this.failed(entry.key, error);
    } finally {
      if (this.entries.get(entry.key) === entry) this.entries.delete(entry.key);
      this.active = null;
      this.drain();
    }
  }

  dispose() {
    this.disposed = true;
    for (const key of this.entries.keys()) this.invalidate(key);
    this.active?.controller.abort();
  }
}

module.exports = { Scheduler };
