"""Provenance and discovery tests for Antigravity."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from skillsaw.discovery.antigravity import (
    ANTIGRAVITY_CONFIG_DIR_NAMES,
    antigravity_manifest_is_contained,
    discover_antigravity_configs,
    discover_antigravity_plugins,
    enumerate_antigravity_local_sources,
)
from skillsaw.formats.agent_plugins import PLUGIN_SCHEMA_ID
from skillsaw.repository_provenance import PluginProvenance

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "antigravity"


# ==============================================================================
# PluginProvenance: antigravity, antigravity_only, truth table
# ==============================================================================


class TestPluginProvenanceAntigravity:
    """PluginProvenance properties for Antigravity ecosystem."""

    def test_antigravity_property_true(self) -> None:
        record = PluginProvenance(ecosystems=frozenset({"antigravity"}))
        assert record.antigravity is True

    def test_antigravity_property_false(self) -> None:
        assert PluginProvenance(ecosystems=frozenset()).antigravity is False
        assert PluginProvenance(ecosystems=frozenset({"claude"})).antigravity is False
        assert PluginProvenance(ecosystems=frozenset({"codex"})).antigravity is False
        assert PluginProvenance(ecosystems=frozenset({"grok"})).antigravity is False
        assert PluginProvenance(ecosystems=frozenset({"agent-plugin"})).antigravity is False

    def test_antigravity_only_property_true(self) -> None:
        record = PluginProvenance(ecosystems=frozenset({"antigravity"}))
        assert record.antigravity_only is True

    def test_antigravity_only_property_false_when_claude_present(self) -> None:
        record = PluginProvenance(ecosystems=frozenset({"antigravity", "claude"}))
        assert record.antigravity_only is False

    def test_antigravity_only_property_true_with_non_claude_ecosystems(self) -> None:
        assert (
            PluginProvenance(ecosystems=frozenset({"antigravity", "codex"})).antigravity_only
            is True
        )
        assert (
            PluginProvenance(ecosystems=frozenset({"antigravity", "agent-plugin"})).antigravity_only
            is True
        )
        assert (
            PluginProvenance(ecosystems=frozenset({"antigravity", "grok"})).antigravity_only is True
        )
        assert (
            PluginProvenance(
                ecosystems=frozenset({"antigravity", "codex", "agent-plugin"})
            ).antigravity_only
            is True
        )


class TestAntigravityOnlyTruthTable:
    """``antigravity_only`` is ``antigravity and not claude``, tested exhaustively.

    Similar to codex_only and grok_only: asks whether Claude's looser reading still
    governs the directory, and only a Claude declaration answers yes.
    """

    TRUTH_TABLE = [
        (frozenset(), False),
        (frozenset({"antigravity"}), True),
        (frozenset({"claude"}), False),
        (frozenset({"codex"}), False),
        (frozenset({"agent-plugin"}), False),
        (frozenset({"grok"}), False),
        (frozenset({"antigravity", "claude"}), False),
        (frozenset({"antigravity", "codex"}), True),
        (frozenset({"antigravity", "agent-plugin"}), True),
        (frozenset({"antigravity", "grok"}), True),
        (frozenset({"antigravity", "claude", "codex"}), False),
        (frozenset({"antigravity", "claude", "agent-plugin"}), False),
        (frozenset({"antigravity", "claude", "grok"}), False),
        (frozenset({"antigravity", "codex", "agent-plugin"}), True),
        (frozenset({"antigravity", "codex", "grok"}), True),
        (frozenset({"antigravity", "agent-plugin", "grok"}), True),
        (frozenset({"antigravity", "claude", "codex", "agent-plugin"}), False),
        (frozenset({"antigravity", "claude", "codex", "grok"}), False),
        (frozenset({"antigravity", "claude", "agent-plugin", "grok"}), False),
        (frozenset({"antigravity", "codex", "agent-plugin", "grok"}), True),
        (frozenset({"antigravity", "claude", "codex", "agent-plugin", "grok"}), False),
    ]

    @pytest.mark.parametrize("ecosystems,expected", TRUTH_TABLE)
    def test_antigravity_only_truth_table(self, ecosystems, expected) -> None:
        assert PluginProvenance(ecosystems=ecosystems).antigravity_only is expected

    @pytest.mark.parametrize("ecosystems,expected", TRUTH_TABLE)
    def test_antigravity_only_is_independent_of_installed(self, ecosystems, expected) -> None:
        assert PluginProvenance(ecosystems=ecosystems, installed=True).antigravity_only is expected

    @pytest.mark.parametrize("ecosystems,expected", TRUTH_TABLE)
    def test_antigravity_only_matches_definition(self, ecosystems, expected) -> None:
        record = PluginProvenance(ecosystems=ecosystems)
        assert record.antigravity is ("antigravity" in ecosystems)
        assert record.claude is ("claude" in ecosystems)
        assert record.antigravity_only is (record.antigravity and not record.claude)

    def test_truth_table_exhaustive_combinations(self) -> None:
        names = ("claude", "antigravity", "codex", "agent-plugin", "grok")
        for size in range(len(names) + 1):
            for combo in itertools.combinations(names, size):
                eco = frozenset(combo)
                record = PluginProvenance(ecosystems=eco)
                expected = ("antigravity" in eco) and ("claude" not in eco)
                assert record.antigravity_only is expected, f"Failed for {eco}"


# ==============================================================================
# Discovery: antigravity_manifest_is_contained
# ==============================================================================


class TestAntigravityManifestIsContained:
    """Tests for ``antigravity_manifest_is_contained``."""

    def test_valid_contained_manifest(self) -> None:
        assert antigravity_manifest_is_contained(FIXTURES_DIR / "valid-plugin") is True

    def test_invalid_plugin_manifest_is_still_contained(self) -> None:
        # Invalid plugin.json (bad syntax or unknown fields) is still an Antigravity plugin manifest file
        assert antigravity_manifest_is_contained(FIXTURES_DIR / "invalid-plugin") is True

    def test_missing_plugin_json(self, tmp_path) -> None:
        assert antigravity_manifest_is_contained(tmp_path) is False

    def test_nonexistent_directory(self, tmp_path) -> None:
        assert antigravity_manifest_is_contained(tmp_path / "does-not-exist") is False

    def test_agent_plugin_schema_is_excluded(self, tmp_path) -> None:
        manifest = tmp_path / "plugin.json"
        manifest.write_text(
            json.dumps(
                {
                    "$schema": PLUGIN_SCHEMA_ID,
                    "name": "portable-plugin",
                }
            ),
            encoding="utf-8",
        )
        assert antigravity_manifest_is_contained(tmp_path) is False

    def test_manifest_is_directory_not_file(self, tmp_path) -> None:
        (tmp_path / "plugin.json").mkdir()
        assert antigravity_manifest_is_contained(tmp_path) is False

    def test_symlink_escaping_plugin_dir(self, tmp_path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_manifest = outside / "plugin.json"
        outside_manifest.write_text('{"name": "outside"}', encoding="utf-8")

        inside = tmp_path / "inside"
        inside.mkdir()
        (inside / "plugin.json").symlink_to(outside_manifest)

        # Contained resolution must fail when symlink escapes plugin_dir
        assert antigravity_manifest_is_contained(inside) is False


# ==============================================================================
# Discovery: discover_antigravity_plugins
# ==============================================================================


class TestDiscoverAntigravityPlugins:
    """Tests for ``discover_antigravity_plugins``."""

    def test_discover_root_plugin(self, tmp_path) -> None:
        (tmp_path / "plugin.json").write_text('{"name": "root-plug"}', encoding="utf-8")
        assert discover_antigravity_plugins(tmp_path) == [tmp_path]

    def test_discover_forced_root_without_manifest(self, tmp_path) -> None:
        assert discover_antigravity_plugins(tmp_path, forced=True) == [tmp_path]

    def test_discover_plugins_subdir(self, tmp_path) -> None:
        # Bare plugins/ directory is not an Antigravity customization root,
        # so it is not discovered unless declared via local_sources
        plug_a = tmp_path / "plugins" / "plug-a"
        plug_a.mkdir(parents=True)
        (plug_a / "plugin.json").write_text('{"name": "plug-a"}', encoding="utf-8")

        plug_b = tmp_path / "plugins" / "plug-b"
        plug_b.mkdir(parents=True)

        discovered = discover_antigravity_plugins(tmp_path)
        assert discovered == []

        # When declared in local_sources, it is discovered
        discovered_with_sources = discover_antigravity_plugins(tmp_path, local_sources=[plug_a])
        assert discovered_with_sources == [plug_a]

    @pytest.mark.parametrize("config_dir", ANTIGRAVITY_CONFIG_DIR_NAMES)
    def test_discover_agents_plugins_subdir(self, tmp_path, config_dir) -> None:
        plug = tmp_path / config_dir / "plugins" / "plug-x"
        plug.mkdir(parents=True)
        (plug / "plugin.json").write_text('{"name": "plug-x"}', encoding="utf-8")

        discovered = discover_antigravity_plugins(tmp_path)
        assert plug in discovered

    def test_discover_with_local_sources(self, tmp_path) -> None:
        source_dir = tmp_path / "external-plugin"
        source_dir.mkdir()
        discovered = discover_antigravity_plugins(tmp_path, local_sources=[source_dir])
        assert source_dir in discovered

    def test_discover_ignores_agent_plugin_schema(self, tmp_path) -> None:
        plug = tmp_path / "plugins" / "portable"
        plug.mkdir(parents=True)
        (plug / "plugin.json").write_text(
            json.dumps(
                {
                    "$schema": PLUGIN_SCHEMA_ID,
                    "name": "portable",
                }
            ),
            encoding="utf-8",
        )
        assert discover_antigravity_plugins(tmp_path) == []

    def test_discover_nonexistent_root(self, tmp_path) -> None:
        assert discover_antigravity_plugins(tmp_path / "does-not-exist") == []

    def test_discover_valid_fixture(self) -> None:
        fixture_dir = FIXTURES_DIR / "valid-plugin"
        assert discover_antigravity_plugins(fixture_dir) == [fixture_dir]


# ==============================================================================
# Discovery: enumerate_antigravity_local_sources
# ==============================================================================


class TestEnumerateAntigravityLocalSources:
    """Tests for ``enumerate_antigravity_local_sources``."""

    def test_enumerate_valid_sources_from_root_config(self, tmp_path) -> None:
        target1 = tmp_path / "plugins" / "target1"
        target1.mkdir(parents=True)
        target2 = tmp_path / "plugins" / "target2"
        target2.mkdir(parents=True)

        config_file = tmp_path / "plugins.json"
        config_file.write_text(
            json.dumps(
                {
                    "entries": [
                        {"path": "plugins/target1"},
                        {"path": "plugins/target2"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        sources = enumerate_antigravity_local_sources(tmp_path, [config_file])
        assert sources == sorted([target1.resolve(), target2.resolve()])

    def test_enumerate_valid_sources_relative_to_subconfig(self, tmp_path) -> None:
        target = tmp_path / "plugins" / "my-plug"
        target.mkdir(parents=True)

        config_file = tmp_path / ".agents" / "plugins.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(
            json.dumps(
                {
                    "entries": [
                        {"path": "../plugins/my-plug"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        sources = enumerate_antigravity_local_sources(tmp_path, [config_file])
        assert sources == [target.resolve()]

    def test_enumerate_ignores_nonexistent_and_file_targets(self, tmp_path) -> None:
        file_target = tmp_path / "plugins" / "not-a-dir.txt"
        file_target.parent.mkdir(parents=True)
        file_target.write_text("hello", encoding="utf-8")

        config_file = tmp_path / "plugins.json"
        config_file.write_text(
            json.dumps(
                {
                    "entries": [
                        {"path": "plugins/nonexistent"},
                        {"path": "plugins/not-a-dir.txt"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        assert enumerate_antigravity_local_sources(tmp_path, [config_file]) == []

    def test_enumerate_ignores_escaping_paths(self, tmp_path) -> None:
        outside = tmp_path.parent / "outside_dir"
        outside.mkdir(exist_ok=True)

        config_file = tmp_path / "plugins.json"
        config_file.write_text(
            json.dumps({"entries": [{"path": f"../{outside.name}"}]}),
            encoding="utf-8",
        )

        assert enumerate_antigravity_local_sources(tmp_path, [config_file]) == []

    def test_enumerate_deduplication(self, tmp_path) -> None:
        target = tmp_path / "plugins" / "target"
        target.mkdir(parents=True)

        cfg1 = tmp_path / "cfg1.json"
        cfg1.write_text(json.dumps({"entries": [{"path": "plugins/target"}]}), encoding="utf-8")
        cfg2 = tmp_path / "cfg2.json"
        cfg2.write_text(json.dumps({"entries": [{"path": "plugins/target"}]}), encoding="utf-8")

        sources = enumerate_antigravity_local_sources(tmp_path, [cfg1, cfg2])
        assert sources == [target.resolve()]

    def test_enumerate_malformed_json_skipped(self, tmp_path) -> None:
        cfg = tmp_path / "bad.json"
        cfg.write_text("{bad json}", encoding="utf-8")
        assert enumerate_antigravity_local_sources(tmp_path, [cfg]) == []

    def test_enumerate_nonexistent_root(self, tmp_path) -> None:
        assert enumerate_antigravity_local_sources(tmp_path / "nonexistent", []) == []


# ==============================================================================
# Discovery: discover_antigravity_configs
# ==============================================================================


class TestDiscoverAntigravityConfigs:
    """Tests for ``discover_antigravity_configs``."""

    def test_discover_root_configs(self, tmp_path) -> None:
        skills = tmp_path / "skills.json"
        skills.write_text("{}", encoding="utf-8")
        plugins = tmp_path / "plugins.json"
        plugins.write_text("{}", encoding="utf-8")

        discovered = discover_antigravity_configs(tmp_path)
        assert set(discovered) == {skills, plugins}

    @pytest.mark.parametrize("config_dir", ANTIGRAVITY_CONFIG_DIR_NAMES)
    def test_discover_config_dir_configs(self, tmp_path, config_dir) -> None:
        d = tmp_path / config_dir
        d.mkdir()
        skills = d / "skills.json"
        skills.write_text("{}", encoding="utf-8")
        plugins = d / "plugins.json"
        plugins.write_text("{}", encoding="utf-8")

        discovered = discover_antigravity_configs(tmp_path)
        assert set(discovered) == {skills, plugins}

    def test_discover_fixture_project_repo(self) -> None:
        repo = FIXTURES_DIR / "project-repo"
        discovered = discover_antigravity_configs(repo)
        assert set(discovered) == {
            repo / ".agents" / "skills.json",
            repo / ".agents" / "plugins.json",
        }

    def test_discover_tool_dirs(self, tmp_path) -> None:
        custom_base = tmp_path / "custom" / ".agents"
        custom_base.mkdir(parents=True)
        skills = custom_base / "skills.json"
        skills.write_text("{}", encoding="utf-8")

        discovered = discover_antigravity_configs(
            tmp_path,
            tool_dirs={".agents": [custom_base]},
        )
        assert skills in discovered

    def test_discover_ignores_directories_named_skills_json(self, tmp_path) -> None:
        (tmp_path / "skills.json").mkdir()
        assert discover_antigravity_configs(tmp_path) == []

    def test_discover_nonexistent_root(self, tmp_path) -> None:
        assert discover_antigravity_configs(tmp_path / "nonexistent") == []
