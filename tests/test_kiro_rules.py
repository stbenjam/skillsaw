"""Tests for Kiro steering file validation rules"""

import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.kiro import KiroSteeringValidRule


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


@pytest.fixture
def repo_with_kiro_steering(temp_dir):
    """Create a repo with .kiro/steering/ directory"""
    kiro_dir = temp_dir / ".kiro"
    kiro_dir.mkdir()
    steering_dir = kiro_dir / "steering"
    steering_dir.mkdir()
    return temp_dir


def _write_steering(temp_dir, name, content):
    """Helper to write a steering file in .kiro/steering/"""
    steering_dir = temp_dir / ".kiro" / "steering"
    path = steering_dir / name
    path.write_text(content)
    return path


class TestKiroSteeringValidRule:
    def test_rule_metadata(self):
        rule = KiroSteeringValidRule()
        assert rule.rule_id == "kiro-steering-valid"
        assert rule.default_severity() == Severity.ERROR
        assert rule.repo_types is None

    def test_no_kiro_dir_passes(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 0

    def test_empty_steering_dir_passes(self, repo_with_kiro_steering):
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 0

    def test_valid_always_steering_file(self, repo_with_kiro_steering):
        content = (
            "---\n"
            "inclusion: always\n"
            "---\n\n"
            "# Product Overview\n\n"
            "This is a web application.\n"
        )
        _write_steering(repo_with_kiro_steering, "product.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 0

    def test_valid_file_match_steering_file(self, repo_with_kiro_steering):
        content = (
            "---\n"
            "inclusion: fileMatch\n"
            'fileMatchPattern: "**/*.tsx"\n'
            "---\n\n"
            "# React Components\n\n"
            "Use functional components.\n"
        )
        _write_steering(repo_with_kiro_steering, "react.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 0

    def test_valid_file_match_with_list(self, repo_with_kiro_steering):
        content = (
            "---\n"
            "inclusion: fileMatch\n"
            "fileMatchPattern:\n"
            '  - "**/*.ts"\n'
            '  - "**/*.tsx"\n'
            '  - "**/tsconfig.*.json"\n'
            "---\n\n"
            "# TypeScript Standards\n"
        )
        _write_steering(repo_with_kiro_steering, "typescript.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 0

    def test_valid_manual_steering_file(self, repo_with_kiro_steering):
        content = (
            "---\n" "inclusion: manual\n" "---\n\n" "# Advanced Patterns\n\n" "Use sparingly.\n"
        )
        _write_steering(repo_with_kiro_steering, "advanced.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 0

    def test_valid_auto_steering_file(self, repo_with_kiro_steering):
        content = (
            "---\n"
            "inclusion: auto\n"
            "name: api-design\n"
            "description: REST API design patterns and conventions.\n"
            "---\n\n"
            "# API Design\n\n"
            "Follow REST conventions.\n"
        )
        _write_steering(repo_with_kiro_steering, "api-design.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 0

    def test_valid_no_frontmatter(self, repo_with_kiro_steering):
        content = "# Product Overview\n\nThis is a web application.\n"
        _write_steering(repo_with_kiro_steering, "product.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 0

    def test_empty_file_warns(self, repo_with_kiro_steering):
        _write_steering(repo_with_kiro_steering, "empty.md", "")
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "empty" in violations[0].message.lower()

    def test_whitespace_only_warns(self, repo_with_kiro_steering):
        _write_steering(repo_with_kiro_steering, "blank.md", "   \n\n  \n")
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert "empty" in violations[0].message.lower()

    def test_non_md_file_warns(self, repo_with_kiro_steering):
        _write_steering(repo_with_kiro_steering, "notes.txt", "some notes")
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert "Non-.md" in violations[0].message
        assert "notes.txt" in violations[0].message

    def test_invalid_encoding_fails(self, repo_with_kiro_steering):
        path = repo_with_kiro_steering / ".kiro" / "steering" / "bad.md"
        path.write_bytes(b"\x80\x81\x82\x83")
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert "read" in violations[0].message.lower()

    def test_unknown_inclusion_mode(self, repo_with_kiro_steering):
        content = "---\ninclusion: onDemand\n---\n\n# Content\n"
        _write_steering(repo_with_kiro_steering, "bad-mode.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert "Unknown inclusion mode" in violations[0].message
        assert "onDemand" in violations[0].message

    def test_inclusion_not_string(self, repo_with_kiro_steering):
        content = "---\ninclusion: 42\n---\n\n# Content\n"
        _write_steering(repo_with_kiro_steering, "bad-type.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert "must be a string" in violations[0].message

    def test_file_match_missing_pattern(self, repo_with_kiro_steering):
        content = "---\ninclusion: fileMatch\n---\n\n# Content\n"
        _write_steering(repo_with_kiro_steering, "no-pattern.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert "fileMatchPattern" in violations[0].message
        assert "missing" in violations[0].message.lower()

    def test_file_match_pattern_wrong_type(self, repo_with_kiro_steering):
        content = "---\ninclusion: fileMatch\nfileMatchPattern: 42\n---\n\n# Content\n"
        _write_steering(repo_with_kiro_steering, "bad-pattern-type.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert "string or list" in violations[0].message.lower()

    def test_file_match_pattern_empty_string(self, repo_with_kiro_steering):
        content = '---\ninclusion: fileMatch\nfileMatchPattern: ""\n---\n\n# Content\n'
        _write_steering(repo_with_kiro_steering, "empty-pattern.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert "empty pattern" in violations[0].message.lower()

    def test_file_match_pattern_list_with_non_string(self, repo_with_kiro_steering):
        content = (
            "---\n"
            "inclusion: fileMatch\n"
            "fileMatchPattern:\n"
            '  - "**/*.py"\n'
            "  - 42\n"
            "---\n\n"
            "# Content\n"
        )
        _write_steering(repo_with_kiro_steering, "mixed-types.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert "non-string" in violations[0].message.lower()

    def test_file_match_pattern_line_number(self, repo_with_kiro_steering):
        content = "---\ninclusion: fileMatch\nfileMatchPattern: 42\n---\n\n# Content\n"
        _write_steering(repo_with_kiro_steering, "line-check.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 3

    def test_auto_missing_name(self, repo_with_kiro_steering):
        content = (
            "---\n" "inclusion: auto\n" "description: Some description\n" "---\n\n" "# Content\n"
        )
        _write_steering(repo_with_kiro_steering, "auto-no-name.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert "'name'" in violations[0].message

    def test_auto_missing_description(self, repo_with_kiro_steering):
        content = "---\ninclusion: auto\nname: my-rule\n---\n\n# Content\n"
        _write_steering(repo_with_kiro_steering, "auto-no-desc.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert "'description'" in violations[0].message

    def test_auto_missing_both(self, repo_with_kiro_steering):
        content = "---\ninclusion: auto\n---\n\n# Content\n"
        _write_steering(repo_with_kiro_steering, "auto-no-both.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 2
        messages = [v.message for v in violations]
        assert any("'name'" in m for m in messages)
        assert any("'description'" in m for m in messages)

    def test_name_not_string(self, repo_with_kiro_steering):
        content = (
            "---\n"
            "inclusion: auto\n"
            "name: 42\n"
            "description: A description\n"
            "---\n\n"
            "# Content\n"
        )
        _write_steering(repo_with_kiro_steering, "bad-name.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert any("'name' must be a string" in v.message for v in violations)

    def test_name_empty(self, repo_with_kiro_steering):
        content = (
            "---\n"
            "inclusion: auto\n"
            "name: ''\n"
            "description: A description\n"
            "---\n\n"
            "# Content\n"
        )
        _write_steering(repo_with_kiro_steering, "empty-name.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert any("'name' is empty" in v.message for v in violations)

    def test_description_not_string(self, repo_with_kiro_steering):
        content = (
            "---\n"
            "inclusion: auto\n"
            "name: my-rule\n"
            "description: 42\n"
            "---\n\n"
            "# Content\n"
        )
        _write_steering(repo_with_kiro_steering, "bad-desc.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert any("'description' must be a string" in v.message for v in violations)

    def test_description_empty(self, repo_with_kiro_steering):
        content = (
            "---\n"
            "inclusion: auto\n"
            "name: my-rule\n"
            "description: ''\n"
            "---\n\n"
            "# Content\n"
        )
        _write_steering(repo_with_kiro_steering, "empty-desc.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert any("'description' is empty" in v.message for v in violations)

    def test_frontmatter_but_no_body(self, repo_with_kiro_steering):
        content = "---\ninclusion: always\n---\n"
        _write_steering(repo_with_kiro_steering, "no-body.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert any("no content body" in v.message.lower() for v in violations)

    def test_multiple_valid_files(self, repo_with_kiro_steering):
        _write_steering(
            repo_with_kiro_steering,
            "product.md",
            "---\ninclusion: always\n---\n\n# Product\n\nOur app.\n",
        )
        _write_steering(
            repo_with_kiro_steering,
            "tech.md",
            "---\ninclusion: always\n---\n\n# Tech Stack\n\nPython.\n",
        )
        _write_steering(
            repo_with_kiro_steering,
            "structure.md",
            "# Structure\n\nSrc layout.\n",
        )
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 0

    def test_inclusion_line_number(self, repo_with_kiro_steering):
        content = "---\ninclusion: invalid\n---\n\n# Content\n"
        _write_steering(repo_with_kiro_steering, "line-test.md", content)
        context = RepositoryContext(repo_with_kiro_steering)
        violations = KiroSteeringValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 2
