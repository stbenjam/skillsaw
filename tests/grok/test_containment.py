"""Containment for Grok Build plugins: what stays inside the checkout.

Grok forces every resolved component path back inside the plugin root —
"manifest path escapes plugin root; skipping" in the loader, ``resolve_inside``
in the official catalog tooling — and skillsaw has a second reason to do the
same: a symlink out of the checkout is a file the linter would read, publish
and, once a fix lands, rewrite. Every escape here is dropped rather than
followed, and the drop is what these tests pin.
"""

from __future__ import annotations

import json

from skillsaw.blocks import GrokHooksBlock, GrokMcpBlock, SkillBlock
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import GrokMarketplaceConfigNode, GrokPluginNode

from tests.grok._helpers import (
    HOOKS_JSON,
    local_catalog,
    relative,
    write_catalog,
    write_plugin,
    write_repo,
)

MANIFEST = {
    "name": "tide-charts",
    "version": "1.0.0",
    "description": "Shoreline survey windows from NOAA tide predictions.",
}

MCP_JSON = json.dumps(
    {"mcpServers": {"tides": {"type": "http", "url": "https://tides.harbour.example/mcp"}}}
)


def _outside(temp_dir):
    """A directory beside the checkout, standing in for anywhere off it."""
    outside = temp_dir / "outside-the-checkout"
    outside.mkdir(parents=True, exist_ok=True)
    return outside


def test_a_manifest_symlinked_out_of_the_checkout_declares_nothing(temp_dir) -> None:
    outside = _outside(temp_dir)
    (outside / ".grok-plugin").mkdir()
    (outside / ".grok-plugin" / "plugin.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    repo = write_repo(temp_dir / "repo")
    plugin = repo / "plugins" / "tide-charts"
    plugin.mkdir(parents=True)
    (plugin / ".grok-plugin").symlink_to(outside / ".grok-plugin")

    context = RepositoryContext(repo)

    assert context.grok_plugins == []
    assert not context.provenance(plugin).grok


def test_a_manifest_pointing_at_another_plugins_manifest_declares_nothing(temp_dir) -> None:
    """Staying inside the checkout is not enough: read through it and plugin
    A would be documented and validated using plugin B's manifest."""
    repo = write_repo(temp_dir / "repo")
    write_plugin(repo / "plugins" / "almanac", {**MANIFEST, "name": "almanac"})
    borrower = repo / "plugins" / "tide-charts"
    borrower.mkdir(parents=True)
    (borrower / ".grok-plugin").symlink_to(repo / "plugins" / "almanac" / ".grok-plugin")

    context = RepositoryContext(repo)

    assert [node.path for node in context.lint_tree.find(GrokPluginNode)] == [
        repo / "plugins" / "almanac"
    ]


def test_a_local_source_escaping_the_repository_is_dropped(temp_dir) -> None:
    outside = _outside(temp_dir)
    write_plugin(outside / "sediment", {**MANIFEST, "name": "sediment"})
    repo = write_repo(temp_dir / "repo")
    write_catalog(repo, local_catalog("../outside-the-checkout/sediment"))

    context = RepositoryContext(repo)

    # The directory out there is a Grok plugin on its own terms — provenance
    # answers about a directory, not about this checkout. What the escape
    # costs it is the claim: nothing here discovers it, so no node is built
    # over it and no fix can reach it.
    assert context.grok_plugins == []
    assert context._grok_claim_set() == set()
    assert context.lint_tree.find(GrokPluginNode) == []


def test_a_local_source_symlinked_out_of_the_repository_is_dropped(temp_dir) -> None:
    outside = _outside(temp_dir)
    write_plugin(outside / "sediment", {**MANIFEST, "name": "sediment"})
    repo = write_repo(temp_dir / "repo")
    write_catalog(repo, local_catalog("./plugins/sediment"))
    (repo / "plugins").mkdir()
    (repo / "plugins" / "sediment").symlink_to(outside / "sediment")

    context = RepositoryContext(repo)

    assert context.grok_plugins == []


def test_a_catalog_symlinked_out_of_the_checkout_is_not_read(temp_dir) -> None:
    outside = _outside(temp_dir)
    (outside / "marketplace.json").write_text(
        json.dumps(local_catalog("./plugins/tide-charts")), encoding="utf-8"
    )
    repo = write_repo(temp_dir / "repo")
    (repo / ".grok-plugin").mkdir()
    (repo / ".grok-plugin" / "marketplace.json").symlink_to(outside / "marketplace.json")
    (repo / "plugins" / "tide-charts").mkdir(parents=True)

    context = RepositoryContext(repo)

    assert not context.grok_catalog_exists()
    assert context.lint_tree.find(GrokMarketplaceConfigNode) == []


def test_a_declared_component_path_escaping_the_plugin_is_not_followed(temp_dir) -> None:
    """Grok drops these too, silently, reporting ``0 skill dir(s)``. Nothing
    outside the plugin may reach the tree through a manifest field."""
    outside = _outside(temp_dir)
    (outside / "hooks.json").write_text(HOOKS_JSON, encoding="utf-8")
    (outside / "servers.json").write_text(MCP_JSON, encoding="utf-8")
    repo = write_repo(temp_dir / "repo")
    write_plugin(
        repo / "plugins" / "tide-charts",
        {
            **MANIFEST,
            "hooks": "../../../outside-the-checkout/hooks.json",
            "mcpServers": "../../../outside-the-checkout/servers.json",
        },
    )

    tree = RepositoryContext(repo).lint_tree

    assert tree.find(GrokHooksBlock) == []
    assert tree.find(GrokMcpBlock) == []


def test_a_skill_symlinked_out_of_the_plugin_is_not_discovered(temp_dir) -> None:
    outside = _outside(temp_dir)
    (outside / "borrowed").mkdir()
    (outside / "borrowed" / "SKILL.md").write_text(
        "---\nname: borrowed\ndescription: Out of the checkout entirely.\n---\n\n# Borrowed\n",
        encoding="utf-8",
    )
    repo = write_repo(temp_dir / "repo")
    plugin = write_plugin(repo / "plugins" / "tide-charts", MANIFEST)
    (plugin / "skills").mkdir()
    (plugin / "skills" / "borrowed").symlink_to(outside / "borrowed")

    context = RepositoryContext(repo)

    assert relative(repo, context.lint_tree.find(SkillBlock)) == []
