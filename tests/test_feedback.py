"""End-to-end coverage for the local feedback bundle command."""

import hashlib
import errno
import io
import json
import os
import subprocess
import sys
import sysconfig
import zipfile
from pathlib import Path

import pytest

from skillsaw.cli import _feedback


def _run_feedback(path: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "skillsaw", "feedback", str(path), *args],
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_feedback_text_output_requires_review_before_sharing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    result = _run_feedback(repo)

    assert result.returncode == 0, result.stderr
    bundles = list((repo / ".skillsaw-feedback").glob("*.zip"))
    assert len(bundles) == 1
    assert bundles[0].name.startswith("skillsaw-feedback-")
    assert "Review before sharing" in result.stdout
    assert "skillsaw's own output only" in result.stdout
    assert "stephen@bitbin.de" in result.stdout
    assert "https://github.com/stbenjam.gpg" in result.stdout
    assert "Extracts: skillsaw-feedback-" in result.stdout


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


@pytest.mark.skipif(os.name != "posix", reason="PTY progress mirroring is POSIX-specific")
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
        "command": [
            "skillsaw",
            "lint",
            "--format",
            "json",
            "--verbose",
            "--no-baseline",
            "--no-custom-rules",
            "--no-plugins",
            "<repository>",
        ],
        "exit_code": None,
        "stdout": "report",
        "stderr": "progress",
        "timed_out": True,
    }


def test_feedback_records_the_command_it_actually_ran(tmp_path, monkeypatch):
    """The bundle's record of its own lint must be reproducible by a maintainer."""
    captured = {}

    def capture(command, cwd):
        captured["command"] = command
        captured["cwd"] = cwd
        return "{}", "", 0

    monkeypatch.setattr(_feedback, "_run_lint_process", capture)
    config = tmp_path / ".skillsaw.yaml"
    config.write_text("version: 0.20.0\n")

    result = _feedback._run_diagnostic_lint(tmp_path, config, with_extensions=True)

    assert captured["command"][1:3] == ["-m", "skillsaw"]
    assert captured["command"][-1] == str(tmp_path)
    assert "--no-custom-rules" not in captured["command"]
    assert result["command"] == ["skillsaw", *captured["command"][3:-1], "<repository>"]
    assert "--config" in result["command"]


def test_feedback_does_not_import_skillsaw_from_the_target_repository(tmp_path):
    """`python -m` puts cwd on sys.path, so the child must not run in the repo."""
    repo = tmp_path / "repo"
    (repo / "skillsaw").mkdir(parents=True)
    marker = repo / "HIJACKED"
    (repo / "skillsaw" / "__init__.py").write_text(
        f"import pathlib\npathlib.Path({str(marker)!r}).write_text('hijacked')\n"
    )
    (repo / "skillsaw" / "__main__.py").write_text("raise SystemExit('hijacked')\n")
    (repo / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill\n---\n\nDo the work.\n"
    )
    output = tmp_path / "report.zip"

    result = _run_feedback(repo, "--output", str(output), "--json")

    assert result.returncode == 0, result.stderr
    assert not marker.exists(), "target repository was imported as the skillsaw package"
    with zipfile.ZipFile(output) as bundle:
        archive_directory = json.loads(result.stdout)["archive_directory"]
        report = json.loads(bundle.read(f"{archive_directory}/lint-report.json"))
        assert "violations" in report, "the diagnostic lint did not produce a real report"


def test_feedback_rejects_a_missing_or_non_file_config(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    missing = _run_feedback(
        repo, "--config", str(repo / "absent.yaml"), "--output", str(tmp_path / "a.zip")
    )
    assert missing.returncode == 1
    assert "Config file not found" in missing.stderr

    directory = repo / "conf.d"
    directory.mkdir()
    not_a_file = _run_feedback(
        repo, "--config", str(directory), "--output", str(tmp_path / "b.zip")
    )
    assert not_a_file.returncode == 1
    assert "Config file not found" in not_a_file.stderr


def test_feedback_keeps_the_local_repository_path_out_of_the_bundle(tmp_path):
    repo = tmp_path / "my-private-repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text("---\nname: demo\n---\n\nNo description field.\n")
    (repo / "private.md").write_text("Confidential prose that must not travel.\n")
    output = tmp_path / "report.zip"

    result = _run_feedback(repo, "--output", str(output), "--json")

    assert result.returncode == 0, result.stderr
    raw = output.read_bytes()
    assert str(repo).encode() not in raw
    assert b"Confidential prose that must not travel" not in raw
    archive_directory = json.loads(result.stdout)["archive_directory"]
    with zipfile.ZipFile(output) as bundle:
        report = bundle.read(f"{archive_directory}/lint-report.json").decode()
    assert "<repository>" in report


def test_replace_local_paths_leaves_a_filesystem_root_alone():
    text = "/ and /x are not the repository"

    assert _feedback._replace_local_paths(text, Path("/"), None) == text


def test_replace_local_paths_scrubs_interpreter_and_home_paths(tmp_path):
    traceback_text = (
        f'  File "{sysconfig.get_paths()["purelib"]}/skillsaw/linter.py", line 1\n'
        f'  File "{Path.home()}/work/repro.py", line 2\n'
    )

    scrubbed = _feedback._replace_local_paths(traceback_text, tmp_path, None)

    assert str(Path.home()) not in scrubbed
    assert sysconfig.get_paths()["purelib"] not in scrubbed
    assert "skillsaw/linter.py" in scrubbed


def test_feedback_bundles_only_skillsaw_output_by_default(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill\n---\n\nDo the work.\n"
    )
    (repo / ".skillsaw.yaml").write_text("api_key: sk-abcdefghijklmnopqrstuvwxyz123456\n")
    (repo / "private.md").write_text("This file must not be included by default.\n")
    output = tmp_path / "report.zip"

    result = _run_feedback(repo, "--output", str(output), "--message", "Lint failed", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["included_files"] == []
    archive_directory = payload["archive_directory"]
    raw = output.read_bytes()
    assert b"This file must not be included by default" not in raw
    assert b"sk-abcdefghijklmnopqrstuvwxyz123456" not in raw
    with zipfile.ZipFile(output) as bundle:
        assert sorted(bundle.namelist()) == [
            f"{archive_directory}/environment.json",
            f"{archive_directory}/lint-report.json",
            f"{archive_directory}/lint-stderr.txt",
            f"{archive_directory}/manifest.json",
        ]


def test_feedback_copies_named_files_verbatim(tmp_path):
    """--include is the reporter's call; skillsaw must not alter what they named."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\n\nWork.\n")
    reproducer = repo / "reproducer.md"
    body = "password: hunter2\napiKey: sk-abcdefghijklmnopqrstuvwxyz123456\n"
    reproducer.write_text(body)
    output = tmp_path / "report.zip"

    result = _run_feedback(repo, "--include", "reproducer.md", "--output", str(output), "--json")

    assert result.returncode == 0, result.stderr
    archive_directory = json.loads(result.stdout)["archive_directory"]
    with zipfile.ZipFile(output) as bundle:
        shipped = bundle.read(f"{archive_directory}/included/reproducer.md").decode()
    assert shipped == body, "a file the reporter named must arrive unmodified"


def test_feedback_refuses_files_an_ignore_file_excludes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("# secrets\n.env\nbuild/\n")
    (repo / ".env").write_text("AWS_SECRET_ACCESS_KEY=hunter2\n")
    (repo / "build").mkdir()
    (repo / "build" / "out.md").write_text("generated\n")

    for target in (".env", "build/out.md"):
        result = _run_feedback(
            repo, "--include", target, "--output", str(tmp_path / f"{target[-5:]}.zip")
        )
        assert result.returncode == 1, target
        assert "ignore file already excludes" in result.stderr, target


def test_feedback_refuses_an_ignored_config(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".dockerignore").write_text(".skillsaw.yaml\n")
    config = repo / ".skillsaw.yaml"
    config.write_text("version: 0.20.0\n")

    result = _run_feedback(repo, "--config", str(config), "--output", str(tmp_path / "r.zip"))

    assert result.returncode == 1
    assert "ignore file already excludes" in result.stderr


def test_feedback_allows_a_file_a_negation_re_includes_nothing_about(tmp_path):
    """A '!' line must never turn the guardrail into a grant."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("!keep.md\n")
    (repo / "keep.md").write_text("shareable\n")
    (repo / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\n\nWork.\n")
    output = tmp_path / "report.zip"

    result = _run_feedback(repo, "--include", "keep.md", "--output", str(output), "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["included_files"] == ["keep.md"]


def test_feedback_names_the_reporter_files_it_bundled(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\n\nWork.\n")
    (repo / "reproducer.md").write_text("steps\n")

    result = _run_feedback(repo, "--include", "reproducer.md", "--output", str(tmp_path / "r.zip"))

    assert result.returncode == 0, result.stderr
    assert "does" in result.stdout and "not scan them for secrets" in result.stdout
    assert "included/reproducer.md" in result.stdout


def test_safe_terminal_text_strips_escapes_and_control_bytes():
    mirrored = _feedback._safe_terminal_text(b"\x1b]0;pwned\x07\x1b[31mred\x1b[0m \x08 done")

    assert b"\x1b" not in mirrored
    assert b"\x07" not in mirrored
    assert b"\x08" not in mirrored
    assert b"red" in mirrored
