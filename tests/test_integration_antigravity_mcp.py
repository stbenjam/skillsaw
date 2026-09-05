"""CLI coverage of Antigravity's ordered MCP view and policy visibility."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks.json_config import AntigravityMcpBlock
from skillsaw.context import RepositoryContext
from tests.antigravity._helpers import copy_fixture
from tests.cli_runner import run_cli

RULE = "antigravity-mcp-valid"
FILE = ".agents/mcp_config.json"


def _lint(repo, *extra):
    result = run_cli(
        [
            "lint",
            str(repo),
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
            "--format",
            "json",
            "--verbose",
            *extra,
        ]
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode, json.loads(result.stdout)["violations"]


def _block(repo):
    blocks = RepositoryContext(repo).lint_tree.find(AntigravityMcpBlock)
    assert [str(block.path.relative_to(repo)) for block in blocks] == [FILE]
    return blocks[0]


def test_accepted_case_fields_reach_the_server_projection(tmp_path):
    repo = copy_fixture("antigravity/mcp-decoder/accepted", tmp_path)
    assert _lint(repo, "--rule", RULE, "--strict") == (0, [])
    servers = {server.name: server for server in _block(repo).servers}
    assert set(servers) == {"timetable", "local", "empty"}
    assert servers["timetable"].url == "https://feeds.example.invalid/mcp"
    assert servers["timetable"].command is None
    assert servers["timetable"].headers == {"X-Region": "north", "X-Optional": None}
    assert servers["timetable"].oauth["clientId"] == "ferrymark"
    assert servers["local"].command == "/audit/not-an-executable"
    assert servers["local"].args == ["--read-only", None]
    assert servers["local"].env == {"Mode": "ferry", "MODE": "read"}
    assert servers["empty"].command is None


def test_dropped_servers_get_one_shape_finding_each(tmp_path):
    repo = copy_fixture("antigravity/mcp-decoder/dropped", tmp_path)
    code, findings = _lint(repo, "--rule", RULE, "--rule", "mcp-valid-json", "--strict")
    assert code == 1
    assert len(findings) == 6
    assert {(v["rule_id"], v["severity"], v["file_path"]) for v in findings} == {
        (RULE, "warning", FILE)
    }
    for name in ("command", "args", "environment", "headers", "oauth", "disabled"):
        assert sum(f"MCP server '{name}':" in v["message"] for v in findings) == 1
    assert all("drops the server silently" in v["message"] for v in findings)
    assert "control" in _block(repo).server_names


def test_replaced_wrapper_and_server_discard_old_errors(tmp_path):
    repo = copy_fixture("antigravity/mcp-decoder/replaced", tmp_path)
    assert _lint(repo, "--rule", RULE, "--strict") == (0, [])
    servers = _block(repo).servers
    assert len(servers) == 1
    assert servers[0].name == "timetable"
    assert servers[0].url == "https://feeds.example.invalid/mcp"


@pytest.mark.parametrize("value", [[], False, 42, "servers"])
@pytest.mark.parametrize("severity", ["error", "warning", "info"])
def test_wrong_wrapper_shape_is_fatal_and_respects_primary_severity(tmp_path, value, severity):
    repo = copy_fixture("antigravity/mcp-decoder/wrapper-array", tmp_path)
    (repo / FILE).write_text(json.dumps({"mcpServers": value}))
    (repo / ".skillsaw.yaml").write_text(f"rules:\n  {RULE}:\n    severity: {severity}\n")
    code, findings = _lint(repo)
    assert code == (1 if severity == "error" else 0)
    assert len(findings) == 1
    assert (findings[0]["rule_id"], findings[0]["severity"], findings[0]["file_path"]) == (
        RULE,
        severity,
        FILE,
    )
    assert "'mcpServers' must be a JSON object or null" in findings[0]["message"]
    assert "exits 1" in findings[0]["message"]
    assert _block(repo).servers == []


@pytest.mark.parametrize("fixture", ["null-root", "wrong-wrapper"])
def test_accepted_no_server_documents_get_only_the_existing_warning(tmp_path, fixture):
    repo = copy_fixture(f"antigravity/mcp-decoder/{fixture}", tmp_path)
    code, findings = _lint(repo, "--rule", RULE)
    assert code == 0
    assert len(findings) == 1
    assert (findings[0]["rule_id"], findings[0]["severity"]) == (RULE, "warning")
    assert "loads no server" in findings[0]["message"]
    assert _block(repo).servers == []


def test_shape_rule_off_keeps_case_normalized_policy_visibility(tmp_path):
    repo = copy_fixture("antigravity/mcp-decoder/policy", tmp_path)
    (repo / ".skillsaw.yaml").write_text(
        f"rules:\n  {RULE}:\n    enabled: false\n"
        "  mcp-prohibited:\n    enabled: true\n    allowlist: [local]\n"
    )
    code, findings = _lint(repo)
    assert code == 1
    assert {(v["rule_id"], v["file_path"]) for v in findings} == {
        ("mcp-valid-json", FILE),
        ("mcp-prohibited", FILE),
    }
    assert len(findings) == 2
    assert any("user information" in v["message"] for v in findings)
    assert any("non-allowlisted MCP servers defined: timetable" in v["message"] for v in findings)
    assert _block(repo).servers[0].command == "/audit/not-an-executable"
