"""
Ephemeral git baseline for ``skillsaw lint --since REF``.

``--since`` reports only the violations introduced since a git ref: it
checks out the merge-base of HEAD and REF into a temporary git worktree,
lints that snapshot with the same configuration, builds an in-memory
:class:`~skillsaw.baseline.BaselineFile` from the result, and hands it to
the normal baseline subtraction.  No committed ``.skillsaw-baseline.json``
is involved.

Mechanics worth knowing:

- Baseline fingerprints hash rule ID + relative file path + stripped
  source-line content (never line numbers — see
  :func:`skillsaw.baseline.fingerprint_violation`), so pre-existing
  violations stay suppressed even when the change shifts every line
  around them.
- Entries are fingerprinted against the *snapshot* toplevel, then the
  returned baseline's ``root_path`` is pointed at the real repository
  toplevel.  Current violations relativize to identical paths, so the
  existing subtraction in :class:`skillsaw.linter.Linter` — and everything
  downstream (suppressed counts, stale entries, formatters, exit codes) —
  works unchanged.
- The configuration is deliberately pinned from the CURRENT working
  tree, not the snapshot: ``--since`` measures how the repository
  changed, not how the rule configuration changed.  Custom rule paths
  therefore also resolve against the current tree.
- Mirroring ``skillsaw baseline`` semantics, INFO-severity violations are
  excluded from the ephemeral baseline and ratchet rules contribute
  their ``baseline_mode`` so value regressions (e.g. a SKILL.md growing
  past its old token count) re-fire with the delta.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

from .baseline import BaselineFile, build_baseline
from .config import LinterConfig
from .context import RepositoryContext
from .linter import Linter
from .rule import RuleViolation, Severity

logger = logging.getLogger(__name__)


class GitBaselineError(Exception):
    """Raised when the ephemeral ``--since`` baseline cannot be built."""


def _git(cwd: Path, *argv: str) -> subprocess.CompletedProcess:
    """Run a git command, capturing output. Raises GitBaselineError if git is missing."""
    try:
        return subprocess.run(
            ["git", *argv],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitBaselineError(
            "--since requires git, but the `git` executable was not found on PATH"
        ) from exc


def repo_toplevel(path: Path) -> Path:
    """Resolve the git working-tree toplevel containing *path*."""
    result = _git(path, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise GitBaselineError(
            f"--since requires a git repository, but {path} is not inside one "
            f"({result.stderr.strip() or 'git rev-parse failed'})"
        )
    return Path(result.stdout.strip()).resolve()


def _is_shallow(repo_root: Path) -> bool:
    result = _git(repo_root, "rev-parse", "--is-shallow-repository")
    return result.returncode == 0 and result.stdout.strip() == "true"


def resolve_merge_base(repo_root: Path, ref: str) -> str:
    """Resolve the merge-base of HEAD and *ref*, with a precise error on failure."""
    result = _git(repo_root, "merge-base", "HEAD", ref)
    if result.returncode == 0:
        return result.stdout.strip()

    detail = result.stderr.strip() or f"no merge-base found between HEAD and '{ref}'"
    message = f"--since {ref}: cannot resolve merge-base: {detail}"
    if _is_shallow(repo_root):
        message += (
            " (this is a shallow clone — fetch more history first, e.g."
            " `git fetch --unshallow` or use `fetch-depth: 0` with"
            " actions/checkout)"
        )
    raise GitBaselineError(message)


@contextmanager
def _snapshot_worktree(repo_root: Path, sha: str) -> Iterator[Path]:
    """Check *sha* out into a temporary detached git worktree.

    The worktree (and its temp directory) is always removed on exit, even
    when the body raises — a leftover registration would break later
    ``git worktree`` operations in the user's repository.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="skillsaw-since-"))
    snapshot = tmpdir / "snapshot"
    result = _git(repo_root, "worktree", "add", "--detach", str(snapshot), sha)
    if result.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise GitBaselineError(
            f"--since: failed to create a temporary worktree for {sha[:12]}: "
            f"{result.stderr.strip()}"
        )
    try:
        yield snapshot.resolve()
    finally:
        remove = _git(repo_root, "worktree", "remove", "--force", str(snapshot))
        if remove.returncode != 0:
            # Fall back to deleting the checkout and pruning the stale
            # registration so nothing lingers in .git/worktrees.
            shutil.rmtree(snapshot, ignore_errors=True)
            _git(repo_root, "worktree", "prune")
        shutil.rmtree(tmpdir, ignore_errors=True)


def build_git_baseline(
    repo_root: Path,
    ref: str,
    config: LinterConfig,
    lint_paths: Sequence[Path],
    version_string: str,
    *,
    rule_ids: Optional[Set[str]] = None,
    skip_rule_ids: Optional[Set[str]] = None,
    no_custom_rules: bool = False,
    no_plugins: bool = False,
) -> Tuple[BaselineFile, str]:
    """Lint the merge-base of HEAD and *ref*; return it as an in-memory baseline.

    Each lint path is mapped to its location inside the snapshot worktree
    (paths that do not exist at the merge-base simply contribute no
    baseline entries).  The snapshot is linted with the caller's *config*
    (from the current working tree) and rule selection flags, INFO
    violations are dropped, and ratchet ``baseline_mode``\\ s are captured —
    all mirroring ``skillsaw baseline`` semantics.

    Returns ``(baseline, merge_base_sha)`` where ``baseline.root_path`` is
    already pointed at *repo_root* so current violations fingerprint to
    the same relative paths as the snapshot entries.
    """
    merge_base = resolve_merge_base(repo_root, ref)

    violations: List[RuleViolation] = []
    baseline_modes: Dict[str, str] = {}

    with _snapshot_worktree(repo_root, merge_base) as snapshot_root:
        for lint_path in lint_paths:
            try:
                rel = lint_path.resolve().relative_to(repo_root)
            except ValueError:
                raise GitBaselineError(
                    f"--since requires every lint path to be inside the git "
                    f"repository at {repo_root}, but {lint_path} is not"
                ) from None

            mapped = snapshot_root / rel
            if not mapped.exists():
                # The path was added after the merge-base: the base
                # contributes no violations for it.
                logger.info(
                    "--since: %s does not exist at merge-base %s; " "no baseline entries for it",
                    rel,
                    merge_base[:12],
                )
                continue

            context = RepositoryContext(
                mapped,
                exclude_patterns=config.exclude_patterns,
                content_paths=config.content_paths,
            )
            try:
                linter = Linter(
                    context,
                    config,
                    rule_ids=rule_ids,
                    skip_rule_ids=skip_rule_ids,
                    no_custom_rules=no_custom_rules,
                    no_plugins=no_plugins,
                )
            except ValueError as e:
                raise GitBaselineError(f"--since: failed to lint base snapshot: {e}") from e

            violations.extend(v for v in linter.run() if v.severity != Severity.INFO)
            for rule in linter.rules:
                if rule.baseline_mode:
                    baseline_modes.setdefault(rule.rule_id, rule.baseline_mode)

        logger.info(
            "--since: baselined %d violation(s) from merge-base %s",
            len(violations),
            merge_base[:12],
        )
        # Fingerprints read source lines from disk, so the baseline must be
        # built while the snapshot worktree still exists.
        baseline = build_baseline(violations, snapshot_root, version_string, baseline_modes)

    # THE key trick: entries were fingerprinted with snapshot-relative
    # paths; pointing root_path at the real repo toplevel makes current
    # violations fingerprint to identical relative paths, so the existing
    # baseline subtraction just works.
    baseline.root_path = repo_root
    return baseline, merge_base
