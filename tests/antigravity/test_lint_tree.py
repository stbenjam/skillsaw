"""What the lint tree attaches for Antigravity, and which rules reach it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillsaw.blocks import (
    AntigravityAgentBlock,
    AntigravityRuleBlock,
    CommandBlock,
    PluginRuleBlock,
)
from skillsaw.blocks.json_config import (
    AntigravityConfigBlock,
    AntigravityHooksBlock,
    AntigravityMcpBlock,
)
from skillsaw.context import RepositoryContext
from skillsaw.formats.antigravity import ANTIGRAVITY_CONFIG_DIR_NAMES, REGISTRY_FILENAMES
from skillsaw.lint_target import AntigravityPluginConfigNode, AntigravityPluginNode
from skillsaw.lint_tree import build_lint_tree

from ._helpers import copy_fixture, run_rule, write_plugin, write_repo


def tree_for(repo: Path):
    return build_lint_tree(RepositoryContext(repo))


class TestWorkspaceAttachment:
    """Every customization root contributes its whole content set."""

    @pytest.mark.parametrize("root_name", ANTIGRAVITY_CONFIG_DIR_NAMES)
    def test_configuration_files(self, tmp_path: Path, root_name: str) -> None:
        repo = write_repo(tmp_path / f"attach-{root_name.lstrip('._')}")
        root = repo / root_name
        root.mkdir()
        (root / "hooks.json").write_text("{}", encoding="utf-8")
        (root / "mcp_config.json").write_text('{"mcpServers": {}}', encoding="utf-8")
        for registry in REGISTRY_FILENAMES:
            (root / registry).write_text('{"entries": []}', encoding="utf-8")
        tree = tree_for(repo)
        assert [b.path for b in tree.find(AntigravityHooksBlock)] == [root / "hooks.json"]
        assert [b.path for b in tree.find(AntigravityMcpBlock)] == [root / "mcp_config.json"]
        assert sorted(b.path.name for b in tree.find(AntigravityConfigBlock)) == sorted(
            REGISTRY_FILENAMES
        )

    def test_rules_are_read_recursively(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "nested-rules")
        nested = repo / ".agents" / "rules" / "schedule"
        nested.mkdir(parents=True)
        (nested / "calendar.md").write_text("# Calendar\n\nRun `make test`.\n", encoding="utf-8")
        assert [b.path for b in tree_for(repo).find(AntigravityRuleBlock)] == [
            nested / "calendar.md"
        ]

    def test_agents_are_read_flat(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "agents")
        agents = repo / ".agents" / "agents"
        agents.mkdir(parents=True)
        (agents / "auditor.md").write_text(
            "---\nname: auditor\ndescription: Use when auditing a schedule change.\n---\n\n"
            "# Auditor\n\nRun `make test`.\n",
            encoding="utf-8",
        )
        assert [b.path for b in tree_for(repo).find(AntigravityAgentBlock)] == [
            agents / "auditor.md"
        ]

    def test_rules_json_is_not_attached(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "rules-json")
        write_repo(repo)
        (repo / ".agents").mkdir()
        (repo / ".agents" / "rules.json").write_text("[]", encoding="utf-8")
        assert tree_for(repo).find(AntigravityConfigBlock) == []


class TestRuleBlockCategory:
    """``rules/**/*.md`` is always-on prose and is budgeted as one."""

    def test_category_is_instruction(self) -> None:
        assert AntigravityRuleBlock.category == "instruction"

    def test_context_budget_reaches_an_oversized_rules_file(self, tmp_path: Path) -> None:
        from skillsaw.rules.builtin.context_budget.budget import ContextBudgetRule

        repo = write_repo(tmp_path / "budget")
        rules = repo / ".agents" / "rules"
        rules.mkdir(parents=True)
        body = "# Timetable\n\n" + (
            "A published timetable is immutable and every sailing keeps the "
            "departure date of its origin port.\n\n" * 900
        )
        (rules / "timetable.md").write_text(body, encoding="utf-8")
        reported = [v.file_path for v in run_rule(ContextBudgetRule, repo)]
        assert rules / "timetable.md" in reported

    def test_instruction_drift_reaches_a_duplicated_rules_file(self, tmp_path: Path) -> None:
        from skillsaw.rules.builtin.content.instruction_drift import ContentInstructionDriftRule

        repo = tmp_path / "drift"
        repo.mkdir()
        section = (
            "# Ferrymark\n\n## Conventions\n\n"
            "- A sailing is identified by `(route_id, departure_utc)` in that order, "
            "and departure times are stored in UTC and rendered in `Europe/Dublin`.\n"
            "- Every migration in `migrations/` is forward-only and carries a "
            "rollback note in its header comment.\n"
            "- HTTP handlers in `internal/api/` stay thin; allocation maths belongs "
            "in `internal/berth/`.\n"
        )
        (repo / "AGENTS.md").write_text(section, encoding="utf-8")
        rules = repo / ".agents" / "rules"
        rules.mkdir(parents=True)
        # One bullet has drifted: the copy still says local time.
        (rules / "conventions.md").write_text(
            section.replace("stored in UTC", "stored in local time"), encoding="utf-8"
        )
        assert run_rule(ContentInstructionDriftRule, repo)


class TestPluginAttachment:
    """A plugin's own files, and nothing another host's convention names."""

    def test_manifest_hooks_and_mcp(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "plugin")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        (plugin / "hooks.json").write_text("{}", encoding="utf-8")
        (plugin / "mcp_config.json").write_text('{"mcpServers": {}}', encoding="utf-8")
        tree = tree_for(repo)
        assert [n.path for n in tree.find(AntigravityPluginConfigNode)] == [plugin / "plugin.json"]
        assert [b.path for b in tree.find(AntigravityHooksBlock)] == [plugin / "hooks.json"]
        assert [b.path for b in tree.find(AntigravityMcpBlock)] == [plugin / "mcp_config.json"]
        assert [n.path for n in tree.find(AntigravityPluginNode)] == [plugin]

    def test_prose_components(self, tmp_path: Path) -> None:
        repo = copy_fixture("antigravity/workspace-clean", tmp_path)
        plugin = repo / ".agents" / "plugins" / "berth-tools"
        tree = tree_for(repo)
        assert [b.path for b in tree.find(CommandBlock)] == [
            plugin / "commands" / "berth-status.md"
        ]
        assert [b.path for b in tree.find(PluginRuleBlock)] == [plugin / "rules" / "berths.md"]

    def test_claude_conventional_files_are_not_attached(self, tmp_path: Path) -> None:
        """``agy`` reads neither ``hooks/hooks.json`` nor ``.mcp.json``."""
        from skillsaw.blocks import HooksBlock, McpBlock

        repo = write_repo(tmp_path / "claude-shaped")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        (plugin / "hooks").mkdir()
        (plugin / "hooks" / "hooks.json").write_text(
            json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}),
            encoding="utf-8",
        )
        (plugin / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
        tree = tree_for(repo)
        assert tree.find(HooksBlock) == []
        assert tree.find(McpBlock) == []

    def test_nothing_descends_into_a_plugin_from_the_workspace_walk(self, tmp_path: Path) -> None:
        """``plugins/`` belongs to plugin discovery, not to the rules glob."""
        repo = write_repo(tmp_path / "no-descent")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        (plugin / "rules").mkdir()
        (plugin / "rules" / "berths.md").write_text(
            "# Berths\n\nRun `make test`.\n", encoding="utf-8"
        )
        assert tree_for(repo).find(AntigravityRuleBlock) == []
