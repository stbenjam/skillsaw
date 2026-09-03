"""Tests for committed project memory under ``.agents/memory/``.

Team notes checked into the repository for whatever agent reads the
checkout — the shared counterpart of Claude Code's per-developer auto
memory. The convention belongs to no tool: projects were committing
``.agents/memory/`` before Muse Code shipped, and Muse reads it the way it
reads ``AGENTS.md``. So the directory is content skillsaw lints
unconditionally, and it is evidence of no tool in particular.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from skillsaw.blocks import AgentMemoryBlock, AgentMemoryIndexBlock
from skillsaw.context import HAS_MUSE, RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.content.progressive_disclosure import (
    ContentProgressiveDisclosureRule,
)
from skillsaw.rules.builtin.context_budget.budget import ContextBudgetRule
from skillsaw.rules.builtin.security.hidden_instructions import SecurityHiddenInstructionsRule
from tests.cli_runner import run_cli

FIXTURES = Path(__file__).parent / "fixtures"


def copy_fixture(name: str, tmp_path: Path) -> Path:
    destination = tmp_path / name.replace("/", "_")
    shutil.copytree(FIXTURES / name, destination)
    return destination


def relative(repo: Path, targets) -> list:
    return sorted(str(target.path.relative_to(repo)) for target in targets)


def _prose(tokens: int) -> str:
    """Roughly *tokens* tokens of plain prose."""
    return " ".join(["reindex the catalog before the alias swap"] * (tokens // 7 + 1))


# ── Ownership ────────────────────────────────────────────────────


def test_memory_alone_is_not_evidence_of_muse(tmp_path) -> None:
    """The convention predates Muse Code and no tool owns it, so a project
    that commits memory and configures no hooks is not a Muse repository."""
    repo = copy_fixture("agent-memory/notes", tmp_path)

    assert HAS_MUSE not in RepositoryContext(repo).detected_formats


def test_memory_is_attached_without_any_tool_evidence(tmp_path) -> None:
    """Content is content: the attach is unconditional, so the notes reach
    every content and security rule whoever ends up reading them."""
    repo = copy_fixture("agent-memory/notes", tmp_path)
    tree = RepositoryContext(repo).lint_tree

    assert relative(repo, tree.find(AgentMemoryIndexBlock)) == [".agents/memory/MEMORY.md"]
    assert relative(repo, tree.find(AgentMemoryBlock)) == [".agents/memory/reindex.md"]


def test_both_block_types_carry_the_memory_budget_category(tmp_path) -> None:
    """The index is loaded whole and a topic file is loaded whole on demand,
    so both are budgeted the same way."""
    repo = copy_fixture("agent-memory/notes", tmp_path)
    tree = RepositoryContext(repo).lint_tree

    assert tree.find(AgentMemoryIndexBlock)[0].category == "memory"
    assert [block.category for block in tree.find(AgentMemoryBlock)] == ["memory"]


def test_an_excluded_memory_tree_is_neither_detected_nor_attached(tmp_path) -> None:
    repo = copy_fixture("agent-memory/notes", tmp_path)

    context = RepositoryContext(repo, exclude_patterns=[".agents/**"])

    assert context.lint_tree.find(AgentMemoryIndexBlock) == []
    assert context.lint_tree.find(AgentMemoryBlock) == []


# ── The rules that read it ───────────────────────────────────────


def test_a_memory_topic_file_gets_the_security_rules(tmp_path) -> None:
    """A topic file is read on demand, so a payload in one reaches the agent."""
    repo = copy_fixture("muse/broken", tmp_path)

    violations = SecurityHiddenInstructionsRule().check(RepositoryContext(repo))

    assert len(violations) == 1
    assert violations[0].file_path.name == "incident-2026-08.md"
    assert "Hidden override instruction" in violations[0].message


def test_the_memory_finding_names_the_topic_file_through_the_cli(tmp_path) -> None:
    repo = copy_fixture("muse/broken", tmp_path)

    result = run_cli(["lint", "--format", "json", "-v", repo])
    found = [
        v
        for v in json.loads(result.stdout)["violations"]
        if v["rule_id"] == "security-hidden-instructions"
    ]

    assert [v["file_path"] for v in found] == [".agents/memory/incident-2026-08.md"]


def test_an_oversized_index_is_a_context_budget_error(tmp_path) -> None:
    """The `memory` category is registered, so an index nobody can afford to
    load is reported like any other over-budget file."""
    repo = copy_fixture("agent-memory/notes", tmp_path)
    (repo / ".agents" / "memory" / "MEMORY.md").write_text(_prose(9000))

    violations = ContextBudgetRule().check(RepositoryContext(repo))
    memory = [v for v in violations if v.file_path.name == "MEMORY.md"]

    assert len(memory) == 1
    assert memory[0].severity == Severity.ERROR
    assert "memory error limit of 8,000" in memory[0].message


def test_an_oversized_note_is_told_to_split_and_link(tmp_path) -> None:
    """`memory` is one of content-progressive-disclosure's default
    categories, so a note over the threshold that references nothing is
    told what to do about its size, not only that it has one. No config
    here on purpose: a `limits` entry would register the category by
    itself and the default would go untested."""
    # One repository per size: the file cache is keyed by path, so rewriting
    # one note would measure the first read twice.
    under = copy_fixture("agent-memory/notes", tmp_path / "under")
    (under / ".agents" / "memory" / "reindex.md").write_text(_prose(2000))
    assert ContentProgressiveDisclosureRule().check(RepositoryContext(under)) == []

    over = copy_fixture("agent-memory/notes", tmp_path / "over")
    (over / ".agents" / "memory" / "reindex.md").write_text(_prose(3500))
    found = ContentProgressiveDisclosureRule().check(RepositoryContext(over))

    assert [v.file_path.name for v in found] == ["reindex.md"]
    assert "threshold for memory" in found[0].message
    assert "loads on demand" in found[0].message


def test_the_memory_limit_is_configurable(tmp_path) -> None:
    """Registered like every other category, so a project that wants a
    bigger memory budget sets one rather than disabling the rule."""
    repo = copy_fixture("agent-memory/notes", tmp_path)
    (repo / ".agents" / "memory" / "reindex.md").write_text(_prose(9000))
    context = RepositoryContext(repo)

    assert [
        v.severity for v in ContextBudgetRule().check(context) if v.file_path.name == "reindex.md"
    ] == [Severity.ERROR]

    raised = ContextBudgetRule({"limits": {"memory": {"warn": 20000, "error": 40000}}})
    assert [v for v in raised.check(context) if v.file_path.name == "reindex.md"] == []
