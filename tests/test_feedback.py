"""End-to-end coverage for the local feedback bundle command."""

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path


def _run_feedback(path: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "skillsaw", "feedback", str(path), *args],
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_feedback_creates_redacted_bundle_without_repository_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill\n---\n\nDo the work.\n"
    )
    (repo / ".skillsaw.yaml").write_text("api_key: sk-abcdefghijklmnopqrstuvwxyz123456\n")
    (repo / "private.md").write_text("This file must not be included by default.\n")
    output = tmp_path / "report.zip"

    result = _run_feedback(
        repo, "--output", str(output), "--message", "Lint failed in CI", "--json"
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert Path(payload["bundle"]) == output.resolve()
    assert payload["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert "template=bug_report.yml" in payload["issue_url"]
    assert payload["included_files"] == []
    with zipfile.ZipFile(output) as bundle:
        assert sorted(bundle.namelist()) == [
            "environment.json",
            "lint-report.json",
            "lint-stderr.txt",
            "manifest.json",
            "skillsaw-config.yaml",
        ]
        assert "private.md" not in bundle.namelist()
        assert (
            "sk-abcdefghijklmnopqrstuvwxyz123456"
            not in bundle.read("skillsaw-config.yaml").decode()
        )
        environment = json.loads(bundle.read("environment.json"))
        assert environment["lint_extensions_enabled"] is False
        assert environment["config_included"] is True
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["redactions"] >= 1
        assert set(manifest["files"]) == set(bundle.namelist()) - {"manifest.json"}


def test_feedback_includes_only_requested_repository_files_and_redacts_them(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    requested = repo / "reproducer.md"
    requested.write_text("token: ghp_abcdefghijklmnopqrstuvwxyz1234567890\n")
    output = tmp_path / "report.zip"

    result = _run_feedback(repo, "--output", str(output), "--include", "reproducer.md", "--json")

    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(output) as bundle:
        included = bundle.read("included/reproducer.md").decode()
        assert "ghp_abcdefghijklmnopqrstuvwxyz1234567890" not in included
        assert "[REDACTED]" in included
        environment = json.loads(bundle.read("environment.json"))
        assert environment["included_files"] == ["reproducer.md"]


def test_feedback_rejects_source_files_outside_the_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("not reportable\n")

    result = _run_feedback(
        repo, "--include", str(outside), "--output", str(tmp_path / "report.zip")
    )

    assert result.returncode == 1
    assert "inside the repository" in result.stderr
