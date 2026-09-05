"""Installer source discovery stops after the root or its immediate children."""

from __future__ import annotations

import shutil

import pytest

from skillsaw.blocks import SkillBlock
from skillsaw.context import RepositoryContext
from skillsaw.lint_target import GrokPluginConfigNode
from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokPluginStructureRule
from tests.grok._helpers import copy_fixture, lint_json

RULE = "grok-plugin-structure"
CONVENTIONAL = {
    "nested-skills",
    "root-skill",
    "placeholder-skills",
    "nested-agents",
    "placeholder-agents",
}
REFUSED = {"readme-only", "commands-only", "lsp-only"}


def test_realistic_structure_shapes_cli(tmp_path):
    repo = copy_fixture("grok/structure-shapes", tmp_path)
    report = lint_json(repo, "--rule", RULE, "--no-custom-rules", "--no-plugins", "--no-baseline")
    assert report["stats"]["rules_run"] == [RULE]
    warnings = [v for v in report["violations"] if v["severity"] == "warning"]
    naming = [v for v in report["violations"] if v["severity"] == "info"]
    assert {v["file_path"] for v in warnings} == {"packages/" + name for name in REFUSED}
    assert {v["file_path"] for v in naming} == {"packages/" + name for name in CONVENTIONAL}
    assert all("immediate child" in v["message"] for v in warnings)
    assert len(report["violations"]) == 8
    tree = RepositoryContext(repo).lint_tree
    assert {node.plugin_dir.name for node in tree.find(GrokPluginConfigNode)} == (
        CONVENTIONAL | REFUSED | {"child-bundle"}
    )
    assert repo / "packages/nested-skills/skills/database/review-migration/SKILL.md" in {
        node.path for node in tree.find(SkillBlock)
    }


@pytest.mark.parametrize(
    "variant, accepted",
    [
        ("manifest-only", True),
        ("invalid-manifest", False),
        ("invalid-manifest-with-skills", True),
        ("too-deep", False),
        ("symlink-child", False),
    ],
)
def test_child_bundle_boundary(tmp_path, variant, accepted):
    repo = copy_fixture("grok/structure-shapes", tmp_path)
    parent = repo / "packages/child-bundle"
    child = parent / "bundle"
    if variant != "invalid-manifest-with-skills":
        shutil.rmtree(child / "skills")
    if variant.startswith("invalid-manifest"):
        (child / "plugin.json").write_text('{"name":42}')
    elif variant == "too-deep":
        nested = child / "deeper"
        nested.mkdir()
        (child / "plugin.json").rename(nested / "plugin.json")
    elif variant == "symlink-child":
        outside = repo / "separate-bundle"
        child.rename(outside)
        child.symlink_to(outside, target_is_directory=True)
    found = [
        v for v in GrokPluginStructureRule().check(RepositoryContext(repo)) if v.file_path == parent
    ]
    if accepted:
        assert found == []
    else:
        assert len(found) == 1 and found[0].severity == Severity.WARNING
        assert "Grok installs nothing" in found[0].message


def test_installability_option_keeps_naming_advice_scoped_to_root(tmp_path):
    repo = copy_fixture("grok/structure-shapes", tmp_path)
    found = GrokPluginStructureRule({"check-installable": False}).check(RepositoryContext(repo))
    assert all(v.severity == Severity.INFO for v in found)
    assert repo / "packages/child-bundle" not in {v.file_path for v in found}
    assert repo / "packages/nested-skills" in {v.file_path for v in found}
