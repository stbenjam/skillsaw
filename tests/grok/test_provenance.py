"""Who claims a plugin directory when Grok Build is one of the claimants.

Grok reads ``.grok-plugin/plugin.json`` first and falls back to
``.claude-plugin/plugin.json``, so one directory can be valid to both tools
at once — verified against Grok Build 1.0.13 by building a plugin carrying
both and watching ``grok plugin validate`` resolve its own. That is the
"two ecosystems claim the same directory" case
``RepositoryContext.provenance()`` exists for, and these tests pin which
declaration counts as which ecosystem's.
"""

from __future__ import annotations

import json
import shutil

from skillsaw.context import RepositoryContext
from skillsaw.repository_provenance import PluginProvenance

from tests.grok._helpers import (
    copy_fixture,
    local_catalog,
    messages,
    write_catalog,
    write_plugin,
    write_repo,
)

MANIFEST = {
    "name": "tide-charts",
    "version": "1.0.0",
    "description": "Shoreline survey windows from NOAA tide predictions.",
}


# ── Which declaration is whose ───────────────────────────────────


def test_a_grok_manifest_claims_the_directory_for_grok_alone(temp_dir) -> None:
    repo = write_plugin(write_repo(temp_dir / "grok-only"), MANIFEST)

    assert RepositoryContext(repo).provenance(repo).ecosystems == frozenset({"grok"})


def test_a_claude_only_plugin_is_not_grok_claimed(temp_dir) -> None:
    """Grok reads ``.claude-plugin/plugin.json`` as a fallback, but that is
    Claude's declaration. Claiming it would put every Claude plugin in the
    repository under Grok's format rules as well."""
    repo = write_repo(temp_dir / "claude-only")
    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin" / "plugin.json").write_text(json.dumps(MANIFEST), encoding="utf-8")

    assert RepositoryContext(repo).provenance(repo).ecosystems == frozenset({"claude"})


def test_a_root_plugin_json_is_not_grok_claimed(temp_dir) -> None:
    """A root ``plugin.json`` is the portable Agent Plugins entrypoint. Grok
    resolves it first of the three, and it is still not Grok's declaration."""
    repo = write_repo(temp_dir / "portable")
    (repo / "plugin.json").write_text(
        json.dumps({"$schema": "https://agentplugins.org/schema/v1/plugin.json", **MANIFEST}),
        encoding="utf-8",
    )

    assert "grok" not in RepositoryContext(repo).provenance(repo).ecosystems


def test_a_dual_manifest_directory_is_both_ecosystems(tmp_path) -> None:
    repo = copy_fixture("grok/dual-manifest", tmp_path)

    assert RepositoryContext(repo).provenance(repo).ecosystems == frozenset({"claude", "grok"})


def test_a_bare_marker_directory_declares_nothing(temp_dir) -> None:
    """Grok treats a manifest as optional, so ``.grok-plugin/`` with nothing
    in it is not a declaration — a marketplace repository's own marker
    directory holds only ``marketplace.json``."""
    repo = write_plugin(write_repo(temp_dir / "bare-marker"), None)

    assert RepositoryContext(repo).provenance(repo).ecosystems == frozenset()


# ── Catalog claims ───────────────────────────────────────────────


def test_a_catalog_local_source_claims_a_manifest_less_directory(temp_dir) -> None:
    """A listed directory is claimed whether or not it ships a manifest, so
    its hooks, prose and skills reach the rules either way."""
    repo = write_repo(temp_dir / "catalog")
    write_catalog(repo, local_catalog("./plugins/tide-charts", "./plugins/almanac"))
    for name in ("tide-charts", "almanac"):
        (repo / "plugins" / name).mkdir(parents=True)

    context = RepositoryContext(repo)

    for name in ("tide-charts", "almanac"):
        assert context.provenance(repo / "plugins" / name).grok, name


def test_a_directory_the_catalog_does_not_list_is_unclaimed(temp_dir) -> None:
    repo = write_repo(temp_dir / "partial-catalog")
    write_catalog(repo, local_catalog("./plugins/tide-charts"))
    (repo / "plugins" / "tide-charts").mkdir(parents=True)
    (repo / "plugins" / "unlisted").mkdir(parents=True)

    context = RepositoryContext(repo)

    assert not context.provenance(repo / "plugins" / "unlisted").ecosystems


def test_a_claude_catalog_is_not_a_grok_catalog(temp_dir) -> None:
    """``.claude-plugin/marketplace.json`` is a documented Grok fallback and
    still Claude's file: the two schemas differ, so linting one against both
    would contradict itself."""
    repo = write_repo(temp_dir / "claude-catalog")
    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(local_catalog("./plugins/tide-charts")), encoding="utf-8"
    )
    (repo / "plugins" / "tide-charts").mkdir(parents=True)

    context = RepositoryContext(repo)

    assert not context.grok_catalog_exists()
    assert not context.provenance(repo / "plugins" / "tide-charts").grok


def test_a_claim_over_an_escaping_marker_is_refused(temp_dir) -> None:
    """A catalog claim is a declaration about a directory, never a licence to
    read through it: a listed plugin whose marker points at another plugin's
    would otherwise be documented and validated using that plugin's manifest."""
    repo = write_repo(temp_dir / "escaping-marker")
    write_catalog(repo, local_catalog("./plugins/tide-charts"))
    write_plugin(repo / "plugins" / "almanac", {**MANIFEST, "name": "almanac"})
    (repo / "plugins" / "tide-charts").mkdir(parents=True)
    (repo / "plugins" / "tide-charts" / ".grok-plugin").symlink_to(
        repo / "plugins" / "almanac" / ".grok-plugin"
    )

    context = RepositoryContext(repo)

    assert not context.provenance(repo / "plugins" / "tide-charts").grok
    assert context.provenance(repo / "plugins" / "almanac").grok


# ── The predicates over the record ───────────────────────────────


class TestGrokOnlyTruthTable:
    """``grok_only`` is ``grok and not claude``, the same shape as
    ``codex_only`` and for the same reason: it asks whether Claude's looser
    reading still governs the directory, and only a Claude declaration
    answers yes. The dual row is load-bearing — it is what keeps a
    dual-manifest directory on its established Claude results."""

    TRUTH_TABLE = [
        (frozenset(), False),
        (frozenset({"grok"}), True),
        (frozenset({"claude"}), False),
        (frozenset({"grok", "claude"}), False),
        (frozenset({"grok", "codex"}), True),
        (frozenset({"grok", "agent-plugin"}), True),
        (frozenset({"grok", "claude", "codex"}), False),
    ]

    def test_grok_only_truth_table(self) -> None:
        for ecosystems, expected in self.TRUTH_TABLE:
            assert PluginProvenance(ecosystems=ecosystems).grok_only is expected, ecosystems


def test_in_grok_only_plugin_gates_on_the_nearest_owner(temp_dir) -> None:
    repo = write_repo(temp_dir / "nearest")
    grok_only = write_plugin(repo / "plugins" / "tide-charts", MANIFEST)
    dual = write_plugin(repo / "plugins" / "almanac", {**MANIFEST, "name": "almanac"})
    (dual / ".claude-plugin").mkdir()
    (dual / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({**MANIFEST, "name": "almanac"}), encoding="utf-8"
    )

    context = RepositoryContext(repo)

    assert context.in_grok_only_plugin(grok_only / "hooks" / "hooks.json")
    assert not context.in_grok_only_plugin(dual / "hooks" / "hooks.json")
    assert not context.in_grok_only_plugin(repo / "AGENTS.md")


# ── Backward compatibility for dual-manifest directories ─────────


class TestDualManifestBackwardCompat:
    """A directory carrying both manifests keeps its established Claude
    results: the hooks file and the MCP config stay Claude's blocks, judged
    by Claude's rules. Each test pins its precondition so a discovery change
    cannot quietly turn the assertions vacuous."""

    def _fixture(self, tmp_path):
        repo = copy_fixture("grok/dual-manifest", tmp_path)
        context = RepositoryContext(repo)
        assert context.provenance(repo).ecosystems == frozenset({"claude", "grok"})
        return repo, context

    def test_the_shared_hooks_file_stays_claudes_block(self, tmp_path) -> None:
        from skillsaw.blocks import ClaudeHooksBlock, GrokPluginHooksBlock

        repo, context = self._fixture(tmp_path)
        hooks = repo / "hooks" / "hooks.json"

        assert [b.path for b in context.lint_tree.find(ClaudeHooksBlock)] == [hooks]
        assert context.lint_tree.find(GrokPluginHooksBlock) == []

    def test_the_shared_mcp_config_stays_one_block(self, tmp_path) -> None:
        from skillsaw.blocks import GrokMcpBlock, McpBlock

        repo, context = self._fixture(tmp_path)

        assert [b.path for b in context.lint_tree.find(McpBlock)] == [repo / ".mcp.json"]
        assert context.lint_tree.find(GrokMcpBlock) == []

    def test_removing_the_grok_manifest_changes_no_claude_result(self, tmp_path) -> None:
        """The strongest form of the compat claim: deleting ``.grok-plugin/``
        must not change what the Claude rules say."""
        from skillsaw.rules.builtin.hooks import ClaudeHooksValidRule
        from skillsaw.rules.builtin.mcp.valid_json import McpValidJsonRule

        repo, context = self._fixture(tmp_path)
        dual = (
            sorted(messages(ClaudeHooksValidRule().check(context))),
            sorted(messages(McpValidJsonRule().check(context))),
        )

        shutil.rmtree(repo / ".grok-plugin")
        claude_context = RepositoryContext(repo)
        claude_only = (
            sorted(messages(ClaudeHooksValidRule().check(claude_context))),
            sorted(messages(McpValidJsonRule().check(claude_context))),
        )

        assert dual == claude_only

    def test_each_manifest_is_judged_by_its_own_host(self, tmp_path) -> None:
        """Grok resolves ``.grok-plugin/plugin.json``, Claude resolves
        ``.claude-plugin/plugin.json``, and a defect in one reaches exactly
        one rule — or a dual-manifest plugin collects both hosts' complaints
        about a file only one of them reads."""
        from skillsaw.rules.builtin.grok import GrokPluginJsonValidRule
        from skillsaw.rules.builtin.plugins.json_valid import PluginJsonValidRule

        repo, _ = self._fixture(tmp_path)
        claude_manifest = repo / ".claude-plugin" / "plugin.json"
        claude_manifest.write_text(
            json.dumps({"name": "tide-charts", "version": "2.0.0"}), encoding="utf-8"
        )

        context = RepositoryContext(repo)
        claude_found = PluginJsonValidRule().check(context)

        assert GrokPluginJsonValidRule().check(context) == []
        assert claude_found, "the Claude rule must still read its own manifest"
        assert {v.file_path for v in claude_found} == {claude_manifest}

    def test_removing_the_claude_manifest_hands_grok_the_fallback(self, tmp_path) -> None:
        """Grok's own resolution order is what the rule follows: with no
        ``.grok-plugin/plugin.json`` and a catalog claiming the directory,
        the manifest Grok reads is Claude's, and the Grok rule judges it."""
        from skillsaw.rules.builtin.grok import GrokPluginJsonValidRule

        repo, _ = self._fixture(tmp_path)
        shutil.rmtree(repo / ".grok-plugin")
        (repo / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "Tide_Charts", "version": "2.0.0", "description": "x"}),
            encoding="utf-8",
        )
        # The catalog sits at the repository root and claims it: a source
        # is contained against its own marketplace root, so a catalog in a
        # subdirectory could not reach back up to claim its parent.
        write_catalog(repo, local_catalog("./"))

        found = messages(GrokPluginJsonValidRule().check(RepositoryContext(repo)))

        assert any("Tide_Charts" in message for message in found), found

    def test_the_grok_only_twin_gets_groks_own_blocks(self, tmp_path) -> None:
        """The same directory minus ``.claude-plugin/`` crosses the gate —
        the half of the conjunction the tests above prove is not firing."""
        from skillsaw.blocks import ClaudeHooksBlock, GrokPluginHooksBlock

        repo, _ = self._fixture(tmp_path)
        shutil.rmtree(repo / ".claude-plugin")

        context = RepositoryContext(repo)

        assert context.provenance(repo).grok_only
        assert [b.path for b in context.lint_tree.find(GrokPluginHooksBlock)] == [
            repo / "hooks" / "hooks.json"
        ]
        assert context.lint_tree.find(ClaudeHooksBlock) == []
