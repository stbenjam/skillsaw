"""Shared CLI utilities used by multiple subcommand handlers."""

from __future__ import annotations

import logging
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


# ---------------------------------------------------------------------------
# LLM patch utilities
# ---------------------------------------------------------------------------


_DEFAULT_PATCH_NAME = ".skillsaw-llm-patch.diff"


def _resolve_patch_path(args, root_path: Path) -> Path:
    if getattr(args, "patch_file", None):
        return args.patch_file.resolve()
    return root_path.resolve() / _DEFAULT_PATCH_NAME


def _save_llm_patch(diffs, patch_path: Path) -> None:
    combined = ""
    for diff_text in diffs.values():
        combined += diff_text
        if not combined.endswith("\n"):
            combined += "\n"
    patch_path.write_text(combined, encoding="utf-8")


def _apply_llm_patch(patch_path: Path, root_path: Path) -> None:
    import subprocess

    c = _ansi_colors()
    if not patch_path.exists():
        print(f"Error: Patch file not found: {patch_path}", file=sys.stderr)
        sys.exit(1)

    patch_content = patch_path.read_text(encoding="utf-8")
    if not patch_content.strip():
        print(f"Error: Patch file is empty: {patch_path}", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        ["git", "apply", "--check", str(patch_path)],
        cwd=str(root_path),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"Error: Patch does not apply cleanly:\n{result.stderr}",
            file=sys.stderr,
        )
        sys.exit(1)

    result = subprocess.run(
        ["git", "apply", str(patch_path)],
        cwd=str(root_path),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: Failed to apply patch:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"{c['green']}Patch applied successfully from {patch_path}{c['reset']}")
    patch_path.unlink()
    print(f"{c['dim']}Patch file removed.{c['reset']}")


# ---------------------------------------------------------------------------
# LLM provider helpers
# ---------------------------------------------------------------------------


def _require_llm_provider(config):
    if not config.llm.model:
        print(
            "Error: No model configured. Set llm.model in your config file,"
            " pass --model, or set SKILLSAW_MODEL.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from ..llm._litellm import LiteLLMProvider
    except ImportError:
        print(
            "Error: LLM features require litellm. Install with: pip install skillsaw[llm]",
            file=sys.stderr,
        )
        sys.exit(1)

    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s", stream=sys.stderr)
    return LiteLLMProvider()


# ---------------------------------------------------------------------------
# Diff / token display
# ---------------------------------------------------------------------------


def _print_colored_diff(diffs, c, header=None, separator=False):
    if not diffs:
        return
    if header:
        print(f"\n{c['bold']}{header}{c['reset']}")
    if separator:
        print(f"{c['dim']}{'─' * 60}{c['reset']}")
    for diff_text in diffs.values():
        for line in diff_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                print(f"{c['green']}{line}{c['reset']}")
            elif line.startswith("-") and not line.startswith("---"):
                print(f"{c['red']}{line}{c['reset']}")
            elif line.startswith("@@"):
                print(f"{c['cyan']}{line}{c['reset']}")
            else:
                print(line)
    if separator:
        print(f"{c['dim']}{'─' * 60}{c['reset']}")


def _print_token_usage(usage, c, indent=""):
    total_tokens = usage.prompt_tokens + usage.completion_tokens
    if total_tokens:
        print(f"{indent}{c['dim']}~{total_tokens:,} tokens{c['reset']}")
