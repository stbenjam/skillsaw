"""ZCode discovery, provenance and lint-tree attachment."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from skillsaw.blocks import (
    ClaudeHooksBlock,
    McpBlock,
    ZCodeAgentBlock,
    ZCodeCommandBlock,
    ZCodeConfigHooksBlock,
    ZCodeConfigMcpBlock,
    ZCodeInlineHooksBlock,
    ZCodeInlineMcpBlock,
    ZCodeMcpBlock,
    ZCodePluginHooksBlock,
)
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formats.zcode import lexically_escapes
from skillsaw.lint_target import (
    PluginNode,
    ZCodeMarketplaceConfigNode,
    ZCodePluginConfigNode,
    ZCodePluginNode,
)
from skillsaw.paths import marker_escapes, marker_manifest_is_contained

from ._helpers import copy_fixture, lint, rule_ids, write_json

MANIFEST = {"name": "tide-charts", "description": "Tide charts for the harbour."}


def _plugin(root: Path, name: str, manifest_dir: str = ".zcode-plugin") -> Path:
    plugin = root / "plugins" / name
    write_json(plugin / manifest_dir / "plugin.json", {**MANIFEST, "name": name})
    (plugin / "README.md").write_text(f"# {name}\n\nCharts the tides.\n")
    return plugin


class TestProvenance:
    def test_zcode_only_plugin_is_claimed_by_zcode_alone(self, tmp_path):
        plugin = _plugin(tmp_path, "tide-charts")
        context = RepositoryContext(tmp_path)
        assert context.provenance(plugin).ecosystems == frozenset({"zcode"})
        assert RepositoryType.ZCODE_PLUGIN in context.repo_types

    def test_dual_manifest_plugin_keeps_its_claude_claim(self, tmp_path):
        plugin = _plugin(tmp_path, "tide-charts")
        write_json(plugin / ".claude-plugin" / "plugin.json", MANIFEST)
        assert RepositoryContext(tmp_path).provenance(plugin).ecosystems == frozenset(
            {"claude", "zcode"}
        )

    def test_claude_fallback_manifest_is_not_zcode_evidence(self, tmp_path):
        """ZCode reads ``.claude-plugin/plugin.json`` too, but claiming it
        would put every Claude plugin under ZCode's rules."""
        plugin = _plugin(tmp_path, "tide-charts", manifest_dir=".claude-plugin")
        context = RepositoryContext(tmp_path)
        assert "zcode" not in context.provenance(plugin).ecosystems
        assert RepositoryType.ZCODE_PLUGIN not in context.repo_types

    def test_catalog_listing_claims_a_claude_only_plugin_for_zcode(self, tmp_path):
        _plugin(tmp_path, "tide-charts")
        listed = _plugin(tmp_path, "berth-notes", manifest_dir=".claude-plugin")
        write_json(
            tmp_path / "marketplace.json",
            {
                "name": "harbor",
                "plugins": [
                    {"name": "tide-charts", "source": "./plugins/tide-charts"},
                    {"name": "berth-notes", "source": "./plugins/berth-notes"},
                ],
            },
        )
        context = RepositoryContext(tmp_path)
        assert context.provenance(listed).ecosystems == frozenset({"claude", "zcode"})

    def test_escaping_marker_claims_nothing(self, tmp_path):
        outside = tmp_path / "outside"
        write_json(outside / "plugin.json", MANIFEST)
        plugin = tmp_path / "repo" / "plugins" / "tide-charts"
        plugin.mkdir(parents=True)
        os.symlink(outside, plugin / ".zcode-plugin")
        context = RepositoryContext(tmp_path / "repo")
        assert "zcode" not in context.provenance(plugin).ecosystems
        assert not context.zcode_plugins


class TestSharedMarkerHelpers:
    """The containment pair Codex, Grok and ZCode share."""

    def test_contained_manifest(self, tmp_path):
        write_json(tmp_path / ".zcode-plugin" / "plugin.json", MANIFEST)
        assert marker_manifest_is_contained(tmp_path, ".zcode-plugin", "plugin.json")
        assert not marker_escapes(tmp_path, ".zcode-plugin", "plugin.json")

    def test_symlinked_manifest_escapes(self, tmp_path):
        outside = write_json(tmp_path / "elsewhere.json", MANIFEST)
        plugin = tmp_path / "plugin"
        (plugin / ".zcode-plugin").mkdir(parents=True)
        os.symlink(outside, plugin / ".zcode-plugin" / "plugin.json")
        assert not marker_manifest_is_contained(plugin, ".zcode-plugin", "plugin.json")
        assert marker_escapes(plugin, ".zcode-plugin", "plugin.json")

    def test_no_marker_does_not_escape(self, tmp_path):
        assert not marker_manifest_is_contained(tmp_path, ".zcode-plugin", "plugin.json")
        assert not marker_escapes(tmp_path, ".zcode-plugin", "plugin.json")


@pytest.mark.parametrize(
    ("value", "escapes"),
    [
        ("./skills", False),
        ("skills/../commands", False),
        ("", False),
        ("../shared", True),
        ("skills/../../shared", True),
        ("/etc/zcode", True),
        ("C:\\plugins", True),
    ],
)
def test_lexically_escapes_matches_resolve_inside(value, escapes):
    assert lexically_escapes(value) is escapes


class TestCatalogEvidence:
    def test_root_marketplace_json_needs_a_zcode_plugin_in_the_repository(self, tmp_path):
        """``marketplace.json`` is a generic filename; alone it claims nothing."""
        write_json(tmp_path / "marketplace.json", {"name": "harbor", "plugins": []})
        context = RepositoryContext(tmp_path)
        assert RepositoryType.ZCODE_MARKETPLACE not in context.repo_types
        assert not context.lint_tree.find(ZCodeMarketplaceConfigNode)

    def test_claude_catalog_takes_precedence(self, tmp_path):
        """ZCode reads ``.claude-plugin/marketplace.json`` first, and that
        file is Claude's to lint."""
        _plugin(tmp_path, "tide-charts")
        write_json(tmp_path / "marketplace.json", {"name": "harbor", "plugins": []})
        write_json(
            tmp_path / ".claude-plugin" / "marketplace.json",
            {"name": "harbor", "owner": {"name": "Harbor"}, "plugins": []},
        )
        assert not RepositoryContext(tmp_path).zcode_marketplace_paths()

    def test_forced_type_checks_the_catalog_without_a_marker(self, tmp_path):
        write_json(tmp_path / "marketplace.json", {"name": "Not Valid", "plugins": []})
        context = RepositoryContext(tmp_path, repo_types={RepositoryType.ZCODE_MARKETPLACE})
        assert context.lint_tree.find(ZCodeMarketplaceConfigNode)

    def test_zcode_json_is_not_read(self, tmp_path):
        """ZCode also reads ``zcode.json``, but unrelated tools commit files
        with that name, so it is not evidence."""
        write_json(tmp_path / "zcode.json", {"hooks": {"Stop": []}})
        assert RepositoryType.ZCODE_PROJECT not in RepositoryContext(tmp_path).repo_types


class TestLintTree:
    def test_zcode_only_plugin_attaches_zcode_blocks(self, tmp_path):
        repo = copy_fixture("zcode/marketplace-clean", tmp_path)
        tree = RepositoryContext(repo).lint_tree
        assert {n.path.name for n in tree.find(ZCodePluginNode)} == {
            "release-notes",
            "standup-digest",
        }
        assert not tree.find(PluginNode)
        assert len(tree.find(ZCodePluginConfigNode)) == 2
        assert [b.path.parent.name for b in tree.find(ZCodePluginHooksBlock)] == ["hooks"]
        assert [b.path.name for b in tree.find(ZCodeMcpBlock) if type(b) is ZCodeMcpBlock] == [
            ".mcp.json"
        ]
        (inline,) = tree.find(ZCodeInlineMcpBlock)
        assert {s.name for s in inline.servers} == {"changelog"}

    def test_dual_manifest_plugin_keeps_claude_blocks_for_shared_files(self, tmp_path):
        repo = copy_fixture("zcode/dual-manifest", tmp_path)
        tree = RepositoryContext(repo).lint_tree
        hooks = {type(b).__name__: b.path.name for b in tree.find(ClaudeHooksBlock)}
        assert hooks == {"ClaudeHooksBlock": "hooks.json"}
        zcode_hooks = [b.path.name for b in tree.find(ZCodePluginHooksBlock)]
        assert zcode_hooks == ["zcode-session.json"]
        mcp = [type(b) for b in tree.find(McpBlock) if b.path.name == ".mcp.json"]
        assert mcp == [McpBlock]

    def test_inline_hooks_attach_to_the_manifest(self, tmp_path):
        repo = copy_fixture("zcode/plugin-broken", tmp_path)
        tree = RepositoryContext(repo).lint_tree
        (inline,) = tree.find(ZCodeInlineHooksBlock)
        assert inline.path.parts[-3:] == ("claude-hooks", ".zcode-plugin", "plugin.json")
        assert set(inline.events) == {"Stop"}

    def test_project_layer_attaches_commands_agents_skills_and_config(self, tmp_path):
        repo = copy_fixture("zcode/project-clean", tmp_path)
        context = RepositoryContext(repo)
        tree = context.lint_tree
        assert RepositoryType.ZCODE_PROJECT in context.repo_types
        assert [b.path.name for b in tree.find(ZCodeCommandBlock)] == ["sync.md"]
        assert [b.path.name for b in tree.find(ZCodeAgentBlock)] == ["migration-reviewer.md"]
        assert {p.name for p in context.skills} == {"migration-check", "api-contract"}
        (hooks,) = tree.find(ZCodeConfigHooksBlock)
        assert set(hooks.events) == {"PostToolUse", "Stop"}
        (mcp,) = tree.find(ZCodeConfigMcpBlock)
        assert {s.name for s in mcp.servers} == {"docs", "db"}

    def test_plugin_declared_skill_root_is_discovered(self, tmp_path):
        plugin = _plugin(tmp_path, "tide-charts")
        manifest = plugin / ".zcode-plugin" / "plugin.json"
        write_json(manifest, {**MANIFEST, "skills": "payload/skills"})
        skill = plugin / "payload" / "skills" / "tide-window"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: tide-window\ndescription: Finds the next safe tide window. "
            "Use when planning a berth move.\n---\n\nRead the tide table.\n"
        )
        assert skill in RepositoryContext(tmp_path).skills


class TestClaudeStandsDown:
    """The false positives ZCode's own marketplace produced before ZCode was an ecosystem."""

    def test_zcode_only_plugins_are_not_claude_plugins(self, tmp_path):
        repo = copy_fixture("zcode/marketplace-clean", tmp_path)
        report = lint(repo)
        assert report["rc"] == 0
        assert not {
            "claude-plugin-json-required",
            "claude-hooks-valid",
            "claude-marketplace-json-valid",
        } & rule_ids(report)


class TestContainmentAndPruning:
    def test_zcode_only_plugin_declares_a_containment_boundary(self, tmp_path):
        """ZCode rejects component paths that leave the plugin and scans its
        skills without following symlinks, so a ZCode-only package gets the
        boundary Grok-only and Codex packages get; a dual-manifest package
        keeps Claude's looser reading."""
        zcode_only = _plugin(tmp_path, "tide-charts")
        dual = _plugin(tmp_path, "berth-notes")
        write_json(dual / ".claude-plugin" / "plugin.json", MANIFEST)
        context = RepositoryContext(tmp_path)
        assert context.provenance(zcode_only).zcode_only
        assert context.contained_plugin_owning(zcode_only / "skills") == zcode_only.resolve()
        assert not context.provenance(dual).zcode_only
        assert context.contained_plugin_owning(dual / "skills") is None

    def test_excluding_the_catalog_keeps_skills_of_a_nested_zcode_plugin(self, tmp_path):
        """Dropping a catalog claim prunes only skills no active plugin owns."""
        outer = tmp_path / "packages" / "outer"
        inner = outer / "inner"
        write_json(inner / ".zcode-plugin" / "plugin.json", {"name": "inner"})
        skill = inner / "skills" / "berth-log"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: berth-log\ndescription: Logs berth moves. Use when a vessel "
            "changes berth.\n---\n\nAppend the move to the log.\n"
        )
        write_json(
            tmp_path / "marketplace.json",
            {"name": "harbor", "plugins": [{"name": "outer", "source": "./packages/outer"}]},
        )
        context = RepositoryContext(tmp_path)
        assert skill in context.skills
        # Narrowing an existing context is the path that prunes.
        context.exclude_patterns.append("marketplace.json")
        context.apply_excludes()
        assert outer.resolve() not in context._zcode_claim_set()
        assert skill in context.skills


def test_long_zcode_command_description_is_budgeted(tmp_path):
    command = tmp_path / ".zcode" / "commands" / "sync.md"
    command.parent.mkdir(parents=True)
    command.write_text("---\ndescription: " + "sync the branch " * 150 + "\n---\n\nSync.\n")
    found = [
        v
        for v in lint(tmp_path)["violations"]
        if v["rule_id"] == "context-budget" and "command-description" in v["message"]
    ]
    assert found and found[0]["file_path"].endswith("sync.md")


def test_live_plugin_roots_include_cursor_and_openclaw_plugins(tmp_path):
    """Every skill prune keeps skills of plugins any ecosystem still claims."""
    cursor = tmp_path / "plugins" / "cursor-tools"
    write_json(cursor / ".cursor-plugin" / "plugin.json", {"name": "cursor-tools"})
    openclaw = tmp_path / "plugins" / "claw-tools"
    write_json(openclaw / "openclaw.plugin.json", {"id": "claw-tools", "configSchema": {}})
    context = RepositoryContext(tmp_path)
    live = context._live_plugin_roots()
    assert set(context.cursor_plugin_roots()) <= live
    assert set(context.openclaw_plugin_roots()) <= live
    assert context.cursor_plugin_roots() and context.openclaw_plugin_roots()
