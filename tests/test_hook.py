"""End-to-end tests for the ``skillsaw hook`` subcommand.

The hook is invoked by Claude Code as a PostToolUse handler: it receives the
tool-call payload as JSON on stdin and lints the file that was just edited,
using the repository's own configuration. These tests drive the real CLI via
subprocess with crafted stdin payloads and assert on exit code and stderr.

Exit-code contract (Claude Code PostToolUse):
  0 — nothing to surface (not a lint target, clean, or below fail-on)
  2 — violations found; stderr is fed back to the agent
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def copy_fixture(name, tmp_path):
    src = FIXTURES / name
    dst = tmp_path / name.replace("/", "_")
    shutil.copytree(src, dst)
    return dst


def run_hook(payload, event="post-tool-use"):
    """Invoke ``skillsaw hook <event>`` with *payload* (dict or str) on stdin."""
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    args = [sys.executable, "-m", "skillsaw", "hook", event]
    return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=60)


def edit_payload(file_path, tool_name="Edit"):
    return {"tool_name": tool_name, "tool_input": {"file_path": str(file_path)}}


# ── Violations are surfaced ──────────────────────────────────────


def test_error_violation_surfaced(tmp_path):
    repo = copy_fixture("hook-lint", tmp_path)
    skill = repo / "bad-skill" / "SKILL.md"
    r = run_hook(edit_payload(skill))
    assert r.returncode == 2
    assert "agentskill-valid" in r.stderr
    assert "SKILL.md" in r.stderr


def test_below_fail_level_not_surfaced_by_default(tmp_path):
    """The bad skill also has a warning; default fail-on is error, so the
    warning must not appear."""
    repo = copy_fixture("hook-lint", tmp_path)
    skill = repo / "bad-skill" / "SKILL.md"
    r = run_hook(edit_payload(skill))
    assert r.returncode == 2
    assert "skill-frontmatter" not in r.stderr


def test_repo_config_lowers_fail_level(tmp_path):
    """A repo config of fail-on: info surfaces the warning too — the hook
    honors the repository's own configuration, not a hardcoded threshold."""
    repo = copy_fixture("hook-lint", tmp_path)
    (repo / ".skillsaw.yaml").write_text('version: "99.0.0"\nfail-on: info\n')
    skill = repo / "bad-skill" / "SKILL.md"
    r = run_hook(edit_payload(skill))
    assert r.returncode == 2
    assert "agentskill-valid" in r.stderr
    assert "skill-frontmatter" in r.stderr


def test_feedback_scoped_to_edited_file(tmp_path):
    """Only violations in the edited file are reported, never siblings."""
    repo = copy_fixture("hook-lint", tmp_path)
    skill = repo / "bad-skill" / "SKILL.md"
    r = run_hook(edit_payload(skill))
    assert "clean-skill" not in r.stderr


# ── Silent no-ops (exit 0, never disrupt the session) ────────────


def test_clean_file_is_silent(tmp_path):
    repo = copy_fixture("hook-lint", tmp_path)
    skill = repo / "clean-skill" / "SKILL.md"
    r = run_hook(edit_payload(skill))
    assert r.returncode == 0
    assert r.stderr.strip() == ""


def test_non_target_file_is_silent(tmp_path):
    repo = copy_fixture("hook-lint", tmp_path)
    r = run_hook(edit_payload(repo / "notes.txt"))
    assert r.returncode == 0
    assert r.stderr.strip() == ""


def test_non_edit_tool_is_silent(tmp_path):
    repo = copy_fixture("hook-lint", tmp_path)
    skill = repo / "bad-skill" / "SKILL.md"
    payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    r = run_hook(payload)
    assert r.returncode == 0
    assert r.stderr.strip() == ""


def test_multiedit_tool_is_handled(tmp_path):
    repo = copy_fixture("hook-lint", tmp_path)
    skill = repo / "bad-skill" / "SKILL.md"
    r = run_hook(edit_payload(skill, tool_name="MultiEdit"))
    assert r.returncode == 2
    assert "agentskill-valid" in r.stderr


def test_missing_file_is_silent(tmp_path):
    r = run_hook(edit_payload(tmp_path / "does-not-exist" / "SKILL.md"))
    assert r.returncode == 0
    assert r.stderr.strip() == ""


def test_malformed_stdin_is_silent():
    r = run_hook("this is not json")
    assert r.returncode == 0
    assert r.stderr.strip() == ""


def test_empty_stdin_is_silent():
    r = run_hook("")
    assert r.returncode == 0


def test_missing_file_path_is_silent():
    r = run_hook({"tool_name": "Edit", "tool_input": {}})
    assert r.returncode == 0


def test_unknown_event_is_silent(tmp_path):
    repo = copy_fixture("hook-lint", tmp_path)
    skill = repo / "bad-skill" / "SKILL.md"
    r = run_hook(edit_payload(skill), event="pre-tool-use")
    assert r.returncode == 0
    assert r.stderr.strip() == ""


# ── Discovery is the source of truth, not a duplicated allowlist ──


def test_instruction_file_weak_language_surfaced(tmp_path):
    """Regression: an edit to a `*.instructions.md` file with a warning-level
    issue is surfaced when the repo config lowers the bar to warning.

    This class of file was silently dropped when the hook kept its own
    filename allowlist; it now relies on skillsaw's real discovery."""
    repo = copy_fixture("hook-lint", tmp_path)
    (repo / ".skillsaw.yaml").write_text('version: "99.0.0"\nfail-on: warning\n')
    instr = repo / "coding.instructions.md"
    r = run_hook(edit_payload(instr))
    assert r.returncode == 2
    assert "content-weak-language" in r.stderr


@pytest.mark.parametrize(
    "rel,content",
    [
        ("src/main.py", "print('hello')\n"),
        ("data.csv", "a,b,c\n1,2,3\n"),
        ("build.log", "compiling...\n"),
    ],
)
def test_source_files_are_silent(tmp_path, rel, content):
    """Files skillsaw doesn't discover produce no violations, so the hook is
    silent — no filename allowlist required."""
    repo = copy_fixture("hook-lint", tmp_path)
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    r = run_hook(edit_payload(target))
    assert r.returncode == 0
    assert r.stderr.strip() == ""
