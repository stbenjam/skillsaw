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
        plugin_dir = FIXTURES_DIR / "valid-plugin" / ".agents" / "plugins" / "valid-plugin"
        assert antigravity_manifest_is_contained(plugin_dir) is True

    def test_invalid_plugin_manifest_is_still_contained(self) -> None:
        # Invalid plugin.json (bad syntax or unknown fields) is still an Antigravity plugin manifest file
        plugin_dir = FIXTURES_DIR / "invalid-plugin" / ".agents" / "plugins" / "invalid-plugin"
        assert antigravity_manifest_is_contained(plugin_dir) is True

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

    @pytest.mark.parametrize("config_dir", (*ANTIGRAVITY_CONFIG_DIR_NAMES, "_agents"))
    def test_discover_agents_plugins_subdir(self, tmp_path, config_dir) -> None:
        plug = tmp_path / config_dir / "plugins" / "plug-x"
        plug.mkdir(parents=True)
        (plug / "plugin.json").write_text('{"name": "plug-x"}', encoding="utf-8")

        discovered = discover_antigravity_plugins(tmp_path)
        assert plug in discovered

    def test_root_plugin_not_discovered(self, tmp_path) -> None:
        (tmp_path / "plugin.json").write_text('{"name": "root-plug"}', encoding="utf-8")
        assert discover_antigravity_plugins(tmp_path) == []

    def test_bare_plugins_subdir_not_discovered(self, tmp_path) -> None:
        plug_a = tmp_path / "plugins" / "plug-a"
        plug_a.mkdir(parents=True)
        (plug_a / "plugin.json").write_text('{"name": "plug-a"}', encoding="utf-8")
        assert discover_antigravity_plugins(tmp_path) == []

    def test_discover_ignores_agent_plugin_schema(self, tmp_path) -> None:
        plug = tmp_path / ".agents" / "plugins" / "portable"
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
        expected = fixture_dir / ".agents" / "plugins" / "valid-plugin"
        assert discover_antigravity_plugins(fixture_dir) == [expected]


# ==============================================================================
# Discovery: discover_antigravity_configs
# ==============================================================================


class TestDiscoverAntigravityConfigs:
    """Tests for ``discover_antigravity_configs``."""

    def test_root_configs_not_discovered(self, tmp_path) -> None:
        skills = tmp_path / "skills.json"
        skills.write_text("{}", encoding="utf-8")
        agents = tmp_path / "agents.json"
        agents.write_text("{}", encoding="utf-8")
        rules = tmp_path / "rules.json"
        rules.write_text("{}", encoding="utf-8")

        assert discover_antigravity_configs(tmp_path) == []

    @pytest.mark.parametrize("config_dir", ANTIGRAVITY_CONFIG_DIR_NAMES)
    def test_discover_config_dir_configs(self, tmp_path, config_dir) -> None:
        d = tmp_path / config_dir
        d.mkdir()
        skills = d / "skills.json"
        skills.write_text("{}", encoding="utf-8")
        agents = d / "agents.json"
        agents.write_text("{}", encoding="utf-8")
        rules = d / "rules.json"
        rules.write_text("{}", encoding="utf-8")

        discovered = discover_antigravity_configs(tmp_path)
        assert set(discovered) == {skills, agents, rules}

    def test_discover_fixture_project_repo(self) -> None:
        repo = FIXTURES_DIR / "project-repo"
        discovered = discover_antigravity_configs(repo)
        assert set(discovered) == {
            repo / ".agents" / "skills.json",
            repo / ".agents" / "agents.json",
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
        (tmp_path / ".agents" / "skills.json").mkdir(parents=True)
        assert discover_antigravity_configs(tmp_path) == []

    def test_discover_nonexistent_root(self, tmp_path) -> None:
        assert discover_antigravity_configs(tmp_path / "nonexistent") == []
