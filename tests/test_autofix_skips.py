"""Policy skips preserve diagnostics, previews and independent eligible fixes."""

import json
import os
import shutil
from pathlib import Path

import pytest

from skillsaw.baseline import build_baseline
from skillsaw.context import RepositoryContext
from skillsaw.linter import Linter
from skillsaw.rule import AutofixConfidence, AutofixResult, Rule, Severity
from tests.cli_runner import run_cli

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Requires ordinary POSIX symlinks")
FIXTURES = Path(__file__).parent / "fixtures"
RULE = "content-unlinked-internal-reference"


def _copy_repo(tmp_path, name="repo", *, linked=True):
    repo = tmp_path / name
    shutil.copytree(FIXTURES / "autofix/unlinked-ref-multiple-paths", repo)
    if linked:
        (repo / "CLAUDE.md").rename(repo / "instructions.txt")
        (repo / "CLAUDE.md").symlink_to("instructions.txt")
    return repo


def _cli(command, *args):
    return run_cli([command, *args, "--no-custom-rules", "--no-plugins"])


def _linter(repo, **kwargs):
    return Linter(
        RepositoryContext(repo), rule_ids={RULE}, no_custom_rules=True, no_plugins=True, **kwargs
    )


@pytest.mark.integration
@pytest.mark.parametrize("linked", [False, True], ids=["regular", "symlink"])
def test_symlink_metadata_preview_and_fix_agree(tmp_path, linked):
    repo = _copy_repo(tmp_path, linked=linked)
    path = repo / "CLAUDE.md"
    original = path.read_bytes()
    report = _cli("lint", repo, "--rule", RULE, "--format", "json", "--verbose")
    assert report.returncode == 0, report.stderr
    findings = json.loads(report.stdout)["violations"]
    assert len(findings) == 3
    assert {v["file_path"] for v in findings} == {"CLAUDE.md"}
    assert all(v["fixable"] is (not linked) for v in findings)
    assert all(v.get("fix_confidence") == (None if linked else "safe") for v in findings)

    preview = _cli("fix", repo, "--rule", RULE, "--dry-run")
    assert preview.returncode == 0, preview.stderr
    assert path.read_bytes() == original
    assert "dry-run — no files were modified" in preview.stdout
    result = _cli("fix", repo, "--rule", RULE)
    assert result.returncode == 0, result.stderr
    if linked:
        for output in (preview.stdout, result.stdout):
            assert "Skipped 1 path(s):" in output
            assert "[CLAUDE.md] symbolic link" in output
            assert "Would fix" not in output and "Fixed " not in output
            assert "No auto-fixable" not in output
            assert "--- a/" not in output
        assert path.is_symlink()
        assert path.read_bytes() == original
    else:
        assert "Would fix 1 issue(s)" in preview.stdout
        assert "Fixed 1 issue(s)" in result.stdout
        assert "Skipped" not in result.stdout
        assert path.read_bytes() != original
        assert path.read_bytes().count(b"\n") == original.count(b"\n")
        assert b"[docs/guide.md](docs/guide.md)" in path.read_bytes()
        clean = _cli("lint", repo, "--rule", RULE, "--format", "json", "--verbose")
        assert clean.returncode == 0, clean.stderr
        assert json.loads(clean.stdout)["violations"] == []
    after = path.read_bytes()
    repeated = _cli("fix", repo, "--rule", RULE)
    assert repeated.returncode == 0, repeated.stderr
    assert path.read_bytes() == after


def test_proposal_generation_does_not_leak_symlink_fixability(tmp_path):
    repo = _copy_repo(tmp_path)
    remaining, proposals = _linter(repo).fix()
    assert len(proposals) == 1
    assert len(proposals[0].violations_fixed) == 3
    assert proposals[0].confidence == AutofixConfidence.SAFE
    assert all(
        not v.fixable and v.fix_confidence is None
        for v in [*remaining, *proposals[0].violations_fixed]
    )
    remaining, proposals = _linter(repo).fix(severity_threshold="error")
    assert len(remaining) == 3 and proposals == []
    assert all(not v.fixable and v.fix_confidence is None for v in remaining)


@pytest.mark.integration
def test_hidden_and_suppressed_findings_do_not_become_skips(tmp_path):
    repo = _copy_repo(tmp_path)
    (repo / ".skillsaw.yaml").write_text(f"rules:\n  {RULE}:\n    severity: info\n")
    hidden = _cli("fix", repo)
    assert hidden.returncode == 0, hidden.stderr
    assert "Skipped" not in hidden.stdout
    visible = _cli("fix", repo, "--rule", RULE)
    assert visible.returncode == 0, visible.stderr
    assert "Skipped 1 path(s):" in visible.stdout

    target = repo / "instructions.txt"
    target.write_text(f"<!-- skillsaw-disable {RULE} -->\n" + target.read_text())
    suppressed = _cli("fix", repo, "--rule", RULE)
    assert suppressed.returncode == 0, suppressed.stderr
    assert "Skipped" not in suppressed.stdout


def test_baselined_findings_do_not_become_skips(tmp_path):
    repo = _copy_repo(tmp_path)
    linter = _linter(repo)
    visible = linter.run()
    assert len(visible) == 3
    baseline = build_baseline(visible, repo, "test")
    baselined = _linter(repo, baseline=baseline)
    assert baselined.fix_and_apply() == ([], [])
    assert baselined.fix_skips == []
    assert baselined.baseline_suppressed_count == 3


class _AliasRule(Rule):
    """Legacy rule: confidence is on results, not violation metadata."""

    rule_id = "test-alias-proposals"
    description = "Independent proposals for two names of one file"
    result_confidence = AutofixConfidence.SAFE

    def default_severity(self):
        return Severity.WARNING

    def check(self, context):
        return [
            self.violation("Update note", file_path=context.root_path / name)
            for name in ("alias.txt", "notes.txt")
        ]

    def fix(self, context, violations):
        return [
            AutofixResult(
                rule_id=self.rule_id,
                file_path=v.file_path,
                confidence=self.result_confidence,
                original_content=v.file_path.read_text(),
                fixed_content="Updated note.\n",
                description="Update note",
                violations_fixed=[v],
            )
            for v in violations
        ]


def _alias_linter(tmp_path):
    (tmp_path / "notes.txt").write_text("Original note.\n")
    (tmp_path / "alias.txt").symlink_to("notes.txt")
    linter = Linter(RepositoryContext(tmp_path), no_custom_rules=True, no_plugins=True)
    linter.rules = [_AliasRule()]
    return linter


def test_filter_reuses_symlink_status_only_within_one_call(tmp_path, monkeypatch):
    import skillsaw.linter as module

    linter = _alias_linter(tmp_path)
    calls = []
    original = module.safe_is_symlink

    def record(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(module, "safe_is_symlink", record)

    def findings():
        return [
            linter.rules[0].violation(
                "Update note",
                file_path=tmp_path / name,
                fixable=True,
                fix_confidence=AutofixConfidence.SAFE,
            )
            for name in ("alias.txt", "alias.txt", "notes.txt", "notes.txt")
        ]

    filtered = linter._filter_violations(findings())
    assert calls == [tmp_path / "alias.txt", tmp_path / "notes.txt"]
    assert [v.fixable for v in filtered] == [False, False, True, True]
    assert [v.fix_confidence for v in filtered] == [
        None,
        None,
        AutofixConfidence.SAFE,
        AutofixConfidence.SAFE,
    ]

    (tmp_path / "alias.txt").unlink()
    (tmp_path / "alias.txt").write_text("Independent note.\n")
    calls.clear()
    filtered = linter._filter_violations(findings())
    assert calls == [tmp_path / "alias.txt", tmp_path / "notes.txt"]
    assert all(v.fixable and v.fix_confidence == AutofixConfidence.SAFE for v in filtered)


def test_skipped_alias_does_not_reserve_eligible_target(tmp_path):
    linter = _alias_linter(tmp_path)
    applied, suggested = linter.fix_and_apply()
    assert [fix.file_path for fix in applied] == [tmp_path / "notes.txt"]
    assert suggested == []
    assert [path for path, _ in linter.fix_skips] == [tmp_path / "alias.txt"]
    assert (tmp_path / "notes.txt").read_text() == "Updated note.\n"
    assert (tmp_path / "alias.txt").is_symlink()


def test_nonfixable_symlink_diagnostic_is_not_a_skip(tmp_path):
    class DiagnosticRule(_AliasRule):
        fix = Rule.fix

    linter = _alias_linter(tmp_path)
    linter.rules = [DiagnosticRule()]
    assert len(linter.run()) == 2
    assert linter.fix_and_apply() == ([], [])
    assert linter.fix_skips == []


def test_unselected_confidence_does_not_report_skips_or_unusable_suggestions(tmp_path):
    linter = _alias_linter(tmp_path)
    linter.rules[0].result_confidence = AutofixConfidence.SUGGEST
    applied, suggested = linter.fix_and_apply()
    assert applied == []
    assert [fix.file_path for fix in suggested] == [tmp_path / "notes.txt"]
    assert linter.fix_skips == []
    assert (tmp_path / "notes.txt").read_text() == "Original note.\n"
    applied, _ = linter.fix_and_apply(AutofixConfidence.SUGGEST)
    assert [fix.file_path for fix in applied] == [tmp_path / "notes.txt"]
    assert len(linter.fix_skips) == 1


@pytest.mark.parametrize("linked_source", [False, True], ids=["regular-source", "linked-source"])
def test_rename_proposal_metadata_tracks_both_endpoints(tmp_path, linked_source):
    class RenameRule(_AliasRule):
        def check(self, context):
            source = context.root_path / "notes.txt"
            if not source.exists():
                return []
            return [
                self.violation(
                    "Rename note",
                    file_path=source,
                    fixable=True,
                    fix_confidence=AutofixConfidence.SAFE,
                )
            ]

        def fix(self, context, violations):
            proposal = super().fix(context, violations)[0]
            proposal.rename_from = context.root_path / (
                "alias.txt" if linked_source else "notes.txt"
            )
            proposal.file_path = context.root_path / "renamed.txt"
            return [proposal]

    linter = _alias_linter(tmp_path)
    linter.rules = [RenameRule()]
    remaining, proposals = linter.fix()
    assert remaining == [] and len(proposals) == 1
    proposal = proposals[0]
    assert proposal.confidence == AutofixConfidence.SAFE
    assert len(proposal.violations_fixed) == 1
    violation = proposal.violations_fixed[0]
    assert violation.file_path == tmp_path / "notes.txt"
    assert violation.fixable is (not linked_source)
    assert violation.fix_confidence == (None if linked_source else AutofixConfidence.SAFE)
    applied, suggested = linter.fix_and_apply()
    assert suggested == []
    if linked_source:
        assert applied == []
        assert [path for path, _ in linter.fix_skips] == [tmp_path / "alias.txt"]
        assert (tmp_path / "notes.txt").read_text() == "Original note.\n"
        assert not (tmp_path / "renamed.txt").exists()
    else:
        assert len(applied) == 1 and linter.fix_skips == []
        assert not (tmp_path / "notes.txt").exists()
        assert (tmp_path / "renamed.txt").read_text() == "Updated note.\n"


def test_write_boundary_reports_symlinked_rename_source(tmp_path):
    linter = _alias_linter(tmp_path)
    _remaining, proposals = linter.fix()
    proposal = proposals[0]
    proposal.rename_from = proposal.file_path
    proposal.file_path = tmp_path / "renamed.txt"
    skips = []
    assert Linter.apply_fixes([proposal], skips=skips) == []
    assert [path for path, _ in skips] == [tmp_path / "alias.txt"]
    assert not proposal.file_path.exists()
    assert (tmp_path / "notes.txt").read_text() == "Original note.\n"


@pytest.mark.integration
def test_two_roots_keep_distinct_lexical_skip_paths(tmp_path):
    first = _copy_repo(tmp_path, "first")
    second = _copy_repo(tmp_path, "second")
    result = _cli("fix", first, second, "--rule", RULE)
    assert result.returncode == 0, result.stderr
    assert "Skipped 2 path(s):" in result.stdout
    assert f"[{first / 'CLAUDE.md'}] symbolic link" in result.stdout
    assert f"[{second / 'CLAUDE.md'}] symbolic link" in result.stdout


@pytest.mark.integration
def test_rename_followup_retains_and_deduplicates_skips(tmp_path, monkeypatch):
    repo = _copy_repo(tmp_path)
    shutil.copytree(FIXTURES / "autofix/fixable-accuracy-name/My_Skill", repo / "handoff")
    calls = []
    original = Linter.fix_and_apply

    def record(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        calls.append(list(self.fix_skips))
        return result

    monkeypatch.setattr(Linter, "fix_and_apply", record)
    result = _cli("fix", repo, "--rule", RULE, "--rule", "agentskill-name")
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2 and all(calls)
    assert "name: handoff" in (repo / "handoff/SKILL.md").read_text()
    assert "Skipped 1 path(s):" in result.stdout
    assert result.stdout.count("[CLAUDE.md] symbolic link") == 1


@pytest.mark.integration
def test_write_failure_still_fails_with_policy_skips(tmp_path, monkeypatch):
    import skillsaw.linter as module

    linked = _copy_repo(tmp_path, "linked")
    regular = _copy_repo(tmp_path, "regular", linked=False)
    original = (regular / "CLAUDE.md").read_bytes()

    def refused(*args, **kwargs):
        raise OSError("Test write refusal")

    monkeypatch.setattr(module, "write_text_preserving", refused)
    result = _cli("fix", linked, regular, "--rule", RULE)
    assert result.returncode == 1
    assert "Skipped 1 path(s):" in result.stdout
    assert "Failed to apply 1 fix(es)" in result.stderr
    assert "Test write refusal" in result.stderr
    assert "Fixed " not in result.stdout and "No auto-fixable" not in result.stdout
    assert (regular / "CLAUDE.md").read_bytes() == original
