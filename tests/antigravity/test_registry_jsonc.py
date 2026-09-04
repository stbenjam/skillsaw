"""JSONC registries attach their targets even while shape lint is disabled."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillsaw.blocks import AntigravityAgentBlock
from skillsaw.blocks.json_config import AntigravityConfigBlock
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import AntigravityPluginConfigNode
from tests.cli_runner import run_cli

from ._helpers import copy_fixture

RULE = "antigravity-config-json-valid"
PLUGIN = "tools/shared/plugins/berth-tools/plugin.json"
AGENT = "tools/shared/agents/timetable-auditor.md"
REGISTRIES = {
    ".agents/agents.json": {"inherits": [{"path": "tools/shared/agent-defaults.json"}]},
    ".agents/plugins.json": {"entries": [{"path": "tools/shared/plugins"}]},
    "tools/shared/agent-defaults.json": {"entries": [{"path": "tools/shared/agents"}]},
}


def _lint(repo: Path, *, enabled: bool = False):
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
            *(["--rule", RULE] if enabled else []),
        ]
    )
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    assert isinstance(report["stats"], dict)
    assert isinstance(report["violations"], list)
    assert (RULE in report["stats"]["rules_run"]) is enabled
    return result.returncode, report


def _paths(context, node_type):
    return sorted(
        str(node.path.relative_to(context.root_path)) for node in context.lint_tree.find(node_type)
    )


@pytest.mark.parametrize("registry", list(REGISTRIES))
@pytest.mark.parametrize("syntax", ["line-comment", "block-comment", "trailing-comma"])
def test_jsonc_syntax_preserves_direct_and_inherited_targets(tmp_path, registry, syntax):
    repo = copy_fixture("antigravity/registry-jsonc", tmp_path)
    body = json.dumps(REGISTRIES[registry])
    if syntax == "line-comment":
        body = "// Shared scheduling configuration\n" + body
    elif syntax == "block-comment":
        body = "/* Shared scheduling configuration */\n" + body
    else:
        body = body[:-1] + ",}"
    (repo / registry).write_text(body)

    context = RepositoryContext(repo)
    assert _paths(context, AntigravityPluginConfigNode) == [PLUGIN]
    assert _paths(context, AntigravityAgentBlock) == [AGENT]
    assert _paths(context, AntigravityConfigBlock) == sorted(REGISTRIES)
    for enabled in (False, True):
        code, report = _lint(repo, enabled=enabled)
        assert code == 0
        assert report["violations"] == []
        assert report["stats"]["plugins"] == [str(repo / Path(PLUGIN).parent)]


def test_jsonc_registry_targets_reach_default_plugin_validation(tmp_path):
    repo = copy_fixture("antigravity/registry-jsonc", tmp_path)
    manifest = repo / PLUGIN
    data = json.loads(manifest.read_text())
    data["disabled"] = "false"
    manifest.write_text(json.dumps(data))
    code, report = _lint(repo)
    assert code == 1
    assert [(v["rule_id"], v["file_path"]) for v in report["violations"]] == [
        ("antigravity-plugin-json-valid", PLUGIN)
    ]
    assert "'disabled' must be a boolean" in report["violations"][0]["message"]


@pytest.mark.parametrize("registry", [".agents/agents.json", ".agents/plugins.json"])
@pytest.mark.parametrize("body", ["{'entries': []}", "{entries: []}"])
def test_json5_extensions_still_fail_and_drop_only_their_targets(tmp_path, registry, body):
    repo = copy_fixture("antigravity/registry-jsonc", tmp_path)
    (repo / registry).write_text(body)
    context = RepositoryContext(repo)
    assert _paths(context, AntigravityPluginConfigNode) == (
        [] if registry == ".agents/plugins.json" else [PLUGIN]
    )
    assert _paths(context, AntigravityAgentBlock) == (
        [] if registry == ".agents/agents.json" else [AGENT]
    )
    code, report = _lint(repo, enabled=True)
    assert code == 1
    assert [(v["rule_id"], v["file_path"], v["severity"]) for v in report["violations"]] == [
        (RULE, registry, "error")
    ]
    assert "does not parse" in report["violations"][0]["message"]


@pytest.mark.parametrize("jsonc", [False, True])
@pytest.mark.parametrize(
    "body",
    [
        '{"entries":[{"path":"tools/shared/plugins/berth-tools/agents"}],'
        '"entries":[{"path":"tools/shared/agents"}]}',
        '{"entries":[{"path":"tools/shared/plugins/berth-tools/agents",'
        '"path":"tools/shared/agents"}]}',
    ],
)
def test_duplicate_registry_keys_keep_only_the_last_directory(tmp_path, body, jsonc):
    repo = copy_fixture("antigravity/registry-jsonc", tmp_path)
    if jsonc:
        body = "/* Duplicate-key behavior is independent of comments. */\n" + body[:-1] + ",}"
    (repo / "tools/shared/agent-defaults.json").write_text(body)
    assert _paths(RepositoryContext(repo), AntigravityAgentBlock) == [AGENT]
    code, report = _lint(repo, enabled=True)
    assert code == 0
    assert report["violations"] == []


def test_commented_registry_preserves_child_containment(tmp_path):
    repo = copy_fixture("antigravity/registry-escape", tmp_path) / "repo"
    registry = repo / ".agents/plugins.json"
    registry.write_text(
        "// Only contained packages belong to the lint tree.\n" + registry.read_text()
    )
    context = RepositoryContext(repo)
    assert [
        node.path.parent.name for node in context.lint_tree.find(AntigravityPluginConfigNode)
    ] == ["inside"]
    escaped_plugin = repo / "tools/shared/plugins/berth-tools"
    assert escaped_plugin.is_symlink()
    assert escaped_plugin.resolve() == repo.parent / "outside/berth-tools"
    assert not context.provenance(escaped_plugin).antigravity
    code, report = _lint(repo, enabled=True)
    assert code == 0
    assert report["violations"] == []


def test_excluding_inherited_jsonc_leaves_the_other_registry_active(tmp_path):
    repo = copy_fixture("antigravity/registry-jsonc", tmp_path)
    context = RepositoryContext(repo, exclude_patterns=["tools/shared/agent-defaults.json"])
    assert _paths(context, AntigravityAgentBlock) == []
    assert _paths(context, AntigravityPluginConfigNode) == [PLUGIN]
    assert _paths(context, AntigravityConfigBlock) == [
        ".agents/agents.json",
        ".agents/plugins.json",
    ]
