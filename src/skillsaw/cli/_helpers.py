"""Shared CLI utilities used by multiple subcommand handlers."""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

from ..context import RepositoryContext, RepositoryType

# ---------------------------------------------------------------------------
# Progress indicator
# ---------------------------------------------------------------------------


class _RuleProgress:
    """Single-line per-rule progress on stderr for interactive runs.

    Inactive unless stderr is a terminal, so JSON/SARIF stdout, shell
    pipelines, and CI logs are never polluted.  Verbose mode also disables
    it — info-level log lines share stderr and would interleave.
    """

    def __init__(self, args) -> None:
        self.enabled = (
            sys.stderr.isatty()
            and not getattr(args, "no_progress", False)
            and not getattr(args, "verbose", False)
        )

    def __call__(self, index: int, total: int, rule_id: str) -> None:
        if self.enabled:
            sys.stderr.write(f"\r\x1b[K  linting [{index}/{total}] {rule_id}")
            sys.stderr.flush()

    def clear(self) -> None:
        """Erase the progress line before real output is printed."""
        if self.enabled:
            sys.stderr.write("\r\x1b[K")
            sys.stderr.flush()


# ---------------------------------------------------------------------------
# Path resolution and context merging
# ---------------------------------------------------------------------------


def _resolve_lint_paths(paths):
    """Normalize CLI paths into a unique list of directories to lint.

    Files resolve to their parent directory, then exact duplicates and
    paths nested inside another entry are dropped (a parent's
    RepositoryContext already discovers everything beneath it).
    First-seen order is preserved.
    """
    normalized = []
    for p in paths:
        resolved = p.resolve()
        if resolved.is_file():
            resolved = resolved.parent
        normalized.append(resolved)

    seen = set()
    result = []
    for p in normalized:
        if p in seen:
            continue
        if any(p != other and _is_subpath(p, other) for other in normalized):
            continue
        seen.add(p)
        result.append(p)
    return result


def _is_subpath(child, parent):
    """Check if child is a strict subpath of parent."""
    try:
        child.relative_to(parent)
        return child != parent
    except ValueError:
        return False


class _MergedContext:
    """Duck-typed context for formatters when linting multiple paths."""

    def __init__(self, root_path, repo_types, plugins, skills, plugin_repo_types=frozenset()):
        self.root_path = root_path
        self.repo_types = repo_types
        self.plugins = plugins
        self.skills = skills
        self.plugin_repo_types = set(plugin_repo_types)

    @property
    def repo_type(self):
        for t in RepositoryContext._TYPE_PRIORITY:
            if t in self.repo_types:
                return t
        return RepositoryType.UNKNOWN

    def repo_type_names(self, include_unknown: bool = True):
        """Sorted names of all detected repository types, builtin and plugin."""
        names = {t.value for t in self.repo_types}
        names.update(self.plugin_repo_types)
        if not include_unknown or len(names) > 1:
            names.discard(RepositoryType.UNKNOWN.value)
        return sorted(names)


def _build_merged_context(contexts):
    """Build a merged context from multiple RepositoryContexts."""
    if len(contexts) == 1:
        return contexts[0]
    try:
        root_path = Path(os.path.commonpath([c.root_path for c in contexts]))
    except ValueError:
        root_path = contexts[0].root_path
    repo_types = set()
    plugin_repo_types = set()
    plugins = []
    skills = []
    for ctx in contexts:
        repo_types |= ctx.repo_types
        plugin_repo_types |= ctx.plugin_repo_types
        plugins.extend(ctx.plugins)
        skills.extend(ctx.skills)
    return _MergedContext(root_path, repo_types, plugins, skills, plugin_repo_types)


def _dedup_rules(rules):
    """Deduplicate rules by rule_id, preserving first occurrence."""
    seen = set()
    result = []
    for rule in rules:
        if rule.rule_id not in seen:
            seen.add(rule.rule_id)
            result.append(rule)
    return result


# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------


def color_enabled(stream, color: bool | None = None) -> bool:
    """Whether ANSI color should be emitted on ``stream``.

    Standard cascade, strongest first:

    1. ``--color`` / ``--no-color`` (the ``color`` argument: ``True`` forces
       on, ``False`` forces off, ``None`` auto-detects)
    2. ``FORCE_COLOR`` — non-empty forces color on (``0`` forces it off)
    3. ``NO_COLOR`` — present (even empty) disables color
    4. ``TERM=dumb`` — disables color (the terminal renders escape codes
       as literal ``^[[91m`` garbage; git, gcc, and CPython all honor it)
    5. ``stream.isatty()``

    ``FORCE_COLOR`` outranks ``NO_COLOR`` so CI setups that export both
    get the color they explicitly asked for. ``TERM=dumb`` sits in the
    terminal-heuristic tier: an explicit ``--color`` or ``FORCE_COLOR``
    still wins.
    """
    if color is not None:
        return color
    force = os.environ.get("FORCE_COLOR")
    if force:
        return force != "0"
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def hyperlinks_enabled(stream, color: bool) -> bool:
    """Whether OSC 8 terminal hyperlinks should be emitted on ``stream``.

    Requires color, a real terminal, and ``TERM`` other than ``dumb``.
    Unlike color, hyperlinks are never forced through a pipe — CI log
    viewers render SGR colors but display raw OSC 8 bytes as garbage.
    """
    if not color or os.environ.get("TERM") == "dumb":
        return False
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def _ansi_colors(enabled: bool):
    return {
        "bold": "\033[1m" if enabled else "",
        "dim": "\033[2m" if enabled else "",
        "green": "\033[92m" if enabled else "",
        "red": "\033[91m" if enabled else "",
        "yellow": "\033[93m" if enabled else "",
        "cyan": "\033[96m" if enabled else "",
        "reset": "\033[0m" if enabled else "",
    }


# ---------------------------------------------------------------------------
# Warning display
# ---------------------------------------------------------------------------


def install_warning_display() -> None:
    """Render skillsaw's own warnings as one readable line on stderr.

    The stock ``warnings`` formatter prints the emitting source location and
    code line (``linter.py:95: UserWarning: ...``), which reads like a crash.
    Skillsaw warning categories get a compact colored line instead; every
    other warning keeps the default rendering.
    """
    from ..linter import CustomRuleWarning

    default_showwarning = warnings.showwarning

    def _showwarning(message, category, filename, lineno, file=None, line=None):
        if isinstance(message, CustomRuleWarning):
            out = sys.stderr if file is None else file
            c = _ansi_colors(color_enabled(out))
            print(
                f"{c['yellow']}⚠ Loading custom rule file:{c['reset']} "
                f"{c['bold']}{message.path}{c['reset']} "
                f"{c['dim']}(use --no-custom-rules to skip){c['reset']}",
                file=out,
            )
        else:
            default_showwarning(message, category, filename, lineno, file, line)

    warnings.showwarning = _showwarning
