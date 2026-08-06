"""Lint-tree routing for Agent Plugins MCP documents across ``--type`` modes.

The AgentPluginMcpBlock tree role is deliberately ``--type``-invariant while
the dedicated agent-plugin-mcp-valid rule is gated on
``RepositoryType.AGENT_PLUGIN``. These tests pin the resulting invariant: an
invalid ``mcp.json`` in a dual-format package is reported by exactly one rule
under ANY ``--type`` — no findings lost, no duplicates.
"""

from typing import Optional, Set

from skillsaw.blocks import AgentPluginMcpBlock, McpBlock
from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.linter import Linter

from ._helpers import copy_fixture

MCP_VALIDATION_RULES = {"mcp-valid-json", "agent-plugin-mcp-valid"}


def _mcp_validation_findings(repo, repo_types: Optional[Set[RepositoryType]] = None):
    """Run the full default rule set and keep only MCP-validity findings.

    Deliberately not ``lint_rules``: passing ``rule_ids`` force-enables the
    requested rules and would bypass the repo-type gating this invariant is
    about.
    """
    context = RepositoryContext(repo, repo_types=repo_types)
    config = LinterConfig.default()
    # Tests describe the branch's complete rule set, independently of the
    # installed package version used to create the virtual environment.
    config.version = "99.0.0"
    findings = Linter(context, config=config).run()
    return [finding for finding in findings if finding.rule_id in MCP_VALIDATION_RULES]


class TestDualPackageMcpValidationAcrossTypes:
    """Invalid mcp.json (with a .mcp.json symlink at it) always surfaces once."""

    def test_forced_codex_type_reports_via_generic_rule(self, tmp_path):
        repo = copy_fixture("agent-plugins/dual-codex-broken-mcp", tmp_path)
        assert (repo / ".mcp.json").is_symlink()

        findings = _mcp_validation_findings(repo, repo_types={RepositoryType.CODEX_PLUGIN})

        assert len(findings) == 1
        assert findings[0].rule_id == "mcp-valid-json"
        assert "invalid json" in findings[0].message.lower()

    def test_auto_detected_dual_package_reports_via_dedicated_rule(self, tmp_path):
        repo = copy_fixture("agent-plugins/dual-codex-broken-mcp", tmp_path)

        findings = _mcp_validation_findings(repo)

        assert len(findings) == 1
        assert findings[0].rule_id == "agent-plugin-mcp-valid"
        assert "invalid json" in findings[0].message.lower()

    def test_forced_agent_plugin_type_reports_via_dedicated_rule(self, tmp_path):
        repo = copy_fixture("agent-plugins/dual-codex-broken-mcp", tmp_path)

        findings = _mcp_validation_findings(repo, repo_types={RepositoryType.AGENT_PLUGIN})

        assert len(findings) == 1
        assert findings[0].rule_id == "agent-plugin-mcp-valid"
        assert "invalid json" in findings[0].message.lower()


def test_distinct_native_and_portable_mcp_files_each_get_one_block(tmp_path):
    """.mcp.json that is NOT the portable mcp.json keeps its own parser role.

    The symlink-shared case collapses to one AgentPluginMcpBlock; two distinct
    real files are two executable surfaces and must yield exactly two blocks
    with correct file attribution.
    """
    repo = copy_fixture("agent-plugins/dual-codex-distinct-mcp", tmp_path)
    assert not (repo / ".mcp.json").is_symlink()
    context = RepositoryContext(repo)

    blocks = context.lint_tree.find(McpBlock)
    assert len(blocks) == 2

    portable = [block for block in blocks if isinstance(block, AgentPluginMcpBlock)]
    native = [block for block in blocks if not isinstance(block, AgentPluginMcpBlock)]
    assert len(portable) == 1
    assert portable[0].path == repo / "mcp.json"
    assert len(native) == 1
    assert native[0].path == repo / ".mcp.json"
