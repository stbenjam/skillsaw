"""``grok-agent-valid`` — the frontmatter Grok registers a subagent by.

Verified against Grok Build 1.0.13 in an isolated ``GROK_HOME``: an agent
file missing ``name`` or ``description``, or carrying malformed YAML, does
not appear in ``grok inspect --json``; one carrying both does, including
when the description is the empty string and when extra keys sit beside
them. Nothing is printed either way, which is why the rule exists.
"""

from __future__ import annotations

import pytest

from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokAgentValidRule
from tests.grok._helpers import copy_fixture, lint_json, messages, violations_for, write_repo

CLEAN_AGENT = (
    "---\nname: migration-reviewer\n"
    "description: Use when reviewing a database migration, to check that it is "
    "forward-only and matched by the code that reads the new columns.\n---\n\n"
    "# Migration reviewer\n\nRead the migration and report what it changes.\n"
)


def write_agent(root, body: str, name: str = "migration-reviewer.md"):
    """Write *body* to ``<root>/.grok/agents/<name>`` and return the path."""
    agents = root / ".grok" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    path = agents / name
    path.write_text(body)
    return path


def check(repo):
    return GrokAgentValidRule().check(RepositoryContext(repo))


# ── Rule metadata ────────────────────────────────────────────────


def test_rule_metadata() -> None:
    rule = GrokAgentValidRule()

    assert rule.rule_id == "grok-agent-valid"
    assert rule.default_severity() == Severity.ERROR
    assert rule.default_enabled == "auto"
    assert rule.since == "0.20.0"
    assert rule.repo_types == frozenset({RepositoryType.GROK_PROJECT})
    # `.grok/agents/` is a tool directory no other ecosystem claims, and the
    # node type exists nowhere else, so there is nothing to filter.
    assert rule.provenance_scope is None


# ── What Grok refuses ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            "---\nname: migration-reviewer\n---\n\n# Migration reviewer\n\nRead the diff.\n",
            "Agent migration-reviewer.md is missing 'description'",
        ),
        (
            "---\ndescription: Use when reviewing a migration.\n---\n\n"
            "# Migration reviewer\n\nRead the diff.\n",
            "Agent migration-reviewer.md is missing 'name'",
        ),
        (
            "# Migration reviewer\n\nRead the diff and report what it changes.\n",
            "Agent migration-reviewer.md has no frontmatter; add 'name' and 'description'",
        ),
    ],
)
def test_an_agent_grok_will_not_register_is_reported(temp_dir, body, message) -> None:
    """One finding per defect, naming the file: Grok drops the subagent and
    prints nothing, so the file looks exactly like an agent the model never
    had a reason to pick."""
    repo = write_repo(temp_dir / f"agent-{abs(hash(body))}")
    write_agent(repo, body)

    violations = check(repo)

    assert messages(violations) == [message]
    assert violations[0].severity == Severity.ERROR


def test_both_missing_keys_are_reported_separately(temp_dir) -> None:
    """Two keys are two things to add, and the fix for one is not the fix
    for the other."""
    repo = write_repo(temp_dir / "agent-bare")
    write_agent(repo, "---\nmodel: grok-code-fast-1\n---\n\n# Reviewer\n\nRead the diff.\n")

    assert messages(check(repo)) == [
        "Agent migration-reviewer.md is missing 'name'",
        "Agent migration-reviewer.md is missing 'description'",
    ]


def test_malformed_frontmatter_is_one_finding_not_two_missing_keys(temp_dir) -> None:
    """Nothing parsed, so nothing is known about the keys. Reporting both as
    missing would send the author looking for the wrong defect."""
    repo = write_repo(temp_dir / "agent-malformed")
    write_agent(
        repo,
        "---\nname: migration-reviewer\n  description: [unclosed\n---\n\n# Reviewer\n\nRead it.\n",
    )

    violations = check(repo)

    assert len(violations) == 1, messages(violations)
    assert violations[0].message.startswith("Agent migration-reviewer.md has invalid frontmatter: ")
    assert violations[0].severity == Severity.ERROR


# ── What Grok accepts ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("body", "note"),
    [
        (CLEAN_AGENT, "both keys, nothing else"),
        (
            '---\nname: migration-reviewer\ndescription: ""\n---\n\n# Reviewer\n\nRead it.\n',
            # Grok registers this one, so demanding content here would be a
            # false positive. Whether an empty description routes anything is
            # `content-description-routing`'s question, not the loader's.
            "an empty description still registers",
        ),
        (
            "---\nname: migration-reviewer\n"
            "description: Use when reviewing a migration for dropped columns.\n"
            "tools: read_file, run_terminal_command\nmodel: grok-code-fast-1\n---\n\n"
            "# Reviewer\n\nRead the migration and report what it changes.\n",
            "extra keys are Grok's to ignore",
        ),
    ],
)
def test_an_agent_grok_registers_is_not_reported(temp_dir, body, note) -> None:
    repo = write_repo(temp_dir / f"ok-{abs(hash(note))}")
    write_agent(repo, body)

    assert check(repo) == [], note


def test_a_command_is_not_held_to_the_agent_contract(temp_dir) -> None:
    """Grok loads a `.grok/commands/*.md` with no frontmatter at all, naming
    it from the filename. Requiring any there would report a file that
    works."""
    repo = write_repo(temp_dir / "bare-command")
    commands = repo / ".grok" / "commands"
    commands.mkdir(parents=True)
    (commands / "tile-check.md").write_text("# Tile check\n\nRun `make test-tiles`.\n")

    assert check(repo) == []


# ── Through the CLI ──────────────────────────────────────────────


def test_the_broken_fixture_reports_the_agent(tmp_path) -> None:
    repo = copy_fixture("grok/project-broken", tmp_path)

    found = violations_for(lint_json(repo, returncode=1), "grok-agent-valid")

    assert [(v["file_path"], v["message"]) for v in found] == [
        (
            ".grok/agents/schema-reviewer.md",
            "Agent schema-reviewer.md is missing 'name'",
        )
    ]


def test_the_clean_fixture_reports_no_agent(tmp_path) -> None:
    repo = copy_fixture("grok/project-clean", tmp_path)

    assert violations_for(lint_json(repo), "grok-agent-valid") == []
