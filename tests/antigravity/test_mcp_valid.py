"""Tests for Antigravity MCP configuration validation rule (antigravity-mcp-valid)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from skillsaw.blocks import AntigravityMcpBlock
from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.linter import Linter
from skillsaw.rules.builtin.antigravity.mcp_valid import AntigravityMcpValidRule

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "antigravity"


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    target = tmp_path / name
    shutil.copytree(FIXTURES_DIR / name, target)
    return target


class TestAntigravityMcpValidRuleUnit:
    """Unit tests for AntigravityMcpValidRule check logic."""

    def test_valid_stdio_server(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "local-server": {
                            "command": "node",
                            "args": ["server.js", "--port", "3000"],
                            "env": {"NODE_ENV": "development"},
                            "timeout": 30,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert violations == []

    def test_valid_remote_server(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "remote-server": {
                            "serverUrl": "https://mcp.example.com/sse",
                            "headers": {"Authorization": "Bearer token"},
                            "timeout": 45.5,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert violations == []

    def test_invalid_root_non_object(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].message == "Antigravity MCP configuration must be an object"

    def test_invalid_mcpservers_non_object(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(json.dumps({"mcpServers": "invalid-servers"}), encoding="utf-8")
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].message == "'mcpServers' must be an object"

    def test_invalid_server_entry_non_object(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps({"mcpServers": {"broken": 123}}),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].message == "MCP server 'broken' configuration must be an object"

    def test_missing_connection_fields(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps({"mcpServers": {"empty-server": {}}}),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert (
            violations[0].message
            == "MCP server 'empty-server' must specify either 'serverUrl' (for remote servers) or 'command' (for local servers)"
        )

    @pytest.mark.parametrize("unsupported_field", ["url", "httpUrl"])
    def test_unsupported_url_fields_reported(self, tmp_path: Path, unsupported_field: str) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps(
                {"mcpServers": {"remote-srv": {unsupported_field: "https://mcp.example.com"}}}
            ),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert (
            violations[0].message
            == f"MCP server 'remote-srv' uses unsupported '{unsupported_field}'; Antigravity requires 'serverUrl'"
        )

    @pytest.mark.parametrize("bad_url", ["", "   ", 123, None, []])
    def test_invalid_server_url_type_or_empty(self, tmp_path: Path, bad_url) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps({"mcpServers": {"srv": {"serverUrl": bad_url}}}),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert any(
            v.message == "MCP server 'srv' 'serverUrl' must be a non-empty string"
            for v in violations
        )

    def test_server_url_with_userinfo(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps(
                {"mcpServers": {"srv": {"serverUrl": "https://user:password@example.com/sse"}}}
            ),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert (
            violations[0].message
            == "MCP server 'srv' 'serverUrl' must not contain user information"
        )

    def test_invalid_headers_type(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "srv": {
                            "serverUrl": "https://example.com/sse",
                            "headers": "not-an-object",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].message == "MCP server 'srv' 'headers' must be an object"

    @pytest.mark.parametrize("bad_cmd", ["", "   ", 123, None, []])
    def test_invalid_command_type_or_empty(self, tmp_path: Path, bad_cmd) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps({"mcpServers": {"srv": {"command": bad_cmd}}}),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert any(
            v.message == "MCP server 'srv' 'command' must be a non-empty string" for v in violations
        )

    @pytest.mark.parametrize("bad_args", ["not-a-list", [1, 2], ["ok", 3]])
    def test_invalid_args_type(self, tmp_path: Path, bad_args) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps({"mcpServers": {"srv": {"command": "echo", "args": bad_args}}}),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].message == "MCP server 'srv' 'args' must be an array of strings"

    def test_invalid_env_type(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps({"mcpServers": {"srv": {"command": "echo", "env": "not-an-object"}}}),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].message == "MCP server 'srv' 'env' must be an object"

    @pytest.mark.parametrize("bad_timeout", [-1, 0, -10.5, "30", True, False, []])
    def test_invalid_timeout(self, tmp_path: Path, bad_timeout) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text(
            json.dumps({"mcpServers": {"srv": {"command": "echo", "timeout": bad_timeout}}}),
            encoding="utf-8",
        )
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].message == "MCP server 'srv' 'timeout' must be a positive number"

    def test_syntax_error_reported(self, tmp_path: Path) -> None:
        agents_dir = tmp_path / ".agents"
        agents_dir.mkdir(parents=True)
        mcp_file = agents_dir / "mcp_config.json"
        mcp_file.write_text("{ unquoted_json: ", encoding="utf-8")
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ANTIGRAVITY})
        rule = AntigravityMcpValidRule()
        violations = rule.check(context)
        assert len(violations) == 1
        assert "Invalid JSON:" in violations[0].message


class TestAntigravityMcpValidIntegration:
    """End-to-end integration tests with Linter."""

    def test_valid_plugin_mcp_passes_in_linter(self, tmp_path: Path) -> None:
        repo = _copy_fixture("valid-plugin", tmp_path)
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        findings = Linter(context, config=config).run()
        mcp_findings = [
            f for f in findings if f.rule_id in ("antigravity-mcp-valid", "mcp-valid-json")
        ]
        assert mcp_findings == []

    def test_valid_project_mcp_passes_in_linter(self, tmp_path: Path) -> None:
        repo = _copy_fixture("project-repo", tmp_path)
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        findings = Linter(context, config=config).run()
        mcp_findings = [
            f for f in findings if f.rule_id in ("antigravity-mcp-valid", "mcp-valid-json")
        ]
        assert mcp_findings == []

    def test_invalid_url_detected_and_shape_deferred(self, tmp_path: Path) -> None:
        repo = _copy_fixture("project-repo", tmp_path)
        mcp_file = repo / ".agents" / "mcp_config.json"
        mcp_file.write_text(
            json.dumps({"mcpServers": {"my-remote": {"url": "https://example.com/sse"}}}),
            encoding="utf-8",
        )
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        findings = Linter(context, config=config).run()

        # antigravity-mcp-valid catches the invalid url field
        ag_findings = [f for f in findings if f.rule_id == "antigravity-mcp-valid"]
        assert len(ag_findings) == 1
        assert (
            ag_findings[0].message
            == "MCP server 'my-remote' uses unsupported 'url'; Antigravity requires 'serverUrl'"
        )

        # mcp-valid-json deferred shape checking, so no duplicate/irrelevant findings
        shared_findings = [f for f in findings if f.rule_id == "mcp-valid-json"]
        assert shared_findings == []
