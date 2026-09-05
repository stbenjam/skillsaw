"""Whole-index typing and accepted representations, derived from native controls."""

from __future__ import annotations

import copy
import json

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.formats.grok_display_index import CATEGORIES, read_display_index
from skillsaw.lint_target import GrokMarketplaceIndexNode
from tests.grok._helpers import copy_fixture, lint_json

INDEX = ".grok-plugin/plugin-index.json"


def documents(base):
    cases = {"baseline": (base, True)}

    def add(name, change, accepted=False):
        data = copy.deepcopy(base)
        result = change(data)
        cases[name] = (data if result is None else result, accepted)

    add("root-array", lambda d: [1, d["plugins"]], True)
    add(
        "entry-array",
        lambda d: d["plugins"].update(
            {"published-review": [None, d["plugins"]["published-review"]["components"]]}
        ),
        True,
    )
    add(
        "components-array",
        lambda d: d["plugins"]["published-review"].update(
            components=[[{"name": "review-migration"}]]
        ),
        True,
    )
    add(
        "item-array",
        lambda d: d["plugins"]["published-review"]["components"].update(
            skills=[["review-migration"]]
        ),
        True,
    )
    for value in (None, False, 1.0, "1", 2):
        add("version-" + repr(value), lambda d, v=value: d.update(version=v))
    add("version-missing", lambda d: (d.pop("version"), None)[1])
    add("entry-array-short", lambda d: d["plugins"].update({"published-review": [None]}))
    add("entry-array-long", lambda d: d["plugins"].update({"published-review": [None, {}, 0]}))
    add(
        "components-missing",
        lambda d: (d["plugins"]["published-review"].pop("components"), None)[1],
    )
    add("components-null", lambda d: d["plugins"]["published-review"].update(components=None))
    add(
        "description-number",
        lambda d: d["plugins"]["published-review"]["components"]["skills"][0].update(description=7),
    )
    add(
        "name-null",
        lambda d: d["plugins"]["published-review"]["components"]["skills"][0].update(name=None),
    )
    add("sha-number", lambda d: d["plugins"]["published-review"].update(sha=7))
    for category in CATEGORIES:
        add(
            "null-" + category,
            lambda d, c=category: d["plugins"]["published-review"]["components"].update({c: None}),
        )
    add("unknown-fields", lambda d: d["plugins"]["published-review"].update(future=[None, 4]), True)
    return cases


BASE = {
    "version": 1,
    "plugins": {
        "published-review": {"components": {"skills": [{"name": "review-migration"}]}},
        "catalog-canary": {"components": {"skills": [{"name": "review-catalog"}]}},
    },
}
CASES = documents(BASE)
RAW_CASES = {
    "duplicate-version": ('{"version":1,"version":1,"plugins":{}}', False),
    "duplicate-unknown": ('{"version":1,"future":1,"future":2}', True),
    "duplicate-map": (
        '{"version":1,"plugins":{"p":{"components":{}},"p":{"components":{}}}}',
        True,
    ),
    "duplicate-map-invalid-first": ('{"version":1,"plugins":{"p":4,"p":{"components":{}}}}', False),
    "duplicate-components": (
        '{"version":1,"plugins":{"p":{"components":{},"components":{}}}}',
        False,
    ),
    "duplicate-sha-null": (
        '{"version":1,"plugins":{"p":{"sha":null,"sha":"x","components":{}}}}',
        False,
    ),
    "bom": ('\ufeff{"version":1}', False),
}


@pytest.mark.parametrize("name", CASES)
def test_whole_index_decoder_cli(tmp_path, name):
    repo = copy_fixture("grok/index-keys", tmp_path)
    data, accepted = CASES[name]
    (repo / INDEX).write_text(json.dumps(data))
    report = lint_json(
        repo,
        "--rule",
        "grok-marketplace-index-parity",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert [n.path for n in RepositoryContext(repo).lint_tree.find(GrokMarketplaceIndexNode)] == [
        repo / INDEX
    ]
    found = report["violations"]
    if accepted:
        assert found == []
    else:
        assert len(found) == 1
        assert found[0]["file_path"] == INDEX
        assert found[0]["severity"] == "warning"
        assert found[0]["message"].startswith("Invalid display index:")
        assert "disagrees" not in found[0]["message"]


@pytest.mark.parametrize("name", RAW_CASES)
def test_duplicate_and_bom_contract(tmp_path, name):
    raw, accepted = RAW_CASES[name]
    path = tmp_path / "plugin-index.json"
    path.write_text(raw, encoding="utf-8")
    plugins, error = read_display_index(path)
    assert (error is None) == accepted, error
    assert (plugins is not None) == accepted


def test_omitted_plugins_defaults_empty_map(tmp_path):
    path = tmp_path / "plugin-index.json"
    path.write_text('{"version":1}')
    assert read_display_index(path) == ({}, None)


def test_component_option_does_not_hide_an_invalid_index(tmp_path):
    repo = copy_fixture("grok/index-keys", tmp_path)
    data = copy.deepcopy(BASE)
    data["plugins"]["published-review"]["components"]["skills"] = "review-migration"
    (repo / INDEX).write_text(json.dumps(data))
    (repo / ".skillsaw.yaml").write_text(
        "rules:\n  grok-marketplace-index-parity:\n    check-components: false\n    severity: info\n"
    )
    report = lint_json(
        repo,
        "--rule",
        "grok-marketplace-index-parity",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert len(report["violations"]) == 1
    assert report["violations"][0]["severity"] == "info"
    assert report["violations"][0]["message"].startswith("Invalid display index:")
