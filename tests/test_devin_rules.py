"""Devin CLI/Desktop rule and native skill validation."""

from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.devin.rules_valid import DevinRulesValidRule
from skillsaw.rules.builtin.devin.skill_valid import DevinSkillValidRule


def _devin_rule(tmp_path, name, content):
    path = tmp_path / ".devin" / "rules" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _native_skill(tmp_path, name, content):
    path = tmp_path / ".devin" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_valid_devin_rule_activation_modes(tmp_path):
    examples = {
        "always.md": "---\ntrigger: always_on\n---\nAlways use focused changes.\n",
        "manual.md": "---\ntrigger: manual\n---\nRun the release checklist.\n",
        "agent.md": "---\ntrigger: agent\n---\nDelegate repository research.\n",
        "glob.md": "---\ntrigger: glob\nglobs:\n  - src/**/*.py\n---\nUse type annotations.\n",
        "model.md": (
            "---\ntrigger: model_decision\ndescription: Apply when editing the API.\n---\n"
            "Return JSON responses.\n"
        ),
    }
    for name, content in examples.items():
        _devin_rule(tmp_path, name, content)

    assert DevinRulesValidRule().check(RepositoryContext(tmp_path)) == []


def test_devin_rule_activation_errors_have_field_lines(tmp_path):
    _devin_rule(tmp_path, "trigger.md", "---\ntrigger: sometimes\n---\nRule body.\n")
    _devin_rule(
        tmp_path,
        "glob.md",
        "---\ntrigger: glob\nglobs:\n  - /etc/*.conf\n  - ../shared/**\n  - ''\n---\nRule body.\n",
    )
    _devin_rule(
        tmp_path,
        "model.md",
        "---\ntrigger: model_decision\ndescription: []\n---\nRule body.\n",
    )
    _devin_rule(tmp_path, "missing.md", "---\ndescription: Manual rule.\n---\nRule body.\n")

    found = DevinRulesValidRule().check(RepositoryContext(tmp_path))
    by_file = {}
    for violation in found:
        by_file.setdefault(violation.file_path.name, []).append(violation)

    assert [(v.line, v.message) for v in by_file["trigger.md"]] == [
        (
            2,
            "Unsupported trigger 'sometimes'; expected one of: agent, always_on, glob, manual, model_decision",
        )
    ]
    assert [v.line for v in by_file["glob.md"]] == [4, 5, 6]
    assert [v.line for v in by_file["model.md"]] == [3]
    assert by_file["missing.md"][0].line is None


def test_devin_rule_reports_malformed_yaml_and_size_limit(tmp_path):
    malformed = _devin_rule(
        tmp_path,
        "malformed.md",
        "---\ntrigger: [unterminated\n---\nRule body.\n",
    )
    oversized = _devin_rule(
        tmp_path,
        "oversized.md",
        "---\ntrigger: always_on\n---\n" + ("x" * 12_001),
    )

    found = DevinRulesValidRule().check(RepositoryContext(tmp_path))

    malformed_finding = next(v for v in found if v.file_path == malformed)
    assert malformed_finding.line is not None
    size_finding = next(v for v in found if v.file_path == oversized)
    assert "exceeds 12,000 characters" in size_finding.message
    assert size_finding.line is None


def test_valid_native_skill_fields_and_optional_frontmatter(tmp_path):
    _native_skill(tmp_path, "plain", "# Plain skill\n\nRun the requested workflow.\n")
    _native_skill(
        tmp_path,
        "configured",
        """---
name: configured
description: Run the configured workflow.
argument-hint: "[target]"
model: sonnet
subagent: false
agent: reviewer
allowed-tools:
  - read
  - grep
permissions:
  allow:
    - Read(src/**)
  deny:
    - exec
  ask:
    - Write(**)
triggers:
  - user
  - model
future-field: accepted
---
Run the requested workflow.
""",
    )

    assert DevinSkillValidRule().check(RepositoryContext(tmp_path)) == []


def test_invalid_native_skill_fields_have_nested_yaml_lines(tmp_path):
    skill = _native_skill(
        tmp_path,
        "broken",
        """---
argument-hint: []
model: false
subagent: maybe
agent: [reviewer]
allowed-tools:
  - read
  - 4
permissions:
  allow: read
  deny:
    - exec
  ask:
    - false
triggers:
  - user
  - autonomous
---
Run the requested workflow.
""",
    )

    found = DevinSkillValidRule().check(RepositoryContext(tmp_path))

    assert [v.line for v in found] == [2, 3, 5, 4, 8, 10, 14, 17]
    assert all(v.file_path == skill for v in found)


def test_agent_precedence_is_informational(tmp_path):
    _native_skill(
        tmp_path,
        "delegated",
        "---\nagent: reviewer\nsubagent: true\n---\nReview the changes.\n",
    )

    found = DevinSkillValidRule().check(RepositoryContext(tmp_path))

    assert len(found) == 1
    assert found[0].severity is Severity.INFO
    assert found[0].line == 2
    assert "uses the named 'agent' profile" in found[0].message
