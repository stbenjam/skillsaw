"""Discovery and block contracts for repository-authored Kiro resources."""

from collections import Counter
import json
from pathlib import Path

import pytest

from skillsaw.blocks import ContentBlock, SkillBlock
from skillsaw.blocks.kiro import (
    KiroAgentConfigRole,
    KiroInlineMcpBlock,
    KiroJsonAgentBlock,
    KiroMarkdownAgentBlock,
    KiroMcpBlock,
    KiroSteeringBlock,
)
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.formats.kiro import agent_field_problems, mcp_field_problems
from tests.test_integration import copy_fixture
from tests.test_integration import run_lint, violations


def test_native_nodes_and_content_are_attached_once(tmp_path):
    repo = copy_fixture("kiro/valid", tmp_path)
    context = RepositoryContext(repo)
    tree = context.lint_tree
    assert RepositoryType.KIRO in context.repo_types
    assert len(tree.find(KiroAgentConfigRole)) == 4
    assert len(tree.find(KiroSteeringBlock)) == 2
    assert len(tree.find(KiroMcpBlock)) == 1
    assert len(tree.find(KiroInlineMcpBlock)) == 2
    assert len(tree.find(SkillBlock)) == 1
    contents = tree.find(ContentBlock)
    counts = Counter(block.path for block in contents)
    assert max(counts.values()) == 1
    bodies = "\n".join(block.read_body(strip_code_blocks=False) or "" for block in contents)
    assert "allowedCommands" not in bodies
    assert "permissions:" not in bodies
    assert "Service review" in bodies
    assert "API conventions" in bodies
    assert repo / ".kiro/settings/mcp.json" not in counts
    assert repo / ".kiro/agents/legacy.json" not in counts


@pytest.mark.parametrize(
    "resource",
    [
        ".kiro/steering/nested/test.md",
        ".kiro/agents/nested/test.json",
        ".kiro/agents/nested/test.md",
        ".kiro/settings/mcp.json",
        ".kiro/skills/test/SKILL.md",
    ],
)
def test_each_nested_marker_activates_its_tool_type(tmp_path, resource):
    path = tmp_path / "packages/service" / resource
    path.parent.mkdir(parents=True)
    path.write_text("{}" if path.suffix == ".json" else "# Service conventions\n")
    context = RepositoryContext(tmp_path)
    assert RepositoryType.KIRO in context.repo_types
    assert any(block.path == path for block in context.lint_tree.walk())


def test_excluded_and_external_resources_do_not_attach(tmp_path):
    repo = copy_fixture("kiro/valid", tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "agent.json").write_text('{"prompt":"External secret"}')
    (repo / ".kiro/agents/outside").symlink_to(outside, target_is_directory=True)
    (repo / ".kiro/agents/external.json").symlink_to(outside / "agent.json")
    context = RepositoryContext(repo, exclude_patterns=[".kiro/steering", "packages/api/.kiro"])
    tree = context.lint_tree
    assert not tree.find(KiroSteeringBlock)
    assert len(tree.find(KiroAgentConfigRole)) == 3
    assert not any("External secret" in (b.read_body() or "") for b in tree.find(ContentBlock))


def test_prompt_reuses_existing_steering_content(tmp_path):
    repo = copy_fixture("kiro/valid", tmp_path)
    path = repo / ".kiro/agents/shared.json"
    path.write_text('{"prompt":"file://../steering/backend/api.md"}')
    tree = RepositoryContext(repo).lint_tree
    target = repo / ".kiro/steering/backend/api.md"
    assert sum(b.path == target for b in tree.find(ContentBlock)) == 1


def test_native_references_respect_containment_and_exclusions(tmp_path):
    repo = copy_fixture("kiro/valid", tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("# Private instructions\n\nexternal-reference-marker\n")
    prompts = repo / ".kiro/prompts"
    (prompts / "external.md").symlink_to(outside)
    excluded = prompts / "excluded/private.md"
    excluded.parent.mkdir()
    excluded.write_text("# Excluded instructions\n\nexcluded-reference-marker\n")
    for name, prompt, resource in (
        ("escape", "../../../outside.md", "../outside.md"),
        ("symlink", "../prompts/external.md", ".kiro/prompts/external.md"),
        ("excluded", "../prompts/excluded/private.md", ".kiro/prompts/excluded/private.md"),
    ):
        (repo / f".kiro/agents/{name}.json").write_text(
            json.dumps({"prompt": f"file://{prompt}", "resources": [f"file://{resource}"]})
        )
    with (repo / ".skillsaw.yaml").open("a") as stream:
        stream.write('exclude:\n  - ".kiro/prompts/excluded/**"\n')
    tree = RepositoryContext(repo, exclude_patterns=[".kiro/prompts/excluded/**"]).lint_tree
    contents = tree.find(ContentBlock)
    bodies = "\n".join(block.read_body(strip_code_blocks=False) or "" for block in contents)
    assert "external-reference-marker" not in bodies
    assert "excluded-reference-marker" not in bodies
    assert any(block.path == prompts / "review.md" for block in contents)
    assert any("packages/api/.kiro" in str(block.path) for block in contents)
    result = run_lint(repo, "--rule", "kiro-references")
    assert result["rc"] == 0, result
    assert violations(result) == []


@pytest.mark.parametrize(
    "data",
    [
        {"allowedTools": ["fs_read"], "toolsSettings": {"fs_read": {"allowedPaths": ["src/**"]}}},
        {"permissions": {"rules": [{"capability": "future-capability", "effect": "allow"}]}},
        {"name": "kiro_default", "model": "private-model-id", "prompt": None},
        {"hooks": {"agentSpawn": [{"command": "git status"}]}},
        {"hooks": [{"trigger": "agentSpawn", "action": {"command": "git status"}}]},
    ],
)
def test_version_specific_policies_are_not_inferred(data):
    assert list(agent_field_problems(data)) == []


@pytest.mark.parametrize(
    "data",
    [
        {"disabled": True},
        {"disabledTools": ["delete"]},
        {"type": "http", "url": "https://mcp.example.com", "command": "", "env": None},
        {"url": "https://mcp.example.com", "oauth": None, "future": True},
    ],
)
def test_partial_and_legacy_mcp_records_are_accepted(data):
    assert list(mcp_field_problems(data)) == []


def test_instruction_suffix_keeps_native_metadata_owner(tmp_path):
    repo = copy_fixture("kiro/broken", tmp_path)
    # Keep this suffix out of the committed fixture: APM compiles every
    # repository *.instructions.md into this project's own instructions.
    for relative in ("steering/nested/policy.md", "agents/team/reviewer.md"):
        source = repo / "packages/api/.kiro" / relative
        source.rename(source.with_suffix(".instructions.md"))
    tree = RepositoryContext(repo).lint_tree
    assert len(tree.find(KiroSteeringBlock)) == 1
    agents = tree.find(KiroMarkdownAgentBlock)
    assert any(block.path.name == "reviewer.instructions.md" for block in agents)
    counts = Counter(block.path for block in tree.find(ContentBlock))
    assert max(counts.values()) == 1
