"""A marketplace catalog declares its entries, not its parent, as plugins."""

import json

import pytest

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import CodexPluginConfigNode, PluginNode
from skillsaw.rules.builtin.marketplace.registration import MarketplaceRegistrationRule
from skillsaw.rules.builtin.marketplace.json_valid import MarketplaceJsonValidRule
from skillsaw.rules.builtin.plugins.json_required import PluginJsonRequiredRule

from ._helpers import copy_fixture

FIXTURE = "codex/root-plugin-claude-marketplace"


@pytest.mark.parametrize(
    "repo_types", [None, {RepositoryType.MARKETPLACE}, {RepositoryType.CODEX_PLUGIN}]
)
def test_catalog_does_not_claim_its_codex_parent(tmp_path, repo_types):
    repo = copy_fixture(FIXTURE, tmp_path)
    context = RepositoryContext(repo, repo_types=repo_types)

    assert context.provenance(repo).codex_only
    assert context.provenance(repo / "plugins/claude-helper").claude
    assert all(node.path != repo for node in context.lint_tree.find(PluginNode))
    if repo_types is None or RepositoryType.CODEX_PLUGIN in repo_types:
        assert any(
            node.plugin_dir == repo for node in context.lint_tree.find(CodexPluginConfigNode)
        )
    assert PluginJsonRequiredRule({}).check(context) == []
    assert MarketplaceRegistrationRule({}).check(context) == []


def test_claude_marketplace_without_codex_does_not_discover_root(tmp_path):
    """A standalone Claude marketplace does not add its root to the plugin union."""
    repo = copy_fixture(FIXTURE, tmp_path)
    (repo / ".codex-plugin/plugin.json").unlink()
    (repo / ".codex-plugin").rmdir()
    context = RepositoryContext(repo)

    assert [node.path for node in context.lint_tree.find(PluginNode)] == [
        repo / "plugins/claude-helper"
    ]
    assert MarketplaceRegistrationRule({}).check(context) == []


@pytest.mark.parametrize("manifest_contents", ['{"name": "root-claude"}', '{"name":'])
def test_claude_manifest_beside_catalog_keeps_claude_provenance(tmp_path, manifest_contents):
    repo = copy_fixture(FIXTURE, tmp_path)
    (repo / ".claude-plugin/plugin.json").write_text(manifest_contents, encoding="utf-8")
    context = RepositoryContext(repo)

    assert context.provenance(repo).claude
    assert len(MarketplaceRegistrationRule({}).check(context)) == 1


def test_empty_claude_marker_still_reports_missing_manifest(tmp_path):
    repo = copy_fixture(FIXTURE, tmp_path)
    (repo / ".claude-plugin/marketplace.json").unlink()
    context = RepositoryContext(repo)

    assert context.provenance(repo).claude
    assert any(
        v.file_path == repo / ".claude-plugin/plugin.json"
        for v in PluginJsonRequiredRule({}).check(context)
    )


@pytest.mark.parametrize("strict", [True, False])
def test_catalog_explicitly_listing_root_keeps_claude_provenance(tmp_path, strict):
    repo = copy_fixture(FIXTURE, tmp_path)
    catalog = repo / ".claude-plugin/marketplace.json"
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["plugins"].append({"name": repo.name, "source": "./", "strict": strict})
    catalog.write_text(json.dumps(data), encoding="utf-8")
    context = RepositoryContext(repo)

    assert context.provenance(repo).claude
    # Without plugin.json the entry is the manifest, whatever ``strict`` says.
    assert PluginJsonRequiredRule({}).check(context) == []
    assert MarketplaceRegistrationRule({}).check(context) == []


def test_malformed_catalog_does_not_turn_codex_parent_into_claude_plugin(tmp_path):
    repo = copy_fixture(FIXTURE, tmp_path)
    (repo / ".claude-plugin/marketplace.json").write_text('{"plugins":', encoding="utf-8")
    context = RepositoryContext(repo)

    assert context.provenance(repo).codex_only
    assert PluginJsonRequiredRule({}).check(context) == []
    assert MarketplaceJsonValidRule({}).check(context)


def test_dangling_claude_manifest_beside_catalog_keeps_missing_manifest_error(tmp_path):
    repo = copy_fixture(FIXTURE, tmp_path)
    manifest = repo / ".claude-plugin/plugin.json"
    manifest.symlink_to("missing.json")
    context = RepositoryContext(repo)

    assert context.provenance(repo).claude
    assert any(v.file_path == manifest for v in PluginJsonRequiredRule({}).check(context))
