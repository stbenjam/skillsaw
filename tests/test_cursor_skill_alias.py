"""Cursor and portable discovery share one node per physical skill."""

import json

import pytest

from skillsaw.blocks import SkillBlock
from skillsaw.blocks.pi import PiSkillBlock
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.lint_target import SkillNode
from skillsaw.rules.builtin.agentskills.valid import AgentSkillValidRule
from tests.cli_runner import run_cli
from tests.test_integration import copy_fixture


@pytest.mark.parametrize("dual_pi", [False, True])
def test_local_alias_has_one_skill_and_no_missing_entrypoint(tmp_path, dual_pi):
    root = copy_fixture("cursor-plugins/skill-alias", tmp_path)
    if dual_pi:
        (root / "package.json").write_text('{"pi":{"skills":["./skills/review"]}}')
    context = RepositoryContext(root)
    nodes = context.lint_tree.find(SkillNode)
    assert len(nodes) == 1
    assert len(context.skills) == 1
    assert context.skills[0].resolve() == root / "skills/review"
    assert len(nodes[0].find(SkillBlock)) == 1
    assert not context.lint_tree.find(PiSkillBlock)
    if dual_pi:
        assert {"cursor", "pi"} <= context.provenance(root).ecosystems
    result = run_cli(
        ["lint", root, "--no-custom-rules", "--rule", "agentskill-valid", "--format", "json"]
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["violations"] == []


def test_pi_canonical_declaration_preserves_portable_alias_role(tmp_path, monkeypatch):
    root = copy_fixture("cursor-plugins/skill-alias", tmp_path)
    (root / "package.json").write_text('{"pi":{"skills":["./skills/review"]}}')
    # Generic discovery retains whichever spelling the filesystem walk finds
    # first. Force the alias case so Pi's canonical declaration must defer to
    # the portable owner regardless of checkout directory enumeration order.
    monkeypatch.setattr(
        "skillsaw.repository_scan.claude_discovery.discover_skills",
        lambda *_args, **_kwargs: [root / "review"],
    )
    context = RepositoryContext(root)
    assert context.skills == [root / "review"]
    nodes = context.lint_tree.find(SkillNode)
    assert len(nodes) == 1
    assert [block.path for block in nodes[0].find(SkillBlock)] == [root / "review/SKILL.md"]
    assert not context.lint_tree.find(PiSkillBlock)
    assert AgentSkillValidRule().check(context) == []


def test_missing_entrypoint_is_still_reported(tmp_path):
    root = copy_fixture("cursor-plugins/skill-alias", tmp_path)
    context = RepositoryContext(root)
    # The entrypoint disappears between discovery and tree construction.
    (root / "skills/review/SKILL.md").unlink()
    findings = AgentSkillValidRule().check(context)
    assert len(findings) == 1
    assert findings[0].message == "SKILL.md not found"


def test_escaping_alias_is_not_discovered(tmp_path):
    root = copy_fixture("cursor-plugins/skill-alias", tmp_path)
    (root / ".claude-plugin/plugin.json").unlink()
    (root / ".claude-plugin").rmdir()
    outside = tmp_path / "outside"
    (root / "skills/review").rename(outside)
    (root / "skills/review").symlink_to(outside, target_is_directory=True)
    context = RepositoryContext(root)
    assert not context.skills
    assert not context.lint_tree.find(SkillBlock)
    result = run_cli(
        ["lint", root, "--no-custom-rules", "--rule", "agentskill-valid", "--format", "json"]
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["violations"] == []


def test_pi_only_selection_remains_native_under_forced_cursor(tmp_path):
    root = copy_fixture("cursor-plugins/skill-alias", tmp_path)
    (root / ".cursor-plugin/plugin.json").unlink()
    (root / ".claude-plugin/plugin.json").unlink()
    (root / ".claude-plugin").rmdir()
    (root / ".cursor-plugin").rmdir()
    (root / "package.json").write_text('{"pi":{"skills":["./skills/review"]}}')
    context = RepositoryContext(root, repo_types={RepositoryType.CURSOR_PLUGIN})
    assert context.provenance(root).ecosystems == frozenset({"pi"})
    assert context.lint_tree.find(PiSkillBlock)
    assert not context.lint_tree.find(SkillBlock)
