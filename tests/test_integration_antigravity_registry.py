"""Registry aliases and ordered fields reach actual CLI targets by default."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks import AntigravityAgentBlock
from skillsaw.blocks.json_config import AntigravityConfigBlock
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import AntigravityPluginConfigNode
from tests.antigravity._helpers import copy_fixture
from tests.cli_runner import run_cli

RULE = "antigravity-config-json-valid"
PLUGIN = "tools/shared/plugins/berth-tools/plugin.json"
AGENT = "tools/shared/agents/timetable-auditor.md"
INHERITED = "tools/shared/agent-defaults.json"


def lint(repo, *, enabled=False):
    result = run_cli(
        [
            "lint",
            str(repo),
            "--no-custom-rules",
            "--no-plugins",
            "--no-baseline",
            "--format",
            "json",
            "--verbose",
            *(["--rule", RULE] if enabled else []),
        ]
    )
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    assert (RULE in report["stats"]["rules_run"]) is enabled
    return result.returncode, report


def paths(context, node_type):
    return sorted(
        str(b.path.relative_to(context.root_path)) for b in context.lint_tree.find(node_type)
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_cased_registries_load_agents_plugins_and_inheritance(tmp_path, enabled):
    repo = copy_fixture("antigravity/registry-decoder/accepted", tmp_path)
    context = RepositoryContext(repo)
    assert paths(context, AntigravityConfigBlock) == [
        ".agents/agents.json",
        ".agents/plugins.json",
        INHERITED,
    ]
    assert paths(context, AntigravityAgentBlock) == [AGENT]
    assert paths(context, AntigravityPluginConfigNode) == [PLUGIN]
    code, report = lint(repo, enabled=enabled)
    assert code == 0
    assert report["violations"] == []
    assert report["stats"]["plugins"] == [str(repo / "tools/shared/plugins/berth-tools")]


def test_discovered_plugin_is_validated_with_registry_rule_off(tmp_path):
    repo = copy_fixture("antigravity/registry-decoder/accepted", tmp_path)
    manifest = repo / PLUGIN
    data = json.loads(manifest.read_text())
    data["disabled"] = "false"
    manifest.write_text(json.dumps(data))
    code, report = lint(repo)
    assert code == 1
    assert [(v["rule_id"], v["file_path"]) for v in report["violations"]] == [
        ("antigravity-plugin-json-valid", PLUGIN)
    ]


def test_reused_paths_survive_shortening_and_regrowing_arrays(tmp_path):
    repo = copy_fixture("antigravity/registry-decoder/replaced", tmp_path)
    context = RepositoryContext(repo)
    assert paths(context, AntigravityAgentBlock) == [
        AGENT,
        "tools/shared/plugins/berth-tools/agents/berth-review.md",
    ]
    assert paths(context, AntigravityPluginConfigNode) == [PLUGIN]
    code, report = lint(repo, enabled=True)
    assert code == 0
    assert report["violations"] == []


@pytest.mark.parametrize("severity", ["error", "warning", "info"])
def test_ordered_errors_and_filter_types_keep_scope_and_severity(tmp_path, severity):
    repo = copy_fixture("antigravity/registry-decoder/invalid", tmp_path)
    (repo / ".skillsaw.yaml").write_text(f"rules:\n  {RULE}:\n    severity: {severity}\n")
    code, report = lint(repo, enabled=True)
    assert code == (1 if severity == "error" else 0)
    found = report["violations"]
    assert len(found) == 2
    assert {(v["rule_id"], v["file_path"], v["severity"]) for v in found} == {
        (RULE, INHERITED, severity),
        (RULE, ".agents/plugins.json", severity),
    }
    assert all("loads nothing from this registry" in v["message"] for v in found)
    assert any("Entries[0].EXCLUDE" in v["message"] for v in found)
    assert any("Entries must be an array" in v["message"] for v in found)


def test_accepted_empty_entries_and_null_root_are_clean(tmp_path):
    repo = copy_fixture("antigravity/registry-decoder/empty", tmp_path)
    context = RepositoryContext(repo)
    assert paths(context, AntigravityConfigBlock) == [".agents/agents.json", ".agents/plugins.json"]
    assert paths(context, AntigravityAgentBlock) == []
    assert paths(context, AntigravityPluginConfigNode) == []
    code, report = lint(repo, enabled=True)
    assert code == 0
    assert report["violations"] == []


def test_cased_inheritance_keeps_containment_and_exclusion(tmp_path):
    repo = copy_fixture("antigravity/registry-decoder/accepted", tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"Entries":42}')
    (repo / ".agents/agents.json").write_text('{"Inherits":[{"Path":"../outside.json"}]}')
    context = RepositoryContext(repo)
    assert paths(context, AntigravityConfigBlock) == [".agents/agents.json", ".agents/plugins.json"]
    assert paths(context, AntigravityAgentBlock) == []
    assert paths(context, AntigravityPluginConfigNode) == [PLUGIN]
    context = RepositoryContext(repo, exclude_patterns=[".agents/plugins.json"])
    assert paths(context, AntigravityPluginConfigNode) == []
    code, report = lint(repo, enabled=True)
    assert code == 0
    assert report["violations"] == []
