"""Integration and unit tests for Antigravity builtin rules."""

import shutil
from pathlib import Path

import pytest

from skillsaw.blocks import (
    AntigravityConfigBlock,
    AntigravityHooksBlock,
    AntigravityMcpBlock,
    AntigravityMdBlock,
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
        # Must report invalid name pattern
        assert any("name" in m for m in messages)
        # Must report unexpected extra_unknown
        assert any("extra_unknown" in m for m in messages)
        # Must report invalid version
        assert any("version" in m for m in messages)
        # Must report invalid disabled
        assert any("disabled" in m for m in messages)

    def test_missing_plugin_json_reported(self, tmp_path: Path) -> None:
        repo = _copy_fixture("valid-plugin", tmp_path)
        (repo / "plugin.json").unlink()
        context = RepositoryContext(repo, repo_types={RepositoryType.ANTIGRAVITY_PLUGIN})
        config = LinterConfig.default()
        config.version = "99.0.0"
        findings = Linter(context, config=config).run()
        manifest_findings = [f for f in findings if f.rule_id == "antigravity-plugin-json-valid"]
        assert len(manifest_findings) >= 1
        assert "not found" in manifest_findings[0].message.lower() or "missing" in manifest_findings[0].message.lower()


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
        assert any("InvalidEvent" in m for m in messages)
        assert any("command" in m for m in messages)

    def test_extra_events_setting_permits_custom_event(self, tmp_path: Path) -> None:
        repo = tmp_path / "custom-hooks"
        repo.mkdir()
        (repo / "plugin.json").write_text(
            '{"name": "custom", "description": "test", "version": "1.0.0"}',
            encoding="utf-8",
        )
        (repo / "hooks.json").write_text(
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
        findings = Linter(context, config=config).run()
        config_findings = [f for f in findings if f.rule_id == "antigravity-config-json-valid"]
        assert config_findings == []

    def test_invalid_config_reported(self, tmp_path: Path) -> None:
        repo = _copy_fixture("project-repo", tmp_path)
        (repo / ".agents" / "skills.json").write_text(
            '{"unknown_field": 123, "entries": "not-a-list"}',
            encoding="utf-8",
        )
        context = RepositoryContext(repo)
        config = LinterConfig.default()
        config.version = "99.0.0"
        findings = Linter(context, config=config).run()
        config_findings = [f for f in findings if f.rule_id == "antigravity-config-json-valid"]
        assert len(config_findings) >= 1
        messages = [f.message for f in config_findings]
        assert any("unknown field" in m.lower() or "entries" in m for m in messages)


class TestAntigravityTreeStructure:
    """Test lint tree integration for Antigravity nodes and blocks."""

    def test_plugin_tree_hierarchy(self, tmp_path: Path) -> None:
        repo = _copy_fixture("valid-plugin", tmp_path)
        context = RepositoryContext(repo)
        tree = context.lint_tree

        # Root has AntigravityPluginConfigNode, HooksBlock, McpBlock
        manifest_nodes = tree.find(AntigravityPluginConfigNode)
        assert len(manifest_nodes) == 1
        assert manifest_nodes[0].path == repo / "plugin.json"

        hooks_blocks = tree.find(AntigravityHooksBlock)
        assert len(hooks_blocks) == 1
        assert hooks_blocks[0].path == repo / "hooks.json"

        mcp_blocks = tree.find(AntigravityMcpBlock)
        assert len(mcp_blocks) == 1
        assert mcp_blocks[0].path == repo / "mcp_config.json"

        # Skill is discovered and owned
        skills = tree.find(SkillNode)
        assert len(skills) == 1
        assert skills[0].plugin_owner == repo.resolve()

    def test_project_tree_hierarchy(self, tmp_path: Path) -> None:
        repo = _copy_fixture("project-repo", tmp_path)
        context = RepositoryContext(repo)
        tree = context.lint_tree

        # ANTIGRAVITY.md attached as AntigravityMdBlock
        instructions = tree.find(AntigravityMdBlock)
        assert len(instructions) == 1
        assert instructions[0].path == repo / "ANTIGRAVITY.md"

        # skills.json and plugins.json attached as AntigravityConfigBlock
        configs = tree.find(AntigravityConfigBlock)
        config_names = sorted(c.path.name for c in configs)
        assert config_names == ["plugins.json", "skills.json"]
