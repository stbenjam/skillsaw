"""Discovery, detection and provenance for Google Antigravity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.discovery.antigravity import (
    antigravity_manifest_is_contained,
    discover_antigravity_plugins,
    is_antigravity_plugin_location,
)
from skillsaw.formats.agent_plugins import PLUGIN_SCHEMA_ID
from skillsaw.formats.antigravity import ANTIGRAVITY_CONFIG_DIR_NAMES
from skillsaw.repository_provenance import PluginProvenance
from skillsaw.repository_types import RepositoryType

from ._helpers import copy_fixture, write_plugin, write_repo


def _customization_dirs(repo: Path) -> list[Path]:
    return RepositoryContext(repo).antigravity_customization_dirs()


class TestCustomizationRoots:
    """All four roots are honoured, and only those four."""

    @pytest.mark.parametrize("root_name", ANTIGRAVITY_CONFIG_DIR_NAMES)
    def test_each_root_is_detected(self, tmp_path: Path, root_name: str) -> None:
        repo = write_repo(tmp_path / root_name.lstrip("._"))
        (repo / root_name).mkdir()
        (repo / root_name / "hooks.json").write_text("{}", encoding="utf-8")
        assert RepositoryType.ANTIGRAVITY in RepositoryContext(repo).repo_types

    def test_four_roots_and_no_more(self) -> None:
        assert ANTIGRAVITY_CONFIG_DIR_NAMES == (".agents", ".agent", "_agents", "_agent")

    @pytest.mark.parametrize("root_name", (".gemini", ".antigravity", ".claude"))
    def test_neighbouring_directories_are_not_roots(self, tmp_path: Path, root_name: str) -> None:
        repo = write_repo(tmp_path / root_name.lstrip("."))
        (repo / root_name).mkdir()
        (repo / root_name / "hooks.json").write_text("{}", encoding="utf-8")
        assert RepositoryType.ANTIGRAVITY not in RepositoryContext(repo).repo_types

    @pytest.mark.parametrize("root_name", ("_agents", "_agent"))
    def test_a_non_dot_root_needs_a_file_not_a_populated_directory(
        self, tmp_path: Path, root_name: str
    ) -> None:
        """A source package may be called either name, and may hold ``rules/``.

        Detection has to agree with attachment, and attachment declines to
        read a non-dot root that declares none of Antigravity's own files.
        """
        repo = write_repo(tmp_path / f"pkg-{root_name.lstrip('_')}")
        rules = repo / "src" / root_name / "rules"
        rules.mkdir(parents=True)
        (rules / "base.md").write_text("# Base\n\nRun `make test`.\n", encoding="utf-8")
        assert RepositoryType.ANTIGRAVITY not in RepositoryContext(repo).repo_types

    @pytest.mark.parametrize("root_name", (".agents", ".agent"))
    def test_a_dot_root_is_still_detected_by_a_populated_directory(
        self, tmp_path: Path, root_name: str
    ) -> None:
        repo = write_repo(tmp_path / f"dot-{root_name.lstrip('.')}")
        rules = repo / root_name / "rules"
        rules.mkdir(parents=True)
        (rules / "base.md").write_text("# Base\n\nRun `make test`.\n", encoding="utf-8")
        assert RepositoryType.ANTIGRAVITY in RepositoryContext(repo).repo_types

    def test_repository_root_hooks_file_is_not_a_root(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "root-hooks")
        (repo / "hooks.json").write_text("{}", encoding="utf-8")
        assert RepositoryType.ANTIGRAVITY not in RepositoryContext(repo).repo_types

    def test_nested_package_root_is_found(self, tmp_path: Path) -> None:
        """``agy`` walks up from the entry directory, so a package root counts."""
        repo = write_repo(tmp_path / "monorepo")
        nested = repo / "services" / "schedule" / ".agents"
        nested.mkdir(parents=True)
        (nested / "hooks.json").write_text("{}", encoding="utf-8")
        assert RepositoryType.ANTIGRAVITY in RepositoryContext(repo).repo_types
        assert nested in _customization_dirs(repo)


class TestDetectionMarkers:
    """Detection agrees with attachment, and stops short of shared conventions."""

    @pytest.mark.parametrize(
        "filename",
        (
            "hooks.json",
            "mcp_config.json",
            "agents.json",
            "plugins.json",
            "skills.json",
            "workflows.json",
        ),
    )
    def test_file_markers(self, tmp_path: Path, filename: str) -> None:
        repo = write_repo(tmp_path / filename.replace(".", "-"))
        (repo / ".agents").mkdir()
        (repo / ".agents" / filename).write_text("{}", encoding="utf-8")
        assert RepositoryType.ANTIGRAVITY in RepositoryContext(repo).repo_types

    @pytest.mark.parametrize("dirname", ("rules", "agents"))
    def test_populated_directory_markers(self, tmp_path: Path, dirname: str) -> None:
        repo = write_repo(tmp_path / dirname)
        directory = repo / ".agents" / dirname
        directory.mkdir(parents=True)
        (directory / "note.md").write_text("# Note\n\nRun `make test`.\n", encoding="utf-8")
        assert RepositoryType.ANTIGRAVITY in RepositoryContext(repo).repo_types

    @pytest.mark.parametrize("dirname", ("rules", "agents", "plugins"))
    def test_empty_directory_is_not_a_marker(self, tmp_path: Path, dirname: str) -> None:
        repo = write_repo(tmp_path / f"empty-{dirname}")
        (repo / ".agents" / dirname).mkdir(parents=True)
        assert RepositoryType.ANTIGRAVITY not in RepositoryContext(repo).repo_types

    def test_plugins_directory_needs_a_manifest(self, tmp_path: Path) -> None:
        """A Codex catalog is a file in ``plugins/`` and is not this host's."""
        repo = write_repo(tmp_path / "catalog-only")
        plugins = repo / ".agents" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "marketplace.json").write_text('{"name": "harbourworks"}', encoding="utf-8")
        assert RepositoryType.ANTIGRAVITY not in RepositoryContext(repo).repo_types

        write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        assert RepositoryType.ANTIGRAVITY in RepositoryContext(repo).repo_types

    def test_skills_alone_is_not_evidence(self, tmp_path: Path) -> None:
        """``.agents/skills/`` is the shared Agent Skills convention."""
        repo = write_repo(tmp_path / "shared-skills")
        skill = repo / ".agents" / "skills" / "gtfs-diff"
        skill.mkdir(parents=True)
        skill.joinpath("SKILL.md").write_text(
            "---\nname: gtfs-diff\ndescription: Use when comparing two GTFS feeds.\n---\n\n"
            "# GTFS diff\n\nRun `make gtfs-export`.\n",
            encoding="utf-8",
        )
        types = RepositoryContext(repo).repo_types
        assert RepositoryType.ANTIGRAVITY not in types
        assert RepositoryType.AGENTSKILLS in types

    def test_memory_alone_is_not_evidence(self, tmp_path: Path) -> None:
        """``.agents/memory/`` is committed project memory owned by nobody."""
        repo = write_repo(tmp_path / "memory-only")
        memory = repo / ".agents" / "memory"
        memory.mkdir(parents=True)
        memory.joinpath("MEMORY.md").write_text(
            "# Memory\n\n- [Berths](berths.md)\n", encoding="utf-8"
        )
        assert RepositoryType.ANTIGRAVITY not in RepositoryContext(repo).repo_types

    def test_escaping_root_is_not_evidence(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        (outside / "rules").mkdir(parents=True)
        (outside / "rules" / "note.md").write_text("# Note\n", encoding="utf-8")
        repo = write_repo(tmp_path / "escaping")
        (repo / ".agents").symlink_to(outside)
        assert RepositoryType.ANTIGRAVITY not in RepositoryContext(repo).repo_types


class TestPluginLocation:
    """``plugins/<name>/plugin.json`` is the marker, and the location matters."""

    def test_direct_child_of_a_root(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "direct")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        assert is_antigravity_plugin_location(plugin) is True
        assert antigravity_manifest_is_contained(plugin) is True

    def test_repository_root_manifest_is_not_a_location(self, tmp_path: Path) -> None:
        """A root ``plugin.json`` is the Agent Plugins marker, not this one."""
        repo = write_repo(tmp_path / "root-manifest")
        (repo / "plugin.json").write_text('{"name": "route-kit"}', encoding="utf-8")
        assert is_antigravity_plugin_location(repo) is False
        assert discover_antigravity_plugins(repo, _customization_dirs(repo)) == []

    def test_bare_plugins_directory_is_not_a_location(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "bare-plugins")
        plugin = repo / "plugins" / "berth-tools"
        plugin.mkdir(parents=True)
        (plugin / "plugin.json").write_text('{"name": "berth-tools"}', encoding="utf-8")
        assert discover_antigravity_plugins(repo, _customization_dirs(repo)) == []

    def test_nested_plugin_is_not_discovered(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "nested")
        inner = repo / ".agents" / "plugins" / "outer" / "inner"
        inner.mkdir(parents=True)
        (inner / "plugin.json").write_text('{"name": "inner"}', encoding="utf-8")
        assert discover_antigravity_plugins(repo, _customization_dirs(repo)) == []

    def test_directory_without_a_manifest_is_not_a_plugin(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "manifest-less")
        plugin = write_plugin(repo, "berth-tools", None)
        (plugin / "skills").mkdir()
        assert discover_antigravity_plugins(repo, _customization_dirs(repo)) == []

    def test_unparseable_manifest_still_declares_the_directory(self, tmp_path: Path) -> None:
        """Reporting a manifest that does not parse needs the node to exist."""
        repo = write_repo(tmp_path / "unparseable")
        plugin = write_plugin(repo, "berth-tools", None)
        (plugin / "plugin.json").write_text("{not json", encoding="utf-8")
        assert discover_antigravity_plugins(repo, _customization_dirs(repo)) == [plugin]

    @pytest.mark.parametrize("root_name", ANTIGRAVITY_CONFIG_DIR_NAMES)
    def test_every_root_contributes_plugins(self, tmp_path: Path, root_name: str) -> None:
        repo = write_repo(tmp_path / f"plugins-{root_name.lstrip('._')}")
        plugin = repo / root_name / "plugins" / "berth-tools"
        plugin.mkdir(parents=True)
        (plugin / "plugin.json").write_text('{"name": "berth-tools"}', encoding="utf-8")
        assert RepositoryContext(repo).antigravity_plugins == [plugin]

    def test_nested_package_plugins_are_discovered(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "monorepo")
        plugin = repo / "services" / "schedule" / ".agents" / "plugins" / "berth-tools"
        plugin.mkdir(parents=True)
        (plugin / "plugin.json").write_text('{"name": "berth-tools"}', encoding="utf-8")
        assert RepositoryContext(repo).antigravity_plugins == [plugin]


class TestAgentPluginsManifestIsClaimed:
    """``agy`` claims a manifest carrying the Agent Plugins schema."""

    def test_portable_schema_is_not_excluded(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "portable")
        plugin = write_plugin(repo, "route-kit", {"$schema": PLUGIN_SCHEMA_ID, "name": "route-kit"})
        assert RepositoryContext(repo).antigravity_plugins == [plugin]

    def test_portable_fixture_lints_clean(self, tmp_path: Path) -> None:
        repo = copy_fixture("antigravity/portable-manifest", tmp_path)
        ctx = RepositoryContext(repo)
        plugin = repo / ".agents" / "plugins" / "route-kit"
        assert ctx.antigravity_plugins == [plugin]
        assert ctx.provenance(plugin).antigravity is True


class TestContainment:
    """skillsaw never reads outside the checkout, where ``agy`` would."""

    def test_escaping_plugin_directory_is_dropped(self, tmp_path: Path) -> None:
        """Nothing behind the symlink reaches the tree, hooks file included."""
        from skillsaw.blocks import HooksBlock
        from skillsaw.lint_tree import build_lint_tree
        from skillsaw.lint_target import AntigravityPluginConfigNode

        repo = copy_fixture("antigravity/symlink-escape", tmp_path) / "repo"
        ctx = RepositoryContext(repo)
        assert ctx.antigravity_plugins == []
        tree = build_lint_tree(ctx)
        assert tree.find(AntigravityPluginConfigNode) == []
        assert tree.find(HooksBlock) == []

    def test_escaping_plugin_directory_is_dropped_when_forced(self, tmp_path: Path) -> None:
        repo = copy_fixture("antigravity/symlink-escape", tmp_path) / "repo"
        ctx = RepositoryContext(repo, repo_types=[RepositoryType.ANTIGRAVITY_PLUGIN])
        assert ctx.antigravity_plugins == []

    def test_escaping_manifest_is_not_a_declaration(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "plugin.json").write_text('{"name": "escaped"}', encoding="utf-8")
        repo = write_repo(tmp_path / "escaping-manifest")
        plugin = write_plugin(repo, "berth-tools", None)
        (plugin / "plugin.json").symlink_to(outside / "plugin.json")
        assert antigravity_manifest_is_contained(plugin) is False
        assert RepositoryContext(repo).provenance(plugin).antigravity is False


class TestProvenance:
    """The claim is filesystem evidence, so ``--type`` does not move it."""

    def test_property_reads_the_ecosystem_set(self) -> None:
        assert PluginProvenance(ecosystems=frozenset({"antigravity"})).antigravity is True
        assert PluginProvenance(ecosystems=frozenset({"codex"})).antigravity is False

    def test_only_is_claude_relative(self) -> None:
        both = PluginProvenance(ecosystems=frozenset({"antigravity", "claude"}))
        assert both.antigravity_only is False
        alone = PluginProvenance(ecosystems=frozenset({"antigravity"}))
        assert alone.antigravity_only is True

    def test_claim_survives_an_unrelated_type_override(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "forced-elsewhere")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        ctx = RepositoryContext(repo, repo_types=[RepositoryType.MARKETPLACE])
        assert ctx.antigravity_plugins == []
        assert ctx.provenance(plugin).antigravity is True

    def test_forced_type_seeds_a_manifest_less_directory(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "forced-plugin")
        plugin = write_plugin(repo, "berth-tools", None)
        ctx = RepositoryContext(repo, repo_types=[RepositoryType.ANTIGRAVITY_PLUGIN])
        assert ctx.antigravity_plugins == [plugin]
        assert ctx.provenance(plugin).antigravity is True

    def test_forced_type_seeds_no_repository_root(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "forced-root")
        ctx = RepositoryContext(repo, repo_types=[RepositoryType.ANTIGRAVITY_PLUGIN])
        assert ctx.antigravity_plugins == []

    def test_excluded_plugin_drops_its_skills(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "excluded")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        skill = plugin / "skills" / "berth-check"
        skill.mkdir(parents=True)
        skill.joinpath("SKILL.md").write_text(
            "---\nname: berth-check\ndescription: Use when a sailing has no berth.\n---\n\n"
            "# Berth check\n\nRun `make berth-status`.\n",
            encoding="utf-8",
        )
        ctx = RepositoryContext(repo)
        assert skill in ctx.skills
        ctx.exclude_patterns = [".agents/plugins/berth-tools"]
        ctx.apply_excludes()
        assert ctx.antigravity_plugins == []
        assert skill not in ctx.skills


class TestForeignLayoutsUnaffected:
    """A customization root another ecosystem owns raises no Antigravity claim."""

    @pytest.mark.parametrize(
        "fixture",
        (
            "antigravity/codex-marketplace",
            "agent-memory/notes",
            "codex/clean",
            "codex/hooks-clean",
            "muse/clean",
        ),
    )
    def test_no_antigravity_type(self, tmp_path: Path, fixture: str) -> None:
        repo = copy_fixture(fixture, tmp_path)
        types = RepositoryContext(repo).repo_types
        assert RepositoryType.ANTIGRAVITY not in types
        assert RepositoryType.ANTIGRAVITY_PLUGIN not in types

    def test_codex_keeps_its_own_claim(self, tmp_path: Path) -> None:
        """The negative half alone would pass if both claims disappeared."""
        repo = copy_fixture("antigravity/codex-marketplace", tmp_path)
        ctx = RepositoryContext(repo)
        plugin = repo / ".agents" / "plugins" / "tide-tools"
        prov = ctx.provenance(plugin)
        assert prov.codex is True
        assert prov.antigravity is False
        assert RepositoryType.CODEX_MARKETPLACE in ctx.repo_types


_CODEX_FIXTURES = sorted(
    p.name
    for p in (Path(__file__).resolve().parent.parent / "fixtures" / "codex").iterdir()
    if p.is_dir()
)
assert _CODEX_FIXTURES, "No Codex fixtures found"


class TestCodexFixturesUnaffected:
    """Every Codex fixture keeps its own types."""

    @pytest.mark.parametrize("fixture_name", _CODEX_FIXTURES)
    def test_codex_fixture_is_not_antigravity(self, fixture_name: str) -> None:
        target = Path(__file__).resolve().parent.parent / "fixtures" / "codex" / fixture_name
        types = RepositoryContext(target).repo_types
        assert RepositoryType.ANTIGRAVITY not in types
        assert RepositoryType.ANTIGRAVITY_PLUGIN not in types


class TestSkillDiscovery:
    """Every root's ``skills/`` reaches the skill rules."""

    @pytest.mark.parametrize("root_name", ANTIGRAVITY_CONFIG_DIR_NAMES)
    def test_skills_under_each_root(self, tmp_path: Path, root_name: str) -> None:
        repo = write_repo(tmp_path / f"skills-{root_name.lstrip('._')}")
        skill = repo / root_name / "skills" / "gtfs-diff"
        skill.mkdir(parents=True)
        skill.joinpath("SKILL.md").write_text(
            "---\nname: gtfs-diff\ndescription: Use when comparing two GTFS feeds.\n---\n\n"
            "# GTFS diff\n\nRun `make gtfs-export`.\n",
            encoding="utf-8",
        )
        assert skill in RepositoryContext(repo).skills

    def test_plugin_skills_are_owned(self, tmp_path: Path) -> None:
        repo = copy_fixture("antigravity/workspace-clean", tmp_path)
        ctx = RepositoryContext(repo)
        plugin_skill = repo / ".agents" / "plugins" / "berth-tools" / "skills" / "berth-check"
        assert plugin_skill in ctx.skills

    def test_plugin_skill_is_a_containment_boundary(self, tmp_path: Path) -> None:
        """An Antigravity-only package contains its own files, as Codex's does."""
        repo = write_repo(tmp_path / "boundary")
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        assert RepositoryContext(repo).contained_plugin_owning(plugin / "skills") is not None


class TestMergedContext:
    """Multi-path runs count Antigravity plugins like every other ecosystem."""

    def test_merged_statistics_include_antigravity(self, tmp_path: Path) -> None:
        from skillsaw.cli._helpers import _build_merged_context

        first = copy_fixture("antigravity/workspace-clean", tmp_path)
        second = write_repo(tmp_path / "second")
        write_plugin(second, "tide-tools", {"name": "tide-tools"})
        merged = _build_merged_context([RepositoryContext(first), RepositoryContext(second)])
        names = {path.name for path in merged.distinct_plugin_dirs()}
        assert names == {"berth-tools", "tide-tools"}


class TestApmCompiledOutput:
    """An authored plugin under ``.agents/`` survives an APM compile target."""

    def test_antigravity_plugin_kept_under_an_apm_agents_target(self, tmp_path: Path) -> None:
        from skillsaw.lint_tree import build_lint_tree
        from skillsaw.lint_target import AntigravityPluginConfigNode

        repo = write_repo(tmp_path / "apm-repo")
        apm = repo / ".apm"
        apm.mkdir()
        (apm / "apm.yml").write_text(
            "name: ferrymark\nversion: 1.0.0\ncompile:\n  targets:\n    - codex\n",
            encoding="utf-8",
        )
        (apm / "instructions").mkdir()
        (apm / "instructions" / "build.instructions.md").write_text(
            "---\napplyTo: '**'\n---\n\n# Build\n\nRun `make test`.\n", encoding="utf-8"
        )
        plugin = write_plugin(repo, "berth-tools", {"name": "berth-tools"})
        (plugin / "hooks.json").write_text(
            json.dumps({"guard": {"Stop": [{"command": "make lint"}]}}), encoding="utf-8"
        )
        tree = build_lint_tree(RepositoryContext(repo))
        manifests = [n.path for n in tree.find(AntigravityPluginConfigNode)]
        assert manifests == [plugin / "plugin.json"]
