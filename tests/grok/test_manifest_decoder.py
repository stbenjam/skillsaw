"""Pinned Grok manifest decoder cases, exercised through real CLI reports."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks import GrokInlineHooksBlock, GrokInlineMcpBlock, SkillBlock
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import GrokPluginConfigNode
from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokPluginJsonValidRule
from tests.grok._helpers import copy_fixture, lint_json

RULE = "grok-plugin-json-valid"
MANIFEST = ".grok-plugin/plugin.json"
OPTIONS = ("--rule", RULE, "--no-custom-rules", "--no-plugins", "--no-baseline")


def fixture(tmp_path):
    repo = copy_fixture("grok/manifest-decoder", tmp_path)
    path = repo / MANIFEST
    return repo, path, json.loads(path.read_text())


def report(repo, *, failed=False):
    result = lint_json(repo, *OPTIONS, returncode=int(failed))
    assert result["stats"]["rules_run"] == [RULE]
    assert "grok-plugin" in result["stats"]["repo_types"]
    tree = RepositoryContext(repo).lint_tree
    assert [node.path for node in tree.find(GrokPluginConfigNode)] == [repo / MANIFEST]
    assert tree.find(GrokPluginConfigNode)[0].plugin_dir == repo
    assert RepositoryContext(repo).provenance(repo).grok
    return result


def test_unknown_and_inline_duplicates_preserve_real_targets(tmp_path):
    repo, _path, _data = fixture(tmp_path)
    assert report(repo)["violations"] == []
    tree = RepositoryContext(repo).lint_tree
    assert [node.path for node in tree.find(SkillBlock)] == [
        repo / "skills/review-migration/SKILL.md"
    ]
    blocks = tree.find(GrokInlineMcpBlock)
    assert len(blocks) == 1
    assert (
        blocks[0].raw_data["mcpServers"]["reference-docs"]["url"]
        == "https://docs.example.invalid/current"
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", 1, "'version' must be a string or null"),
        ("description", False, "'description' must be a string or null"),
        ("homepage", 3, "'homepage' must be a string or null"),
        ("repository", {}, "'repository' must be a string or null"),
        ("license", [], "'license' must be a string or null"),
        ("author", "Data Platform", "'author' must be an object or null"),
        ("author", {"name": 1}, "'author.name' must be a string or null"),
        ("author", {"email": []}, "'author.email' must be a string or null"),
        ("author", {"url": False}, "'author.url' must be a string or null"),
        ("keywords", None, "'keywords' must be an array of strings"),
        ("keywords", ["review", 5], "'keywords' must be an array of strings"),
        ("keywords", "review", "'keywords' must be an array of strings"),
        ("skills", 42, "'skills' must be a path string, an array of path strings, or null"),
        (
            "skills",
            ["skills", 7],
            "'skills' must be a path string, an array of path strings, or null",
        ),
        ("commands", {}, "'commands' must be a path string, an array of path strings, or null"),
        ("agents", [None], "'agents' must be a path string, an array of path strings, or null"),
    ],
)
def test_invalid_typed_fields_fail_before_component_advice(tmp_path, field, value, message):
    repo, path, data = fixture(tmp_path)
    data[field] = value
    path.write_text(json.dumps(data))
    found = report(repo, failed=True)["violations"]
    assert [(v["rule_id"], v["file_path"], v["severity"], v["message"]) for v in found] == [
        (RULE, MANIFEST, "error", message)
    ]
    overridden = GrokPluginJsonValidRule({"severity": "warning"}).check(RepositoryContext(repo))
    assert [(v.severity, v.message) for v in overridden] == [(Severity.WARNING, message)]


@pytest.mark.parametrize(
    "field",
    [
        "version",
        "description",
        "homepage",
        "repository",
        "license",
        "author",
        "skills",
        "commands",
        "agents",
        "hooks",
        "mcpServers",
        "lspServers",
    ],
)
@pytest.mark.parametrize("present", [True, False])
def test_optional_null_and_omitted_members_stay_accepted(tmp_path, field, present):
    repo, path, data = fixture(tmp_path)
    if present:
        data[field] = None
    else:
        data.pop(field, None)
    path.write_text(json.dumps(data))
    found = report(repo)["violations"]
    assert all(v["severity"] == "info" for v in found)
    assert all(v["message"] == "Missing 'description'" for v in found)


@pytest.mark.parametrize("present", [True, False])
def test_keywords_default_or_empty_vector_is_accepted(tmp_path, present):
    repo, path, data = fixture(tmp_path)
    if present:
        data["keywords"] = []
    else:
        data.pop("keywords")
    path.write_text(json.dumps(data))
    assert report(repo)["violations"] == []


@pytest.mark.parametrize("field", ["name", "email", "url"])
@pytest.mark.parametrize("present", [True, False])
def test_author_members_are_nullable_optional_strings(tmp_path, field, present):
    repo, path, data = fixture(tmp_path)
    data["author"] = {
        "name": "Data Platform",
        "email": "platform@example.invalid",
        "url": "https://example.invalid",
    }
    if present:
        data["author"][field] = None
    else:
        data["author"].pop(field)
    path.write_text(json.dumps(data))
    assert report(repo)["violations"] == []


@pytest.mark.parametrize("field", ["skills", "commands", "agents"])
def test_empty_directory_vectors_are_valid_overrides(tmp_path, field):
    repo, path, data = fixture(tmp_path)
    data[field] = []
    path.write_text(json.dumps(data))
    assert report(repo)["violations"] == []


@pytest.mark.parametrize("value", [None, False, 7, {}, {"hooks": {}}, [], ["ignored"]])
@pytest.mark.parametrize("field", ["hooks", "mcpServers", "lspServers"])
def test_inline_components_keep_their_json_value_contract(tmp_path, field, value):
    repo, path, data = fixture(tmp_path)
    data[field] = value
    path.write_text(json.dumps(data))
    assert not [v for v in report(repo)["violations"] if v["severity"] == "error"]


@pytest.mark.parametrize(
    "field",
    [
        "name",
        "version",
        "description",
        "homepage",
        "repository",
        "license",
        "keywords",
        "author",
        "skills",
        "commands",
        "agents",
        "hooks",
        "mcpServers",
        "lspServers",
    ],
)
def test_known_top_level_duplicates_are_rejected(tmp_path, field):
    repo, path, data = fixture(tmp_path)
    value = data.setdefault(field, None if field != "keywords" else [])
    source = json.dumps(data)
    path.write_text(source[:-1] + "," + json.dumps(field) + ":" + json.dumps(value) + "}")
    found = report(repo, failed=True)["violations"]
    assert [v["message"] for v in found] == [f"Duplicate manifest field '{field}'"]
    assert found[0]["file_path"] == MANIFEST
    assert found[0]["severity"] == "error"


@pytest.mark.parametrize("field", ["name", "email", "url"])
def test_known_author_duplicates_are_rejected(tmp_path, field):
    repo, path, data = fixture(tmp_path)
    del data["author"]
    path.write_text(
        json.dumps(data)[:-1]
        + ',"author":{'
        + json.dumps(field)
        + ":null,"
        + json.dumps(field)
        + ":null}}"
    )
    assert [v["message"] for v in report(repo, failed=True)["violations"]] == [
        f"Duplicate manifest field 'author.{field}'"
    ]


@pytest.mark.parametrize("prefix", [b"", b"\xef\xbb\xbf"])
def test_manifest_bom_is_checked_before_text_normalization(tmp_path, prefix):
    repo, path, _data = fixture(tmp_path)
    path.write_bytes(prefix + path.read_bytes())
    found = report(repo, failed=bool(prefix))["violations"]
    if prefix:
        assert [(v["file_path"], v["severity"]) for v in found] == [(MANIFEST, "error")]
        assert "UTF-8 BOM" in found[0]["message"]
    else:
        assert found == []


def test_typed_error_does_not_remove_authored_hook_commands_from_the_tree(tmp_path):
    repo, path, data = fixture(tmp_path)
    data["version"] = 1
    data["hooks"] = {
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "printf inspect"}]}]}
    }
    path.write_text(json.dumps(data))
    assert (
        report(repo, failed=True)["violations"][0]["message"]
        == "'version' must be a string or null"
    )
    blocks = RepositoryContext(repo).lint_tree.find(GrokInlineHooksBlock)
    assert len(blocks) == 1
    assert blocks[0].raw_data == data["hooks"]
