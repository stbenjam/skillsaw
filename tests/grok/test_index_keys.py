"""Catalog lookup names are independent of the plugin's listing name."""

from __future__ import annotations

import copy
import json

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.lint_target import GrokMarketplaceConfigNode, GrokMarketplaceIndexNode, GrokPluginNode
from skillsaw.rules.builtin.grok import GrokMarketplaceIndexParityRule
from tests.grok._helpers import copy_fixture, lint_json

RULE = "grok-marketplace-index-parity"
CATALOG = ".grok-plugin/marketplace.json"
INDEX = ".grok-plugin/plugin-index.json"
CASES = [
    ("literal", "published-review", "literal", None),
    ("manifest", "published-review", "manifest", None),
    ("both-literal-correct", "published-review", "both", "manifest"),
    ("both-literal-stale", "published-review", "both", "literal"),
    ("empty-literal", "", "literal", None),
    ("empty-manifest", "", "manifest", None),
]


def configure(repo, name, keys, stale):
    catalog = repo / CATALOG
    data = json.loads(catalog.read_text())
    data["plugins"][0]["name"] = name
    catalog.write_text(json.dumps(data))
    index = repo / INDEX
    data = json.loads(index.read_text())
    entry = data["plugins"].pop("published-review")
    if keys in ("literal", "both"):
        data["plugins"][name] = copy.deepcopy(entry)
    if keys in ("manifest", "both"):
        data["plugins"]["migration-tools"] = copy.deepcopy(entry)
    if stale is not None:
        key = name if stale == "literal" else "migration-tools"
        data["plugins"][key]["components"]["skills"] = [{"name": "retired-review"}]
    index.write_text(json.dumps(data))


def check(repo):
    result = lint_json(
        repo,
        "--rule",
        RULE,
        "--rule",
        "grok-marketplace-json-valid",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert set(result["stats"]["rules_run"]) == {RULE, "grok-marketplace-json-valid"}
    assert "grok-marketplace" in result["stats"]["repo_types"]
    tree = RepositoryContext(repo).lint_tree
    assert [node.path for node in tree.find(GrokMarketplaceConfigNode)] == [repo / CATALOG]
    assert [node.path for node in tree.find(GrokMarketplaceIndexNode)] == [repo / INDEX]
    assert {node.path for node in tree.find(GrokPluginNode)} == {
        repo / "packages/migration-tools",
        repo / "packages/catalog-canary",
    }
    return result["violations"]


@pytest.mark.parametrize("case,name,keys,stale", CASES, ids=[row[0] for row in CASES])
def test_literal_catalog_keys_control_component_lookup(tmp_path, case, name, keys, stale):
    repo = copy_fixture("grok/index-keys", tmp_path)
    configure(repo, name, keys, stale)
    found = check(repo)
    if keys == "literal":
        assert found == []
        return
    assert len(found) == 1
    violation = found[0]
    assert (violation["rule_id"], violation["file_path"], violation["severity"]) == (
        RULE,
        INDEX,
        "warning",
    )
    parts = []
    display = name or '""'
    if keys == "manifest":
        parts.append("not in the index: " + display)
    parts.append("not in the catalog: migration-tools")
    if stale == "literal":
        parts.extend(
            [
                "skills only the index lists: published-review/retired-review",
                "skills only the plugin ships: published-review/review-migration",
            ]
        )
    assert violation[
        "message"
    ] == "plugin-index.json disagrees with marketplace.json: " + "; ".join(parts)


def test_component_option_preserves_literal_key_comparison(tmp_path):
    repo = copy_fixture("grok/index-keys", tmp_path)
    configure(repo, "published-review", "both", "literal")
    found = GrokMarketplaceIndexParityRule({"check-components": False}).check(
        RepositoryContext(repo)
    )
    assert [v.message for v in found] == [
        "plugin-index.json disagrees with marketplace.json: not in the catalog: migration-tools"
    ]


def test_an_unknown_empty_index_key_has_a_visible_label(tmp_path):
    repo = copy_fixture("grok/index-keys", tmp_path)
    path = repo / INDEX
    data = json.loads(path.read_text())
    data["plugins"][""] = {"components": {}}
    path.write_text(json.dumps(data))
    assert check(repo)[0]["message"] == (
        'plugin-index.json disagrees with marketplace.json: not in the catalog: ""'
    )
