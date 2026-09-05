"""Plugin component paths use canonical containment, not catalog grammar."""

from __future__ import annotations

import json

import pytest

from skillsaw.blocks import SkillBlock
from skillsaw.context import RepositoryContext
from skillsaw.formats.grok import grok_declared_skill_dirs
from tests.grok._helpers import copy_fixture, lint_json

CASES = ["nested/../skills", "", ".", "./", "absolute"]


def configure(repo, spelling):
    path = repo / ".grok-plugin/plugin.json"
    data = json.loads(path.read_text())
    data["skills"] = str(repo / "skills") if spelling == "absolute" else spelling
    path.write_text(json.dumps(data))


@pytest.mark.parametrize("spelling", CASES)
def test_contained_declaration_stays_visible_and_covers_conventions(tmp_path, spelling):
    repo = copy_fixture("grok/plugin-contained-paths", tmp_path)
    configure(repo, spelling)
    expected = repo if spelling in ("", ".", "./") else repo / "skills"
    assert grok_declared_skill_dirs(repo) == [expected]
    assert [node.path for node in RepositoryContext(repo).lint_tree.find(SkillBlock)] == [
        repo / "skills/review-migration/SKILL.md"
    ]
    report = lint_json(
        repo,
        "--rule",
        "grok-plugin-json-valid",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert report["stats"]["rules_run"] == ["grok-plugin-json-valid"]
    assert report["violations"] == []


def test_empty_file_field_still_needs_a_file(tmp_path):
    repo = copy_fixture("grok/plugin-contained-paths", tmp_path)
    path = repo / ".grok-plugin/plugin.json"
    data = json.loads(path.read_text())
    data["hooks"] = ""
    path.write_text(json.dumps(data))
    report = lint_json(
        repo,
        "--rule",
        "grok-plugin-json-valid",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    )
    assert [v["message"] for v in report["violations"]] == ["'hooks': '' is not a file"]
