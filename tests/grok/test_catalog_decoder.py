"""Native-derived catalog decoder controls with listing and fallback canaries."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks import SkillBlock
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import GrokMarketplaceConfigNode, GrokPluginNode
from skillsaw.rules.builtin.grok import GrokMarketplaceJsonValidRule
from skillsaw.rule import Severity
from tests.grok._helpers import copy_fixture, lint_json

RULE = "grok-marketplace-json-valid"
PARITY = "grok-marketplace-index-parity"
CATALOG = ".grok-plugin/marketplace.json"
OPTIONS = ("--no-custom-rules", "--no-plugins", "--no-baseline")
BAD_FIELDS = [
    ("name", None, "Marketplace catalog 'name' must be a string"),
    ("name", 3, "Marketplace catalog 'name' must be a string"),
    ("description", 3, "Marketplace catalog description must be a string or null"),
    ("owner", "Platform", "owner must be an object or null"),
    ("owner", {}, "owner missing required 'name'"),
    ("owner.name", None, "owner 'name' must be a string"),
    ("owner.name", 3, "owner 'name' must be a string"),
    ("owner.email", False, "owner.email must be a string or null"),
    ("plugins", None, "'plugins' must be an array"),
    ("plugins", {}, "'plugins' must be an array"),
    ("plugins.0", "tools", "plugins[0] must be an object"),
    ("plugins.0.name", None, "plugins[0] 'name' must be a string"),
    ("plugins.0.name", 3, "plugins[0] 'name' must be a string"),
    ("plugins.0.version", 3, "plugins[0].version must be a string or null"),
    ("plugins.0.description", False, "plugins[0].description must be a string or null"),
    ("plugins.0.category", [], "plugins[0].category must be a string or null"),
    ("plugins.0.homepage", {}, "plugins[0].homepage must be a string or null"),
    ("plugins.0.author", 3, "plugins[0].author must be an object or null"),
    ("plugins.0.author", {}, "plugins[0].author missing required 'name'"),
    ("plugins.0.author.name", 3, "plugins[0].author 'name' must be a string"),
    ("plugins.0.author.name", None, "plugins[0].author 'name' must be a string"),
    ("plugins.0.source", 3, "plugins[0].source must be a path string or an object"),
]
BAD_FIELDS += [
    (f"plugins.0.{field}", value, f"plugins[0].{field} must be an array of strings")
    for field in ("tags", "keywords", "domains")
    for value in (None, "review", ["review", 3])
]
BAD_FIELDS += [
    (f"plugins.0.source.{field}", 3, f"plugins[0].source.{field} must be a string or null")
    for field in ("type", "source", "url", "path", "ref", "sha")
]
OPTIONALS = [
    "description",
    "owner",
    "owner.email",
    "plugins.0.description",
    "plugins.0.version",
    "plugins.0.category",
    "plugins.0.homepage",
    "plugins.0.author",
    "plugins.0.source.type",
    "plugins.0.source.source",
    "plugins.0.source.url",
    "plugins.0.source.ref",
    "plugins.0.source.sha",
]
DUPLICATES = (
    [("", field) for field in ("name", "description", "owner", "plugins")]
    + [("owner", field) for field in ("name", "email")]
    + [
        ("plugins.0", field)
        for field in (
            "name",
            "version",
            "description",
            "category",
            "homepage",
            "author",
            "source",
            "tags",
            "keywords",
            "domains",
        )
    ]
    + [("plugins.0.author", "name")]
)


def set_value(data, path, value, *, remove=False):
    parts = path.split(".")
    parent = data
    for key in parts[:-1]:
        parent = parent[int(key)] if isinstance(parent, list) else parent[key]
    key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
    if remove:
        parent.pop(key, None)
    else:
        parent[key] = value


def fixture(tmp_path):
    repo = copy_fixture("grok/catalog-decoder", tmp_path)
    path = repo / CATALOG
    return repo, path, json.loads(path.read_text())


def report(repo, *, failed=False, parity=True):
    rules = ("--rule", RULE, "--rule", PARITY) if parity else ("--rule", RULE)
    result = lint_json(repo, *rules, *OPTIONS, returncode=int(failed))
    assert set(result["stats"]["rules_run"]) == ({RULE, PARITY} if parity else {RULE})
    assert "grok-marketplace" in result["stats"]["repo_types"]
    assert [
        node.path for node in RepositoryContext(repo).lint_tree.find(GrokMarketplaceConfigNode)
    ] == [repo / CATALOG]
    return result


def assert_local_targets(repo):
    context = RepositoryContext(repo)
    plugins = context.lint_tree.find(GrokPluginNode)
    expected = {
        repo / "packages/migration-tools",
        repo / "packages/catalog-canary",
        repo / "plugins/fallback-canary",
    }
    assert {node.path for node in plugins} == expected
    assert all(context.provenance(path).grok for path in expected)
    skills = {node.path for node in context.lint_tree.find(SkillBlock)}
    assert {
        path / "skills" / name / "SKILL.md"
        for path, name in [
            (repo / "packages/migration-tools", "review-migration"),
            (repo / "packages/catalog-canary", "review-catalog"),
        ]
    } <= skills


def test_accepted_unknown_and_source_duplicates_keep_targets_and_parity(tmp_path):
    repo, _path, _data = fixture(tmp_path)
    assert report(repo)["violations"] == []
    assert_local_targets(repo)


@pytest.mark.parametrize("field,value,message", BAD_FIELDS)
def test_bad_typed_member_rejects_whole_catalog_and_skips_parity(tmp_path, field, value, message):
    repo, path, data = fixture(tmp_path)
    set_value(data, field, value)
    path.write_text(json.dumps(data))
    found = report(repo, failed=True)["violations"]
    assert [(v["rule_id"], v["file_path"], v["severity"], v["message"]) for v in found] == [
        (RULE, CATALOG, "error", message)
    ]
    assert [
        (v.severity, v.message)
        for v in GrokMarketplaceJsonValidRule({"severity": "warning"}).check(
            RepositoryContext(repo)
        )
    ] == [(Severity.WARNING, message)]


@pytest.mark.parametrize("field", ["name", "owner.name", "plugins.0.name", "plugins.0.author.name"])
def test_required_names_are_distinct_from_empty_strings(tmp_path, field):
    repo, path, data = fixture(tmp_path)
    set_value(data, field, None, remove=True)
    path.write_text(json.dumps(data))
    found = report(repo, failed=True)["violations"]
    assert len(found) == 1
    assert "missing required 'name'" in found[0]["message"]
    set_value(data, field, "")
    path.write_text(json.dumps(data))
    # The local empty catalog name has a distinct display-index identity;
    # this assertion covers decoding and discovery, not that other consumer.
    assert report(repo, parity=False)["violations"] == []
    assert_local_targets(repo)


@pytest.mark.parametrize("field", OPTIONALS)
@pytest.mark.parametrize("present", [False, True])
def test_optional_members_accept_omission_or_null(tmp_path, field, present):
    repo, path, data = fixture(tmp_path)
    set_value(data, field, None, remove=not present)
    path.write_text(json.dumps(data))
    assert report(repo)["violations"] == []
    assert_local_targets(repo)


@pytest.mark.parametrize("field", ["tags", "keywords", "domains"])
@pytest.mark.parametrize("present", [False, True])
def test_defaulted_entry_vectors_accept_omission_or_empty_list(tmp_path, field, present):
    repo, path, data = fixture(tmp_path)
    set_value(data, "plugins.0." + field, [], remove=not present)
    path.write_text(json.dumps(data))
    assert report(repo)["violations"] == []


@pytest.mark.parametrize("present", [False, True])
def test_empty_catalog_does_not_claim_catalog_only_packages(tmp_path, present):
    repo, path, data = fixture(tmp_path)
    set_value(data, "plugins", [], remove=not present)
    path.write_text(json.dumps(data))
    assert report(repo, parity=False)["violations"] == []
    context = RepositoryContext(repo)
    # The fallback's explicit marker remains diagnostic evidence regardless
    # of whether this catalog causes the native scanner to list it.
    assert [node.path for node in context.lint_tree.find(GrokPluginNode)] == [
        repo / "plugins/fallback-canary"
    ]
    assert not context.provenance(repo / "packages/migration-tools").grok
    assert not context.provenance(repo / "packages/catalog-canary").grok


def duplicate(data, path, field):
    """Serialize one duplicated known struct field without normalizing it."""
    target = data
    for key in path.split(".") if path else []:
        target = target[int(key)] if isinstance(target, list) else target[key]
    value = target.setdefault(field, None)
    marker = "__catalog_duplicate_control__"
    target[field] = marker
    return json.dumps(data).replace(
        json.dumps(field) + ": " + json.dumps(marker),
        json.dumps(field)
        + ": "
        + json.dumps(value)
        + ", "
        + json.dumps(field)
        + ": "
        + json.dumps(value),
        1,
    )


@pytest.mark.parametrize("path,field", DUPLICATES)
def test_known_struct_duplicates_reject_the_catalog(tmp_path, path, field):
    repo, file, data = fixture(tmp_path)
    file.write_text(duplicate(data, path, field))
    found = report(repo, failed=True)["violations"]
    assert len(found) == 1
    assert found[0]["message"].startswith("Duplicate catalog field")
    assert found[0]["file_path"] == CATALOG


@pytest.mark.parametrize("field", ["type", "source", "path", "url", "ref", "sha"])
def test_source_duplicates_decode_every_value_before_last_wins(tmp_path, field):
    repo, path, data = fixture(tmp_path)
    data["plugins"][0]["source"] = {"path": "./packages/migration-tools"}
    raw = json.dumps(data)
    original = json.dumps(data["plugins"][0]["source"])
    replacement = '{"' + field + '": 3, ' + original[1:]
    if field != "path":
        replacement = replacement[:-1] + ', "' + field + '": null}'
    path.write_text(raw.replace(original, replacement, 1))
    assert [v["message"] for v in report(repo, failed=True)["violations"]] == [
        f"plugins[0].source.{field} must be a string or null"
    ]


@pytest.mark.parametrize("prefix", [b"", b"\xef\xbb\xbf"])
def test_bom_rejection_is_distinct_from_an_empty_catalog(tmp_path, prefix):
    repo, path, _data = fixture(tmp_path)
    path.write_bytes(prefix + path.read_bytes())
    found = report(repo, failed=bool(prefix))["violations"]
    if prefix:
        assert len(found) == 1 and "UTF-8 BOM" in found[0]["message"]
    else:
        assert found == []


def test_bad_metadata_keeps_declared_diagnostic_ownership(tmp_path):
    repo, path, data = fixture(tmp_path)
    data["description"] = 3
    path.write_text(json.dumps(data))
    assert report(repo, failed=True)["violations"][0]["message"] == (
        "Marketplace catalog description must be a string or null"
    )
    assert_local_targets(repo)
