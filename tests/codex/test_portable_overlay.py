"""Codex 0.154.0 portable identity and OpenAI extension precedence."""

import json
import shutil

import pytest

from skillsaw.blocks import AgentPluginMcpBlock, CodexHooksBlock, HooksBlock, McpBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.config import LinterConfig
from skillsaw.linter import Linter
from skillsaw.formats.codex import codex_declared_skill_dirs, codex_plugin_name
from skillsaw.formats.codex_manifest import codex_manifest_view
from skillsaw.lint_target import AgentPluginConfigNode, CodexPluginConfigNode
from skillsaw.rules.builtin.codex import CodexPluginJsonValidRule, CodexPluginStructureRule

from ._helpers import copy_fixture


def _set_extension(repo, value):
    path = repo / "plugin.json"
    data = json.loads(path.read_text())
    data["extensions"]["com.openai"] = value
    path.write_text(json.dumps(data))


def _hooks(context):
    return [block.path.name for block in context.lint_tree.find(HooksBlock)]


def _catalog_package(tmp_path):
    source = copy_fixture("codex/portable-overlay", tmp_path)
    repo = tmp_path / "catalog"
    package = repo / "packages/release"
    package.parent.mkdir(parents=True)
    source.rename(package)
    catalog = repo / ".agents/plugins/marketplace.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps(
            {
                "name": "release-catalog",
                "plugins": [
                    {
                        "name": "portable-release",
                        "source": {"source": "local", "path": "./packages/release"},
                    }
                ],
            }
        )
    )
    return repo, package


@pytest.mark.parametrize(
    "override", [None, {RepositoryType.AGENT_PLUGIN}, {RepositoryType.MARKETPLACE}]
)
def test_late_catalog_exclusion_removes_portable_configs_and_skills(tmp_path, override):
    repo, package = _catalog_package(tmp_path)
    context = RepositoryContext(repo, repo_types=override)
    assert package in context.agent_plugin_roots()
    assert context.lint_tree.find(AgentPluginMcpBlock)
    config = LinterConfig.default()
    config.exclude_patterns = [".agents/plugins/**"]
    linter = Linter(context, config, rule_ids={"agent-plugin-mcp-valid"})
    assert package not in linter.context.agent_plugins
    assert all(
        node.plugin_dir != package for node in linter.context.lint_tree.find(AgentPluginConfigNode)
    )
    assert not linter.context.lint_tree.find(AgentPluginMcpBlock)
    assert package / "skills/release-summary" not in linter.context.skills


def test_forced_codex_validates_portable_root_identity(tmp_path):
    repo, package = _catalog_package(tmp_path)
    path = package / "plugin.json"
    data = json.loads(path.read_text())
    data.pop("name")
    path.write_text(json.dumps(data))
    context = RepositoryContext(repo, repo_types={RepositoryType.CODEX_PLUGIN})
    findings = Linter(context).run()
    assert any(v.file_path == path and v.severity.value == "error" for v in findings)


@pytest.mark.parametrize("kind", ["directory", "dangling", "blocked"])
def test_occupied_fallback_remains_the_diagnostic_target(tmp_path, kind):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    _set_extension(repo, None)
    path = repo / ".codex-plugin/plugin.json"
    path.unlink()
    if kind == "directory":
        path.mkdir()
    elif kind == "dangling":
        path.symlink_to(repo / "missing-fallback.json")
    else:
        path.parent.rmdir()
        path.parent.write_text("blocked")
    assert codex_manifest_view(repo).path == path
    findings = CodexPluginJsonValidRule({}).check(RepositoryContext(repo))
    assert len(findings) == 1 and findings[0].file_path == path


@pytest.mark.parametrize("location", ["packages/release", ".codex/plugins/release"])
def test_forced_agent_plugin_does_not_claim_legacy_host_sources(tmp_path, location):
    repo, package = _catalog_package(tmp_path)
    (package / "plugin.json").unlink()
    if location.startswith(".codex"):
        installed = repo / location
        installed.parent.mkdir(parents=True)
        package.rename(installed)
        package = installed
    context = RepositoryContext(repo, repo_types={RepositoryType.AGENT_PLUGIN})
    assert package not in context.agent_plugins
    assert all(n.plugin_dir != package for n in context.lint_tree.find(AgentPluginConfigNode))


def test_installed_portable_package_is_not_documented(tmp_path):
    from skillsaw.docs.extractor import extract_docs

    source = copy_fixture("codex/portable-overlay", tmp_path)
    repo = tmp_path / "installed-repo"
    package = repo / ".codex/plugins/release"
    package.parent.mkdir(parents=True)
    source.rename(package)
    docs = extract_docs(RepositoryContext(repo))
    assert docs.plugins == []
    assert docs.skills == []


@pytest.mark.parametrize(
    "override", [None, {RepositoryType.CODEX_PLUGIN}, {RepositoryType.MARKETPLACE}]
)
def test_portable_skills_are_immediate_only(tmp_path, override):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    immediate = repo / "skills/release-summary"
    nested = repo / "skills/private/nested"
    shutil.copytree(immediate, nested)
    context = RepositoryContext(repo, repo_types=override)
    assert immediate in context.skills
    assert nested not in context.skills


def test_malformed_active_overlay_is_not_registerable(tmp_path):
    from skillsaw.rules.builtin.codex import CodexMarketplaceRegistrationRule

    repo = copy_fixture("codex/portable-overlay", tmp_path)
    _set_extension(repo, None)
    (repo / ".codex-plugin/plugin.json").write_text("{invalid")
    assert not CodexMarketplaceRegistrationRule._has_declared_name(RepositoryContext(repo), repo)


def test_symlinked_pure_portable_install_retains_codex_hooks_under_override(tmp_path):
    source = copy_fixture("codex/portable-overlay", tmp_path)
    repo = tmp_path / "install-repo"
    package = repo / "packages/release"
    package.parent.mkdir(parents=True)
    source.rename(package)
    shutil.rmtree(package / ".codex-plugin")
    path = package / "plugin.json"
    data = json.loads(path.read_text())
    data.pop("extensions")
    path.write_text(json.dumps(data))
    hooks = package / "hooks/hooks.json"
    hooks.parent.mkdir()
    shutil.copyfile(package / "lifecycle/start.json", hooks)
    installed = repo / ".codex/plugins/release"
    installed.parent.mkdir(parents=True)
    installed.symlink_to(package)
    context = RepositoryContext(repo, repo_types={RepositoryType.MARKETPLACE})
    assert context.provenance(package).codex
    assert any(block.path == hooks for block in context.lint_tree.find(CodexHooksBlock))


@pytest.mark.parametrize(
    "override", [None, {RepositoryType.AGENT_PLUGIN}, {RepositoryType.CODEX_PLUGIN}]
)
def test_inline_extension_wins_and_survives_type_overrides(tmp_path, override):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    context = RepositoryContext(repo, repo_types=override)
    assert context.provenance(repo).ecosystems == frozenset({"codex", "agent-plugin"})
    assert _hooks(context) == ["start.json"]
    assert len(context.lint_tree.find(CodexHooksBlock)) == 1
    nodes = context.lint_tree.find(CodexPluginConfigNode)
    assert len(nodes) == 1
    assert nodes[0].path == repo / "plugin.json"
    assert nodes[0].plugin_dir == repo
    assert codex_plugin_name(repo) == "portable-release"
    assert codex_declared_skill_dirs(repo) == []
    assert len(context.lint_tree.find(AgentPluginMcpBlock)) == 1
    assert [block.path.name for block in context.lint_tree.find(McpBlock)] == ["mcp.json"]
    assert CodexPluginJsonValidRule({}).check(context) == []
    assert CodexPluginStructureRule({}).check(context) == []


def test_inline_extension_needs_no_compatibility_marker(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    shutil.rmtree(repo / ".codex-plugin")
    context = RepositoryContext(repo)
    assert RepositoryType.CODEX_PLUGIN in context.repo_types
    assert _hooks(context) == ["start.json"]


def test_empty_object_shadows_compatibility_hooks(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    _set_extension(repo, {})
    assert _hooks(RepositoryContext(repo)) == []


@pytest.mark.parametrize("value", [None, [], "ignored", False, 3])
def test_non_object_extension_uses_compatibility_overlay(tmp_path, value):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    _set_extension(repo, value)
    context = RepositoryContext(repo)
    assert _hooks(context) == ["fallback.json"]
    assert codex_plugin_name(repo) == "portable-release"
    assert codex_declared_skill_dirs(repo) == []
    assert [block.path.name for block in context.lint_tree.find(McpBlock)] == ["mcp.json"]
    assert CodexPluginJsonValidRule({}).check(context) == []


def test_shadowed_broken_compatibility_manifest_is_not_validated(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    (repo / ".codex-plugin/plugin.json").write_text("{invalid")
    context = RepositoryContext(repo)
    assert _hooks(context) == ["start.json"]
    assert CodexPluginJsonValidRule({}).check(context) == []


def test_inline_hook_is_attributed_to_root_manifest(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    _set_extension(
        repo,
        {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo inline"}]}]}},
    )
    blocks = RepositoryContext(repo).lint_tree.find(CodexHooksBlock)
    assert len(blocks) == 1
    assert blocks[0].path == repo / "plugin.json"
    assert blocks[0].events["SessionStart"][0].handlers[0].command == "echo inline"


def test_escaping_hook_path_is_reported_and_not_attached(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    _set_extension(repo, {"hooks": "../outside.json"})
    context = RepositoryContext(repo)
    assert _hooks(context) == []
    findings = CodexPluginJsonValidRule({}).check(context)
    assert len(findings) == 1
    assert findings[0].file_path == repo / "plugin.json"
    assert "'..'" in findings[0].message


def test_nonportable_extension_does_not_claim_codex(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    shutil.rmtree(repo / ".codex-plugin")
    path = repo / "plugin.json"
    data = json.loads(path.read_text())
    data.pop("$schema")
    path.write_text(json.dumps(data))
    assert not RepositoryContext(repo).provenance(repo).codex


@pytest.mark.parametrize("version", ["1.1.0", "9.0.0"])
def test_unreleased_schema_does_not_supply_a_codex_overlay(tmp_path, version):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    shutil.rmtree(repo / ".codex-plugin")
    path = repo / "plugin.json"
    data = json.loads(path.read_text())
    data["$schema"] = f"https://agent-plugins.org/schemas/{version}/plugin.schema.json"
    path.write_text(json.dumps(data))
    assert not RepositoryContext(repo).provenance(repo).codex
    assert codex_manifest_view(repo).portable is False


def test_escaping_portable_manifest_is_not_read(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    shutil.rmtree(repo / ".codex-plugin")
    path = repo / "plugin.json"
    outside = tmp_path / "outside.json"
    path.rename(outside)
    path.symlink_to(outside)
    assert not RepositoryContext(repo).provenance(repo).codex
    assert codex_manifest_view(repo).portable is False


def test_inline_extension_ignores_escaping_compatibility_marker(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    marker = repo / ".codex-plugin"
    outside = tmp_path / "outside-marker"
    marker.rename(outside)
    marker.symlink_to(outside, target_is_directory=True)
    context = RepositoryContext(repo)
    assert context.provenance(repo).codex
    assert _hooks(context) == ["start.json"]


def test_overlay_identity_and_component_overrides_are_ignored(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    _set_extension(
        repo, {"name": "wrong", "skills": "./unused-skills", "mcpServers": "./unused-mcp.json"}
    )
    context = RepositoryContext(repo)
    assert codex_plugin_name(repo) == "portable-release"
    assert codex_declared_skill_dirs(repo) == []
    assert [block.path.name for block in context.lint_tree.find(McpBlock)] == ["mcp.json"]


def test_pure_portable_plugin_is_not_a_codex_declaration(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    shutil.rmtree(repo / ".codex-plugin")
    path = repo / "plugin.json"
    data = json.loads(path.read_text())
    data.pop("extensions")
    path.write_text(json.dumps(data))
    context = RepositoryContext(repo)
    assert not context.provenance(repo).codex
    assert _hooks(context) == []


def test_malformed_fallback_overlay_is_reported(tmp_path):
    repo = copy_fixture("codex/portable-overlay", tmp_path)
    _set_extension(repo, None)
    (repo / ".codex-plugin/plugin.json").write_text("{invalid")
    findings = CodexPluginJsonValidRule({}).check(RepositoryContext(repo))
    assert len(findings) == 1
    assert "Invalid JSON" in findings[0].message


@pytest.mark.parametrize("fallback", [False, True])
def test_docs_use_portable_identity_and_effective_overlay(tmp_path, fallback):
    from skillsaw.docs.extractor import extract_docs

    repo = copy_fixture("codex/portable-overlay", tmp_path)
    if fallback:
        _set_extension(repo, None)
    docs = extract_docs(RepositoryContext(repo))
    assert len(docs.plugins) == 1
    plugin = docs.plugins[0]
    assert plugin.name == "portable-release"
    assert plugin.version == "1.0.0"
    assert plugin.description.startswith("Review release evidence")
    assert [skill.name for skill in plugin.skills] == ["release-summary"]
    assert [server.name for server in plugin.mcp_servers] == ["release-api"]
    assert [hook.event_type for hook in plugin.hooks] == ["SessionStart"]
    if not fallback:
        assert plugin.display_name == "Portable Release"
