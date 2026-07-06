"""Handler for the ``skillsaw hook`` subcommand.

Runs skillsaw as a Claude Code plugin hook. Reads the hook payload as JSON
on stdin and lints the file that was just edited, using the repository's own
configuration, then surfaces any violations back to the agent.

There is deliberately no allowlist of "files skillsaw lints" here: that set
lives in skillsaw's discovery (the lint tree) and would drift if duplicated.
Instead the hook lints the edited file's repository and reports only the
violations that land on that file — if skillsaw doesn't discover the file,
it produces no violations and the hook stays silent.

Fail-safe by design: malformed input, a missing file, a broken config, or
any internal error exits 0 silently, so the hook never disrupts an editing
session. Violations at (or above) the repository's configured ``fail-on``
severity are printed to stderr and the hook exits 2, which Claude Code
surfaces to the agent as feedback on the edit it just made.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_LEVEL_ORDER = {"info": 1, "warning": 2, "error": 3}


def _edited_file(payload: dict) -> Path | None:
    """Extract the edited file path from a hook payload.

    Keys off ``tool_input.file_path`` rather than an allowlist of tool names:
    the ``hooks.json`` matcher (``Edit|Write|MultiEdit|Update``) is the single
    gate on *which* tools fire the hook, so this stays agnostic and never
    drifts out of sync with it. Any editing tool Claude Code gains later works
    as soon as it's added to the matcher.
    """
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path or not isinstance(file_path, str):
        return None
    return Path(file_path)


def _lint_file(path: Path):
    """Lint *path*'s repository with its own config.

    Returns ``(violations, fail_level)`` where *violations* are only those
    that land on *path* itself — the file the agent just edited — even when
    the surrounding repository context surfaces more. skillsaw's discovery is
    the sole authority on whether *path* is lintable at all: a file it does
    not recognize simply yields no violations.
    """
    from ..baseline import find_baseline, load_baseline
    from ..config import LinterConfig, find_config
    from ..context import RepositoryContext
    from ..linter import Linter

    config_path = find_config(path.parent)
    try:
        config = LinterConfig.from_file(config_path) if config_path else LinterConfig.default()
    except ValueError:
        config = LinterConfig.default()

    baseline = None
    baseline_path = find_baseline(config.config_dir or path.parent)
    if baseline_path:
        try:
            baseline = load_baseline(baseline_path)
        except (ValueError, OSError):
            baseline = None

    context = RepositoryContext(
        path.parent,
        exclude_patterns=config.exclude_patterns,
        content_paths=config.content_paths,
    )
    linter = Linter(context, config, baseline=baseline)
    violations = linter.run()

    target = path.resolve()
    scoped = [v for v in violations if v.file_path is not None and v.file_path.resolve() == target]
    return scoped, config.effective_fail_level()


def _format_feedback(path: Path, surfaced) -> str:
    """Compact, agent-facing summary of the violations in the edited file."""
    count = len(surfaced)
    noun = "violation" if count == 1 else "violations"
    lines = [
        f"skillsaw found {count} {noun} in {path.name} (the file you just edited):",
        "",
    ]
    for v in surfaced:
        loc = f":{v.file_line}" if v.file_line else ""
        lines.append(f"  {v.severity.value}: {path.name}{loc}  {v.rule_id} — {v.message}")
    lines += [
        "",
        "Fix these before continuing. Run `skillsaw explain <rule>` for guidance "
        "on a rule, or `skillsaw fix` to apply automatic fixes.",
    ]
    return "\n".join(lines)


def _run_hook(args) -> None:
    # Only the PostToolUse event is wired up today; ignore anything else so
    # the same entry point can grow other events without breaking callers.
    if getattr(args, "event", "post-tool-use") != "post-tool-use":
        sys.exit(0)

    try:
        payload = json.loads(sys.stdin.read())
    except (ValueError, TypeError):
        sys.exit(0)
    if not isinstance(payload, dict):
        sys.exit(0)

    path = _edited_file(payload)
    if path is None:
        sys.exit(0)
    try:
        if not path.is_file():
            sys.exit(0)
    except OSError:
        sys.exit(0)

    try:
        violations, fail_level = _lint_file(path)
    except SystemExit:
        raise
    except Exception:
        # A linter bug must never break the user's editing session.
        sys.exit(0)

    threshold = _LEVEL_ORDER.get(fail_level, _LEVEL_ORDER["error"])
    surfaced = [v for v in violations if _LEVEL_ORDER[v.severity.value] >= threshold]
    if not surfaced:
        sys.exit(0)

    surfaced.sort(key=lambda v: (-_LEVEL_ORDER[v.severity.value], v.file_line or 0, v.rule_id))
    print(_format_feedback(path, surfaced), file=sys.stderr)
    sys.exit(2)
