"""Keep the shipped publisher walkthrough reproducible through the real CLI."""

import json
import shutil
from pathlib import Path

from tests.cli_runner import run_cli


def test_editor_onboarding_edit_fix_ci(tmp_path):
    fixture = Path(__file__).resolve().parents[1] / "examples" / "editor-onboarding"
    repo = tmp_path / "publisher"
    shutil.copytree(fixture, repo)
    skill = repo / "skills" / "release-notes" / "SKILL.md"
    original = skill.read_text(encoding="utf-8")

    def lint(*extra):
        return run_cli(["lint", "--format", "json", "--verbose", *extra, "."], cwd=repo)

    clean = lint()
    assert clean.returncode == 0, clean.stderr
    assert json.loads(clean.stdout)["violations"] == []
    skill.write_text(
        original.replace("name: release-notes", "name: Release_Notes"), encoding="utf-8"
    )
    broken = lint()
    assert broken.returncode == 1
    violations = json.loads(broken.stdout)["violations"]
    assert any(
        item["rule_id"] == "agentskill-name"
        and item["file_path"] == "skills/release-notes/SKILL.md"
        and item["line"] == 2
        and item["severity"] == "error"
        for item in violations
    )

    preview = run_cli(["fix", "--dry-run", "."], cwd=repo)
    assert preview.returncode == 0, preview.stderr
    assert "name: Release_Notes" in skill.read_text(encoding="utf-8")
    fixed = run_cli(["fix", "."], cwd=repo)
    assert fixed.returncode == 0, fixed.stderr
    assert skill.read_text(encoding="utf-8") == original
    assert run_cli(["fix", "."], cwd=repo).returncode == 0
    assert skill.read_text(encoding="utf-8") == original
    # The published action defaults to this flag for untrusted PRs.
    ci = lint("--no-custom-rules")
    assert ci.returncode == 0, ci.stderr
    assert json.loads(ci.stdout)["violations"] == []
