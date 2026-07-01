"""Shared CLI utilities used by multiple subcommand handlers."""

from __future__ import annotations

import os
import sys
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

    def __init__(self, root_path, repo_types, plugins, skills):
        self.root_path = root_path
        self.repo_types = repo_types
        self.plugins = plugins
        self.skills = skills

    @property
    def repo_type(self):
        for t in RepositoryContext._TYPE_PRIORITY:
            if t in self.repo_types:
                return t
        return RepositoryType.UNKNOWN


def _build_merged_context(contexts):
    """Build a merged context from multiple RepositoryContexts."""
    if len(contexts) == 1:
        return contexts[0]
    try:
        root_path = Path(os.path.commonpath([c.root_path for c in contexts]))
    except ValueError:
        root_path = contexts[0].root_path
    repo_types = set()
    plugins = []
    skills = []
    for ctx in contexts:
        repo_types |= ctx.repo_types
        plugins.extend(ctx.plugins)
        skills.extend(ctx.skills)
    return _MergedContext(root_path, repo_types, plugins, skills)


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


def _ansi_colors():
    no_color = "NO_COLOR" in os.environ
    return {
        "bold": "" if no_color else "\033[1m",
        "dim": "" if no_color else "\033[2m",
        "green": "" if no_color else "\033[92m",
        "red": "" if no_color else "\033[91m",
        "yellow": "" if no_color else "\033[93m",
        "cyan": "" if no_color else "\033[96m",
        "reset": "" if no_color else "\033[0m",
        "no_color": no_color,
    }
