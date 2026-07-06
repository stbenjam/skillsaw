"""
In-process unit tests for ``skillsaw.git_baseline`` and the ``--since``
branch of the lint CLI.

The subprocess integration tests in ``test_lint_since.py`` exercise the
same code end-to-end; these tests import and call it directly so the
behavior is also visible to coverage. They reuse the ``lint-since``
fixture and its git helpers: three legacy violations — two
``content-weak-language`` warnings in ``CLAUDE.md`` and one
``context-budget`` ratchet warning on ``.claude/rules/architecture.md``.
"""

import json
import subprocess

import pytest

from skillsaw.baseline import BaselineFile
from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
from skillsaw.git_baseline import (
    GitBaselineError,
    _snapshot_worktree,
    build_git_baseline,
    repo_toplevel,
    resolve_merge_base,
)
from skillsaw.linter import Linter
from skillsaw.rule import Severity

from .test_lint_since import (
    SECRET_LINE,
    append,
    commit_all,
    copy_fixture,
    git,
    git_repo,
    worktree_count,
)


def rev_parse(repo, ref):
    return git(repo, "rev-parse", ref).stdout.strip()


def fixture_config(repo):
    return LinterConfig.from_file(repo / ".skillsaw.yaml")


# ── repo_toplevel ────────────────────────────────────────────────


class TestRepoToplevel:
    def test_resolves_toplevel(self, tmp_path):
        repo = git_repo(tmp_path)
        assert repo_toplevel(repo) == repo.resolve()

    def test_resolves_toplevel_from_subdirectory(self, tmp_path):
        repo = git_repo(tmp_path)
        assert repo_toplevel(repo / ".claude" / "rules") == repo.resolve()

    def test_not_a_git_repo(self, tmp_path):
        plain = copy_fixture(tmp_path)
        with pytest.raises(GitBaselineError, match="requires a git repository"):
            repo_toplevel(plain)

    def test_git_not_on_path(self, tmp_path, monkeypatch):
        def raise_missing(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr("skillsaw.git_baseline.subprocess.run", raise_missing)
        with pytest.raises(GitBaselineError, match="was not found on PATH"):
            repo_toplevel(tmp_path)


# ── resolve_merge_base ───────────────────────────────────────────


class TestResolveMergeBase:
    def test_resolves_merge_base_of_two_commits(self, tmp_path):
        repo = git_repo(tmp_path)
        append(repo / "CLAUDE.md", "\nRun `make docs` to rebuild the API reference.\n")
        commit_all(repo, "Mention docs build")

        assert resolve_merge_base(repo, "HEAD~1") == rev_parse(repo, "HEAD~1")

    def test_unknown_ref(self, tmp_path):
        repo = git_repo(tmp_path)
        with pytest.raises(GitBaselineError, match="cannot resolve merge-base") as exc:
            resolve_merge_base(repo, "no-such-branch")
        assert "no-such-branch" in str(exc.value)

    def test_shallow_clone_mentions_fetching_history(self, tmp_path):
        origin = git_repo(tmp_path)
        append(origin / "CLAUDE.md", "\nRun `make docs` to rebuild the API reference.\n")
        commit_all(origin, "Mention docs build")

        clone = tmp_path / "shallow"
        git(tmp_path, "clone", "-q", "--depth", "1", f"file://{origin}", str(clone))

        with pytest.raises(GitBaselineError, match="shallow") as exc:
            resolve_merge_base(clone, "HEAD~1")
        assert "fetch" in str(exc.value)


# ── _snapshot_worktree ───────────────────────────────────────────


class TestSnapshotWorktree:
    def test_yields_checkout_of_requested_sha(self, tmp_path):
        repo = git_repo(tmp_path)
        base_sha = rev_parse(repo, "HEAD")
        append(repo / "CLAUDE.md", SECRET_LINE)
        commit_all(repo, "Add deploy token")

        with _snapshot_worktree(repo, base_sha) as snapshot:
            assert snapshot.is_dir()
            assert rev_parse(snapshot, "HEAD") == base_sha
            # The snapshot holds the base content, not the working tree's.
            assert "ghp_" not in (snapshot / "CLAUDE.md").read_text()

        assert not snapshot.exists()
        assert worktree_count(repo) == 1

    def test_removed_when_body_raises(self, tmp_path):
        repo = git_repo(tmp_path)
        sha = rev_parse(repo, "HEAD")

        with pytest.raises(RuntimeError, match="boom"):
            with _snapshot_worktree(repo, sha) as snapshot:
                assert snapshot.is_dir()
                raise RuntimeError("boom")

        assert not snapshot.exists()
        assert worktree_count(repo) == 1

    def test_invalid_sha_is_a_clear_error(self, tmp_path):
        repo = git_repo(tmp_path)

        with pytest.raises(GitBaselineError, match="failed to create a temporary worktree"):
            with _snapshot_worktree(repo, "0" * 40):
                pass  # pragma: no cover - the context manager raises first

        assert worktree_count(repo) == 1

    def test_remove_failure_falls_back_to_prune(self, tmp_path, monkeypatch):
        import skillsaw.git_baseline as git_baseline_module

        repo = git_repo(tmp_path)
        sha = rev_parse(repo, "HEAD")

        real_git = git_baseline_module._git

        def failing_remove(cwd, *argv):
            if argv[:2] == ("worktree", "remove"):
                return subprocess.CompletedProcess(argv, 1, "", "simulated remove failure")
            return real_git(cwd, *argv)

        monkeypatch.setattr(git_baseline_module, "_git", failing_remove)

        with _snapshot_worktree(repo, sha) as snapshot:
            assert snapshot.is_dir()

        # The fallback deletes the checkout and prunes the registration.
        assert not snapshot.exists()
        assert worktree_count(repo) == 1


# ── build_git_baseline ───────────────────────────────────────────


class TestBuildGitBaseline:
    def test_baselines_merge_base_violations(self, tmp_path):
        repo = git_repo(tmp_path)
        base_sha = rev_parse(repo, "HEAD")
        append(repo / "CLAUDE.md", "\nRun `make docs` to rebuild the API reference.\n")
        commit_all(repo, "Mention docs build")

        repo_root = repo.resolve()
        baseline, merge_base = build_git_baseline(
            repo_root, "HEAD~1", fixture_config(repo), [repo_root], "0.0.0-test"
        )

        assert merge_base == base_sha
        assert isinstance(baseline, BaselineFile)
        # root_path is repointed from the snapshot to the real toplevel so
        # current violations fingerprint to the same relative paths.
        assert baseline.root_path == repo_root

        by_rule = {}
        for entry in baseline.violations:
            by_rule.setdefault(entry.rule_id, []).append(entry)
        assert len(by_rule["content-weak-language"]) == 2
        assert len(by_rule["context-budget"]) == 1

        # Entry paths are repo-relative, never snapshot-absolute.
        assert {e.file_path for e in baseline.violations} == {
            "CLAUDE.md",
            ".claude/rules/architecture.md",
        }

        # INFO violations are excluded, mirroring `skillsaw baseline`.
        assert all(e.severity != "info" for e in baseline.violations)

        # The ratchet entry carries its value and baseline mode.
        ratchet = by_rule["context-budget"][0]
        assert ratchet.baseline_mode == "ceiling"
        assert ratchet.value is not None and ratchet.value > 40

        assert worktree_count(repo) == 1

    def test_baseline_suppresses_current_violations_via_linter(self, tmp_path):
        repo = git_repo(tmp_path)
        append(repo / "CLAUDE.md", SECRET_LINE)  # uncommitted new violation

        repo_root = repo.resolve()
        config = fixture_config(repo)
        baseline, _ = build_git_baseline(repo_root, "HEAD", config, [repo_root], "0.0.0-test")

        context = RepositoryContext(
            repo_root,
            exclude_patterns=config.exclude_patterns,
            content_paths=config.content_paths,
        )
        linter = Linter(context, config, baseline=baseline)
        kept = [v for v in linter.run() if v.severity != Severity.INFO]

        assert [v.rule_id for v in kept] == ["content-embedded-secrets"]
        assert linter.baseline_suppressed_count == 3
        assert linter.stale_baseline_entries == []

    def test_lint_path_missing_at_merge_base_contributes_nothing(self, tmp_path):
        repo = git_repo(tmp_path)
        nested = repo / "nested"
        nested.mkdir()
        (nested / "CLAUDE.md").write_text(
            "# Nested Tool Guidelines\n\n"
            "Run `make check` before committing changes to this tool.\n"
        )

        repo_root = repo.resolve()
        baseline, _ = build_git_baseline(
            repo_root, "HEAD", fixture_config(repo), [nested.resolve()], "0.0.0-test"
        )

        assert baseline.violations == []
        assert worktree_count(repo) == 1

    def test_lint_path_outside_repository_is_an_error(self, tmp_path):
        repo = git_repo(tmp_path)
        outside = tmp_path / "elsewhere"
        outside.mkdir()

        with pytest.raises(GitBaselineError, match="inside the git repository"):
            build_git_baseline(
                repo.resolve(), "HEAD", fixture_config(repo), [outside.resolve()], "0.0.0-test"
            )
        assert worktree_count(repo) == 1

    def test_bad_rule_selection_is_a_clear_error(self, tmp_path):
        repo = git_repo(tmp_path)
        repo_root = repo.resolve()

        with pytest.raises(GitBaselineError, match="failed to lint base snapshot"):
            build_git_baseline(
                repo_root,
                "HEAD",
                fixture_config(repo),
                [repo_root],
                "0.0.0-test",
                rule_ids={"does-not-exist"},
            )
        assert worktree_count(repo) == 1


# ── CLI --since branch (in-process) ──────────────────────────────


def run_lint_in_process(capsys, *argv):
    """Drive _run_lint directly through the real parser so coverage sees it."""
    from skillsaw.cli._lint import _run_lint
    from skillsaw.cli._parser import _build_parser

    args = _build_parser().parse_args(["lint", *argv])
    with pytest.raises(SystemExit) as exc:
        _run_lint(args)
    captured = capsys.readouterr()
    return exc.value.code or 0, captured.out, captured.err


class TestLintSinceCli:
    def test_since_with_no_baseline_conflict(self, tmp_path, capsys):
        repo = git_repo(tmp_path)

        rc, _, err = run_lint_in_process(capsys, "--since", "HEAD", "--no-baseline", str(repo))

        assert rc == 1
        assert "--since and --no-baseline cannot be combined" in err

    def test_rule_and_skip_rule_conflict(self, tmp_path, capsys):
        repo = git_repo(tmp_path)

        rc, _, err = run_lint_in_process(
            capsys, "--rule", "context-budget", "--skip-rule", "content-weak-language", str(repo)
        )

        assert rc == 1
        assert "--rule and --skip-rule cannot be combined" in err

    def test_since_git_error_exits_cleanly(self, tmp_path, capsys):
        plain = copy_fixture(tmp_path)

        rc, _, err = run_lint_in_process(capsys, "--since", "HEAD~1", str(plain))

        assert rc == 1
        assert "requires a git repository" in err

    def test_since_reports_only_new_violations(self, tmp_path, capsys):
        repo = git_repo(tmp_path)
        append(repo / "CLAUDE.md", SECRET_LINE)
        commit_all(repo, "Add deploy token")

        rc, out, _ = run_lint_in_process(capsys, "--format", "json", "--since", "HEAD~1", str(repo))

        assert rc == 1
        report = json.loads(out)
        assert [v["rule_id"] for v in report["violations"]] == ["content-embedded-secrets"]
        assert report["summary"]["baseline_suppressed"] == 3

    def test_since_text_output_header_and_fixed_hint(self, tmp_path, capsys):
        repo = git_repo(tmp_path)
        merge_base = rev_parse(repo, "HEAD")
        content = (repo / "CLAUDE.md").read_text()
        content = content.replace("- Try to keep functions under 50 lines.\n", "")
        (repo / "CLAUDE.md").write_text(content)
        commit_all(repo, "Drop the function-length guideline")

        rc, out, _ = run_lint_in_process(capsys, "--since", "HEAD~1", str(repo))

        assert rc == 0
        assert f"Comparing against merge-base {merge_base[:12]} (--since HEAD~1)" in out
        assert "1 violation(s) fixed since HEAD~1" in out
        assert "skillsaw baseline" not in out

    def test_since_verbose_lists_fixed_violations(self, tmp_path, capsys):
        repo = git_repo(tmp_path)
        content = (repo / "CLAUDE.md").read_text()
        content = content.replace("- Try to keep functions under 50 lines.\n", "")
        (repo / "CLAUDE.md").write_text(content)
        commit_all(repo, "Drop the function-length guideline")

        rc, out, _ = run_lint_in_process(capsys, "-v", "--since", "HEAD~1", str(repo))

        assert rc == 0
        assert "1 violation(s) fixed since HEAD~1" in out
        assert "- content-weak-language [CLAUDE.md]:" in out


class TestCommittedBaselineCli:
    """The committed-baseline branch that --since takes precedence over."""

    def _write_committed_baseline(self, repo, capsys):
        from skillsaw.cli._baseline import _run_baseline
        from skillsaw.cli._parser import _build_parser

        args = _build_parser().parse_args(["baseline", str(repo)])
        with pytest.raises(SystemExit) as exc:
            _run_baseline(args)
        assert (exc.value.code or 0) == 0
        capsys.readouterr()  # discard the "Baselined N violation(s)" line

    def test_committed_baseline_loaded_without_since(self, tmp_path, capsys):
        repo = git_repo(tmp_path)
        self._write_committed_baseline(repo, capsys)

        rc, out, _ = run_lint_in_process(capsys, "-v", str(repo))

        assert rc == 0
        assert "Using baseline:" in out
        assert "(3 entries)" in out

    def test_committed_baseline_stale_hint_suggests_refresh(self, tmp_path, capsys):
        repo = git_repo(tmp_path)
        self._write_committed_baseline(repo, capsys)
        content = (repo / "CLAUDE.md").read_text()
        content = content.replace("- Try to keep functions under 50 lines.\n", "")
        (repo / "CLAUDE.md").write_text(content)

        rc, out, _ = run_lint_in_process(capsys, str(repo))

        assert rc == 0
        assert "Baseline: 1 stale entry (violations resolved since baseline was set)" in out
        assert "Run `skillsaw baseline` to update." in out

    def test_corrupt_committed_baseline_warns_and_continues(self, tmp_path, capsys):
        repo = git_repo(tmp_path)
        (repo / ".skillsaw-baseline.json").write_text("{not json")

        rc, _, err = run_lint_in_process(capsys, str(repo))

        # The fixture only has warning-level violations, so the lint still
        # passes; the unreadable baseline is a warning, not a crash.
        assert rc == 0
        assert "Warning: Failed to load baseline:" in err
