"""
End-to-end tests for ``skillsaw lint --since REF``.

Each test copies the static ``lint-since`` fixture into a temp directory,
turns it into a real git repository (fixtures cannot contain ``.git``
directories, so history is created here), invokes ``python -m skillsaw
lint --since ...`` via subprocess, and asserts on exit codes and the
parsed JSON output.

The fixture carries three deliberate legacy violations:

- two ``content-weak-language`` warnings in ``CLAUDE.md`` (lines with
  "Try to" / "Be careful")
- one ``context-budget`` ratchet warning on
  ``.claude/rules/architecture.md`` (82 tokens against the 40-token
  ``rule`` budget configured in ``.skillsaw.yaml``)
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

SECRET_LINE = "\nUse the deploy token `ghp_abcdefghij0123456789abcdefghij012345` when pushing.\n"


# ── Helpers ──────────────────────────────────────────────────────


def git(cwd, *argv):
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.email=skillsaw-tests@example.com",
            "-c",
            "user.name=skillsaw tests",
            "-c",
            "commit.gpgsign=false",
            *argv,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"git {' '.join(argv)} failed: {result.stderr}"
    return result


def copy_fixture(tmp_path):
    dst = tmp_path / "repo"
    shutil.copytree(FIXTURES / "lint-since", dst)
    return dst


def commit_all(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def git_repo(tmp_path):
    """Copy the fixture and commit it as the initial state."""
    repo = copy_fixture(tmp_path)
    git(repo, "init", "-q")
    commit_all(repo, "Initial import")
    return repo


def run_lint(path, *extra_args, fmt="json", verbose=False):
    args = [sys.executable, "-m", "skillsaw", "lint"]
    if fmt:
        args.extend(["--format", fmt])
    if verbose:
        args.append("-v")
    args.append(str(path))
    args.extend(extra_args)
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    output = None
    if fmt == "json" and result.stdout.strip():
        output = json.loads(result.stdout)
    return {
        "rc": result.returncode,
        "out": output,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def violations(r):
    return r["out"]["violations"] if r["out"] else []


def rule_ids(r):
    return {v["rule_id"] for v in violations(r)}


def suppressed(r):
    return r["out"]["summary"]["baseline_suppressed"]


def worktree_count(repo):
    result = git(repo, "worktree", "list", "--porcelain")
    return result.stdout.count("worktree ")


def append(path, text):
    path.write_text(path.read_text() + text)


# ── Baseline subtraction ─────────────────────────────────────────


def test_clean_change_suppresses_all_legacy_violations(tmp_path):
    repo = git_repo(tmp_path)
    append(repo / "CLAUDE.md", "\n## Releases\n\nTag releases with `make release VERSION=x.y.z`.\n")
    commit_all(repo, "Document the release process")

    r = run_lint(repo, "--since", "HEAD~1", "--strict")

    assert r["rc"] == 0, r["stderr"]
    assert violations(r) == []
    assert suppressed(r) == 3


def test_new_error_is_the_only_violation_reported(tmp_path):
    repo = git_repo(tmp_path)
    append(repo / "CLAUDE.md", SECRET_LINE)
    commit_all(repo, "Add deploy instructions")

    r = run_lint(repo, "--since", "HEAD~1")

    assert r["rc"] == 1
    assert [v["rule_id"] for v in violations(r)] == ["content-embedded-secrets"]
    assert suppressed(r) == 3


def test_text_mode_prints_merge_base_header(tmp_path):
    repo = git_repo(tmp_path)
    merge_base = git(repo, "rev-parse", "HEAD").stdout.strip()
    append(repo / "CLAUDE.md", "\nRun `make docs` to rebuild the API reference.\n")
    commit_all(repo, "Mention docs build")

    r = run_lint(repo, "--since", "HEAD~1", fmt="text")

    assert r["rc"] == 0
    assert f"Comparing against merge-base {merge_base[:12]} (--since HEAD~1)" in r["stdout"]
    assert "3 suppressed" in r["stdout"]


def test_fixed_violations_reported_without_baseline_hint(tmp_path):
    repo = git_repo(tmp_path)
    content = (repo / "CLAUDE.md").read_text()
    content = content.replace("- Try to keep functions under 50 lines.\n", "")
    (repo / "CLAUDE.md").write_text(content)
    commit_all(repo, "Drop the function-length guideline")

    r = run_lint(repo, "--since", "HEAD~1", fmt="text")

    assert r["rc"] == 0
    assert "1 violation(s) fixed since HEAD~1" in r["stdout"]
    # The committed-baseline refresh hint makes no sense for --since.
    assert "skillsaw baseline" not in r["stdout"]


# ── Drift immunity ───────────────────────────────────────────────


def test_line_drift_keeps_legacy_violations_suppressed(tmp_path):
    repo = git_repo(tmp_path)
    content = (repo / "CLAUDE.md").read_text()
    header = (
        "# Pipeline Service Guidelines\n\n"
        "## Environment\n\n"
        "Local development requires Python 3.11 and Docker 24 or newer.\n"
        "Copy `.env.example` to `.env` before the first run.\n"
    )
    # Insert a new section right below the title so every legacy
    # violation moves to a different line number.
    (repo / "CLAUDE.md").write_text(content.replace("# Pipeline Service Guidelines\n", header, 1))
    commit_all(repo, "Document local environment setup")

    r = run_lint(repo, "--since", "HEAD~1", "--strict")

    assert r["rc"] == 0, r["stdout"]
    assert violations(r) == []
    assert suppressed(r) == 3


def test_type_override_applies_to_merge_base_lint(tmp_path):
    repo = git_repo(tmp_path)
    append(repo / "CLAUDE.md", "\nRun `make docs` to rebuild the API reference.\n")
    commit_all(repo, "Mention docs build")

    # --type single-plugin enables rules (plugin-json-required,
    # plugin-readme) that dot-claude auto-detection would not. The
    # override must apply to the merge-base snapshot too, or those rules
    # would fire only on the current tree and report spurious "new"
    # violations for an unchanged repo.
    r = run_lint(repo, "--since", "HEAD~1", "--type", "single-plugin", "--strict")

    assert r["rc"] == 0, r["stdout"]
    assert violations(r) == []
    assert suppressed(r) > 0


# ── Ratchet composition ──────────────────────────────────────────


def test_ratchet_refires_when_tracked_value_grows(tmp_path):
    repo = git_repo(tmp_path)
    append(
        repo / ".claude/rules/architecture.md",
        "\nBackground jobs run through Celery workers defined in `jobs/`.\n"
        "Every job must be idempotent — retries are automatic on failure.\n",
    )
    commit_all(repo, "Document background jobs")

    r = run_lint(repo, "--since", "HEAD~1", "--strict")

    assert r["rc"] == 1
    assert [v["rule_id"] for v in violations(r)] == ["context-budget"]
    assert "exceeds rule warn limit" in violations(r)[0]["message"]
    # The two weak-language violations stay suppressed.
    assert suppressed(r) == 2


def test_ratchet_improvement_stays_suppressed(tmp_path):
    repo = git_repo(tmp_path)
    content = (repo / ".claude/rules/architecture.md").read_text()
    content = content.replace(
        "Name migration files with a numeric prefix: `0042_add_index.py`.\n", ""
    )
    (repo / ".claude/rules/architecture.md").write_text(content)
    commit_all(repo, "Trim the migration naming rule")

    r = run_lint(repo, "--since", "HEAD~1", "--strict")

    # Still over the 40-token budget, but better than the merge-base
    # value — the ratchet suppresses it.
    assert r["rc"] == 0, r["stdout"]
    assert violations(r) == []
    assert suppressed(r) == 3


# ── Flag validation and error paths ──────────────────────────────


def test_since_with_no_baseline_is_an_error(tmp_path):
    repo = git_repo(tmp_path)

    r = run_lint(repo, "--since", "HEAD~1", "--no-baseline")

    assert r["rc"] == 1
    assert "--since and --no-baseline cannot be combined" in r["stderr"]


def test_non_git_directory_is_a_clear_error(tmp_path):
    repo = copy_fixture(tmp_path)

    r = run_lint(repo, "--since", "HEAD~1")

    assert r["rc"] == 1
    assert "--since requires a git repository" in r["stderr"]
    assert "Traceback" not in r["stderr"]


def test_unknown_ref_is_a_clear_error(tmp_path):
    repo = git_repo(tmp_path)

    r = run_lint(repo, "--since", "no-such-branch")

    assert r["rc"] == 1
    assert "cannot resolve merge-base" in r["stderr"]
    assert "no-such-branch" in r["stderr"]
    assert "Traceback" not in r["stderr"]


def test_ref_starting_with_dash_is_rejected(tmp_path):
    repo = git_repo(tmp_path)

    # A ref like "-foo" must not reach git, where it would parse as a flag.
    r = run_lint(repo, "--since=-foo")

    assert r["rc"] == 1
    assert "invalid ref" in r["stderr"]
    assert "Traceback" not in r["stderr"]


def test_shallow_clone_error_suggests_fetching_history(tmp_path):
    origin = git_repo(tmp_path)
    append(origin / "CLAUDE.md", "\nRun `make docs` to rebuild the API reference.\n")
    commit_all(origin, "Mention docs build")

    clone = tmp_path / "shallow"
    # as_uri() builds a portable file:// URL (a plain local path would make
    # git silently ignore --depth and produce a full, non-shallow clone).
    git(tmp_path, "clone", "-q", "--depth", "1", origin.as_uri(), str(clone))

    r = run_lint(clone, "--since", "HEAD~1")

    assert r["rc"] == 1
    assert "cannot resolve merge-base" in r["stderr"]
    assert "shallow" in r["stderr"]
    assert "fetch" in r["stderr"]
    assert "Traceback" not in r["stderr"]


# ── Precedence over a committed baseline ─────────────────────────


def test_since_takes_precedence_over_committed_baseline(tmp_path):
    repo = git_repo(tmp_path)
    append(repo / "CLAUDE.md", SECRET_LINE)
    # Baseline the secret into a committed .skillsaw-baseline.json.
    result = subprocess.run(
        [sys.executable, "-m", "skillsaw", "baseline", str(repo)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    commit_all(repo, "Add deploy token and baseline it")

    # The committed baseline suppresses the secret...
    r = run_lint(repo)
    assert r["rc"] == 0
    assert violations(r) == []

    # ...but --since compares against the merge-base instead, where the
    # secret did not exist yet.
    r = run_lint(repo, "--since", "HEAD~1")
    assert r["rc"] == 1
    assert rule_ids(r) == {"content-embedded-secrets"}


# ── Worktree hygiene ─────────────────────────────────────────────


def test_worktree_removed_after_successful_run(tmp_path):
    repo = git_repo(tmp_path)
    append(repo / "CLAUDE.md", "\nRun `make docs` to rebuild the API reference.\n")
    commit_all(repo, "Mention docs build")

    r = run_lint(repo, "--since", "HEAD~1")

    assert r["rc"] == 0
    assert worktree_count(repo) == 1  # only the main worktree


def test_worktree_removed_after_failing_run(tmp_path):
    repo = git_repo(tmp_path)
    append(repo / "CLAUDE.md", "\nRun `make docs` to rebuild the API reference.\n")
    commit_all(repo, "Mention docs build")

    # The unknown rule id makes Linter construction fail while the
    # snapshot worktree exists — cleanup must still run.
    r = run_lint(repo, "--since", "HEAD~1", "--rule", "does-not-exist")

    assert r["rc"] == 1
    assert "does-not-exist" in r["stderr"]
    assert worktree_count(repo) == 1


# ── Working tree states ──────────────────────────────────────────


def test_uncommitted_new_violation_is_caught(tmp_path):
    repo = git_repo(tmp_path)
    append(repo / "CLAUDE.md", "\nRun `make docs` to rebuild the API reference.\n")
    commit_all(repo, "Mention docs build")
    # Dirty working tree: the secret is not committed anywhere.
    append(repo / "CLAUDE.md", SECRET_LINE)

    r = run_lint(repo, "--since", "HEAD~1")

    assert r["rc"] == 1
    assert rule_ids(r) == {"content-embedded-secrets"}


def test_lint_path_missing_at_merge_base_contributes_no_baseline(tmp_path):
    repo = git_repo(tmp_path)
    nested = repo / "nested"
    nested.mkdir()
    (nested / "CLAUDE.md").write_text(
        "# Nested Tool Guidelines\n\n"
        "Run `make check` before committing changes to this tool.\n" + SECRET_LINE
    )
    commit_all(repo, "Add nested tool")

    # nested/ does not exist at the merge-base: the base contributes no
    # violations for it, so everything in it is new.
    r = run_lint(nested, "--since", "HEAD~1")

    assert r["rc"] == 1
    assert "content-embedded-secrets" in rule_ids(r)
    assert suppressed(r) == 0
    assert worktree_count(repo) == 1
