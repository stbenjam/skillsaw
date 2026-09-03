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

from skillsaw.blocks import GrokMcpBlock, HooksBlock, SkillBlock, SkillRefBlock
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import (
    GrokMarketplaceConfigNode,
    GrokMarketplaceIndexNode,
    GrokPluginNode,
)

from skillsaw.rules.builtin.grok import (
    GrokMarketplaceIndexParityRule,
    GrokPluginStructureRule,
)

from tests.grok._helpers import (
    HOOKS_JSON,
    local_catalog,
    relative,
    run_rule,
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

    # ``HooksBlock``, the shared base: a plugin's hooks attach as
    # ``GrokPluginHooksBlock``, a *sibling* of the project layer's
    # ``GrokHooksBlock``, so asserting on that class could never fail here.
    assert tree.find(HooksBlock) == []
    assert tree.find(GrokMcpBlock) == []


def test_a_declared_component_path_reaching_a_sibling_plugin_is_not_followed(temp_dir) -> None:
    """The escape that only the manifest reader can reject: the target stays
    inside the checkout, so repository containment passes it, and it is still
    another plugin's file rather than this plugin's."""
    repo = write_repo(temp_dir / "repo")
    almanac = write_plugin(repo / "plugins" / "almanac", {**MANIFEST, "name": "almanac"})
    (almanac / "hooks").mkdir()
    (almanac / "hooks" / "hooks.json").write_text(HOOKS_JSON, encoding="utf-8")
    (almanac / "servers.json").write_text(MCP_JSON, encoding="utf-8")
    write_plugin(
        repo / "plugins" / "tide-charts",
        {
            **MANIFEST,
            "hooks": "../almanac/hooks/hooks.json",
            "mcpServers": "../almanac/servers.json",
        },
    )

    tree = RepositoryContext(repo).lint_tree

    # ``almanac`` ships its own conventional hooks file, which is its block:
    # what must not appear is a second block for it under tide-charts, or any
    # block at all for the sibling's ``servers.json``.
    assert [block.path for block in tree.find(HooksBlock)] == [almanac / "hooks" / "hooks.json"]
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


def test_a_local_source_escaping_its_marketplace_root_is_dropped(temp_dir) -> None:
    """A catalog contains its sources against its own marketplace root, not
    the checkout: a package marketplace reaching into a sibling package is an
    entry Grok drops, and claiming the directory anyway would take it out of
    every other ecosystem's format scope."""
    repo = write_repo(temp_dir / "monorepo")
    write_catalog(repo / "pkg-a", local_catalog("../pkg-b/plugins/sediment"))
    borrowed = repo / "pkg-b" / "plugins" / "sediment"
    borrowed.mkdir(parents=True)
    (borrowed / ".claude-plugin").mkdir()
    (borrowed / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "sediment"}), encoding="utf-8"
    )

    context = RepositoryContext(repo)

    assert context._grok_claim_set() == set()
    assert not context.provenance(borrowed).grok
    # Claude declared it and Claude still owns it: a stray Grok claim here
    # would put the directory in Grok's scope and out of Claude's.
    assert context.provenance(borrowed).ecosystems == frozenset({"claude"})


def test_a_skill_reference_symlinked_out_of_a_grok_plugin_is_not_attached(temp_dir) -> None:
    """Grok enforces containment on a plugin's own files, so a plugin root is
    a package boundary like a Codex one: a ``references/`` symlink to an
    in-repository file outside the plugin is not this plugin's content, and a
    content fix must never rewrite it through one."""
    repo = write_repo(temp_dir / "references")
    (repo / "docs").mkdir()
    (repo / "docs" / "handbook.md").write_text("# Handbook\n\nHouse style.\n", encoding="utf-8")
    plugin = write_plugin(repo / "plugins" / "tide-charts", MANIFEST)
    skill = plugin / "skills" / "tide-window"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: tide-window\ndescription: Find low-tide survey windows.\n---\n\n# Window\n",
        encoding="utf-8",
    )
    (skill / "references" / "handbook.md").symlink_to(repo / "docs" / "handbook.md")

    context = RepositoryContext(repo)

    assert context.contained_plugin_owning(skill) == (repo / "plugins" / "tide-charts").resolve()
    assert relative(repo, context.lint_tree.find(SkillRefBlock)) == []


def test_a_claude_only_plugin_keeps_claudes_looser_reading(temp_dir) -> None:
    """Only the ecosystems that contain their package files draw the
    boundary. Claude's legacy format has no such contract, so the same
    layout under a Claude-only plugin keeps its established result."""
    repo = write_repo(temp_dir / "claude-references")
    (repo / "docs").mkdir()
    (repo / "docs" / "handbook.md").write_text("# Handbook\n\nHouse style.\n", encoding="utf-8")
    plugin = repo / "plugins" / "tide-charts"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    skill = plugin / "skills" / "tide-window"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: tide-window\ndescription: Find low-tide survey windows.\n---\n\n# Window\n",
        encoding="utf-8",
    )
    (skill / "references" / "handbook.md").symlink_to(repo / "docs" / "handbook.md")

    context = RepositoryContext(repo)

    assert context.contained_plugin_owning(skill) is None
    assert relative(repo, context.lint_tree.find(SkillRefBlock)) == [
        "plugins/tide-charts/skills/tide-window/references/handbook.md"
    ]


def test_a_dual_manifest_plugin_keeps_claudes_looser_reading(temp_dir) -> None:
    """The boundary is drawn on the Grok-*only* line, as Codex's is: a
    directory Claude also declares stays on Claude's reading, where a
    supplied file has no package-wide containment contract."""
    repo = write_repo(temp_dir / "dual-references")
    (repo / "docs").mkdir()
    (repo / "docs" / "handbook.md").write_text("# Handbook\n\nHouse style.\n", encoding="utf-8")
    plugin = write_plugin(repo / "plugins" / "tide-charts", MANIFEST)
    (plugin / ".claude-plugin").mkdir()
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    skill = plugin / "skills" / "tide-window"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: tide-window\ndescription: Find low-tide survey windows.\n---\n\n# Window\n",
        encoding="utf-8",
    )
    (skill / "references" / "handbook.md").symlink_to(repo / "docs" / "handbook.md")

    context = RepositoryContext(repo)

    assert context.provenance(plugin).ecosystems == frozenset({"claude", "grok"})
    assert context.contained_plugin_owning(skill) is None
    assert relative(repo, context.lint_tree.find(SkillRefBlock)) == [
        "plugins/tide-charts/skills/tide-window/references/handbook.md"
    ]


def test_an_index_symlinked_out_of_the_marketplace_is_not_attached(temp_dir) -> None:
    """The display catalog is held to the boundary the catalog's own sources
    are held to: a symlink out of the marketplace names a file this
    marketplace does not own, and the parity rule would report it."""
    outside = _outside(temp_dir)
    (outside / "plugin-index.json").write_text(
        json.dumps({"version": 1, "plugins": {}}), encoding="utf-8"
    )
    repo = write_repo(temp_dir / "repo")
    write_catalog(repo / "packages" / "harbour", local_catalog("./plugins/almanac"))
    (repo / "packages" / "harbour" / "plugins" / "almanac").mkdir(parents=True)
    (repo / "packages" / "harbour" / ".grok-plugin" / "plugin-index.json").symlink_to(
        outside / "plugin-index.json"
    )

    tree = RepositoryContext(repo).lint_tree

    assert tree.find(GrokMarketplaceConfigNode) != []
    assert tree.find(GrokMarketplaceIndexNode) == []


def test_a_skill_symlinked_out_of_the_checkout_is_not_read_by_the_parity_walk(temp_dir) -> None:
    """The parity rule stats and reads every SKILL.md it finds, so its walk
    is held to the plugin root the way the manifest reader is."""
    outside = _outside(temp_dir)
    (outside / "borrowed").mkdir()
    (outside / "borrowed" / "SKILL.md").write_text(
        "---\nname: borrowed\ndescription: Out of the checkout entirely.\n---\n\n# Borrowed\n",
        encoding="utf-8",
    )
    repo = write_repo(temp_dir / "repo")
    write_catalog(repo, local_catalog("./plugins/almanac"))
    write_catalog(
        repo,
        {"version": 1, "plugins": {"almanac": {"components": {"skills": []}}}},
        filename="plugin-index.json",
    )
    plugin = write_plugin(repo / "plugins" / "almanac", {"name": "almanac"})
    (plugin / "skills").mkdir()
    (plugin / "skills" / "borrowed").symlink_to(outside / "borrowed")

    assert run_rule(GrokMarketplaceIndexParityRule, repo) == []


def test_a_component_symlinked_out_of_the_plugin_does_not_make_it_installable(temp_dir) -> None:
    """Grok drops a component that leaves the plugin root, so counting one
    would call a directory installable that the installer refuses."""
    outside = _outside(temp_dir)
    (outside / "borrowed").mkdir()
    (outside / "borrowed" / "SKILL.md").write_text(
        "---\nname: borrowed\ndescription: Out of the checkout entirely.\n---\n\n# Borrowed\n",
        encoding="utf-8",
    )
    repo = write_repo(temp_dir / "repo")
    write_catalog(repo, local_catalog("./plugins/almanac"))
    plugin = repo / "plugins" / "almanac"
    (plugin / "skills").mkdir(parents=True)
    (plugin / "skills" / "borrowed").symlink_to(outside / "borrowed")

    found = run_rule(GrokPluginStructureRule, repo)

    assert [v.message for v in found] == [
        "Grok installs nothing from 'almanac/': no .grok-plugin/plugin.json and none of "
        "skills/<name>/SKILL.md, agents/*.md, hooks/hooks.json or .mcp.json"
    ]


def test_a_stray_index_symlinked_out_of_the_marketplace_is_not_attached(temp_dir) -> None:
    """The fallback locations are held to the same boundary as the one Grok
    reads."""
    outside = _outside(temp_dir)
    (outside / "plugin-index.json").write_text(
        json.dumps({"version": 1, "plugins": {}}), encoding="utf-8"
    )
    repo = write_repo(temp_dir / "repo")
    write_catalog(repo, local_catalog("./plugins/almanac"))
    (repo / "plugins" / "almanac").mkdir(parents=True)
    (repo / "plugin-index.json").symlink_to(outside / "plugin-index.json")

    tree = RepositoryContext(repo).lint_tree

    assert tree.find(GrokMarketplaceConfigNode) != []
    assert tree.find(GrokMarketplaceIndexNode) == []


def test_one_index_reached_by_two_locations_is_one_node(temp_dir) -> None:
    """A stray location symlinked at the one Grok reads is one file; a
    second node would report it twice."""
    repo = write_repo(temp_dir / "repo")
    write_catalog(repo, local_catalog("./plugins/almanac"))
    (repo / "plugins" / "almanac").mkdir(parents=True)
    index = write_catalog(repo, {"version": 1, "plugins": {}}, filename="plugin-index.json")
    (repo / "plugin-index.json").symlink_to(index)

    nodes = RepositoryContext(repo).lint_tree.find(GrokMarketplaceIndexNode)

    assert [node.path for node in nodes] == [index]
