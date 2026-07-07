"""
Tests for the ``skillsaw mcp`` MCP server.

Tool tests use the mcp SDK's in-memory client/server session, so every
tool is exercised end-to-end (schema generation, argument validation,
JSON serialization) against static fixtures without spawning a
subprocess. They skip cleanly when the optional ``mcp`` dependency is
unavailable (it requires Python >= 3.10; skillsaw's floor is 3.9).

The CLI gate tests (missing-dependency error path) run everywhere — they
must not require the SDK.
"""

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

HAS_MCP = sys.version_info >= (3, 10) and importlib.util.find_spec("mcp") is not None

needs_mcp = pytest.mark.skipif(
    not HAS_MCP,
    reason="mcp SDK not installed (requires Python >= 3.10 and `pip install 'skillsaw[mcp]'`)",
)


# ── Helpers ──────────────────────────────────────────────────────


def copy_fixture(name, tmp_path):
    src = FIXTURES / name
    dst = tmp_path / name.replace("/", "_")
    shutil.copytree(src, dst)
    return dst


def call_tool(name, arguments):
    """Call one tool against an in-memory server and return the raw result."""
    from mcp.shared.memory import create_connected_server_and_client_session

    from skillsaw.mcp_server import create_server

    async def _run():
        server = create_server()
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            return await session.call_tool(name, arguments)

    return asyncio.run(_run())


def payload(result):
    """Parse a successful tool result's JSON payload."""
    assert not result.isError, f"tool errored: {result.content}"
    return json.loads(result.content[0].text)


def snapshot_files(root):
    """Map of relative path -> bytes for every file under *root*."""
    return {p.relative_to(root): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ── Server surface ───────────────────────────────────────────────


@needs_mcp
def test_all_tools_registered():
    from mcp.shared.memory import create_connected_server_and_client_session

    from skillsaw.mcp_server import create_server

    async def _run():
        server = create_server()
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            return await session.list_tools()

    listed = asyncio.run(_run())
    names = {tool.name for tool in listed.tools}
    assert names == {"lint", "grade", "explain_rule", "list_rules", "fix"}
    for tool in listed.tools:
        assert tool.description, f"tool {tool.name} has no description"


# ── lint ─────────────────────────────────────────────────────────


@needs_mcp
class TestLintTool:
    def test_reports_violations_for_bad_fixture(self, tmp_path):
        repo = copy_fixture("agentskills/broken", tmp_path)
        data = payload(call_tool("lint", {"path": str(repo)}))

        assert data["violations"], "expected violations in the broken fixture"
        for violation in data["violations"]:
            assert violation["rule_id"]
            assert violation["severity"] in ("error", "warning", "info")
            assert violation["message"]
        builtin = [v for v in data["violations"] if v["source"] == "builtin"]
        assert builtin, "expected builtin violations"
        for violation in builtin:
            assert violation["docs"] == f"https://skillsaw.org/rules/{violation['rule_id']}/"

        summary = data["summary"]
        assert summary["total"] == len(data["violations"])
        assert summary["errors"] == sum(1 for v in data["violations"] if v["severity"] == "error")
        # The broken fixture has errors, so the lint fails.
        assert summary["errors"] > 0
        assert data["passed"] is False

        from skillsaw.grade import LETTER_NOTCHES

        assert data["grade"]["letter"] in LETTER_NOTCHES

    def test_line_numbers_reported(self, tmp_path):
        repo = copy_fixture("agentskills/broken", tmp_path)
        data = payload(call_tool("lint", {"path": str(repo)}))
        with_lines = [v for v in data["violations"] if v["line"] is not None]
        assert with_lines, "expected line numbers on line-traceable violations"
        assert all(v["line"] >= 1 for v in with_lines)

    def test_rules_filter_limits_rules(self, tmp_path):
        repo = copy_fixture("agentskills/broken", tmp_path)
        data = payload(call_tool("lint", {"path": str(repo), "rules": ["content-weak-language"]}))
        assert data["violations"], "filtered rule should still fire on the fixture"
        assert {v["rule_id"] for v in data["violations"]} == {"content-weak-language"}

    def test_strict_fails_on_warnings(self, tmp_path):
        repo = copy_fixture("agentskills/broken", tmp_path)
        args = {"path": str(repo), "rules": ["content-weak-language"]}

        relaxed = payload(call_tool("lint", args))
        assert relaxed["summary"]["errors"] == 0
        assert relaxed["summary"]["warnings"] > 0
        assert relaxed["passed"] is True

        strict = payload(call_tool("lint", {**args, "strict": True}))
        assert strict["passed"] is False

    def test_unknown_rule_errors(self, tmp_path):
        repo = copy_fixture("agentskills/broken", tmp_path)
        result = call_tool("lint", {"path": str(repo), "rules": ["not-a-rule"]})
        assert result.isError
        assert "Unknown rule" in result.content[0].text

    def test_missing_path_errors(self, tmp_path):
        result = call_tool("lint", {"path": str(tmp_path / "does-not-exist")})
        assert result.isError
        assert "not found" in result.content[0].text.lower()


# ── grade ────────────────────────────────────────────────────────


@needs_mcp
class TestGradeTool:
    def test_returns_letter_density_and_tokens(self, tmp_path):
        repo = copy_fixture("agentskills/broken", tmp_path)
        data = payload(call_tool("grade", {"path": str(repo)}))

        from skillsaw.grade import LETTER_NOTCHES

        assert data["letter"] in LETTER_NOTCHES
        assert data["density"] >= 0
        assert data["content_tokens"] > 0
        assert data["errors"] + data["warnings"] + data["info"] > 0

    def test_clean_fixture_grades_better_than_broken(self, tmp_path):
        from skillsaw.grade import LETTER_NOTCHES

        broken = copy_fixture("agentskills/broken", tmp_path)
        clean = copy_fixture("agentskills/clean", tmp_path)
        broken_grade = payload(call_tool("grade", {"path": str(broken)}))
        clean_grade = payload(call_tool("grade", {"path": str(clean)}))
        assert LETTER_NOTCHES.index(clean_grade["letter"]) < LETTER_NOTCHES.index(
            broken_grade["letter"]
        )


# ── explain_rule ─────────────────────────────────────────────────


@needs_mcp
class TestExplainRuleTool:
    def test_known_rule_returns_long_form_markdown(self):
        result = call_tool("explain_rule", {"rule_id": "content-weak-language"})
        assert not result.isError
        text = result.content[0].text

        assert "content-weak-language" in text
        assert "## Configuration (.skillsaw.yaml)" in text
        assert "https://skillsaw.org/rules/content-weak-language/" in text

        # The same long-form docs `skillsaw explain` prints.
        from skillsaw.rule_docs import load_rule_docs

        long_docs = load_rule_docs("content-weak-language")
        assert long_docs, "fixture rule should have long-form docs"
        assert long_docs.splitlines()[0] in text

    def test_unknown_rule_errors_with_suggestion(self):
        result = call_tool("explain_rule", {"rule_id": "content-weak-languge"})
        assert result.isError
        text = result.content[0].text
        assert "Unknown rule 'content-weak-languge'" in text
        assert "content-weak-language" in text  # close-match suggestion


# ── list_rules ───────────────────────────────────────────────────


@needs_mcp
class TestListRulesTool:
    def test_lists_builtin_rules_with_metadata(self):
        data = payload(call_tool("list_rules", {}))
        assert data["count"] == len(data["rules"])

        by_id = {entry["rule_id"]: entry for entry in data["rules"]}
        assert "agentskill-name" in by_id
        assert "content-weak-language" in by_id
        for entry in data["rules"]:
            assert entry["description"]
            assert entry["default_severity"] in ("error", "warning", "info")
            assert isinstance(entry["autofix"], bool)

        from skillsaw.rules.builtin import BUILTIN_RULES

        assert data["count"] >= len(BUILTIN_RULES)


# ── fix ──────────────────────────────────────────────────────────


@needs_mcp
class TestFixTool:
    def test_dry_run_is_default_and_modifies_nothing(self, tmp_path):
        repo = copy_fixture("autofix/safe-idempotency", tmp_path)
        before = snapshot_files(repo)

        data = payload(call_tool("fix", {"path": str(repo)}))

        assert data["dry_run"] is True
        assert data["fixes"], "fixture should have safe autofixable violations"
        assert data["summary"]["fixed"] == len(data["fixes"])
        assert data["summary"]["files"], "expected a per-file summary"
        assert snapshot_files(repo) == before, "dry_run must not modify files"

    def test_apply_writes_fixes_and_is_idempotent(self, tmp_path):
        repo = copy_fixture("autofix/safe-idempotency", tmp_path)
        before = snapshot_files(repo)
        lint_before = payload(call_tool("lint", {"path": str(repo)}))

        data = payload(call_tool("fix", {"path": str(repo), "dry_run": False}))
        assert data["dry_run"] is False
        assert data["fixes"]
        after_first = snapshot_files(repo)
        assert after_first != before

        # Independent re-lint confirms the fixes resolved violations (some
        # rules keep unfixable instances, so the count drops, not zeroes).
        lint_after = payload(call_tool("lint", {"path": str(repo)}))
        assert lint_after["summary"]["total"] < lint_before["summary"]["total"]

        # Second run finds nothing left to fix and changes nothing.
        again = payload(call_tool("fix", {"path": str(repo), "dry_run": False}))
        assert again["fixes"] == []
        assert snapshot_files(repo) == after_first


# ── CLI gate (`skillsaw mcp` without the SDK) ────────────────────


class TestCliGate:
    def test_missing_mcp_dependency_exits_with_install_hint(self, monkeypatch, capsys):
        import argparse
        import importlib.util as importlib_util

        from skillsaw.cli import _mcp

        real_find_spec = importlib_util.find_spec
        monkeypatch.setattr(
            importlib_util,
            "find_spec",
            lambda name, *args, **kwargs: (
                None if name == "mcp" else real_find_spec(name, *args, **kwargs)
            ),
        )

        with pytest.raises(SystemExit) as excinfo:
            _mcp._run_mcp(argparse.Namespace(command="mcp"))

        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "'mcp'" in err
        if sys.version_info >= (3, 10):
            assert "pip install 'skillsaw[mcp]'" in err
        else:
            assert "Python 3.10" in err


# ── stdio integration ────────────────────────────────────────────


@needs_mcp
@pytest.mark.integration
def test_stdio_server_starts_and_exits_cleanly_on_eof():
    result = subprocess.run(
        [sys.executable, "-m", "skillsaw", "mcp"],
        input="",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
