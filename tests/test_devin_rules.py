"""Devin CLI/Desktop rule and native skill validation."""

import pytest

from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.agentskills.valid import AgentSkillValidRule
from skillsaw.rules.builtin.devin.rules_valid import DevinRulesValidRule
from skillsaw.rules.builtin.description_routing import DescriptionRoutingRule
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


def _windsurf_skill(tmp_path, name, content):
    path = tmp_path / ".windsurf" / "skills" / name / "SKILL.md"
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


def test_devin_rule_trigger_is_optional(tmp_path):
    """`devin rules list` infers the mode: globs -> glob-activated,
    description -> agent-decidable. Neither is a defect."""
    _devin_rule(
        tmp_path,
        "globs-only.md",
        "---\nglobs:\n  - src/**/*.ts\n---\nPrefer named exports.\n",
    )
    _devin_rule(
        tmp_path,
        "description-only.md",
        "---\ndescription: Apply when touching the payments service.\n---\nUse idempotency keys.\n",
    )

    assert DevinRulesValidRule().check(RepositoryContext(tmp_path)) == []


def test_devin_rule_without_activation_is_informational(tmp_path):
    """A rule with no trigger, globs, or description is manual (`@rule`)."""
    _devin_rule(tmp_path, "manual-style.md", "Run the release checklist before tagging.\n")

    found = DevinRulesValidRule().check(RepositoryContext(tmp_path))

    assert [(v.severity, v.line) for v in found] == [(Severity.INFO, None)]
    assert "never activates on its own" in found[0].message
    assert found[0].message.endswith("@manual-style")


def test_devin_rule_inferred_glob_mode_still_checks_globs(tmp_path):
    _devin_rule(
        tmp_path,
        "escaping.md",
        "---\nglobs:\n  - ../shared/**\n---\nRule body.\n",
    )

    found = DevinRulesValidRule().check(RepositoryContext(tmp_path))

    assert [(v.severity, v.line) for v in found] == [(Severity.ERROR, 3)]


def test_devin_documented_unquoted_glob_scalar_parses_but_is_an_error(tmp_path):
    """Devin Desktop may accept `globs: **/*.test.ts`; the Devin CLI fails to
    load it ("expected a sequence"). The scalar parses — nothing else in
    the file is reported — and the scalar itself is an error: a YAML list
    is the one form both hosts read."""
    _devin_rule(
        tmp_path,
        "documented-glob.md",
        "---\ntrigger: glob\nglobs: **/*.test.ts # documented syntax\n---\nUse test helpers.\n",
    )

    found = DevinRulesValidRule().check(RepositoryContext(tmp_path))

    assert [(v.severity, v.line) for v in found] == [(Severity.ERROR, 3)]
    assert "must be a YAML list" in found[0].message
    assert "expected a sequence" in found[0].message


def test_devin_glob_fallback_does_not_hide_unrelated_malformed_yaml(tmp_path):
    malformed = _devin_rule(
        tmp_path,
        "malformed-after-glob.md",
        "---\ntrigger: [unterminated\nglobs: **/*.test.ts\n---\nRule body.\n",
    )

    found = DevinRulesValidRule().check(RepositoryContext(tmp_path))

    assert len(found) == 1
    assert found[0].file_path == malformed
    assert found[0].line == 3
    assert "Invalid frontmatter" in found[0].message


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
    # A description alone makes the rule agent-decidable; nothing to report.
    assert "missing.md" not in by_file


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


def test_devin_rule_reports_activation_shapes_and_recovers_from_bad_limit(tmp_path):
    _devin_rule(tmp_path, "trigger-type.md", "---\ntrigger: []\n---\nRule body.\n")
    _devin_rule(tmp_path, "glob-missing.md", "---\ntrigger: glob\n---\nRule body.\n")
    _devin_rule(
        tmp_path,
        "glob-object.md",
        "---\ntrigger: glob\nglobs: {src: true}\n---\nRule body.\n",
    )
    _devin_rule(tmp_path, "glob-empty.md", "---\ntrigger: glob\nglobs: []\n---\nRule body.\n")

    found = DevinRulesValidRule(config={"max-characters": False}).check(RepositoryContext(tmp_path))
    by_file = {violation.file_path.name: violation for violation in found}

    assert set(by_file) == {
        "trigger-type.md",
        "glob-missing.md",
        "glob-object.md",
        "glob-empty.md",
    }
    assert by_file["trigger-type.md"].line == 2
    assert "must be a string" in by_file["trigger-type.md"].message
    assert by_file["glob-missing.md"].line is None
    assert "requires a non-empty 'globs'" in by_file["glob-missing.md"].message
    assert by_file["glob-object.md"].line == 3
    assert "YAML list" in by_file["glob-object.md"].message
    assert by_file["glob-empty.md"].line == 3
    assert "at least one pattern" in by_file["glob-empty.md"].message


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


@pytest.mark.parametrize(
    "allowed_tools",
    [
        "Read Bash",
        "Bash(openspec:*)",
        "mcp__github__get_issue",
        "yes",
    ],
)
def test_native_skill_accepts_scalar_allowed_tools(tmp_path, allowed_tools):
    _native_skill(
        tmp_path,
        "scalar-tools",
        f"---\nallowed-tools: {allowed_tools}\n---\nRun the requested workflow.\n",
    )

    assert DevinSkillValidRule().check(RepositoryContext(tmp_path)) == []


@pytest.mark.parametrize("allowed_tools", ["42", "false", "{}"])
def test_native_skill_rejects_non_string_allowed_tools_scalar(tmp_path, allowed_tools):
    skill = _native_skill(
        tmp_path,
        "invalid-tools",
        f"---\nallowed-tools: {allowed_tools}\n---\nRun the requested workflow.\n",
    )

    found = DevinSkillValidRule().check(RepositoryContext(tmp_path))

    assert [(violation.file_path, violation.line, violation.message) for violation in found] == [
        (skill, 2, "'allowed-tools' must be a string or a list of strings")
    ]


def test_windsurf_skills_use_portable_agent_skills_dialect(tmp_path):
    portable = _windsurf_skill(
        tmp_path,
        "portable",
        "---\nname: portable\ndescription: Run the portable workflow.\n"
        "allowed-tools: Read Bash\n---\nRun the workflow.\n",
    )
    missing = _windsurf_skill(tmp_path, "missing", "# Missing metadata\n\nRun the workflow.\n")
    context = RepositoryContext(tmp_path)

    assert DevinSkillValidRule().check(context) == []
    portable_findings = AgentSkillValidRule().check(context)

    assert all(violation.file_path != portable for violation in portable_findings)
    assert {violation.file_path for violation in portable_findings} == {missing}
    assert {violation.message for violation in portable_findings} == {
        "Missing YAML frontmatter (must start with ---)",
    }


def test_invalid_native_skill_fields_have_nested_yaml_lines(tmp_path):
    skill = _native_skill(
        tmp_path,
        "broken",
        """---
argument-hint: []
model: {}
subagent: maybe
agent: [reviewer]
allowed-tools:
  - read
  - {}
permissions:
  allow: read
  deny:
    - exec
  ask:
    - []
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


def test_native_skill_reports_malformed_yaml_and_container_shapes(tmp_path):
    malformed = _native_skill(
        tmp_path,
        "malformed",
        "---\npermissions: [unterminated\n---\nRun the workflow.\n",
    )
    shaped = _native_skill(
        tmp_path,
        "shaped",
        "---\npermissions: []\ntriggers: []\n---\nRun the workflow.\n",
    )

    found = DevinSkillValidRule().check(RepositoryContext(tmp_path))
    malformed_finding = next(v for v in found if v.file_path == malformed)
    shaped_findings = [v for v in found if v.file_path == shaped]

    assert malformed_finding.line is not None
    assert [(v.line, v.message) for v in shaped_findings] == [
        (2, "'permissions' must be an object"),
        (3, "'triggers' must be a non-empty list containing 'user' and/or 'model'"),
    ]


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


def test_native_skill_bad_triggers_is_one_finding_naming_the_values(tmp_path):
    """Activation phrases instead of the two enum values are one mistake, not
    one error per phrase — a 40-line list was 40 identical errors."""
    _native_skill(
        tmp_path,
        "deploy",
        "---\ntriggers:\n  - deploy the app\n  - ship it\n  - release\n  - user\n---\nDeploy.\n",
    )

    found = DevinSkillValidRule().check(RepositoryContext(tmp_path))

    assert len(found) == 1
    assert found[0].line == 3
    assert found[0].message == (
        "'triggers' must list only 'user' and/or 'model'; got 'deploy the app', 'ship it', 'release'"
    )


def test_native_skill_bad_triggers_message_truncates_long_lists(tmp_path):
    values = "".join(f"  - phrase {index}\n" for index in range(12))
    _native_skill(tmp_path, "many", f"---\ntriggers:\n{values}---\nBody.\n")

    found = DevinSkillValidRule().check(RepositoryContext(tmp_path))

    assert len(found) == 1
    assert found[0].message.endswith("… (12 values)")


def test_native_skills_get_description_routing_when_they_carry_frontmatter(tmp_path):
    """`.devin/skills` follows the Agent Skills standard for descriptions, so
    the shared routing advice applies — but Devin makes frontmatter optional,
    and a skill without one has no description to judge."""
    _native_skill(
        tmp_path,
        "review",
        "---\ndescription: Reviews code.\n---\nReview the current changes.\n",
    )
    _native_skill(tmp_path, "bare", "Review the current changes.\n")
    _native_skill(
        tmp_path,
        "routed",
        "---\ndescription: Reviews a diff for correctness defects. Use when asked to "
        "review a pull request.\n---\nReview.\n",
    )

    found = DescriptionRoutingRule().check(RepositoryContext(tmp_path))

    assert [(v.file_path.parent.name, v.line) for v in found] == [("review", 2)]
    assert "when to use" in found[0].message
