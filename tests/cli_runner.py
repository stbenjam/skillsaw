"""In-process runner for the skillsaw CLI.

The integration suite drives the CLI several hundred times. Spawning an
interpreter for each costs ~160ms, and over half of that is importing
skillsaw before a single file is read — which dominated the suite's
runtime. Calling :func:`skillsaw.cli.main` directly costs ~10ms and still
exercises the same argument parsing, subcommand dispatch, reporting and
exit-code paths.

What a real subprocess still buys, and which tests therefore keep using one:

* **Import isolation.** The ``--no-custom-rules`` tests prove that a rule
  file on disk does or does not get imported. In-process they would
  execute an arbitrary rule inside the test worker, and ``sys.modules``
  could mask a repeat import and make the negative case pass vacuously.
* **A real encoding on stdout.** The lone-surrogate regressions assert
  that rendering a report does not raise ``UnicodeEncodeError``. A
  ``StringIO`` never encodes, so in-process they would pass vacuously.
* **TTY and colour-cascade behaviour**, which depends on the real stream.

Those call ``subprocess.run`` directly and are deliberately left alone.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import traceback
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


@dataclass
class CliResult:
    """Stand-in for ``subprocess.CompletedProcess`` from an in-process run."""

    returncode: int
    stdout: str
    stderr: str


def _reset_process_globals() -> None:
    """Restore the state a freshly spawned CLI process would start with.

    Two globals outlive a single ``main()`` call and would otherwise leak
    between runs:

    * ``logging.basicConfig`` is a no-op once the root logger has handlers,
      so a second run would keep writing to the first run's captured
      stream and keep its verbosity.
    * The file-content cache in ``skillsaw.utils`` is process-global and is
      only invalidated inside the autofix loop, because every real run
      starts in a new process with it empty. Without this a lint that
      follows a fix would read the pre-fix text.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)

    from skillsaw.rules.builtin.utils import invalidate_read_caches

    invalidate_read_caches()


def run_cli(
    args: Sequence[object],
    *,
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[object] = None,
) -> CliResult:
    """Run ``skillsaw <args>`` in this process and capture its output.

    Args:
        args: CLI arguments after the program name, e.g. ``["lint", path]``.
            Every element is coerced with ``str`` so callers may pass
            ``Path`` objects, as they would to ``subprocess.run``.
        env: Replaces ``os.environ`` for the duration of the call, matching
            the ``env=`` argument of ``subprocess.run``.
        cwd: Directory to run from, restored afterwards.
    """
    from skillsaw.cli import main

    argv = ["skillsaw"] + [str(a) for a in args]
    out, err = io.StringIO(), io.StringIO()

    saved_argv, saved_out, saved_err = sys.argv, sys.stdout, sys.stderr
    saved_env = dict(os.environ) if env is not None else None
    saved_cwd = os.getcwd() if cwd is not None else None

    returncode = 0
    try:
        sys.argv, sys.stdout, sys.stderr = argv, out, err
        if env is not None:
            os.environ.clear()
            os.environ.update(env)
        if cwd is not None:
            os.chdir(str(cwd))
        _reset_process_globals()

        try:
            main()
        except SystemExit as exc:
            code = exc.code
            returncode = 0 if code is None else code if isinstance(code, int) else 1
        except Exception:
            # An uncaught exception in a real run prints a traceback to
            # stderr and exits 1. Tests assert on both, so reproduce that
            # rather than failing the test with the raw exception.
            # KeyboardInterrupt and other BaseExceptions deliberately
            # propagate, so Ctrl-C still stops the suite.
            traceback.print_exc(file=err)
            returncode = 1
    finally:
        sys.argv, sys.stdout, sys.stderr = saved_argv, saved_out, saved_err
        if saved_env is not None:
            os.environ.clear()
            os.environ.update(saved_env)
        if saved_cwd is not None:
            os.chdir(saved_cwd)

    return CliResult(returncode=returncode, stdout=out.getvalue(), stderr=err.getvalue())
