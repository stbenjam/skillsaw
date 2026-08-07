"""Tests for the security-dynamic-context rule."""

from skillsaw.context import RepositoryContext
from skillsaw.rule import Severity
from skillsaw.rules.builtin.security.dynamic_context import SecurityDynamicContextRule


def _write_skill(temp_dir, body):
    (temp_dir / "SKILL.md").write_text(
        "---\n"
        "name: test-skill\n"
        "description: A skill used by the dynamic-context tests\n"
        "---\n" + body
    )


def _check(temp_dir, config=None):
    return SecurityDynamicContextRule(config).check(RepositoryContext(temp_dir))


class TestSecurityDynamicContextRule:
    def test_rule_metadata(self):
        rule = SecurityDynamicContextRule()
        assert rule.rule_id == "security-dynamic-context"
        assert rule.default_severity() == Severity.ERROR
        assert rule.default_enabled == "auto"
        assert rule.since == "0.18.0"
        assert not rule.supports_autofix
        assert "allowlist" in rule.config_schema

    def test_inline_dynamic_context_fires_with_file_line(self, temp_dir):
        _write_skill(temp_dir, "# Review\n\n" "Show the current changes: !`git diff HEAD`\n")

        violations = _check(temp_dir)

        assert len(violations) == 1
        assert violations[0].line == 3
        assert violations[0].file_line == 7
        assert "git diff HEAD" in violations[0].message
        assert "prohibited" in violations[0].message

    def test_inline_form_requires_line_start_or_whitespace(self, temp_dir):
        _write_skill(
            temp_dir,
            "KEY=!`git status --short`\n"
            "!`git diff HEAD`\n"
            "Run !`pwd` when reviewing changes.\n",
        )

        violations = _check(temp_dir)

        assert [violation.line for violation in violations] == [2, 3]
        assert [violation.file_line for violation in violations] == [6, 7]
        assert all("KEY" not in violation.message for violation in violations)

    def test_fenced_dynamic_context_fires_once_at_opening_line(self, temp_dir):
        _write_skill(
            temp_dir, "# Environment\n\n" "```!\n" "node --version\n" "git status --short\n" "```\n"
        )

        violations = _check(temp_dir)

        assert len(violations) == 1
        assert violations[0].line == 3
        assert violations[0].file_line == 7
        assert "node --version\\ngit status --short" in violations[0].message
        assert "command block" in violations[0].message

    def test_allowlist_matches_inline_command_exactly(self, temp_dir):
        _write_skill(temp_dir, "!`git diff HEAD`\n" "!`git diff HEAD --stat`\n")

        violations = _check(temp_dir, {"allowlist": ["git diff HEAD"]})

        assert len(violations) == 1
        assert violations[0].line == 2
        assert violations[0].file_line == 6
        assert "Non-allowlisted" in violations[0].message
        assert "git diff HEAD --stat" in violations[0].message

    def test_allowlist_matches_complete_fenced_command(self, temp_dir):
        _write_skill(temp_dir, "```!\n" "node --version\n" "git status --short\n" "```\n")

        assert (
            _check(
                temp_dir,
                {"allowlist": ["node --version\ngit status --short"]},
            )
            == []
        )

    def test_allowlist_does_not_match_a_command_prefix(self, temp_dir):
        _write_skill(temp_dir, "!`git diff HEAD --stat`\n")

        violations = _check(temp_dir, {"allowlist": ["git diff HEAD"]})

        assert len(violations) == 1

    def test_ordinary_code_and_non_dynamic_fence_are_clean(self, temp_dir):
        _write_skill(
            temp_dir,
            "Use `git diff HEAD` to inspect changes.\n"
            "\n"
            "```bash\n"
            "!`git status --short`\n"
            "```\n",
        )

        assert _check(temp_dir) == []

    def test_other_content_blocks_are_scanned(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "This is not a skill: !`git diff HEAD`\n" "```!\n" "git status --short\n" "```\n"
        )

        violations = _check(temp_dir)

        assert len(violations) == 2
        assert all(violation.file_path.name == "CLAUDE.md" for violation in violations)
