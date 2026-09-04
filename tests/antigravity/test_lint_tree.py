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
    CursorMcpBlock,
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

    def test_plugin_mcp_keeps_its_parser_when_shared_with_cursor(self, tmp_path: Path) -> None:
        from tests.cli_runner import run_cli

        repo = copy_fixture("antigravity/shared-plugin-hooks", tmp_path)
        plugin = repo / ".agents/plugins/berth-tools"
        mcp = plugin / "mcp_config.json"
        cursor = repo / ".cursor"
        cursor.mkdir(exist_ok=True)
        (cursor / "mcp.json").symlink_to(mcp)

        tree = tree_for(repo)
        assert len(tree.find(CursorMcpBlock)) == 1
        blocks = tree.find(AntigravityMcpBlock)
        assert len(blocks) == 1
        assert blocks[0].plugin_owner == plugin
        assert blocks[0].server_names == {"berth-status"}

        mcp.write_text('{"mcpServers": {"berth-status": {"args": "ready"}}}', encoding="utf-8")
        result = run_cli(
            [
                "lint",
                str(repo),
                "--rule",
                "antigravity-mcp-valid",
                "--format",
                "json",
                "--fail-on",
                "warning",
            ]
        )
        assert result.returncode == 1
        findings = json.loads(result.stdout)["violations"]
        assert len(findings) == 1
        assert findings[0]["rule_id"] == "antigravity-mcp-valid"
        assert "'args'" in findings[0]["message"]


class TestTheNonDotRootsNeedAMarker:
    """``_agents/`` and ``_agent/`` are ordinary source-package names too."""

    def _package_rules(self, repo: Path, root_name: str) -> Path:
        rules = repo / "src" / root_name / "rules"
        rules.mkdir(parents=True)
        (rules / "scheduling.md").write_text(
            "# Scheduling\n\nA published timetable row is superseded, never edited.\n",
            encoding="utf-8",
        )
        return rules / "scheduling.md"

    @pytest.mark.parametrize("root_name", ("_agents", "_agent"))
    def test_a_marked_root_attaches_its_prose(self, tmp_path: Path, root_name: str) -> None:
        repo = write_repo(tmp_path / f"marked-{root_name.lstrip('_')}")
        prose = self._package_rules(repo, root_name)
        (repo / "src" / root_name / "hooks.json").write_text("{}", encoding="utf-8")
        assert [b.path for b in tree_for(repo).find(AntigravityRuleBlock)] == [prose]

    @pytest.mark.parametrize("root_name", ("_agents", "_agent"))
    def test_a_source_package_of_the_same_name_attaches_nothing(
        self, tmp_path: Path, root_name: str
    ) -> None:
        """No hooks file, no MCP file, no registry — a populated ``rules/``
        is the only thing here, and on its own it is not this host."""
        repo = write_repo(tmp_path / f"plain-{root_name.lstrip('_')}")
        self._package_rules(repo, root_name)
        assert tree_for(repo).find(AntigravityRuleBlock) == []

    @pytest.mark.parametrize("root_name", (".agents", ".agent"))
    def test_a_dot_root_attaches_without_a_second_marker(
        self, tmp_path: Path, root_name: str
    ) -> None:
        """The gate is the two non-dot names only; a dot root is claimed by
        nothing else, so its established behaviour is unchanged."""
        repo = write_repo(tmp_path / f"dot-{root_name.lstrip('.')}")
        prose = self._package_rules(repo, root_name)
        assert [b.path for b in tree_for(repo).find(AntigravityRuleBlock)] == [prose]

    def test_an_instruction_named_file_under_an_unmarked_root_still_attaches(
        self, tmp_path: Path
    ) -> None:
        """The sweep must not yield to an owner the gate will not produce.

        ``AGENTS.md`` under an ordinary package's ``_agents/rules/`` was an
        ``InstructionBlock`` before Antigravity existed, and it stays one.
        """
        from skillsaw.blocks import AgentsMdBlock

        repo = write_repo(tmp_path / "sweep-unmarked")
        rules = repo / "src" / "_agents" / "rules"
        rules.mkdir(parents=True)
        authored = rules / "AGENTS.md"
        authored.write_text(
            "# Package rules\n\nNever widen `route_id` past 32 bytes.\n", encoding="utf-8"
        )
        tree = tree_for(repo)
        assert [b.path for b in tree.find(AgentsMdBlock) if b.path == authored] == [authored]
        assert tree.find(AntigravityRuleBlock) == []

    def test_the_same_file_under_a_marked_root_is_antigravity_prose(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "sweep-marked")
        root = repo / "src" / "_agents"
        rules = root / "rules"
        rules.mkdir(parents=True)
        authored = rules / "AGENTS.md"
        authored.write_text(
            "# Package rules\n\nNever widen `route_id` past 32 bytes.\n", encoding="utf-8"
        )
        (root / "hooks.json").write_text("{}", encoding="utf-8")
        assert [b.path for b in tree_for(repo).find(AntigravityRuleBlock)] == [authored]


class TestDescriptionRoutingActivation:
    """The rule gates on ``repo_types``, so attaching the block is not enough."""

    def test_a_plugin_agent_earns_the_routing_finding(self, tmp_path: Path) -> None:
        from skillsaw.linter import Linter

        repo = write_repo(tmp_path / "routing-agent")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        agents = plugin / "agents"
        agents.mkdir()
        (agents / "helper.md").write_text(
            "---\nname: helper\ndescription: A helper agent\n---\n\n"
            "# Helper\n\nRead the berth allocation and report what it changes.\n",
            encoding="utf-8",
        )

        found = [
            v
            for v in Linter(RepositoryContext(repo)).run()
            if v.rule_id == "content-description-routing"
        ]

        assert [v.file_path for v in found] == [agents / "helper.md"] * len(found)
        assert found

    def test_a_plugin_skill_earns_it_too(self, tmp_path: Path) -> None:
        from skillsaw.linter import Linter

        repo = write_repo(tmp_path / "routing-skill")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        skill = plugin / "skills" / "berth-audit"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: berth-audit\ndescription: Berth audit\n---\n\n"
            "# Berth audit\n\nRead the allocation and report what it changes.\n",
            encoding="utf-8",
        )

        found = [
            v
            for v in Linter(RepositoryContext(repo)).run()
            if v.rule_id == "content-description-routing"
        ]

        assert [v.file_path for v in found] == [skill / "SKILL.md"] * len(found)
        assert found

    def test_the_workspace_agent_block_stays_out_of_the_traversal(self, tmp_path: Path) -> None:
        """Activation, not traversal: ``<root>/agents/*.md`` is unmeasured."""
        from skillsaw.linter import Linter

        repo = write_repo(tmp_path / "routing-workspace")
        agents = repo / ".agents" / "agents"
        agents.mkdir(parents=True)
        (agents / "helper.md").write_text(
            "---\nname: helper\ndescription: A helper agent\n---\n\n"
            "# Helper\n\nRead the berth allocation and report what it changes.\n",
            encoding="utf-8",
        )

        found = [
            v
            for v in Linter(RepositoryContext(repo)).run()
            if v.rule_id == "content-description-routing"
        ]

        assert found == []


class TestApmDoesNotSuppressAuthoredRules:
    """A Codex target converges *skills* on ``.agents/``, never ``rules/``."""

    def _apm_repo(self, tmp_path: Path, name: str) -> Path:
        repo = write_repo(tmp_path / name)
        (repo / "apm.yml").write_text(
            "name: ferrymark\nversion: 0.1.0\ntargets:\n  - codex\n", encoding="utf-8"
        )
        source = repo / ".apm" / "instructions"
        source.mkdir(parents=True)
        (source / "scheduling.instructions.md").write_text(
            "---\napplyTo: '**'\n---\n\n# Scheduling\n\nRun `make test` before pushing.\n",
            encoding="utf-8",
        )
        return repo

    def test_authored_rules_are_not_content_suppressed(self, tmp_path: Path) -> None:
        repo = self._apm_repo(tmp_path, "apm-codex")
        rules = repo / ".agents" / "rules"
        rules.mkdir(parents=True)
        authored = rules / "berths.md"
        authored.write_text("# Berths\n\nNever widen `route_id` past 32 bytes.\n", encoding="utf-8")
        blocks = [b for b in tree_for(repo).find(AntigravityRuleBlock) if b.path == authored]
        assert len(blocks) == 1
        assert blocks[0].content_suppressed is False

    def test_a_converged_skill_under_the_same_root_is_still_held_back(self, tmp_path: Path) -> None:
        """What the ``.agents`` → ``codex`` mapping is really for.

        A skill APM converges on ``.agents/skills/`` is dropped by skill
        *discovery*, which reads the compiled roots directly — so the rules
        glob was never what protected it, and dropping the flag there costs
        nothing here.
        """
        from skillsaw.blocks import SkillBlock

        repo = self._apm_repo(tmp_path, "apm-codex-skill")
        skill = repo / ".agents" / "skills" / "berth-audit"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: berth-audit\ndescription: Use when auditing a berth allocation change.\n"
            "---\n\n# Berth audit\n\nRun `make test`.\n",
            encoding="utf-8",
        )
        context = RepositoryContext(repo)
        assert context.apm_compiled_roots() == {repo / ".agents"}
        assert context.skills == []
        assert [b for b in build_lint_tree(context).find(SkillBlock)] == []


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
