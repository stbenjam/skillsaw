"""Catalog coordinates drive validation, ownership and display-index identity."""

from __future__ import annotations

import json

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.formats import grok
from skillsaw.lint_target import GrokMarketplaceConfigNode, GrokMarketplaceIndexNode, GrokPluginNode
from tests.grok._helpers import copy_fixture, lint_json, violations_for

CATALOG_RULE = "grok-marketplace-json-valid"
PARITY_RULE = "grok-marketplace-index-parity"
LOCAL_NAMES = {"almanac", "field-notes", "station-check", "canary"}


def _set_source(repo, source, index=0):
    catalog = repo / ".grok-plugin" / "marketplace.json"
    data = json.loads(catalog.read_text())
    data["plugins"][index]["source"] = source
    catalog.write_text(json.dumps(data), encoding="utf-8")


def _report(repo, *, returncode=0):
    report = lint_json(
        repo,
        "--rule",
        CATALOG_RULE,
        "--rule",
        PARITY_RULE,
        "--no-custom-rules",
        "--no-plugins",
        returncode=returncode,
    )
    assert set(report["stats"]["rules_run"]) == {CATALOG_RULE, PARITY_RULE}
    assert "grok-marketplace" in report["stats"]["repo_types"]
    return report


def _local_names(repo):
    context = RepositoryContext(repo)
    tree = context.lint_tree
    assert [node.path for node in tree.find(GrokMarketplaceConfigNode)] == [
        repo / ".grok-plugin" / "marketplace.json"
    ]
    assert [node.path for node in tree.find(GrokMarketplaceIndexNode)] == [
        repo / ".grok-plugin" / "plugin-index.json"
    ]
    nodes = tree.find(GrokPluginNode)
    assert len(nodes) == len({node.path for node in nodes})
    assert all(node.path.parent == repo / "packages" for node in nodes)
    return {node.path.name for node in nodes}


@pytest.mark.integration
@pytest.mark.parametrize(
    "source",
    [
        "./packages/almanac",
        "packages/almanac",
        "packages\\almanac",
        "./packages\\almanac",
        {"path": "./packages/almanac"},
        {"type": "local", "path": "./packages/almanac"},
        {"source": "local", "path": "./packages/almanac"},
        {"type": "other", "path": "./packages/almanac"},
        {"url": None, "path": "./packages/almanac"},
        {"source": "url", "path": "./packages/almanac"},
    ],
)
def test_valid_local_coordinates_keep_targets_and_index_identity(tmp_path, source):
    # No plugin has a Grok marker: each target must be reached through its
    # catalog source. The canary and remote pin also have matching index entries.
    repo = copy_fixture("grok/marketplace-sources", tmp_path)
    _set_source(repo, source)

    assert _local_names(repo) == LOCAL_NAMES
    assert _report(repo)["violations"] == []


@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    [
        ".",
        "./",
        "./.",
        "./packages/almanac/",
        "./packages//almanac",
        "packages/./almanac",
        "././packages/almanac",
        "packages/nested/../almanac",
        "packages\\\\almanac",
        ".\\packages\\almanac",
        "packages/almanac:other",
    ],
)
def test_invalid_local_path_components_are_reported_and_not_claimed(tmp_path, path):
    repo = copy_fixture("grok/marketplace-sources", tmp_path)
    _set_source(repo, {"url": None, "path": path})

    assert _local_names(repo) == LOCAL_NAMES - {"almanac"}
    report = _report(repo, returncode=1)
    found = violations_for(report, CATALOG_RULE)
    assert len(found) == 1
    assert found[0]["severity"] == "error"
    assert found[0]["file_path"] == ".grok-plugin/marketplace.json"
    assert "plugins[0].source" in found[0]["message"]
    drift = violations_for(report, PARITY_RULE)
    assert len(drift) == 1
    assert "not in the catalog: almanac" in drift[0]["message"]
    assert "canary" not in drift[0]["message"]


@pytest.mark.parametrize("field", ["url", "path"])
@pytest.mark.parametrize("value", [False, 0, [], {}])
def test_mistyped_coordinates_are_not_coerced_into_local_sources(tmp_path, field, value):
    repo = copy_fixture("grok/marketplace-sources", tmp_path)
    _set_source(repo, {"path": "./packages/almanac", field: value})

    assert _local_names(repo) == LOCAL_NAMES - {"almanac"}
    report = _report(repo, returncode=1)
    found = violations_for(report, CATALOG_RULE)
    assert [(v["severity"], v["message"]) for v in found] == [
        ("error", f"plugins[0].source.{field} must be a string or null")
    ]


def test_an_empty_url_does_not_fall_back_to_its_local_path(tmp_path):
    repo = copy_fixture("grok/marketplace-sources", tmp_path)
    _set_source(repo, {"url": "", "path": "./packages/almanac"})

    assert _local_names(repo) == LOCAL_NAMES - {"almanac"}
    report = _report(repo, returncode=1)
    assert [v["message"] for v in violations_for(report, CATALOG_RULE)] == [
        "plugins[0].source is a url source with no 'url' to clone"
    ]


@pytest.mark.parametrize("path", [None, "packages/almanac", "packages\\almanac"])
def test_a_remote_subdirectory_keeps_its_remote_identity(tmp_path, path):
    repo = copy_fixture("grok/marketplace-sources", tmp_path)
    catalog = json.loads((repo / ".grok-plugin" / "marketplace.json").read_text())
    source = {**catalog["plugins"][4]["source"], "path": path}
    _set_source(repo, source, index=4)

    assert _local_names(repo) == LOCAL_NAMES
    assert _report(repo)["violations"] == []


@pytest.mark.parametrize("path", ["", ".", "./", "packages/almanac/", "packages//almanac"])
@pytest.mark.parametrize("index_present", [True, False])
def test_invalid_remote_subdirectories_keep_display_identity(tmp_path, path, index_present):
    """Native listing still attaches indexed components to these entries.

    Installer rejection does not make them absent from the display catalog;
    omitting their index entry must still produce the ordinary parity warning.
    """
    repo = copy_fixture("grok/marketplace-sources", tmp_path)
    catalog = json.loads((repo / ".grok-plugin" / "marketplace.json").read_text())
    source = {**catalog["plugins"][4]["source"], "path": path}
    _set_source(repo, source, index=4)
    index_path = repo / ".grok-plugin" / "plugin-index.json"
    index = json.loads(index_path.read_text())
    if index_present:
        index["plugins"]["remote-kit"]["components"] = {
            "skills": [{"name": "remote-display-canary", "description": "Review remote metadata."}]
        }
    else:
        del index["plugins"]["remote-kit"]
    index_path.write_text(json.dumps(index), encoding="utf-8")

    assert _local_names(repo) == LOCAL_NAMES
    report = _report(repo)
    found = violations_for(report, CATALOG_RULE)
    assert len(found) == 1
    assert found[0]["severity"] == "warning"
    assert "relative subdirectory of the cloned repository" in found[0]["message"]
    drift = violations_for(report, PARITY_RULE)
    if index_present:
        assert drift == []
    else:
        assert [(v["severity"], v["file_path"], v["message"]) for v in drift] == [
            (
                "warning",
                ".grok-plugin/plugin-index.json",
                "plugin-index.json disagrees with marketplace.json: not in the index: remote-kit",
            )
        ]


def test_a_backslash_source_still_checks_canonical_containment(tmp_path):
    repo = copy_fixture("grok/marketplace-sources", tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "packages" / "external").symlink_to(outside, target_is_directory=True)
    _set_source(repo, {"url": None, "path": "packages\\external"})

    assert _local_names(repo) == LOCAL_NAMES - {"almanac"}
    report = _report(repo, returncode=1)
    found = violations_for(report, CATALOG_RULE)
    assert len(found) == 1
    assert "resolves outside the marketplace root" in found[0]["message"]


def test_plugin_component_paths_keep_their_distinct_resolution_contract(tmp_path):
    repo = copy_fixture("grok/marketplace-sources", tmp_path)
    plugin = repo / "packages" / "almanac"
    (plugin / "nested").mkdir()
    (plugin / "plugin.json").write_text(
        json.dumps({"name": "almanac", "skills": "nested/../skills"}), encoding="utf-8"
    )

    assert grok.grok_declared_skill_dirs(plugin) == [plugin / "skills"]
