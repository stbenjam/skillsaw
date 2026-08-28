"""End-to-end coverage for the local feedback bundle command."""

import hashlib
import errno
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from skillsaw.cli import _feedback
from skillsaw.redaction import redact_text


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
    archive_directory = payload["archive_directory"]
    assert archive_directory.startswith("skillsaw-feedback-")
    assert "template=bug_report.yml" in payload["issue_url"]
    assert payload["email"] == {
        "to": "stephen@bitbin.de",
        "gpg_key": "https://github.com/stbenjam.gpg",
    }
    assert payload["included_files"] == []
    with zipfile.ZipFile(output) as bundle:
        assert sorted(bundle.namelist()) == [
            f"{archive_directory}/environment.json",
            f"{archive_directory}/lint-report.json",
            f"{archive_directory}/lint-stderr.txt",
            f"{archive_directory}/manifest.json",
        ]
        assert all(name.startswith(f"{archive_directory}/") for name in bundle.namelist())
        environment = json.loads(bundle.read(f"{archive_directory}/environment.json"))
        assert environment["lint_extensions_enabled"] is False
        assert environment["config_included"] is False
        manifest = json.loads(bundle.read(f"{archive_directory}/manifest.json"))
        assert manifest["redactions"] >= 1
        assert set(manifest["files"]) == {
            name.removeprefix(f"{archive_directory}/")
            for name in bundle.namelist()
            if not name.endswith("/manifest.json")
        }


def test_feedback_text_output_requires_review_before_sharing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    result = _run_feedback(repo)

    assert result.returncode == 0, result.stderr
    bundles = list((repo / ".skillsaw-feedback").glob("*.zip"))
    assert len(bundles) == 1
    assert bundles[0].name.startswith("skillsaw-feedback-")
    assert "Review before sharing" in result.stdout
    assert "best effort to redact" in result.stdout
    assert "not guaranteed to catch every secret" in result.stdout
    assert "stephen@bitbin.de" in result.stdout
    assert "https://github.com/stbenjam.gpg" in result.stdout
    assert "Extracts: skillsaw-feedback-" in result.stdout


def test_feedback_includes_only_requested_repository_files_and_redacts_them(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    requested = repo / "reproducer.md"
    requested.write_text("token: ghp_abcdefghijklmnopqrstuvwxyz1234567890\n")
    output = tmp_path / "report.zip"

    result = _run_feedback(repo, "--output", str(output), "--include", "reproducer.md", "--json")

    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(output) as bundle:
        archive_directory = bundle.namelist()[0].split("/", 1)[0]
        included = bundle.read(f"{archive_directory}/included/reproducer.md").decode()
        assert "ghp_abcdefghijklmnopqrstuvwxyz1234567890" not in included
        assert "[REDACTED]" in included
        environment = json.loads(bundle.read(f"{archive_directory}/environment.json"))
        assert environment["included_files"] == ["reproducer.md"]


def test_feedback_redacts_private_keys_and_exact_credential_names():
    text, count = _feedback._redact_text(
        "password: not-a-known-token\n"
        "secret=also-not-known\n"
        "-----BEGIN PRIVATE KEY-----\nprivate material\n-----END PRIVATE KEY-----\n"
    )

    assert "not-a-known-token" not in text
    assert "also-not-known" not in text
    assert "private material" not in text
    assert count >= 3


def test_feedback_redacts_block_scalar_credentials_without_losing_siblings():
    text, count = _feedback._redact_text(
        "outer:\n"
        "  password: |\n"
        "    first secret\n"
        "\n"
        "    second secret\n"
        "  host: localhost\n"
    )

    assert "first secret" not in text
    assert "second secret" not in text
    assert "host: localhost" in text
    assert count == 1


def test_shared_redactor_handles_multiline_secrets_and_is_idempotent():
    source = (
        "password: >\r\n"
        "  first secret\r\n"
        "\r\n"
        "  second secret\r\n"
        "host: localhost\r\n"
        "-----BEGIN PRIVATE KEY-----\r\n"
        "private material\r\n"
        "-----END PRIVATE KEY-----\r\n"
    )

    result = redact_text(source)

    assert result.count == 2
    assert "first secret" not in result.text
    assert "second secret" not in result.text
    assert "private material" not in result.text
    assert "password: [REDACTED]\r\n" in result.text
    assert "host: localhost\r\n" in result.text
    repeated = redact_text(result.text)
    assert repeated.text == result.text
    assert repeated.count == 0


def test_shared_redactor_handles_container_syntax_and_canonical_aliases():
    source = (
        '{"password":"swordfish","host":"localhost"}\n'
        "- passwd: real-value\n"
        "private_key: another-real-value\n"
        "password:\n\n"
        "host: still-here\n"
    )

    result = redact_text(source)

    assert result.count == 3
    assert '"password":"[REDACTED]"' in result.text
    assert "- passwd: [REDACTED]" in result.text
    assert "private_key: [REDACTED]" in result.text
    assert "host: still-here" in result.text


def test_shared_redactor_counts_structured_assignment_once():
    result = redact_text("api_key: sk-abcdefghijklmnopqrstuvwxyz123456\n")

    assert result.count == 1


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


def test_feedback_mirrors_interactive_lint_progress(tmp_path, monkeypatch):
    class InteractiveStderr:
        def __init__(self):
            self.buffer = io.BytesIO()

        def isatty(self):
            return True

    terminal = InteractiveStderr()
    monkeypatch.setattr(_feedback.sys, "stderr", terminal)

    stdout, stderr, return_code = _feedback._run_lint_process(
        [
            sys.executable,
            "-c",
            "import sys; print('lint report'); print('linting [1/1]', file=sys.stderr)",
        ],
        tmp_path,
    )

    assert return_code == 0
    assert stdout == "lint report\n"
    assert "linting [1/1]" in stderr
    assert terminal.buffer.getvalue() == stderr.encode()


@pytest.mark.skipif(os.name != "posix", reason="PTY EOF behavior is POSIX-specific")
def test_feedback_handles_linux_pty_eof(tmp_path, monkeypatch):
    import pty

    class InteractiveStderr:
        def __init__(self):
            self.buffer = io.BytesIO()

        def isatty(self):
            return True

    monkeypatch.setattr(_feedback.sys, "stderr", InteractiveStderr())

    master_fds = []
    openpty = pty.openpty

    def recording_openpty():
        master, slave = openpty()
        master_fds.append(master)
        return master, slave

    original_read = _feedback.os.read

    def closed_pty(file_descriptor, size):
        if file_descriptor in master_fds:
            raise OSError(errno.EIO, "Input/output error")
        return original_read(file_descriptor, size)

    monkeypatch.setattr(pty, "openpty", recording_openpty)
    monkeypatch.setattr(_feedback.os, "read", closed_pty)

    stdout, stderr, return_code = _feedback._run_lint_process(
        [sys.executable, "-c", "print('lint report')"], tmp_path
    )

    assert return_code == 0
    assert stdout == "lint report\n"
    assert stderr == ""


def test_feedback_records_a_timed_out_diagnostic_lint(tmp_path, monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("skillsaw lint", 120, output=b"report", stderr=b"progress")

    monkeypatch.setattr(_feedback, "_run_lint_process", timeout)

    result = _feedback._run_diagnostic_lint(tmp_path, None, with_extensions=False)

    assert result == {
        "command": ["skillsaw", "lint", "--format", "json", "--verbose", "--no-baseline"],
        "exit_code": None,
        "stdout": "report",
        "stderr": "progress",
        "timed_out": True,
    }
