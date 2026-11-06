"""ZCode plugin manifests, components and the lint tree."""

from __future__ import annotations


from skillsaw.blocks import CommandBlock
from skillsaw.context import RepositoryContext

from ._helpers import lint, messages, write_json, zcode_plugin

AGENT = "---\ndescription: Reviews tide tables. Use when a berth move is planned.\n---\n\nReview.\n"


def test_forced_plugin_type_reports_a_missing_manifest(tmp_path):
    (tmp_path / "README.md").write_text("# Tide charts\n")
    report = lint(tmp_path, "--type", "zcode-plugin")
    assert any(
        "No .zcode-plugin/plugin.json" in m for m in messages(report, "zcode-plugin-json-valid")
    )


def test_manifest_that_is_a_directory_is_reported(tmp_path):
    (tmp_path / ".zcode-plugin" / "plugin.json").mkdir(parents=True)
    report = lint(tmp_path, "--type", "zcode-plugin")
    assert any("not a regular file" in m for m in messages(report, "zcode-plugin-json-valid"))


def test_nested_conventional_plugin_commands_are_attached(tmp_path):
    zcode_plugin(tmp_path)
    nested = tmp_path / "commands" / "git" / "sync.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("---\ndescription: Sync the branch\n---\n\nRebase onto main.\n")
    paths = {b.path for b in RepositoryContext(tmp_path).lint_tree.find(CommandBlock)}
    assert nested in paths


def test_plugin_agents_need_a_name_in_zcode_plugins_only(tmp_path):
    tide_charts = zcode_plugin(tmp_path / "plugins" / "tide-charts")
    (tide_charts / "agents").mkdir()
    (tide_charts / "agents" / "tide-reviewer.md").write_text(AGENT)
    claude_plugin = tmp_path / "plugins" / "berth-notes"
    write_json(claude_plugin / ".claude-plugin" / "plugin.json", {"name": "berth-notes"})
    (claude_plugin / "agents").mkdir()
    (claude_plugin / "agents" / "berth-reviewer.md").write_text(AGENT)
    found = messages(lint(tmp_path), "zcode-agent-valid")
    assert any("tide-reviewer.md needs a non-empty 'name'" in m for m in found)
    assert not any("berth-reviewer.md" in m for m in found)


def test_object_form_command_sources_are_attached(tmp_path):
    zcode_plugin(tmp_path, commands={"deploy": {"source": "./prompts/deploy.md"}})
    source = tmp_path / "prompts" / "deploy.md"
    source.parent.mkdir()
    source.write_text("---\ndescription: Deploy the harbor service\n---\n\nDeploy it.\n")
    paths = {b.path for b in RepositoryContext(tmp_path).lint_tree.find(CommandBlock)}
    assert source in paths


def test_declared_agent_plugin_mcp_is_attached_once(tmp_path):
    """A ZCode manifest naming the Agent Plugins ``mcp.json`` must not add a
    second parser role over it, or every server is reported twice."""
    from skillsaw.blocks import McpBlock

    write_json(
        tmp_path / "plugin.json",
        {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "tide-charts",
            "version": "1.0.0",
            "description": "Tide charts.",
        },
    )
    write_json(tmp_path / "mcp.json", {"mcpServers": {"tides": {"command": "tides-mcp"}}})
    zcode_plugin(tmp_path, mcpServers="mcp.json")
    mcp = [
        b for b in RepositoryContext(tmp_path).lint_tree.find(McpBlock) if b.path.name == "mcp.json"
    ]
    assert len(mcp) == 1


def test_excluding_another_ecosystems_catalog_keeps_zcode_owned_skills(tmp_path):
    """Every skill prune keeps skills a ZCode plugin still owns."""
    shared = zcode_plugin(tmp_path / "packages" / "shared", name="shared")
    skill = shared / "skills" / "berth-log"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: berth-log\ndescription: Logs berth moves. Use when a vessel changes "
        "berth.\n---\n\nAppend the move to the log.\n"
    )
    write_json(
        tmp_path / ".grok-plugin" / "marketplace.json",
        {
            "name": "harbor",
            "owner": {"name": "Harbor"},
            "plugins": [{"name": "shared", "source": "./packages/shared"}],
        },
    )
    context = RepositoryContext(tmp_path)
    assert skill in context.skills
    context.exclude_patterns.append(".grok-plugin/**")
    context.apply_excludes()
    assert skill in context.skills


def test_routing_leaves_zcode_plugin_agent_descriptions_to_the_agent_rule(tmp_path):
    plugin = zcode_plugin(tmp_path / "plugins" / "tide-charts")
    (plugin / "agents").mkdir()
    (plugin / "agents" / "tide-reviewer.md").write_text(
        "---\nname: tide-reviewer\n---\n\nReview.\n"
    )
    report = lint(tmp_path)
    assert any("'description'" in m for m in messages(report, "zcode-agent-valid"))
    assert not any(
        "tide-reviewer" in v["file_path"]
        for v in report["violations"]
        if v["rule_id"] == "content-description-routing"
    )


def test_missing_and_directory_mcp_paths_are_reported(tmp_path):
    zcode_plugin(tmp_path, mcpServers=["servers.json", "config"])
    (tmp_path / "config").mkdir()
    found = {
        v["message"]: v["severity"]
        for v in lint(tmp_path)["violations"]
        if v["rule_id"] == "zcode-plugin-json-valid" and "'mcpServers'" in v["message"]
    }
    assert any("'servers.json'" in m and s == "warning" for m, s in found.items())
    assert any("'config'" in m and s == "error" for m, s in found.items())


def test_marker_backed_plugin_stays_in_the_tree_under_a_type_override(tmp_path):
    from skillsaw.context import RepositoryContext, RepositoryType
    from skillsaw.lint_target import ZCodePluginConfigNode

    plugin = zcode_plugin(tmp_path / "packages" / "tide-charts")
    context = RepositoryContext(tmp_path, repo_types={RepositoryType.AGENTSKILLS})
    dirs = {n.plugin_dir for n in context.lint_tree.find(ZCodePluginConfigNode)}
    assert plugin in dirs
