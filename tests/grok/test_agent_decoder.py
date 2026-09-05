"""Grok 1.0.13 agent delimiter and required-scalar decoder controls.

Native metadata inspection registers the accepted forms and drops collection
values. These tests exercise the CLI and the exact attached body/field locations.
"""

from __future__ import annotations

import pytest

from skillsaw.blocks import AgentBlock, BodyContent, GrokAgentBlock
from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.grok import GrokAgentValidRule
from tests.cli_runner import run_cli
from tests.grok._helpers import copy_fixture, lint_json

AGENT = ".grok/agents/migration-reviewer.md"
OPTIONS = ("--rule", "grok-agent-valid", "--no-custom-rules", "--no-plugins", "--no-baseline")


def fixture(tmp_path):
    repo = copy_fixture("grok/agent-decoder", tmp_path)
    path = repo / AGENT
    source = path.read_text()
    plain = source.lstrip().replace("--- # Agent metadata", "---", 1)
    plain = plain.replace("--- # Prompt follows", "---", 1)
    return repo, path, plain


def agent_block(repo):
    blocks = RepositoryContext(repo).lint_tree.find(GrokAgentBlock)
    assert sorted(block.path.name for block in blocks) == [
        "migration-reviewer.md",
        "review-canary.md",
    ]
    return next(block for block in blocks if block.path.name == "migration-reviewer.md")


def test_decorated_static_fixture_reaches_fields_and_routing(tmp_path):
    repo, path, _plain = fixture(tmp_path)
    report = lint_json(repo, "--no-custom-rules", "--no-plugins", "--no-baseline")
    assert report["violations"] == []
    assert "grok-project" in report["stats"]["repo_types"]
    block = agent_block(repo)
    assert block.field_value("name") == "migration-reviewer"
    assert block.field_value("description").startswith("Use when reviewing database migrations")
    assert block.line_map() == {"name": 3, "description": 4}
    assert "# Agent metadata" in block.read_frontmatter_text()
    body = block.find(BodyContent)[0]
    assert body.parent is block
    assert body.file_line(1) == 6
    assert [(link.href, link.file_line) for link in body.markdown.links()] == [
        ("../../docs/migrations.md", 9)
    ]
    # The same bytes do not change Claude-family frontmatter behavior.
    generic = AgentBlock(path=path)
    assert not generic.has_frontmatter


@pytest.mark.parametrize(
    ("prefix", "opening", "closing", "newline"),
    [
        ("", "---", "---", "\n"),
        ("\n", "---", "---", "\n"),
        ("  ", "---", "---", "\n"),
        ("\t", "---", "---", "\n"),
        ("\n \t\n", "---", "---", "\n"),
        ("", "--- # Agent metadata", "---", "\n"),
        ("", "---", "--- # Prompt follows", "\n"),
        ("", "---", "---- trailing suffix", "\n"),
        ("\n", "--- # Agent metadata", "--- # Prompt follows", "\r\n"),
    ],
)
def test_accepted_delimiters_preserve_source_locations(tmp_path, prefix, opening, closing, newline):
    repo, path, plain = fixture(tmp_path)
    source = prefix + plain.replace("---\n", opening + "\n", 1)
    source = source.replace("\n---\n", "\n" + closing + "\n", 1)
    path.write_bytes(source.replace("\n", newline).encode())
    assert lint_json(repo, *OPTIONS)["violations"] == []
    block = agent_block(repo)
    assert block.field_value("name") == "migration-reviewer"
    assert block.key_line("name") == prefix.count("\n") + 2
    assert block.key_line("description") == prefix.count("\n") + 3
    body = block.find(BodyContent)[0]
    assert len(body.markdown.links()) == 1
    assert (
        body.markdown.links()[0].file_line
        == source.splitlines().index(
            "Read [the migration guide](../../docs/migrations.md) before reviewing schema changes."
        )
        + 1
    )
    assert "Agent metadata" not in body.read_body(strip_code_blocks=False)
    assert "Prompt follows" not in body.read_body(strip_code_blocks=False)


@pytest.mark.parametrize("key", ["name", "description"])
@pytest.mark.parametrize("value", ["[reviewer]", "{text: reviewer}", "!!set {reviewer}"])
def test_collection_required_fields_are_rejected_at_the_key(tmp_path, key, value):
    repo, path, plain = fixture(tmp_path)
    lines = plain.splitlines(keepends=True)
    line = 2 if key == "name" else 3
    lines[line - 1] = key + ": " + value + "\n"
    path.write_text("\n" + "".join(lines))
    report = lint_json(repo, *OPTIONS, returncode=1)
    assert [
        (v["rule_id"], v["file_path"], v["line"], v["severity"]) for v in report["violations"]
    ] == [("grok-agent-valid", AGENT, line + 1, "error")]
    assert "scalar value, not a collection" in report["violations"][0]["message"]
    block = agent_block(repo)
    assert block.field(key) is not None
    overridden = GrokAgentValidRule({"severity": "warning"}).check(RepositoryContext(repo))
    assert len(overridden) == 1
    assert overridden[0].severity == Severity.WARNING
    assert overridden[0].line == line + 1


@pytest.mark.parametrize("key", ["name", "description"])
@pytest.mark.parametrize(
    "value", ["123", "true", "null", "", "''", "|\n  Review migrations", ">\n  Review migrations"]
)
def test_required_scalar_coercion_is_preserved(tmp_path, key, value):
    repo, path, plain = fixture(tmp_path)
    lines = plain.splitlines(keepends=True)
    lines[1 if key == "name" else 2] = key + ": " + value + "\n"
    path.write_text("".join(lines))
    assert lint_json(repo, *OPTIONS)["violations"] == []
    assert agent_block(repo).field(key) is not None


@pytest.mark.parametrize(
    ("source", "line"),
    [
        ("\n\n--- # Metadata\nname: reviewer\n  description: [unclosed\n---\nBody.\n", 5),
        ("\t---\nname: reviewer\ndescription: [unclosed\n---\nBody.\n", 4),
        ("\n---\nname: reviewer\ndescription: Review migrations.\n", None),
        ("---\n!!set {name, description}\n---\n", None),
    ],
)
def test_rejected_frontmatter_keeps_one_actionable_diagnostic(tmp_path, source, line):
    repo, path, _plain = fixture(tmp_path)
    path.write_text(source)
    report = lint_json(repo, *OPTIONS, returncode=1)
    assert len(report["violations"]) == 1
    finding = report["violations"][0]
    assert finding["rule_id"] == "grok-agent-valid"
    assert finding["file_path"] == AGENT
    assert finding["line"] == line
    assert "invalid frontmatter" in finding["message"]
    agent_block(repo)  # The sibling canary remains discoverable too.


def test_content_autofix_uses_original_file_span_after_decorated_frontmatter(tmp_path):
    repo, path, _plain = fixture(tmp_path)
    original = path.read_text().replace(
        "[the migration guide](../../docs/migrations.md)", "../../docs/migrations.md"
    )
    path.write_text(original)
    options = [
        str(repo),
        "--rule",
        "content-unlinked-internal-reference",
        "--no-custom-rules",
        "--no-plugins",
        "--no-baseline",
    ]
    first = lint_json(repo, *options[1:])
    assert [(v["rule_id"], v["file_path"], v["line"]) for v in first["violations"]] == [
        ("content-unlinked-internal-reference", AGENT, 9)
    ]
    fixed = run_cli(["fix", *options[:-1]])
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    after = path.read_text()
    assert after == original.replace(
        "Read ../../docs/migrations.md", "Read [../../docs/migrations.md](../../docs/migrations.md)"
    )
    assert lint_json(repo, *options[1:])["violations"] == []
    assert lint_json(repo, *OPTIONS)["violations"] == []


@pytest.mark.parametrize("suffix", ["", " Read ../../docs/migrations.md"])
def test_closing_prefix_at_eof_retains_suffix_as_body(tmp_path, suffix):
    repo, path, plain = fixture(tmp_path)
    frontmatter = plain.split("\n---\n", 1)[0]
    source = frontmatter + "\n---" + suffix
    path.write_text(source)
    assert lint_json(repo, *OPTIONS)["violations"] == []
    block = agent_block(repo)
    assert block.field_value("name") == "migration-reviewer"
    assert block.body_text == suffix
    bodies = block.find(BodyContent)
    if not suffix:
        assert bodies == []
        return
    assert len(bodies) == 1
    assert bodies[0].file_line(1) == 4
    args = [
        str(repo),
        "--rule",
        "content-unlinked-internal-reference",
        "--no-custom-rules",
        "--no-plugins",
    ]
    report = lint_json(repo, *args[1:])
    assert [(v["file_path"], v["line"]) for v in report["violations"]] == [(AGENT, 4)]
    fixed = run_cli(["fix", *args])
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert path.read_text() == source.replace(
        "Read ../../docs/migrations.md", "Read [../../docs/migrations.md](../../docs/migrations.md)"
    )
    assert lint_json(repo, *OPTIONS)["violations"] == []
