"""Display index fallback is independent of marketplace catalog location."""

from __future__ import annotations

import json

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import GrokMarketplaceIndexNode
from tests.grok._helpers import copy_fixture, lint_json

PRIMARY = ".grok-plugin/plugin-index.json"
FALLBACK = ".claude-plugin/plugin-index.json"
CASES = ["fallback", "both", "broken-primary", "directory-primary", "root", "absent"]


def configure(repo, mode):
    primary = repo / PRIMARY
    fallback = repo / FALLBACK
    body = primary.read_text()
    if mode in ("fallback", "both", "broken-primary", "directory-primary"):
        fallback.parent.mkdir()
        fallback.write_text(body)
    if mode == "both":
        # The stale legal copy must not be compared once the preferred file wins.
        data = json.loads(body)
        data["plugins"] = {"retired": {"components": {}}}
        fallback.write_text(json.dumps(data))
    if mode == "broken-primary":
        primary.write_text('{"version":')
    elif mode == "directory-primary":
        primary.unlink()
        primary.mkdir()
    elif mode in ("fallback", "root", "absent"):
        primary.unlink()
    if mode == "root":
        (repo / "plugin-index.json").write_text(body)


@pytest.mark.parametrize("mode", CASES)
def test_selected_index_cli_and_targets(tmp_path, mode):
    repo = copy_fixture("grok/index-keys", tmp_path)
    configure(repo, mode)
    report = lint_json(
        repo,
        "--rule",
        "grok-marketplace-index-parity",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert report["stats"]["rules_run"] == ["grok-marketplace-index-parity"]
    nodes = RepositoryContext(repo).lint_tree.find(GrokMarketplaceIndexNode)
    observed = [(str(n.path.relative_to(repo)), n.stray, n.shadowed) for n in nodes]
    if mode in ("both", "broken-primary", "directory-primary"):
        assert observed == [(PRIMARY, False, False), (FALLBACK, False, True)]
    elif mode == "fallback":
        assert observed == [(FALLBACK, False, False)]
    elif mode == "root":
        assert observed == [("plugin-index.json", True, False)]
    else:
        assert observed == []
    found = report["violations"]
    if mode in ("broken-primary", "directory-primary", "root"):
        assert len(found) == 1
        assert found[0]["file_path"] == ("plugin-index.json" if mode == "root" else PRIMARY)
        assert ("must be in" if mode == "root" else "Invalid JSON") in found[0]["message"]
    else:
        assert found == []


def test_selected_fallback_is_compared(tmp_path):
    repo = copy_fixture("grok/index-keys", tmp_path)
    configure(repo, "fallback")
    path = repo / FALLBACK
    data = json.loads(path.read_text())
    data["plugins"].pop("published-review")
    path.write_text(json.dumps(data))
    report = lint_json(
        repo,
        "--rule",
        "grok-marketplace-index-parity",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert len(report["violations"]) == 1
    assert report["violations"][0]["file_path"] == FALLBACK
    assert "not in the index: published-review" in report["violations"][0]["message"]


@pytest.mark.parametrize("excluded", [False, True])
def test_primary_outside_lint_scope_still_shadows_fallback(tmp_path, excluded):
    repo = copy_fixture("grok/index-keys", tmp_path)
    configure(repo, "both")
    if excluded:
        context = RepositoryContext(repo, exclude_patterns=[PRIMARY])
    else:
        outside = tmp_path / "outside-index.json"
        outside.write_text((repo / PRIMARY).read_text())
        (repo / PRIMARY).unlink()
        (repo / PRIMARY).symlink_to(outside)
        context = RepositoryContext(repo)
    nodes = context.lint_tree.find(GrokMarketplaceIndexNode)
    assert [(n.path, n.stray, n.shadowed) for n in nodes] == [(repo / FALLBACK, False, True)]


def test_compatibility_alias_keeps_one_index_node(tmp_path):
    repo = copy_fixture("grok/index-keys", tmp_path)
    fallback = repo / FALLBACK
    fallback.parent.mkdir()
    fallback.symlink_to(repo / PRIMARY)
    nodes = RepositoryContext(repo).lint_tree.find(GrokMarketplaceIndexNode)
    assert [(n.path, n.stray, n.shadowed) for n in nodes] == [(repo / PRIMARY, False, False)]
