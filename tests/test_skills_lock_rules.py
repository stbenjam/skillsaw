"""Tests for Vercel skills CLI project lockfiles."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from skillsaw.blocks import SkillsLockBlock
from skillsaw.config import LinterConfig
from skillsaw.context import HAS_SKILLS_LOCK, RepositoryContext
from skillsaw.linter import Linter
from skillsaw.rule import Severity
from skillsaw.rules.builtin.skills_lock import SkillsLockValidRule

FIXTURES = Path(__file__).parent / "fixtures"
HASH = "0123456789abcdef" * 4


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    destination = tmp_path / name.replace("/", "_")
    shutil.copytree(FIXTURES / name, destination)
    return destination


def _write_lock(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _entry(**overrides: object) -> dict:
    entry = {
        "source": "vercel-labs/skills",
        "sourceType": "github",
        "computedHash": HASH,
    }
    entry.update(overrides)
    return entry


def _messages(repo: Path, config: dict | None = None) -> list[str]:
    rule = SkillsLockValidRule(config)
    return [violation.message for violation in rule.check(RepositoryContext(repo))]


def test_rule_defaults_to_auto_and_error() -> None:
    config = LinterConfig.default().get_rule_config("skills-lock-valid")
    assert config["enabled"] == "auto"
    assert SkillsLockValidRule().default_severity() == Severity.ERROR


def test_valid_root_and_nested_lockfiles_pass(tmp_path: Path) -> None:
    repo = _copy_fixture("skills-lock/valid", tmp_path)
    context = RepositoryContext(repo)

    assert HAS_SKILLS_LOCK in context.detected_formats
    blocks = context.lint_tree.find(SkillsLockBlock)
    assert [block.path.relative_to(repo) for block in blocks] == [
        Path("packages/web/skills-lock.json"),
        Path("skills-lock.json"),
    ]
    assert SkillsLockValidRule().check(context) == []


def test_rule_auto_enables_for_an_unknown_repository(tmp_path: Path) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {"version": 1, "skills": {"broken": _entry(computedHash="bad")}},
    )

    violations = Linter(RepositoryContext(tmp_path), LinterConfig.default()).run()

    lock_violations = [v for v in violations if v.rule_id == "skills-lock-valid"]
    assert len(lock_violations) == 1
    assert "computedHash" in lock_violations[0].message


def test_exact_filename_excludes_and_vendored_trees(tmp_path: Path) -> None:
    _write_lock(tmp_path / "skills-lock.json", {"version": 1, "skills": {}})
    _write_lock(tmp_path / ".skill-lock.json", {"version": 1, "skills": {}})
    _write_lock(
        tmp_path / "packages" / "private" / "skills-lock.json",
        {"version": 1, "skills": {}},
    )
    _write_lock(
        tmp_path / "vendor" / "dependency" / "skills-lock.json",
        {"version": 1, "skills": {}},
    )

    context = RepositoryContext(tmp_path, exclude_patterns=["packages/private/**"])

    assert context.skills_lock_files() == [tmp_path / "skills-lock.json"]
    assert [block.path for block in context.lint_tree.find(SkillsLockBlock)] == [
        tmp_path / "skills-lock.json"
    ]


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        ('{"version": 1, "skills": {}, "bad": NaN}', "Invalid JSON"),
        ("[]", "must contain a JSON object"),
        ('{"version": 1,', "Invalid JSON"),
    ],
)
def test_strict_json_and_top_level_shape(tmp_path: Path, contents: str, expected: str) -> None:
    (tmp_path / "skills-lock.json").write_text(contents)

    messages = _messages(tmp_path)

    assert len(messages) == 1
    assert expected in messages[0]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"skills": {}}, "Missing required top-level field 'version'"),
        ({"version": True, "skills": {}}, "'version' must be a number"),
        ({"version": 0, "skills": {}}, "'version' must be at least 1"),
        ({"version": 1}, "Missing required top-level field 'skills'"),
        ({"version": 1, "skills": []}, "'skills' must be an object"),
    ],
)
def test_required_top_level_fields(tmp_path: Path, data: dict, expected: str) -> None:
    _write_lock(tmp_path / "skills-lock.json", data)

    assert any(expected in message for message in _messages(tmp_path))


def test_invalid_fixture_reports_each_broken_field(tmp_path: Path) -> None:
    repo = _copy_fixture("skills-lock/invalid", tmp_path)

    violations = SkillsLockValidRule().check(RepositoryContext(repo))
    messages = [violation.message for violation in violations]

    assert any("newer than the supported version" in message for message in messages)
    assert any("Skill names" in message for message in messages)
    assert any("must be an object" in message for message in messages)
    assert any("field 'source'" in message for message in messages)
    assert any("unrecognized sourceType" in message for message in messages)
    assert any("computedHash" in message for message in messages)
    assert any("optional field 'sourceUrl'" in message for message in messages)
    assert any("optional field 'ref'" in message for message in messages)
    assert any("subagents[1]" in message for message in messages)
    assert any("stay relative" in message for message in messages)
    assert any("must end with 'SKILL.md'" in message for message in messages)
    assert any("wellKnownDigest" in message for message in messages)
    assert all(violation.line is None for violation in violations)


def test_git_restore_and_local_portability_warnings(tmp_path: Path) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {
            "version": 1,
            "skills": {
                "gitlab-skill": _entry(source="group/project", sourceType="gitlab"),
                "local-posix": _entry(source="/opt/team/skill", sourceType="local"),
                "local-windows": _entry(source="C:\\team\\skill", sourceType="local"),
                "backslash-path": _entry(skillPath="skills\\demo\\SKILL.md"),
            },
        },
    )

    violations = SkillsLockValidRule().check(RepositoryContext(tmp_path))
    warnings = [v.message for v in violations if v.severity == Severity.WARNING]

    assert any("without 'sourceUrl'" in message for message in warnings)
    assert sum("absolute local source path" in message for message in warnings) == 2
    assert any("uses backslashes" in message for message in warnings)
    assert all(v.severity == Severity.WARNING for v in violations)


def test_unknown_source_type_can_be_allowlisted(tmp_path: Path) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {
            "version": 1,
            "skills": {"registry-skill": _entry(source="registry:id", sourceType="registry")},
        },
    )

    violations = SkillsLockValidRule().check(RepositoryContext(tmp_path))
    assert len(violations) == 1
    assert violations[0].severity == Severity.INFO
    assert "extra-source-types" in violations[0].message

    configured = {"extra-source-types": ["registry"]}
    assert SkillsLockValidRule(configured).check(RepositoryContext(tmp_path)) == []


def test_optional_fields_accept_empty_subagent_name_but_not_empty_strings(
    tmp_path: Path,
) -> None:
    _write_lock(
        tmp_path / "skills-lock.json",
        {
            "version": 1,
            "skills": {
                "valid": _entry(subagents=[""], skillPath="SKILL.md"),
                "invalid": _entry(sourceUrl=" ", wellKnownDigest=" "),
            },
        },
    )

    messages = _messages(tmp_path)

    assert len(messages) == 2
    assert any("sourceUrl" in message for message in messages)
    assert any("wellKnownDigest" in message for message in messages)
