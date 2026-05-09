"""Tests for rule bundles and CLI enable/disable commands."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from skillsaw.bundles import (
    BUILTIN_BUNDLES,
    get_bundle_rules,
    is_bundle,
    is_rule,
    resolve_names,
    enable_rules,
    disable_rules,
)


class TestBundleDefinitions:
    def test_all_bundles_return_list(self):
        for bundle_name in BUILTIN_BUNDLES:
            rules = get_bundle_rules(bundle_name)
            assert rules is not None, f"Bundle '{bundle_name}' returned None"
            assert isinstance(rules, list), f"Bundle '{bundle_name}' returned {type(rules)}"

    def test_all_bundle_contains_every_rule(self):
        from skillsaw.rules.builtin import BUILTIN_RULES

        all_ids = {rc().rule_id for rc in BUILTIN_RULES}
        bundle_all = set(get_bundle_rules("all"))
        assert bundle_all == all_ids

    def test_agentskills_bundle(self):
        rules = get_bundle_rules("agentskills")
        assert "agentskill-valid" in rules
        assert all(r.startswith("agentskill-") for r in rules)

    def test_marketplace_bundle(self):
        rules = get_bundle_rules("marketplace")
        assert "marketplace-json-valid" in rules
        assert all(r.startswith("marketplace-") for r in rules)

    def test_plugin_bundle(self):
        rules = get_bundle_rules("plugin")
        assert len(rules) > 0
        valid_prefixes = ("plugin-", "command-", "skill-", "agent-", "hooks-", "mcp-", "rules-")
        assert all(any(r.startswith(p) for p in valid_prefixes) for r in rules)

    def test_unknown_bundle_returns_none(self):
        assert get_bundle_rules("nonexistent") is None


class TestResolveNames:
    def test_resolve_bundle(self):
        rule_ids, was_bundle = resolve_names("agentskills")
        assert was_bundle is True
        assert len(rule_ids) > 0
        assert all(r.startswith("agentskill-") for r in rule_ids)

    def test_resolve_rule(self):
        rule_ids, was_bundle = resolve_names("plugin-json-valid")
        assert was_bundle is False
        assert rule_ids == ["plugin-json-valid"]

    def test_resolve_unknown(self):
        rule_ids, was_bundle = resolve_names("nonexistent")
        assert rule_ids == []
        assert was_bundle is False


class TestIsHelpers:
    def test_is_bundle(self):
        assert is_bundle("cursor") is True
        assert is_bundle("all") is True
        assert is_bundle("plugin-json-valid") is False
        assert is_bundle("nonexistent") is False

    def test_is_rule(self):
        assert is_rule("plugin-json-valid") is True
        assert is_rule("cursor") is False
        assert is_rule("nonexistent") is False


class TestEnableDisable:
    def test_disable_rules(self, tmp_path):
        results = disable_rules(["plugin-json-valid", "plugin-json-required"], tmp_path)
        assert ("plugin-json-valid", "disabled") in results
        assert ("plugin-json-required", "disabled") in results

        config_path = tmp_path / ".skillsaw.yaml"
        assert config_path.exists()
        data = yaml.safe_load(config_path.read_text())
        assert data["rules"]["plugin-json-valid"]["enabled"] is False
        assert data["rules"]["plugin-json-required"]["enabled"] is False

    def test_enable_after_disable(self, tmp_path):
        disable_rules(["plugin-json-valid"], tmp_path)
        results = enable_rules(["plugin-json-valid"], tmp_path)
        assert ("plugin-json-valid", "enabled") in results

        data = yaml.safe_load((tmp_path / ".skillsaw.yaml").read_text())
        assert data["rules"]["plugin-json-valid"]["enabled"] == "auto"

    def test_disable_already_disabled(self, tmp_path):
        disable_rules(["plugin-json-valid"], tmp_path)
        results = disable_rules(["plugin-json-valid"], tmp_path)
        assert ("plugin-json-valid", "already disabled") in results

    def test_enable_already_enabled(self, tmp_path):
        results = enable_rules(["plugin-json-valid"], tmp_path)
        assert ("plugin-json-valid", "already enabled") in results

    def test_dry_run_no_write(self, tmp_path):
        results = disable_rules(["plugin-json-valid"], tmp_path, dry_run=True)
        assert ("plugin-json-valid", "disabled") in results
        data = yaml.safe_load((tmp_path / ".skillsaw.yaml").read_text())
        assert data["rules"]["plugin-json-valid"]["enabled"] == "auto"

    def test_creates_config_if_missing(self, tmp_path):
        assert not (tmp_path / ".skillsaw.yaml").exists()
        disable_rules(["plugin-json-valid"], tmp_path)
        assert (tmp_path / ".skillsaw.yaml").exists()

    def test_preserves_other_rules(self, tmp_path):
        disable_rules(["plugin-json-valid"], tmp_path)
        data = yaml.safe_load((tmp_path / ".skillsaw.yaml").read_text())
        assert "plugin-json-required" in data["rules"]
        assert data["rules"]["plugin-json-required"]["enabled"] == "auto"


class TestCLI:
    def _run(self, *args, cwd=None):
        cmd = [sys.executable, "-m", "skillsaw"] + list(args)
        env = {"PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src")}
        import os

        env.update(os.environ)
        return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)

    def test_bundles_command(self):
        result = self._run("bundles")
        assert result.returncode == 0
        assert "agentskills" in result.stdout
        assert "plugin" in result.stdout
        assert "all" in result.stdout

    def test_enable_bundle(self, tmp_path):
        self._run("disable", "plugin", str(tmp_path))
        result = self._run("enable", "plugin", str(tmp_path))
        assert result.returncode == 0
        assert "plugin-json-valid" in result.stdout

    def test_disable_bundle(self, tmp_path):
        result = self._run("disable", "plugin", str(tmp_path))
        assert result.returncode == 0
        assert "plugin-json-valid" in result.stdout

    def test_enable_single_rule(self, tmp_path):
        self._run("disable", "plugin-json-valid", str(tmp_path))
        result = self._run("enable", "plugin-json-valid", str(tmp_path))
        assert result.returncode == 0
        assert "plugin-json-valid" in result.stdout

    def test_disable_single_rule(self, tmp_path):
        result = self._run("disable", "plugin-json-valid", str(tmp_path))
        assert result.returncode == 0
        assert "plugin-json-valid" in result.stdout

    def test_unknown_name_error(self, tmp_path):
        result = self._run("enable", "nonexistent-thing", str(tmp_path))
        assert result.returncode == 1
        assert "not a known rule or bundle" in result.stderr

    def test_dry_run(self, tmp_path):
        result = self._run("disable", "plugin", "--dry-run", str(tmp_path))
        assert result.returncode == 0
        assert "dry run" in result.stdout

    def test_disable_dry_run_no_write(self, tmp_path):
        self._run("disable", "plugin", "--dry-run", str(tmp_path))
        data = yaml.safe_load((tmp_path / ".skillsaw.yaml").read_text())
        assert data["rules"]["plugin-json-valid"]["enabled"] == "auto"
