"""Native Cursor packages: CLI coverage and cross-ecosystem tree invariants."""

import json
from pathlib import Path

import pytest

from skillsaw.blocks import CursorRuleBlock, CursorCommandBlock, SkillBlock, HooksBlock, McpBlock
from skillsaw.blocks.cursor import CursorAgentBlock, CursorPluginBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rules.builtin.cursor.plugin_valid import CursorPluginValidRule
from skillsaw.rules.builtin.cursor.marketplace_valid import CursorMarketplaceValidRule
from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture


def test_cursor_native_components(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    context = RepositoryContext(repo)
    assert context.repo_type == RepositoryType.CURSOR_MARKETPLACE
    assert RepositoryType.MARKETPLACE not in context.repo_types
    tree = context.lint_tree
    for cls in (
        CursorRuleBlock,
        CursorCommandBlock,
        CursorAgentBlock,
        CursorPluginBlock,
    ):
        assert len(tree.find(cls)) == 1, cls
    assert len(tree.find(HooksBlock)) == 1
    assert len(tree.find(McpBlock)) == 2
    # Cursor loads capabilities/ only; the default skills/ it overrides
    # stays on the portable walk.
    plugin = repo / "packages/review"
    assert {b.path.parent for b in tree.find(SkillBlock)} == {
        plugin / "capabilities/review",
        plugin / "skills/ignored",
    }
    assert all("ignored" not in str(b.path) for b in tree.find(CursorCommandBlock))
    assert not CursorPluginValidRule().check(context)
    assert not CursorMarketplaceValidRule().check(context)


@pytest.mark.parametrize("forced", [RepositoryType.MARKETPLACE, RepositoryType.CURSOR_PLUGIN])
def test_cursor_provenance_survives_override(tmp_path, forced):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    context = RepositoryContext(repo, repo_types={forced})
    plugin = repo / "packages/review"
    assert context.provenance(plugin).ecosystems == frozenset({"cursor"})
    assert len(context.lint_tree.find(CursorRuleBlock)) == 1
    assert len(context.lint_tree.find(SkillBlock)) == 1


def test_cursor_forced_missing_manifest(tmp_path):
    context = RepositoryContext(tmp_path, repo_types={RepositoryType.CURSOR_PLUGIN})
    assert CursorPluginValidRule().check(context)


def test_cursor_component_escape(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.mdc").write_text("Do not read this outside the plugin.\n")
    (plugin / "guidance").rename(plugin / "old-guidance")
    (plugin / "guidance").symlink_to(outside, target_is_directory=True)
    context = RepositoryContext(repo)
    assert not context.lint_tree.find(CursorRuleBlock)
    assert CursorPluginValidRule().check(context)


def test_cursor_excluded_catalog_drops_claim(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    # Remove the standalone marker: only the catalog now claims the plugin.
    manifest = repo / "packages/review/.cursor-plugin/plugin.json"
    manifest.unlink()
    context = RepositoryContext(repo, exclude_patterns=[".cursor-plugin"])
    assert not context.cursor_plugin_roots()


def test_cursor_late_excludes_drop_catalog_only_skills(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    manifest = repo / "packages/review/.cursor-plugin/plugin.json"
    manifest.unlink()
    context = RepositoryContext(repo)
    assert context.cursor_plugin_roots()
    context.exclude_patterns.append(".cursor-plugin")
    context.apply_excludes()
    assert not context.cursor_plugin_roots()
    assert not context.lint_tree.find(CursorPluginBlock)
    assert not context.lint_tree.find(SkillBlock)


def test_cursor_dual_manifest_preserves_claude_scope(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin/plugin.json").write_text('{"name":"review"}')
    context = RepositoryContext(repo)
    assert context.provenance(plugin).ecosystems == frozenset({"claude", "cursor"})
    assert len(context.lint_tree.find(CursorPluginBlock)) == 1
    assert len(context.lint_tree.find(CursorRuleBlock)) == 1
    assert len(context.lint_tree.find(SkillBlock)) == 2


def test_cursor_default_and_root_skill(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    manifest = plugin / ".cursor-plugin/plugin.json"
    manifest.write_text('{"name":"review"}')
    context = RepositoryContext(plugin)
    # capabilities/ is no longer declared, so it is portable content only.
    assert context.skills == [plugin / "capabilities/review", plugin / "skills/ignored"]
    # With no default directory, use the root skill.
    (plugin / "skills").rename(plugin / "unused-skills")
    (plugin / "SKILL.md").write_text((plugin / "capabilities/review/SKILL.md").read_text())
    context = RepositoryContext(plugin)
    assert context.skills == [plugin]
    manifest.write_text('{"name":"review","skills":[]}')
    from skillsaw.utils import invalidate_read_caches

    invalidate_read_caches(manifest)
    # Cursor loads no skills, but the root SKILL.md is still a portable skill.
    assert RepositoryContext(plugin).skills == [plugin]


def test_cursor_nested_marketplace_and_excluded_component(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    context = RepositoryContext(tmp_path, exclude_patterns=["**/guidance"])
    assert context.cursor_marketplace_paths() == [repo / ".cursor-plugin/marketplace.json"]
    assert not context.lint_tree.find(CursorRuleBlock)
    assert len(context.lint_tree.find(CursorAgentBlock)) == 1


@pytest.mark.parametrize(
    "payload, expected",
    [
        ("[]", "expected a JSON object"),
        ("{", "Invalid Cursor manifest:"),
        ('{"name":null}', "name:"),
        ('{"name":"ok","variables":{"type":"string"}}', "variables.type:"),
    ],
)
def test_cursor_malformed_manifest(tmp_path, payload, expected):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    manifest = plugin / ".cursor-plugin/plugin.json"
    manifest.write_text(payload)
    findings = CursorPluginValidRule().check(RepositoryContext(plugin))
    assert any(v.file_path == manifest and expected in v.message for v in findings)


def test_cursor_inline_mcp_array_keeps_every_server(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    path = repo / "packages/review/.cursor-plugin/plugin.json"
    data = json.loads(path.read_text())
    data["mcpServers"] = [{"one": {"command": "first"}}, {"two": {"command": "second"}}]
    path.write_text(json.dumps(data))
    blocks = RepositoryContext(repo).lint_tree.find(McpBlock)
    assert {s.name for block in blocks for s in block.servers} == {"one", "two"}


def test_cursor_project_agents_detected_without_other_components(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    project = tmp_path / "project"
    directory = project / ".cursor/agents"
    directory.mkdir(parents=True)
    (directory / "review.md").write_text(
        (repo / "packages/review/reviewers/security.markdown").read_text()
    )
    context = RepositoryContext(project)
    assert RepositoryType.CURSOR in context.repo_types
    assert len(context.lint_tree.find(CursorAgentBlock)) == 1


def test_cursor_catalog_inline_hooks_keep_source_location(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    context = RepositoryContext(repo)
    hooks = context.lint_tree.find(HooksBlock)
    assert hooks[0].path == repo / ".cursor-plugin/marketplace.json"


@pytest.mark.parametrize(
    "source", ["C:\\outside", "../outside", "/outside", "https://example.com/repo.git"]
)
def test_cursor_source_containment_and_remote_sources(tmp_path, source):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    catalog = repo / ".cursor-plugin/marketplace.json"
    catalog.write_text(
        json.dumps({"name": "catalog", "plugins": [{"name": "one", "source": source}]})
    )
    findings = CursorMarketplaceValidRule().check(RepositoryContext(repo))
    assert bool(findings) == (not source.startswith("https://"))


def test_cursor_missing_sources_truncate_long_lists(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    catalog = repo / ".cursor-plugin/marketplace.json"
    plugins = [{"name": f"plugin-{i}", "source": f"missing-{i}"} for i in range(8)]
    catalog.write_text(json.dumps({"name": "catalog", "plugins": plugins}))
    findings = CursorMarketplaceValidRule().check(RepositoryContext(repo))
    assert [v.message for v in findings] == [
        "8 plugin entries have no local plugin directory: 'plugin-0', 'plugin-1', "
        "'plugin-2', 'plugin-3', 'plugin-4', and 3 more; point each source at an "
        "existing directory inside this marketplace"
    ]


def test_cursor_inline_claude_format_hooks_report_once(tmp_path):
    from skillsaw.rules.builtin.cursor.hooks_valid import CursorHooksValidRule

    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    catalog = repo / ".cursor-plugin/marketplace.json"
    data = json.loads(catalog.read_text())
    group = {"matcher": "Bash", "hooks": [{"type": "command", "command": "./check.sh"}]}
    data["plugins"][0]["hooks"] = {"hooks": {"PreToolUse": [group, group]}}
    catalog.write_text(json.dumps(data))
    findings = CursorHooksValidRule().check(RepositoryContext(repo))
    assert [v.message for v in findings] == [
        "Hooks use Claude Code's format (matcher groups nesting a 'hooks' array), "
        "not Cursor's; rewrite each hook as {command, matcher?} directly under a Cursor event"
    ]


def test_cursor_plugin_mcp_duplicate_keys_keep_last_value(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    path = repo / "packages/review/config/mcp.json"
    path.write_text('{"mcpServers":{"local":{"command":"old","command":"new"}}}')
    blocks = RepositoryContext(repo).lint_tree.find(McpBlock)
    block = next(b for b in blocks if b.path == path)
    assert block.parse_error is None
    assert block.servers[0].command == "new"


def test_cursor_prefix_cannot_hide_absolute_source(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    path = repo / ".cursor-plugin/marketplace.json"
    data = json.loads(path.read_text())
    data["plugins"][0]["source"] = "/review"
    path.write_text(json.dumps(data))
    assert CursorMarketplaceValidRule().check(RepositoryContext(repo))


def test_cursor_readme_cannot_escape_plugin(tmp_path):
    from skillsaw.blocks import ReadmeBlock

    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    other = repo / "outside.md"
    other.write_text("Outside the plugin boundary.\n")
    (repo / "packages/review/README.md").symlink_to(other)
    assert not RepositoryContext(repo).lint_tree.find(ReadmeBlock)


def test_non_cursor_skill_discovery_preserves_order(tmp_path):
    context = RepositoryContext(tmp_path)
    discovered = [tmp_path / "z-first", tmp_path / "a-second"]
    assert context._filter_cursor_skills(iter(discovered)) == discovered


@pytest.mark.parametrize("kind", ["plugin", "marketplace"])
def test_cursor_metadata_is_forward_compatible(kind):
    from skillsaw.formats.cursor_schema import validator

    schema = validator(kind).schema

    def assert_open(value):
        if isinstance(value, dict):
            assert value.get("additionalProperties") is not False
            for child in value.values():
                assert_open(child)
        elif isinstance(value, list):
            for child in value:
                assert_open(child)

    assert_open(schema)
    for author in ("A Team", {"name": "A Team", "url": "custom:team", "email": ""}):
        plugin = {
            "name": "sample",
            "author": author,
            "repository": {"type": "git", "url": "git@example.com:team/repo"},
            "futureMetadata": {"extra": True},
        }
        data = (
            plugin
            if kind == "plugin"
            else {
                "name": "catalog",
                "owner": author,
                "plugins": [{**plugin, "source": "./sample"}],
            }
        )
        assert not list(validator(kind).iter_errors(data))


def test_cursor_inline_payload_identity_and_accounting(tmp_path):
    from skillsaw.blocks.cursor import CursorInlineHooksBlock, CursorInlineMcpBlock
    from skillsaw.blocks.json_config import _inline_payload_token_count

    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    manifest = repo / "packages/review/.cursor-plugin/plugin.json"
    data = json.loads(manifest.read_text())
    data["mcpServers"] = [{"one": {"command": "first"}}, {"two": {"command": "second"}}]
    data["unrelated"] = "x" * 10000
    manifest.write_text(json.dumps(data))
    tree = RepositoryContext(repo).lint_tree
    blocks = tree.find(CursorInlineMcpBlock)
    assert len(set(blocks)) == 2
    assert blocks[0] != blocks[1]
    for block in [*blocks, *tree.find(CursorInlineHooksBlock)]:
        assert block.estimate_tokens() == _inline_payload_token_count(block.inline_data)
        assert block.estimate_tokens() < 100
        assert not block.has_utf8_bom()
        assert "inline Cursor" in block.tree_label()


@pytest.mark.parametrize("part", ["source", "prefix"])
@pytest.mark.parametrize("spelling", ["absolute", "traversal", "symlink"])
def test_cursor_rejects_existing_escaped_sources(tmp_path, part, spelling):
    from skillsaw.formats.cursor import source_path

    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "review").mkdir()
    (repo / "escape").symlink_to(outside, target_is_directory=True)
    value = {"absolute": str(outside), "traversal": "../outside", "symlink": "escape"}[spelling]
    prefix, source = (value, "review") if part == "prefix" else ("", value)
    assert source_path(repo, prefix, source) is None
    catalog = repo / ".cursor-plugin/marketplace.json"
    catalog.write_text(
        json.dumps(
            {
                "name": "catalog",
                "metadata": {"pluginRoot": prefix},
                "plugins": [{"name": "escaped", "source": source}],
            }
        )
    )
    findings = CursorMarketplaceValidRule().check(RepositoryContext(repo))
    assert any(v.file_path == catalog and "inside this marketplace" in v.message for v in findings)


def test_cursor_glob_cannot_attach_symlinked_file(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    outside = tmp_path / "secret.mdc"
    outside.write_text("Private guidance outside the plugin.\n")
    guidance = repo / "packages/review/guidance"
    (guidance / "escape.mdc").symlink_to(outside)
    blocks = RepositoryContext(repo).lint_tree.find(CursorRuleBlock)
    assert len(blocks) == 1
    assert all(b.path.name != "escape.mdc" for b in blocks)


def test_cursor_bad_manifest_still_checks_catalog_components(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    (repo / "packages/review/.cursor-plugin/plugin.json").write_text("{")
    findings = CursorPluginValidRule().check(RepositoryContext(repo))
    catalog = repo / ".cursor-plugin/marketplace.json"
    assert any(v.file_path == catalog and "catalog-commands" in v.message for v in findings)


@pytest.mark.parametrize("payload", ['{"name":"catalog","plugins":false}', "{", "[]"])
def test_cursor_size_limit_independent_of_entry_shape(tmp_path, payload):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    catalog = repo / ".cursor-plugin/marketplace.json"
    catalog.write_text(payload + " " * (10 * 1024 * 1024))
    findings = CursorMarketplaceValidRule().check(RepositoryContext(repo))
    assert any("10 MB" in v.message for v in findings)


@pytest.mark.parametrize(
    "marker, ecosystem", [(".codex-plugin", "codex"), (".grok-plugin", "grok")]
)
def test_cursor_late_excludes_preserve_forced_other_claim(tmp_path, marker, ecosystem):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    (plugin / marker).mkdir()
    (plugin / marker / "plugin.json").write_text('{"name":"review"}')
    manifest = plugin / ".cursor-plugin/plugin.json"
    data = json.loads(manifest.read_text())
    data["skills"] = "skills"
    manifest.write_text(json.dumps(data))
    catalog = repo / (
        ".agents/plugins/other.json" if ecosystem == "codex" else ".grok-plugin/marketplace.json"
    )
    catalog.parent.mkdir(parents=True)
    source = (
        {"source": "local", "path": "./packages/review"}
        if ecosystem == "codex"
        else "./packages/review"
    )
    catalog.write_text(
        json.dumps({"name": "other", "plugins": [{"name": "review", "source": source}]})
    )
    context = RepositoryContext(repo, repo_types={RepositoryType.CURSOR_PLUGIN})
    skill = plugin / "skills/ignored"
    assert skill in context.skills
    assert not getattr(context, f"{ecosystem}_plugins")
    context.exclude_patterns.append("**/.cursor-plugin/**")
    context.apply_excludes()
    assert not context.cursor_plugin_roots()
    assert skill in context.skills
    assert any(b.path == skill / "SKILL.md" for b in context.lint_tree.find(SkillBlock))


def test_cursor_claude_reference_keeps_legacy_containment(tmp_path):
    from skillsaw.blocks import SkillRefBlock

    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin/plugin.json").write_text('{"name":"review"}')
    reference = repo / "shared.md"
    reference.write_text("Shared review guidance.\n")
    refs = plugin / "skills/ignored/references"
    refs.mkdir()
    (refs / "shared.md").symlink_to(reference)
    context = RepositoryContext(repo)
    assert not context.provenance(plugin).cursor_only
    assert context.contained_plugin_owning(refs) is None
    assert any(b.path == refs / "shared.md" for b in context.lint_tree.find(SkillRefBlock))


def test_cursor_inline_wrapper_name_keeps_sibling_servers(tmp_path):
    from skillsaw.rules.builtin.mcp.prohibited import McpProhibitedRule

    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    path = repo / "packages/review/.cursor-plugin/plugin.json"
    data = json.loads(path.read_text())
    data["mcpServers"] = {"mcpServers": {"command": "echo"}, "sibling": {"command": "sh"}}
    path.write_text(json.dumps(data))
    context = RepositoryContext(repo)
    assert {
        server.name for block in context.lint_tree.find(McpBlock) for server in block.servers
    } == {"mcpServers", "sibling"}
    findings = McpProhibitedRule(config={"allowlist": ["mcpServers"]}).check(context)
    assert any(v.file_path == path and "sibling" in v.message for v in findings)


def test_cursor_repeated_catalog_components_expand_once(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    catalog = repo / ".cursor-plugin/marketplace.json"
    data = json.loads(catalog.read_text())
    original = data["plugins"][0]
    data["plugins"] = [{**original, "name": f"alias-{n}"} for n in range(100)]
    catalog.write_text(json.dumps(data))
    context = RepositoryContext(repo)
    assert len(context.cursor_views(repo / "packages/review")) == 1
    assert len(context.lint_tree.find(CursorPluginBlock)) == 1
    assert len(context.lint_tree.find(HooksBlock)) == 1
    assert len(context.lint_tree.find(McpBlock)) == 2


def test_cursor_default_skill_directory_is_one_level(tmp_path):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    manifest = plugin / ".cursor-plugin/plugin.json"
    manifest.write_text('{"name":"review"}')
    grouped = plugin / "skills/group/nested"
    grouped.mkdir(parents=True)
    (grouped / "SKILL.md").write_text((plugin / "skills/ignored/SKILL.md").read_text())
    # Cursor's default skills/ is one level deep; capabilities/ is portable.
    assert RepositoryContext(plugin).skills == [
        plugin / "capabilities/review",
        plugin / "skills/ignored",
    ]
    # Explicit component directories are recursively expanded by the host.
    manifest.write_text('{"name":"review","skills":"skills"}')
    from skillsaw.utils import invalidate_read_caches

    invalidate_read_caches(manifest)
    assert set(RepositoryContext(plugin).skills) == {
        plugin / "capabilities/review",
        plugin / "skills/ignored",
        grouped,
    }


@pytest.mark.parametrize(
    "field, filename, block_type",
    [("hooks", "hooks.json", HooksBlock), ("mcpServers", "mcp.json", McpBlock)],
)
def test_cursor_config_components_honor_parent_exclusion(tmp_path, field, filename, block_type):
    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    manifest = plugin / ".cursor-plugin/plugin.json"
    data = json.loads(manifest.read_text())
    data[field] = f"config/{filename}"
    manifest.write_text(json.dumps(data))
    config = plugin / "config" / filename
    config.write_text("{")
    context = RepositoryContext(repo, exclude_patterns=["**/config"])
    assert context.is_path_excluded(config.parent)
    assert not any(b.path == config for b in context.lint_tree.find(block_type))


@pytest.mark.parametrize(
    "location", ["rules/review.md", "commands/review.md", "agents/review.md", "README.md"]
)
def test_cursor_mixed_rule_keeps_parser_and_body_once(tmp_path, location):
    from skillsaw.blocks import BodyContent, CommandBlock, AgentBlock
    from skillsaw.rules.builtin.cursor.rules_valid import CursorRulesValidRule

    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    manifest = plugin / ".cursor-plugin/plugin.json"
    manifest.write_text(json.dumps({"name": "review", "rules": location}))
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin/plugin.json").write_text('{"name":"review"}')
    rule = plugin / location
    rule.parent.mkdir(exist_ok=True)
    rule.write_text("---\nalwaysApply: [broken]\n---\nUse pytest for tests.\n")
    context = RepositoryContext(repo)
    assert len([b for b in context.lint_tree.find(CursorRuleBlock) if b.path == rule]) == 1
    assert len([b for b in context.lint_tree.find(BodyContent) if b.path == rule]) == 1
    assert any(
        v.file_path == rule and "boolean" in v.message
        for v in CursorRulesValidRule().check(context)
    )
    original_type = (
        CommandBlock
        if location.startswith("commands")
        else AgentBlock if location.startswith("agents") else None
    )
    if original_type:
        assert len([b for b in context.lint_tree.find(original_type) if b.path == rule]) == 1


@pytest.mark.parametrize("lenient", [False, True])
def test_cursor_rule_view_preserves_host_parser_and_secret_checks(tmp_path, lenient):
    from skillsaw.blocks import CommandBlock
    from skillsaw.rules.builtin.content.embedded_secrets import ContentEmbeddedSecretsRule

    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    (plugin / ".cursor-plugin/plugin.json").write_text(
        '{"name":"review","rules":"commands/review.md"}'
    )
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin/plugin.json").write_text('{"name":"review"}')
    rule = plugin / "commands/review.md"
    glob = "globs: **/*.py\n" if lenient else ""
    rule.write_text(
        "---\n"
        + glob
        + "description: ghp_"
        + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        + "\nalwaysApply: true\n---\nUse pytest for tests.\n"
    )
    context = RepositoryContext(repo)
    original = next(b for b in context.lint_tree.find(CommandBlock) if b.path == rule)
    view = next(b for b in context.lint_tree.find(CursorRuleBlock) if b.path == rule)
    assert bool(original.frontmatter_error) == lenient
    assert not view.frontmatter_error
    assert view.estimate_tokens() == 0
    findings = [v for v in ContentEmbeddedSecretsRule().check(context) if v.file_path == rule]
    assert len(findings) == 1


@pytest.mark.parametrize("connection", [{"command": "echo"}, {"url": "https://example.com/mcp"}])
def test_cursor_sole_mcp_wrapper_named_server(tmp_path, connection):
    from skillsaw.rules.builtin.mcp.prohibited import McpProhibitedRule
    from skillsaw.rules.builtin.mcp.valid_json import McpValidJsonRule

    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    manifest = plugin / ".cursor-plugin/plugin.json"
    manifest.write_text(json.dumps({"name": "review", "mcpServers": {"mcpServers": connection}}))
    context = RepositoryContext(plugin)
    assert [s.name for b in context.lint_tree.find(McpBlock) for s in b.servers] == ["mcpServers"]
    assert McpProhibitedRule().check(context)
    assert not McpValidJsonRule().check(context)


@pytest.mark.parametrize("component", ["rules", "commands", "agents"])
def test_cursor_component_override_keeps_skill_role(tmp_path, component):
    from skillsaw.blocks import BodyContent

    repo = copy_fixture("cursor-plugins/clean", tmp_path)
    plugin = repo / "packages/review"
    manifest = plugin / ".cursor-plugin/plugin.json"
    manifest.write_text(json.dumps({"name": "review", component: "skills/ignored/SKILL.md"}))
    context = RepositoryContext(plugin)
    path = plugin / "skills/ignored/SKILL.md"
    assert len([b for b in context.lint_tree.find(SkillBlock) if b.path == path]) == 1
    assert len([b for b in context.lint_tree.find(BodyContent) if b.path == path]) == 1
    if component == "rules":
        assert len([b for b in context.lint_tree.find(CursorRuleBlock) if b.path == path]) == 1


@pytest.mark.parametrize("args", [(), ("--type", "agentskills")])
def test_cursor_undeclared_skills_stay_portable(tmp_path, args):
    """A declared ``skills`` path replaces Cursor's folder discovery, but a
    SKILL.md elsewhere in the package is still portable Agent Skills content
    that 0.20.0 linted; only skills under Cursor's own roots are replaced."""
    repo = copy_fixture("cursor-plugins/undeclared-skills", tmp_path)
    context = RepositoryContext(repo)
    assert context.provenance(repo).ecosystems == frozenset({"cursor"})
    assert context.skills == [
        repo / "shared/skills/changelog-draft",
        repo / "skills/pr-summary",
    ]
    result = run_cli(
        ["lint", str(repo), "--no-custom-rules", "--no-baseline", "--format", "json", "-v", *args]
    )
    report = json.loads(result.stdout)
    # Verbose reports list the skill directories rather than counting them.
    assert len(report["stats"]["skills"]) == 2
    unlinked = sorted(
        v["file_path"]
        for v in report["violations"]
        if v["rule_id"] == "content-unlinked-internal-reference"
    )
    assert unlinked == [
        "shared/skills/changelog-draft/SKILL.md",
        "skills/pr-summary/SKILL.md",
    ]


def test_cursor_declared_skills_stop_at_a_skill_directory(tmp_path):
    """A declared ``skills`` path must not turn a skill's phase files into
    skills of their own: the default one-level walk and the portable walk
    both stop at a directory holding SKILL.md (microsoft/skills
    azure-app-onboard ships deploy/, prepare/ and scaffold/ phases)."""
    repo = copy_fixture("cursor-plugins/nested-skill-phases", tmp_path)
    skill = repo / "skills/app-onboard"
    phases = [skill / "prepare/SKILL.md", skill / "deploy/SKILL.md"]
    before = [p.read_bytes() for p in phases]
    assert RepositoryContext(repo).skills == [skill]
    result = run_cli(["lint", str(repo), "--no-custom-rules", "--format", "json", "-v"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["violations"] == []
    run_cli(["fix", "--suggest", "--no-custom-rules", str(repo)])
    assert [p.read_bytes() for p in phases] == before
