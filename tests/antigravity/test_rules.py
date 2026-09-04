"""Integration and unit tests for Antigravity builtin rules."""

import shutil
from pathlib import Path

import pytest

from skillsaw.blocks import (
    AntigravityConfigBlock,
    AntigravityHooksBlock,
    AntigravityMcpBlock,
    AntigravityRuleBlock,
    ClaudeHooksBlock,
    HooksBlock,
    InstructionBlock,
    McpBlock,
    SettingsBlock,
)
from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import AntigravityPluginConfigNode, AntigravityPluginNode, SkillNode
from skillsaw.linter import Linter

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "antigravity"


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    target = tmp_path / name
    shutil.copytree(FIXTURES_DIR / name, target)
    return target


class TestAntigravityPluginJsonValidRule:
    """Test antigravity-plugin-json-valid rule."""

    def test_valid_plugin_has_no_manifest_violations(self, tmp_path: Path) -> None:
        repo = _copy_fixture("valid-plugin", tmp_path)
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        findings = Linter(context, config=config).run()
        manifest_findings = [f for f in findings if f.rule_id == "antigravity-plugin-json-valid"]
        assert manifest_findings == []

    def test_invalid_plugin_reports_expected_errors(self, tmp_path: Path) -> None:
        repo = _copy_fixture("invalid-plugin", tmp_path)
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        findings = Linter(context, config=config).run()
        manifest_findings = [f for f in findings if f.rule_id == "antigravity-plugin-json-valid"]
        messages = [f.message for f in manifest_findings]
        assert set(messages) == {
            "plugin.json: unknown field 'extra_unknown'",
            "plugin.json: invalid plugin name 'Invalid Name!' (must contain only alphanumeric characters, dashes, or underscores)",
            "plugin.json: 'version' must be a non-empty string",
            "plugin.json: 'disabled' must be a boolean",
        }

    def test_missing_plugin_json_reported(self, tmp_path: Path) -> None:
        repo = _copy_fixture("valid-plugin", tmp_path)
        (repo / ".agents" / "plugins" / "valid-plugin" / "plugin.json").unlink()
        context = RepositoryContext(repo, repo_types={RepositoryType.ANTIGRAVITY_PLUGIN})
        config = LinterConfig.default()
        config.version = "99.0.0"
        findings = Linter(context, config=config).run()
        manifest_findings = [f for f in findings if f.rule_id == "antigravity-plugin-json-valid"]
        assert len(manifest_findings) == 1
        assert manifest_findings[0].message == "plugin.json: missing manifest file"


class TestAntigravityHooksValidRule:
    """Test antigravity-hooks-valid rule."""

    def test_valid_hooks_pass(self, tmp_path: Path) -> None:
        repo = _copy_fixture("valid-plugin", tmp_path)
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        findings = Linter(context, config=config).run()
        hooks_findings = [f for f in findings if f.rule_id == "antigravity-hooks-valid"]
        assert hooks_findings == []

    def test_invalid_hooks_report_errors(self, tmp_path: Path) -> None:
        repo = _copy_fixture("invalid-plugin", tmp_path)
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        findings = Linter(context, config=config).run()
        hooks_findings = [f for f in findings if f.rule_id == "antigravity-hooks-valid"]
        messages = [f.message for f in hooks_findings]
        assert set(messages) == {
            "hooks.json: hook 'bad-hook': unknown event 'InvalidEvent'",
            "hooks.json: hook 'bad-hook': PreToolUse[0]: invalid regex in 'matcher': unterminated character set at position 0",
            "hooks.json: hook 'bad-hook': PreToolUse[0]: hooks[0]: missing required field 'command'",
            "hooks.json: hook 'bad-hook': PreToolUse[0]: hooks[0]: unsupported handler type 'unsupported' (only 'command' is supported)",
        }

    def test_extra_events_setting_permits_custom_event(self, tmp_path: Path) -> None:
        repo = tmp_path / "custom-hooks"
        plugin_dir = repo / ".agents" / "plugins" / "custom"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(
            '{"name": "custom", "description": "test", "version": "1.0.0"}',
            encoding="utf-8",
        )
        (plugin_dir / "hooks.json").write_text(
            '{"my-hook": {"CustomLifecycleEvent": [{"command": "echo 1"}]}}',
            encoding="utf-8",
        )
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        config.rules["antigravity-hooks-valid"] = {
            "extra-events": ["CustomLifecycleEvent"],
        }
        findings = Linter(context, config=config).run()
        hooks_findings = [f for f in findings if f.rule_id == "antigravity-hooks-valid"]
        assert hooks_findings == []


class TestAntigravityConfigJsonValidRule:
    """Test antigravity-config-json-valid rule."""

    def test_valid_project_configs_pass(self, tmp_path: Path) -> None:
        repo = _copy_fixture("project-repo", tmp_path)
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        config.rules["antigravity-config-json-valid"] = {"enabled": True}
        findings = Linter(context, config=config).run()
        config_findings = [f for f in findings if f.rule_id == "antigravity-config-json-valid"]
        assert config_findings == []

    def test_invalid_config_reported(self, tmp_path: Path) -> None:
        repo = _copy_fixture("project-repo", tmp_path)
        (repo / ".agents" / "skills.json").write_text(
            '["not-a-dict"]',
            encoding="utf-8",
        )
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        config.rules["antigravity-config-json-valid"] = {"enabled": True}
        findings = Linter(context, config=config).run()
        config_findings = [f for f in findings if f.rule_id == "antigravity-config-json-valid"]
        assert len(config_findings) == 1
        assert config_findings[0].message == "skills.json: expected JSON object (mapping) at root"


class TestAntigravityTreeStructure:
    """Test lint tree integration for Antigravity nodes and blocks."""

    def test_plugin_tree_hierarchy(self, tmp_path: Path) -> None:
        repo = _copy_fixture("valid-plugin", tmp_path)
        plugin_dir = repo / ".agents" / "plugins" / "valid-plugin"
        context = RepositoryContext(repo)
        tree = context.lint_tree

        # Manifest, hooks, MCP blocks attached inside plugin container
        manifest_nodes = tree.find(AntigravityPluginConfigNode)
        assert len(manifest_nodes) == 1
        assert manifest_nodes[0].path == plugin_dir / "plugin.json"

        hooks_blocks = tree.find(AntigravityHooksBlock)
        assert len(hooks_blocks) == 1
        assert hooks_blocks[0].path == plugin_dir / "hooks.json"

        mcp_blocks = tree.find(AntigravityMcpBlock)
        assert len(mcp_blocks) == 1
        assert mcp_blocks[0].path == plugin_dir / "mcp_config.json"

        # Skill is discovered and owned
        skills = tree.find(SkillNode)
        assert len(skills) == 1
        assert skills[0].plugin_owner == plugin_dir.resolve()

    def test_project_tree_hierarchy(self, tmp_path: Path) -> None:
        repo = _copy_fixture("project-repo", tmp_path)
        context = RepositoryContext(repo)
        tree = context.lint_tree

        # my-rule.md attached as AntigravityRuleBlock
        rules = tree.find(AntigravityRuleBlock)
        assert len(rules) == 1
        assert rules[0].path == repo / ".agents" / "rules" / "my-rule.md"

        # skills.json and agents.json attached as AntigravityConfigBlock
        configs = tree.find(AntigravityConfigBlock)
        config_names = sorted(c.path.name for c in configs)
        assert config_names == ["agents.json", "skills.json"]

        # mcp_config.json attached as AntigravityMcpBlock
        mcp_blocks = tree.find(AntigravityMcpBlock)
        assert len(mcp_blocks) == 1
        assert mcp_blocks[0].path == repo / ".agents" / "mcp_config.json"

    def test_escaping_manifest_not_attached_as_config_node(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        plugin_dir = repo / ".agents" / "plugins" / "my-plugin"
        plugin_dir.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_manifest = outside / "plugin.json"
        outside_manifest.write_text('{"name": "outside"}', encoding="utf-8")
        (plugin_dir / "plugin.json").symlink_to(outside_manifest)

        context = RepositoryContext(repo)
        tree = context.lint_tree
        manifest_nodes = tree.find(AntigravityPluginConfigNode)
        assert manifest_nodes == []

    def test_settings_json_not_attached_to_antigravity_plugin(self, tmp_path: Path) -> None:
        repo = _copy_fixture("valid-plugin", tmp_path)
        plugin_dir = repo / ".agents" / "plugins" / "valid-plugin"
        (plugin_dir / "settings.json").write_text('{"setting": 1}', encoding="utf-8")
        (plugin_dir / "settings.local.json").write_text('{"setting": 2}', encoding="utf-8")

        context = RepositoryContext(repo)
        tree = context.lint_tree
        settings_blocks = tree.find(SettingsBlock)
        assert settings_blocks == []

    def test_claude_hooks_and_mcp_class_selection_by_provenance(self, tmp_path: Path) -> None:
        repo = _copy_fixture("valid-plugin", tmp_path)
        plugin_dir = repo / ".agents" / "plugins" / "valid-plugin"
        hooks_dir = plugin_dir / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "hooks.json").write_text("{}", encoding="utf-8")
        (plugin_dir / ".mcp.json").write_text("{}", encoding="utf-8")

        context = RepositoryContext(repo)
        tree = context.lint_tree
        # Without Claude provenance, fallback to HooksBlock and McpBlock
        hooks_blocks = [b for b in tree.find(HooksBlock) if b.path == hooks_dir / "hooks.json"]
        assert len(hooks_blocks) == 1
        assert type(hooks_blocks[0]) is HooksBlock

        # When Claude provenance is present
        claude_dir = plugin_dir / ".claude-plugin"
        claude_dir.mkdir()
        (claude_dir / "plugin.json").write_text('{"name": "claude-valid"}', encoding="utf-8")

        context_dual = RepositoryContext(repo)
        tree_dual = context_dual.lint_tree
        claude_hooks = [
            b for b in tree_dual.find(ClaudeHooksBlock) if b.path == hooks_dir / "hooks.json"
        ]
        assert len(claude_hooks) == 1

    def test_editor_globs_nested_rules(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        agents_rules_sub = repo / ".agents" / "rules" / "nested" / "sub"
        agents_rules_sub.mkdir(parents=True)
        rule1 = agents_rules_sub / "rule1.md"
        rule1.write_text("# Rule 1\nSome rule content.", encoding="utf-8")

        agent_rules_sub = repo / ".agent" / "rules"
        agent_rules_sub.mkdir(parents=True)
        rule2 = agent_rules_sub / "rule2.md"
        rule2.write_text("# Rule 2\nSome other rule content.", encoding="utf-8")

        context = RepositoryContext(repo)
        tree = context.lint_tree

        rules = tree.find(AntigravityRuleBlock)
        rule_paths = {r.path for r in rules}
        assert rule1 in rule_paths
        assert rule2 in rule_paths

        # Ensure they are attached as AntigravityRuleBlock, not bare InstructionBlock
        instructions = tree.find(InstructionBlock)
        bare_instructions = [i for i in instructions if type(i) is InstructionBlock]
        assert bare_instructions == []
