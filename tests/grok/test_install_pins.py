"""Install pin normalization must not change catalog/display identity."""

from __future__ import annotations

import json

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.formats.grok_install import effective_install_pin
from skillsaw.lint_target import GrokMarketplaceConfigNode, GrokPluginNode
from skillsaw.rules.builtin.grok import GrokMarketplaceJsonValidRule
from tests.grok._helpers import copy_fixture, lint_json
from tests.grok.test_marketplace_json import SHA_A, SHA_B, SHA_256

RULE = "grok-marketplace-json-valid"
CATALOG = ".grok-plugin/marketplace.json"
CASES = [
    ("sha", {"sha": SHA_A}, ("sha", SHA_A)),
    ("spaced-sha", {"sha": " \t" + SHA_A + "\n"}, ("sha", SHA_A)),
    ("unicode-sha", {"sha": "\u00a0" + SHA_A + "\u2003"}, ("sha", SHA_A)),
    ("ref", {"ref": SHA_A}, ("ref", SHA_A)),
    ("spaced-ref", {"ref": "\n" + SHA_A + " \t"}, ("ref", SHA_A)),
    ("unicode-ref", {"ref": "\u00a0" + SHA_A + "\u2003"}, ("ref", SHA_A)),
    ("null-sha", {"sha": None, "ref": SHA_A}, ("ref", SHA_A)),
    ("uppercase-ref", {"ref": SHA_A.upper()}, ("ref", SHA_A.upper())),
    ("long-ref", {"ref": SHA_256}, ("ref", SHA_256)),
    ("branch-and-sha", {"sha": SHA_A, "ref": "main"}, ("sha", SHA_A)),
    ("different-ref", {"sha": SHA_A, "ref": SHA_B}, ("sha", SHA_A)),
    ("missing", {}, ("sha", None)),
    ("branch", {"ref": "main"}, ("sha", None)),
    ("tag", {"ref": "v1.0.0"}, ("sha", None)),
    ("short-ref", {"ref": SHA_A[:7]}, ("sha", None)),
    ("empty-sha", {"sha": "", "ref": SHA_A}, ("sha", "")),
    ("blank-sha", {"sha": " \n", "ref": SHA_A}, ("sha", "")),
    ("bad-sha", {"sha": "main", "ref": SHA_A}, ("sha", "main")),
    ("short-sha", {"sha": SHA_A[:7], "ref": SHA_A}, ("sha", SHA_A[:7])),
    ("python-only-space-sha", {"sha": "\x1c" + SHA_A}, ("sha", "\x1c" + SHA_A)),
    ("python-only-space-ref", {"ref": "\x1c" + SHA_A}, ("sha", None)),
]


def fixture(tmp_path, source=None):
    repo = copy_fixture("grok/install-pins", tmp_path)
    path = repo / CATALOG
    if source is not None:
        data = json.loads(path.read_text())
        data["plugins"][0]["source"] = {
            "url": "https://example.invalid/remote-review.git",
            **source,
        }
        path.write_text(json.dumps(data))
    return repo, path


def report(repo, *, failed=False):
    result = lint_json(
        repo,
        "--rule",
        RULE,
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
        returncode=int(failed),
    )
    assert result["stats"]["rules_run"] == [RULE]
    assert "grok-marketplace" in result["stats"]["repo_types"]
    tree = RepositoryContext(repo).lint_tree
    assert [node.path for node in tree.find(GrokMarketplaceConfigNode)] == [repo / CATALOG]
    assert [node.path for node in tree.find(GrokPluginNode)] == [repo / "packages/local-canary"]
    return result


def test_actual_ref_and_whitespace_pins_pass_without_changing_source(tmp_path):
    repo, path = fixture(tmp_path)
    original = path.read_bytes()
    assert report(repo)["violations"] == []
    assert path.read_bytes() == original


@pytest.mark.parametrize("name,source,expected", CASES, ids=[row[0] for row in CASES])
def test_pin_selection_matches_the_released_install_contract(tmp_path, name, source, expected):
    field, pin = expected
    assert effective_install_pin(source.get("ref"), source.get("sha")) == expected
    repo, path = fixture(tmp_path, source)
    original = path.read_bytes()
    valid = (
        pin is not None and len(pin) in (40, 64) and all(c in "0123456789abcdefABCDEF" for c in pin)
    )
    found = report(repo, failed=not valid)["violations"]
    if valid:
        assert len(found) == int(len(pin) == 64 or pin != pin.lower())
        assert all(v["severity"] == "info" and f".source.{field} " in v["message"] for v in found)
    elif pin is None:
        assert len(found) == 1 and "has no 'sha' or full-commit 'ref' pin" in found[0]["message"]
    else:
        assert len(found) == 1 and ".source.sha " in found[0]["message"]
        assert "is not a 40 or 64 character hex commit id" in found[0]["message"]
    assert all(v["file_path"] == CATALOG for v in found)
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "source,expected_errors",
    [
        ({"ref": "main"}, 0),
        ({"ref": SHA_A}, 0),
        ({"sha": "bad", "ref": SHA_A}, 1),
    ],
)
def test_disabling_pin_policy_keeps_invalid_explicit_sha_errors(tmp_path, source, expected_errors):
    repo, _path = fixture(tmp_path, source)
    found = GrokMarketplaceJsonValidRule({"require-sha": False}).check(RepositoryContext(repo))
    assert len(found) == expected_errors
    if found:
        assert ".source.sha " in found[0].message


@pytest.mark.parametrize("field", ["ref", "sha"])
def test_typed_invalid_pin_fields_still_fail_before_pin_selection(tmp_path, field):
    repo, _path = fixture(tmp_path, {field: 3})
    found = report(repo, failed=True)["violations"]
    assert [v["message"] for v in found] == [f"plugins[0].source.{field} must be a string or null"]


def test_display_index_keeps_literal_sha_comparison(tmp_path):
    repo, path = fixture(tmp_path)
    raw = path.read_bytes()
    data = {
        "version": 1,
        "plugins": {
            "remote-review": {"sha": SHA_A, "components": {}},
            "schema-tools": {"sha": SHA_A, "components": {}},
            "local-canary": {"components": {"skills": [{"name": "review-catalog"}]}},
        },
    }
    (repo / ".grok-plugin/plugin-index.json").write_text(json.dumps(data))
    result = lint_json(
        repo,
        "--rule",
        RULE,
        "--rule",
        "grok-marketplace-index-parity",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert set(result["stats"]["rules_run"]) == {RULE, "grok-marketplace-index-parity"}
    found = result["violations"]
    assert len(found) == 1 and found[0]["rule_id"] == "grok-marketplace-index-parity"
    assert "'sha' in the index only: remote-review" in found[0]["message"]
    assert "'sha' differs: schema-tools" in found[0]["message"]
    assert path.read_bytes() == raw
