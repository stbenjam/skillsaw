"""Tests for Codex plugin and marketplace discovery and validation."""

import json
import shutil
from pathlib import Path

import pytest

from skillsaw.config import LinterConfig
from skillsaw.blocks import HooksBlock, McpBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.linter import Linter
from skillsaw.lint_target import CodexMarketplaceConfigNode, CodexPluginNode, SkillNode
from skillsaw.rules.builtin.codex.marketplace_json_valid import (
    CodexMarketplaceJsonValidRule,
)
from skillsaw.rules.builtin.codex.marketplace_registration import (
    CodexMarketplaceRegistrationRule,
)
from skillsaw.rules.builtin.codex.plugin_json_required import CodexPluginJsonRequiredRule
from skillsaw.rules.builtin.codex.plugin_json_valid import CodexPluginJsonValidRule

FIXTURES = Path(__file__).parent / "fixtures"


def copy_fixture(name: str, tmp_path: Path) -> Path:
    destination = tmp_path / name.replace("/", "_")
    shutil.copytree(FIXTURES / name, destination)
    return destination


def _messages(rule, repo: Path) -> list[str]:
    return [violation.message for violation in rule.check(RepositoryContext(repo))]


def test_codex_marketplace_discovery_builds_distinct_nodes(tmp_path):
    repo = copy_fixture("codex-marketplace/clean", tmp_path)
    context = RepositoryContext(repo)

    assert RepositoryType.CODEX_MARKETPLACE in context.repo_types
    assert RepositoryType.MARKETPLACE not in context.repo_types
    assert [path.name for path in context.codex_plugins] == ["research-helper"]
    assert len(context.lint_tree.find(CodexMarketplaceConfigNode)) == 1
    assert len(context.lint_tree.find(CodexPluginNode)) == 1
    assert len(context.lint_tree.find(SkillNode)) == 1
    assert len(context.lint_tree.find(HooksBlock)) == 1
    assert len(context.lint_tree.find(McpBlock)) == 1


def test_clean_codex_fixture_passes_codex_rules(tmp_path):
    repo = copy_fixture("codex-marketplace/clean", tmp_path)
    context = RepositoryContext(repo)

    for rule in (
        CodexPluginJsonRequiredRule(),
        CodexPluginJsonValidRule(),
        CodexMarketplaceJsonValidRule(),
        CodexMarketplaceRegistrationRule(),
    ):
        assert rule.check(context) == [], rule.rule_id


def test_codex_rules_auto_activate_without_claude_marketplace_rules(tmp_path):
    repo = copy_fixture("codex-marketplace/clean", tmp_path)
    linter = Linter(RepositoryContext(repo), LinterConfig.default())

    active_ids = {rule.rule_id for rule in linter.rules}
    assert "codex-plugin-json-valid" in active_ids
    assert "codex-marketplace-json-valid" in active_ids
    assert "marketplace-json-valid" not in active_ids


def test_codex_plugin_manifest_reports_identity_and_path_errors(tmp_path):
    repo = copy_fixture("codex-marketplace/clean", tmp_path)
    manifest = repo / "plugins" / "research-helper" / ".codex-plugin" / "plugin.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "Research Helper",
                "version": "latest",
                "description": "",
                "skills": "../outside",
                "interface": {"logo": "/tmp/logo.png"},
            }
        ),
        encoding="utf-8",
    )

    messages = _messages(CodexPluginJsonValidRule(), repo)
    assert any("required field 'description'" in message for message in messages)
    assert any("kebab-case" in message for message in messages)
    assert any("semver" in message for message in messages)
    assert any("skills must stay inside" in message for message in messages)
    assert any("interface.logo must be relative" in message for message in messages)


def test_codex_plugin_required_finds_component_only_plugin(tmp_path):
    repo = copy_fixture("codex-marketplace/clean", tmp_path)
    manifest = repo / "plugins" / "research-helper" / ".codex-plugin" / "plugin.json"
    manifest.unlink()

    messages = _messages(CodexPluginJsonRequiredRule(), repo)
    assert messages == ["Missing plugin.json"]


def test_codex_plugin_directory_without_manifest_activates_required_rule(tmp_path):
    (tmp_path / ".codex-plugin").mkdir()

    context = RepositoryContext(tmp_path)

    assert RepositoryType.CODEX_PLUGIN in context.repo_types
    assert _messages(CodexPluginJsonRequiredRule(), tmp_path) == ["Missing plugin.json"]


def test_legacy_codex_marketplace_directory_is_not_a_plugin(tmp_path):
    manifest_dir = tmp_path / ".codex-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "marketplace.json").write_text(
        json.dumps({"name": "legacy", "plugins": []}), encoding="utf-8"
    )

    context = RepositoryContext(tmp_path)

    assert RepositoryType.CODEX_PLUGIN not in context.repo_types
    assert context.codex_plugins == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({"source": "local", "path": "../escape"}, "must stay inside"),
        ({"source": "git-subdir", "url": "ftp://example.test/repo", "path": "./p"}, "Git URL"),
        (
            {
                "source": "npm",
                "package": "@example/plugin",
                "registry": "https://user@example.test/npm?token=secret",
            },
            "without credentials",
        ),
    ],
)
def test_codex_marketplace_rejects_unsafe_sources(tmp_path, source, expected):
    repo = copy_fixture("codex-marketplace/clean", tmp_path)
    marketplace = repo / ".agents" / "plugins" / "marketplace.json"
    data = json.loads(marketplace.read_text(encoding="utf-8"))
    data["plugins"][0]["source"] = source
    marketplace.write_text(json.dumps(data), encoding="utf-8")

    assert any(expected in message for message in _messages(CodexMarketplaceJsonValidRule(), repo))


def test_codex_marketplace_requires_policy_and_category(tmp_path):
    repo = copy_fixture("codex-marketplace/clean", tmp_path)
    marketplace = repo / ".agents" / "plugins" / "marketplace.json"
    data = json.loads(marketplace.read_text(encoding="utf-8"))
    data["plugins"][0].pop("policy")
    data["plugins"][0].pop("category")
    marketplace.write_text(json.dumps(data), encoding="utf-8")

    messages = _messages(CodexMarketplaceJsonValidRule(), repo)
    assert any("'policy' object" in message for message in messages)
    assert any("'category'" in message for message in messages)


def test_codex_marketplace_reports_unregistered_local_plugin(tmp_path):
    repo = copy_fixture("codex-marketplace/clean", tmp_path)
    plugin = repo / "plugins" / "unregistered"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "unregistered",
                "version": "1.0.0",
                "description": "A local plugin omitted from the marketplace",
            }
        ),
        encoding="utf-8",
    )

    messages = _messages(CodexMarketplaceRegistrationRule(), repo)
    assert messages == ["Codex plugin 'unregistered' not registered in marketplace.json"]
