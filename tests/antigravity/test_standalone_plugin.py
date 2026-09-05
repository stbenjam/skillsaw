"""Standalone Antigravity packages use the shared discovery and plugin pass."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillsaw.blocks import AgentBlock
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import AntigravityPluginConfigNode, PluginNode
from skillsaw.repository_types import RepositoryType
from tests.cli_runner import run_cli

from ._helpers import copy_fixture

RULE = "antigravity-plugin-json-valid"


def _lint(repo: Path, *, forced: bool = False):
    result = run_cli(
        [
            "lint",
            str(repo),
            "--format",
            "json",
            "--verbose",
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
            *(["--type", "antigravity-plugin"] if forced else []),
        ]
    )
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    assert isinstance(report["stats"], dict)
    assert isinstance(report["violations"], list)
    return result.returncode, report


def _context(repo: Path, *, forced: bool = False):
    return RepositoryContext(
        repo, repo_types=[RepositoryType.ANTIGRAVITY_PLUGIN] if forced else None
    )


@pytest.mark.parametrize("forced", [False, True])
@pytest.mark.parametrize("disabled", [False, "false"])
def test_standalone_manifest_and_agent_reach_default_rules(tmp_path, forced, disabled):
    repo = copy_fixture("antigravity/standalone-plugin", tmp_path)
    manifest = repo / "plugin.json"
    data = json.loads(manifest.read_text())
    data["disabled"] = disabled
    manifest.write_text(json.dumps(data))

    context = _context(repo, forced=forced)
    assert context.antigravity_plugin_roots() == [repo]
    assert context.provenance(repo).antigravity_only
    nodes = context.lint_tree.find(AntigravityPluginConfigNode)
    assert [(node.path, node.plugin_owner) for node in nodes] == [(manifest, repo)]
    assert [node.path for node in context.lint_tree.find(AgentBlock)] == [
        repo / "agents/berth-review.md"
    ]

    code, report = _lint(repo, forced=forced)
    assert RULE in report["stats"]["rules_run"]
    if disabled is False:
        assert code == 0
        assert report["violations"] == []
    else:
        assert code == 1
        assert [(v["rule_id"], v["file_path"], v["severity"]) for v in report["violations"]] == [
            (RULE, "plugin.json", "error")
        ]
        assert "'disabled' must be a boolean" in report["violations"][0]["message"]


@pytest.mark.parametrize(
    "schema",
    [
        None,
        "https://antigravity.google/schemas/v2/plugin.json",
        "https://antigravity.google/schemas/v1/plugin.json#fragment",
        {"url": "https://antigravity.google/schemas/v1/plugin.json"},
    ],
)
def test_other_root_manifests_need_explicit_type(tmp_path, schema):
    repo = copy_fixture("antigravity/standalone-plugin", tmp_path)
    manifest = repo / "plugin.json"
    data = json.loads(manifest.read_text())
    data.pop("$schema")
    if schema is not None:
        data["$schema"] = schema
    data["disabled"] = "false"
    manifest.write_text(json.dumps(data))

    context = RepositoryContext(repo)
    assert RepositoryType.ANTIGRAVITY_PLUGIN not in context.repo_types
    assert not context.provenance(repo).antigravity
    assert context.lint_tree.find(AntigravityPluginConfigNode) == []
    code, report = _lint(repo)
    assert code == 0
    assert not [v for v in report["violations"] if v["rule_id"] == RULE]

    forced = _context(repo, forced=True)
    assert [node.path for node in forced.lint_tree.find(AntigravityPluginConfigNode)] == [manifest]
    code, report = _lint(repo, forced=True)
    assert code == 1
    assert [(v["rule_id"], v["file_path"]) for v in report["violations"]] == [(RULE, "plugin.json")]


def test_malformed_root_manifest_is_checked_when_forced(tmp_path):
    repo = copy_fixture("antigravity/standalone-plugin", tmp_path)
    manifest = repo / "plugin.json"
    manifest.write_text('{"name": "berth-tools",')
    assert RepositoryContext(repo).lint_tree.find(AntigravityPluginConfigNode) == []
    context = _context(repo, forced=True)
    assert [node.path for node in context.lint_tree.find(AntigravityPluginConfigNode)] == [manifest]
    code, report = _lint(repo, forced=True)
    assert code == 1
    assert [(v["rule_id"], v["file_path"]) for v in report["violations"]] == [(RULE, "plugin.json")]
    assert "does not parse" in report["violations"][0]["message"]


@pytest.mark.parametrize("override", [RepositoryType.MARKETPLACE, RepositoryType.CODEX_PLUGIN])
def test_schema_provenance_survives_another_forced_type(tmp_path, override):
    repo = copy_fixture("antigravity/standalone-plugin", tmp_path)
    context = RepositoryContext(repo, repo_types=[override])
    assert context.provenance(repo).antigravity
    assert [node.path for node in context.lint_tree.find(AntigravityPluginConfigNode)] == [
        repo / "plugin.json"
    ]
    assert [node.path for node in context.lint_tree.find(AgentBlock)] == [
        repo / "agents/berth-review.md"
    ]


def test_dual_manifest_root_has_one_shared_agent_and_both_claims(tmp_path):
    repo = copy_fixture("antigravity/standalone-plugin", tmp_path)
    marker = repo / ".claude-plugin"
    marker.mkdir()
    (marker / "plugin.json").write_text('{"name":"berth-tools","version":"1.0.0"}')
    context = RepositoryContext(repo)
    assert context.provenance(repo).ecosystems == frozenset({"antigravity", "claude"})
    assert [node.path for node in context.lint_tree.find(PluginNode)] == [repo]
    assert [node.path for node in context.lint_tree.find(AntigravityPluginConfigNode)] == [
        repo / "plugin.json"
    ]
    assert [node.path for node in context.lint_tree.find(AgentBlock)] == [
        repo / "agents/berth-review.md"
    ]
    code, report = _lint(repo)
    assert code == 0
    assert RULE in report["stats"]["rules_run"]
    assert not [v for v in report["violations"] if v["rule_id"] == RULE]


def test_forced_collection_does_not_add_an_empty_root_manifest(tmp_path):
    repo = copy_fixture("antigravity/portable-manifest", tmp_path)
    plugin = repo / ".agents/plugins/route-kit"
    (plugin / "plugin.json").unlink()
    context = _context(repo, forced=True)
    assert context.antigravity_plugins == [plugin]
    assert [node.path for node in context.lint_tree.find(AntigravityPluginConfigNode)] == [
        plugin / "plugin.json"
    ]
    code, report = _lint(repo, forced=True)
    assert code == 1
    findings = [v for v in report["violations"] if v["rule_id"] == RULE]
    assert [v["file_path"] for v in findings] == [".agents/plugins/route-kit/plugin.json"]
    assert "plugin.json is missing" in findings[0]["message"]


@pytest.mark.parametrize("forced", [False, True])
def test_escaping_root_manifest_is_not_read_or_claimed(tmp_path, monkeypatch, forced):
    from skillsaw.discovery import antigravity

    repo = copy_fixture("antigravity/standalone-plugin", tmp_path)
    manifest = repo / "plugin.json"
    outside = tmp_path / "outside-plugin.json"
    outside.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(outside)
    read = antigravity.read_json_strict

    def contained_read(path, *args, **kwargs):
        assert path.resolve() != outside, "Read an escaping standalone manifest"
        return read(path, *args, **kwargs)

    monkeypatch.setattr(antigravity, "read_json_strict", contained_read)
    context = _context(repo, forced=forced)
    assert context.antigravity_plugins == []
    assert not context.provenance(repo).antigravity
    assert context.lint_tree.find(AntigravityPluginConfigNode) == []
    code, report = _lint(repo, forced=forced)
    assert code == 0
    assert not [v for v in report["violations"] if v["rule_id"] == RULE]


def test_standalone_plugin_prose_still_honors_exclusions(tmp_path):
    repo = copy_fixture("antigravity/standalone-plugin", tmp_path)
    context = RepositoryContext(repo, exclude_patterns=["agents/**"])
    assert [node.path for node in context.lint_tree.find(AntigravityPluginConfigNode)] == [
        repo / "plugin.json"
    ]
    assert context.lint_tree.find(AgentBlock) == []
