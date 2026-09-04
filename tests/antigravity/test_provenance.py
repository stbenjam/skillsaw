"""Provenance and discovery tests for Antigravity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.discovery.antigravity import (
    ANTIGRAVITY_CONFIG_DIR_NAMES,
    antigravity_manifest_is_contained,
    discover_antigravity_plugins,
)
from skillsaw.formats.agent_plugins import PLUGIN_SCHEMA_ID
from skillsaw.repository_provenance import PluginProvenance

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "antigravity"


# PluginProvenance: antigravity


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


# Discovery: antigravity_manifest_is_contained


class TestAntigravityManifestIsContained:
    """Tests for ``antigravity_manifest_is_contained``."""

    def test_valid_contained_manifest(self) -> None:
        plugin_dir = FIXTURES_DIR / "valid-plugin" / ".agents" / "plugins" / "valid-plugin"
        assert antigravity_manifest_is_contained(plugin_dir) is True

    def test_invalid_plugin_manifest_is_still_contained(self) -> None:
        # Invalid plugin.json (bad syntax or unknown fields) is still an Antigravity plugin manifest file
        plugin_dir = FIXTURES_DIR / "invalid-plugin" / ".agents" / "plugins" / "invalid-plugin"
        assert antigravity_manifest_is_contained(plugin_dir) is True

    def test_missing_manifest(self, tmp_path) -> None:
        assert antigravity_manifest_is_contained(tmp_path) is False

    def test_directory_manifest_rejected(self, tmp_path) -> None:
        (tmp_path / "plugin.json").mkdir()
        assert antigravity_manifest_is_contained(tmp_path) is False

    def test_non_dict_manifest_rejected(self, tmp_path) -> None:
        (tmp_path / "plugin.json").write_text("[]", encoding="utf-8")
        assert antigravity_manifest_is_contained(tmp_path) is False

    def test_invalid_json_manifest_rejected(self, tmp_path) -> None:
        (tmp_path / "plugin.json").write_text("{bad json", encoding="utf-8")
        assert antigravity_manifest_is_contained(tmp_path) is False

    def test_foreign_nested_plugin_fixture_not_claimed(self) -> None:
        fixture_dir = FIXTURES_DIR / "foreign-nested-plugin"
        foreign_plugin = fixture_dir / ".agents" / "plugins" / "foreign-plugin"
        assert antigravity_manifest_is_contained(foreign_plugin) is False

    def test_agent_plugin_schema_rejected(self, tmp_path) -> None:
        (tmp_path / "plugin.json").write_text(
            json.dumps(
                {
                    "$schema": PLUGIN_SCHEMA_ID,
                    "name": "cross-compat-plugin",
                }
            ),
            encoding="utf-8",
        )
        assert antigravity_manifest_is_contained(tmp_path) is False

    def test_symlink_escaping_plugin_dir_rejected(self, tmp_path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_manifest = outside / "plugin.json"
        outside_manifest.write_text('{"name": "escaped"}', encoding="utf-8")

        inside = tmp_path / "inside"
        inside.mkdir()
        (inside / "plugin.json").symlink_to(outside_manifest)

        # Contained resolution must fail when symlink escapes plugin_dir
        assert antigravity_manifest_is_contained(inside) is False


# Discovery: discover_antigravity_plugins


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

    def test_foreign_nested_plugin_fixture_not_discovered(self) -> None:
        fixture_dir = FIXTURES_DIR / "foreign-nested-plugin"
        assert discover_antigravity_plugins(fixture_dir) == []

    def test_foreign_nested_plugin_not_claimed_in_context(self) -> None:
        fixture_dir = FIXTURES_DIR / "foreign-nested-plugin"
        ctx = RepositoryContext(fixture_dir)
        assert ctx.antigravity_plugins == []
        foreign_plugin = fixture_dir / ".agents" / "plugins" / "foreign-plugin"
        prov = ctx.provenance(foreign_plugin)
        assert prov.antigravity is False

    def test_symlink_escaping_plugin_dir_is_dropped(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        plugins_dir = repo / ".agents" / "plugins"
        plugins_dir.mkdir(parents=True)

        outside = tmp_path / "outside_plugin"
        outside.mkdir(parents=True)
        (outside / "plugin.json").write_text('{"name": "outside"}', encoding="utf-8")

        symlink_plugin = plugins_dir / "symlink-plugin"
        symlink_plugin.symlink_to(outside)

        assert discover_antigravity_plugins(repo) == []

    def test_symlink_escaping_plugin_dir_is_dropped_forced_mode(self, tmp_path) -> None:
        repo = tmp_path / "repo"
        plugins_dir = repo / ".agents" / "plugins"
        plugins_dir.mkdir(parents=True)

        outside = tmp_path / "outside_plugin"
        outside.mkdir(parents=True)
        (outside / "plugin.json").write_text('{"name": "outside"}', encoding="utf-8")

        symlink_plugin = plugins_dir / "symlink-plugin"
        symlink_plugin.symlink_to(outside)

        assert discover_antigravity_plugins(repo, forced=True) == []
