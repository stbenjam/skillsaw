"""``antigravity-plugin-json-valid``: the manifest is the marker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillsaw.repository_types import RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.antigravity.plugin_json_valid import AntigravityPluginJsonValidRule

from ._helpers import messages, only, run_rule, write_plugin, write_repo


def check(tmp_path: Path, name: str, manifest, *, raw: bool = False, repo_types=None):
    repo = write_repo(tmp_path / name)
    plugin = write_plugin(repo, "berth-tools", None if raw else manifest)
    if raw:
        (plugin / "plugin.json").write_text(manifest, encoding="utf-8")
    return run_rule(AntigravityPluginJsonValidRule, repo, repo_types=repo_types)


class TestAcceptedManifests:
    """Manifests ``agy`` loads, including every key it discards."""

    @pytest.mark.parametrize(
        "name,manifest",
        [
            (
                "full",
                {"name": "berth-tools", "description": "d", "disabled": False, "logo": "a.png"},
            ),
            ("name-only", {"name": "berth-tools"}),
            ("underscored", {"name": "berth_tools_2"}),
            ("uppercase", {"name": "BerthTools"}),
            ("disabled", {"name": "berth-tools", "disabled": True}),
            # Every other key is discarded as unknown and the plugin loads.
            ("schema", {"name": "berth-tools", "$schema": "https://agentplugins.org/x.json"}),
            ("version", {"name": "berth-tools", "version": "1.4.0"}),
            ("author-string", {"name": "berth-tools", "author": "Routeboard"}),
            ("author-object", {"name": "berth-tools", "author": {"name": "Routeboard"}}),
            ("inline-mcp", {"name": "berth-tools", "mcpServers": {"db": {"command": "x"}}}),
            ("keywords", {"name": "berth-tools", "keywords": ["berth", "ferry"]}),
        ],
    )
    def test_no_findings(self, tmp_path: Path, name: str, manifest) -> None:
        assert messages(check(tmp_path, name, manifest)) == []


class TestNotAPlugin:
    """A manifest that does not parse means the whole tree goes unloaded."""

    @pytest.mark.parametrize(
        "name,body,needle",
        [
            ("unparseable", '{"name": "berth-tools"', "does not parse"),
            ("array-root", '[{"name": "berth-tools"}]', "must be a JSON object"),
            ("string-root", '"berth-tools"', "must be a JSON object"),
            (
                "duplicate-name",
                '{"name": "a", "description": "d", "name": "b"}',
                'duplicate JSON object key: "name"',
            ),
        ],
    )
    def test_reported_at_error(self, tmp_path: Path, name: str, body: str, needle: str) -> None:
        found = only(check(tmp_path, name, body, raw=True), needle)
        assert found.severity == Severity.ERROR

    @pytest.mark.parametrize(
        "field,value,label",
        [
            ("name", 42, "string"),
            ("description", ["d"], "string"),
            ("disabled", "no", "boolean"),
            ("logo", {"path": "a.png"}, "string"),
        ],
    )
    def test_field_types(self, tmp_path: Path, field: str, value, label: str) -> None:
        manifest = {"name": "berth-tools"}
        manifest[field] = value
        found = only(check(tmp_path, f"type-{field}", manifest), f"'{field}' must be a {label}")
        assert found.severity == Severity.ERROR

    def test_missing_manifest_under_a_forced_type(self, tmp_path: Path) -> None:
        """``--type antigravity-plugin`` is what asks for this check."""
        violations = check(
            tmp_path,
            "forced-missing",
            None,
            raw=False,
            repo_types=[RepositoryType.ANTIGRAVITY_PLUGIN],
        )
        found = only(violations, "plugin.json is missing")
        assert found.severity == Severity.ERROR


class TestInstallability:
    """What discovery tolerates and ``agy plugin install`` refuses."""

    @pytest.mark.parametrize("name", ("Berth Tools", "berth/tools", "../escape", ".hidden", ""))
    def test_uninstallable_names(self, tmp_path: Path, name: str) -> None:
        found = only(
            check(tmp_path, f"charset-{abs(hash(name))}", {"name": name}), "is not installable"
        )
        assert found.severity == Severity.WARNING

    def test_absent_name_is_advisory(self, tmp_path: Path) -> None:
        found = only(check(tmp_path, "unnamed", {}), "'name' is absent")
        assert found.severity == Severity.INFO

    def test_absent_name_is_not_also_a_charset_finding(self, tmp_path: Path) -> None:
        assert len(check(tmp_path, "unnamed-once", {})) == 1

    def test_mistyped_name_is_not_also_a_charset_finding(self, tmp_path: Path) -> None:
        violations = check(tmp_path, "mistyped-once", {"name": 42})
        assert len(violations) == 1
        assert "must be a string" in violations[0].message


class TestUnknownKeysAreNeverReported:
    """``$schema``, ``version`` and ``author`` are discarded by ``agy``."""

    def test_a_dense_foreign_manifest_reports_nothing(self, tmp_path: Path) -> None:
        manifest = {
            "$schema": "https://agentplugins.org/schemas/v1/plugin.json",
            "name": "route-kit",
            "version": "1.4.0",
            "author": {"name": "Routeboard"},
            "homepage": "https://routeboard.example",
            "license": "Apache-2.0",
            "entrypoint": "./bin/route-kit",
        }
        assert messages(check(tmp_path, "foreign", manifest)) == []


class TestDiagnosticSafety:
    """A hostile manifest cannot write its own content into the report."""

    def test_lone_surrogate_in_a_name(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "surrogate")
        plugin = write_plugin(repo, "berth-tools", None)
        (plugin / "plugin.json").write_text(
            json.dumps({"name": "berth\ud800tools"}), encoding="utf-8"
        )
        rendered = messages(run_rule(AntigravityPluginJsonValidRule, repo))
        assert rendered
        for message in rendered:
            message.encode("utf-8")

    def test_rtl_override_in_a_name(self, tmp_path: Path) -> None:
        repo = write_repo(tmp_path / "rtl")
        write_plugin(repo, "berth-tools", {"name": "berth‮tools"})
        rendered = messages(run_rule(AntigravityPluginJsonValidRule, repo))
        assert rendered
        assert all("‮" not in message for message in rendered)


class TestGating:
    """``auto``, versioned, and gated on the two Antigravity types."""

    def test_rule_declares_the_release_it_shipped_in(self) -> None:
        assert AntigravityPluginJsonValidRule.since == "0.20.0"
        assert AntigravityPluginJsonValidRule.default_enabled == "auto"

    def test_repo_types(self) -> None:
        assert AntigravityPluginJsonValidRule.repo_types == frozenset(
            {RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN}
        )

    def test_severity_override_reaches_the_default_findings(self, tmp_path: Path) -> None:
        from tests.test_integration import run_lint

        repo = write_repo(tmp_path / "override")
        write_plugin(repo, "berth-tools", {"name": 42})
        (repo / ".skillsaw.yaml").write_text(
            "rules:\n  antigravity-plugin-json-valid:\n    severity: warning\n", encoding="utf-8"
        )
        report = run_lint(repo)["out"] or {}
        severities = {
            v["severity"]
            for v in report.get("violations", [])
            if v["rule_id"] == "antigravity-plugin-json-valid"
        }
        assert severities == {"warning"}
