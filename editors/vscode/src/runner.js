const { spawn } = require('node:child_process');
const path = require('node:path');

const LINT_ARGS = Object.freeze(['lint', '--format', 'json', '--verbose', '.']);
const MAX_OUTPUT_BYTES = 8 * 1024 * 1024;

function runCli({ executable, cwd, timeoutMs, signal, maxBytes = MAX_OUTPUT_BYTES }) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error('Lint cancelled.'));
      return;
    }
    if (typeof executable !== 'string' || !executable.trim() || executable.includes('\0')) {
      reject(new Error('Set skillsaw.executable to a CLI executable name or path.'));
      return;
    }
    const command = /[/\\]/.test(executable) ? path.resolve(cwd, executable) : executable;
    let child;
    try {
      child = spawn(command, LINT_ARGS, {
        cwd,
        shell: false,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      });
    } catch (error) {
      reject(error);
      return;
    }
    const stdout = [],
      stderr = [];
    let bytes = 0,
      failure,
      finished = false,
      killTimer,
      closeTimer;
    const timer = setTimeout(
      () =>
        stop(
          new Error(
            `skillsaw exceeded ${timeoutMs} ms. Increase skillsaw.timeoutMs or lint in the terminal.`,
          ),
        ),
      timeoutMs,
    );
    function finish(error, result) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      clearTimeout(killTimer);
      clearTimeout(closeTimer);
      signal.removeEventListener('abort', cancel);
      if (error) reject(error);
      else resolve(result);
    }
    function stop(error) {
      if (failure || finished) return;
      failure = error;
      child.kill('SIGTERM');
      killTimer = setTimeout(() => {
        child.kill('SIGKILL');
        // A custom rule can leave a descendant holding its inherited pipes.
        // Bound cleanup even when those pipes never close.
        closeTimer = setTimeout(() => {
          child.stdout.destroy();
          child.stderr.destroy();
          finish(failure);
        }, 250);
      }, 250);
    }
    const cancel = () => stop(new Error('Lint cancelled.'));
    signal.addEventListener('abort', cancel, { once: true });
    function collect(chunks, data) {
      if (failure) return;
      bytes += data.length;
      if (bytes > maxBytes)
        stop(
          new Error(
            `skillsaw output exceeded ${maxBytes} bytes. Lint in the terminal or reduce findings using CLI configuration.`,
          ),
        );
      else chunks.push(data);
    }
    child.stdout.on('data', (data) => collect(stdout, data));
    child.stderr.on('data', (data) => collect(stderr, data));
    child.on('error', (error) =>
      finish(
        new Error(
          error.code === 'ENOENT'
            ? `Cannot find skillsaw executable: ${executable}. Install skillsaw or set skillsaw.executable.`
            : `Cannot run skillsaw: ${error.message}`,
        ),
      ),
    );
    child.on('close', (code, exitSignal) => {
      const result = {
        code,
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8'),
      };
      if (failure) finish(failure);
      else if (code !== 0 && code !== 1)
        finish(
          new Error(
            `skillsaw failed (${exitSignal ?? `exit ${code}`}): ${result.stderr.slice(0, 4000)}`,
          ),
        );
      else finish(null, result);
    });
  });
}

module.exports = { runCli, LINT_ARGS };
