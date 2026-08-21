"""Tests for the security-dynamic-context rule."""

import pytest

from skillsaw.baseline import build_baseline, fingerprint_violation, save_baseline
from skillsaw.context import RepositoryContext
from skillsaw.formatters import format_report
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
        assert rule.default_severity() == Severity.WARNING
        assert rule.default_enabled == "auto"
        assert rule.since == "0.19.0"
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

    def test_tilde_fenced_dynamic_context_is_detected(self, temp_dir):
        _write_skill(temp_dir, "~~~!\nnode --version\n~~~\n")

        violations = _check(temp_dir)

        assert len(violations) == 1
        assert "node --version" in violations[0].message

    def test_unterminated_fenced_dynamic_context_is_detected(self, temp_dir):
        _write_skill(temp_dir, "```!\necho one\n")

        violations = _check(temp_dir)

        assert len(violations) == 1
        assert "echo one" in violations[0].message

    @pytest.mark.parametrize(
        "body",
        [
            "> ```!\n> echo one\n> echo two\n> ```\n",
            "- item\n  ```!\n  echo one\n  echo two\n  ```\n",
        ],
    )
    def test_nested_fence_allowlist_uses_command_content(self, temp_dir, body):
        _write_skill(temp_dir, body)

        assert (
            _check(
                temp_dir,
                {"allowlist": ["echo one\necho two"]},
            )
            == []
        )

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

    def test_allowlist_matching_preserves_inline_whitespace(self, temp_dir):
        _write_skill(temp_dir, "!`git diff HEAD `\n")

        assert _check(temp_dir, {"allowlist": ["git diff HEAD"]})
        assert _check(temp_dir, {"allowlist": ["git diff HEAD "]}) == []

    def test_allowlist_matching_preserves_fenced_whitespace(self, temp_dir):
        _write_skill(temp_dir, "```!\necho one \n```\n")

        assert _check(temp_dir, {"allowlist": ["echo one"]})
        assert _check(temp_dir, {"allowlist": ["echo one "]}) == []

    def test_same_line_commands_have_distinct_fingerprints(self, temp_dir):
        _write_skill(temp_dir, "!`git status` and !`git diff`\n")

        violations = _check(temp_dir)

        assert len(violations) == 2
        assert len({v.fingerprint_discriminator for v in violations}) == 2

    def test_repeated_fenced_commands_have_distinct_fingerprints(self, temp_dir):
        _write_skill(
            temp_dir,
            "# Setup\n\n```!\nnode --version\n```\n\n# Teardown\n\n```!\nnode --version\n```\n",
        )

        violations = _check(temp_dir)

        assert len(violations) == 2
        fingerprints = {fingerprint_violation(v, temp_dir) for v in violations}
        assert len(fingerprints) == 2

    def test_repeated_fenced_fingerprints_survive_insertions_above(self, tmp_path):
        before_dir = tmp_path / "before"
        after_dir = tmp_path / "after"
        before_dir.mkdir()
        after_dir.mkdir()
        repeated = "```!\nnode --version\n```\n\n```!\nnode --version\n```\n"
        _write_skill(before_dir, "# Environment\n\n" + repeated)
        _write_skill(after_dir, "# Environment\n\nAn unrelated paragraph.\n\n" + repeated)

        before = _check(before_dir)
        after = _check(after_dir)

        assert len(before) == len(after) == 2
        assert {fingerprint_violation(v, after_dir) for v in after} == {
            fingerprint_violation(v, before_dir) for v in before
        }

    def test_fenced_fingerprint_survives_insertions_above(self, tmp_path):
        # Two directories rather than one rewritten file so the comparison
        # cannot be masked by mtime-granularity content caching.
        before_dir = tmp_path / "before"
        after_dir = tmp_path / "after"
        before_dir.mkdir()
        after_dir.mkdir()
        _write_skill(before_dir, "# Environment\n\n```!\nnode --version\n```\n")
        _write_skill(
            after_dir, "# Environment\n\nAn unrelated paragraph.\n\n```!\nnode --version\n```\n"
        )

        before = _check(before_dir)
        after = _check(after_dir)

        assert len(before) == len(after) == 1
        assert after[0].file_line == before[0].file_line + 2
        assert fingerprint_violation(after[0], after_dir) == fingerprint_violation(
            before[0], before_dir
        )

    def test_fenced_trailing_blank_lines_are_part_of_the_command(self, temp_dir):
        _write_skill(temp_dir, "```!\necho one\n\n```\n")

        assert _check(temp_dir, {"allowlist": ["echo one"]})
        assert _check(temp_dir, {"allowlist": ["echo one\n"]}) == []

    def test_fence_info_starting_with_marker_is_detected(self, temp_dir):
        _write_skill(temp_dir, "```!bash\ngit status --short\n```\n")

        violations = _check(temp_dir)

        assert len(violations) == 1
        assert "git status --short" in violations[0].message

    def test_long_command_is_truncated_in_message_but_matched_exactly(self, temp_dir):
        command = "echo " + "a" * 200
        _write_skill(temp_dir, f"!`{command}`\n")

        violations = _check(temp_dir)

        assert len(violations) == 1
        assert command not in violations[0].message
        assert "…" in violations[0].message
        assert _check(temp_dir, {"allowlist": [command]}) == []

    def test_command_url_credentials_are_redacted_from_message(self, temp_dir):
        secret = "FAKE_DYNCTX_TOKEN_9Z7Q"
        command = f"curl https://user:{secret}@example.invalid/x"
        _write_skill(temp_dir, f"!`{command}`\n")

        violations = _check(temp_dir)

        assert len(violations) == 1
        assert secret not in violations[0].message
        assert "https://[redacted]@example.invalid/x" in violations[0].message
        assert _check(temp_dir, {"allowlist": [command]}) == []

    @pytest.mark.parametrize("output_format", ["text", "json", "sarif", "html"])
    def test_command_url_credentials_are_redacted_from_reports(self, temp_dir, output_format):
        secret = "FAKE_DYNCTX_REPORT_TOKEN_9Z7Q"
        _write_skill(
            temp_dir,
            f"!`curl https://user:{secret}@example.invalid/report`\n",
        )
        context = RepositoryContext(temp_dir)
        rule = SecurityDynamicContextRule()
        violations = rule.check(context)

        output = format_report(output_format, violations, context, [rule], "0.19.0")

        assert secret not in output
        assert "[redacted]" in output

    def test_command_url_credentials_are_redacted_from_baseline(self, temp_dir):
        secret = "FAKE_DYNCTX_BASELINE_TOKEN_9Z7Q"
        _write_skill(
            temp_dir,
            f"!`curl https://user:{secret}@example.invalid/baseline`\n",
        )
        violations = _check(temp_dir)
        baseline_path = temp_dir / ".skillsaw-baseline.json"

        save_baseline(
            baseline_path,
            build_baseline(violations, temp_dir, "0.19.0"),
        )

        baseline_text = baseline_path.read_text()
        assert secret not in baseline_text
        assert "[redacted]" in baseline_text

    def test_credentials_are_redacted_before_command_display_truncation(self, temp_dir):
        secret = "S" * 80
        command = f"curl https://user:{secret}@example.invalid/x"
        _write_skill(temp_dir, f"!`{command}`\n")

        violations = _check(temp_dir)

        assert len(violations) == 1
        assert secret not in violations[0].message
        assert "user:" not in violations[0].message
        assert "[redacted]" in violations[0].message
        assert len(command) > 60

    def test_credentials_split_across_a_continuation_are_redacted(self, temp_dir):
        # A backslash-newline joins the shell's words, so the credential is
        # one logical token even though no single line holds all of it —
        # line-local redaction would leak the fragment before the split.
        # A multi-line command needs the fenced form; an inline code span
        # cannot contain a newline.
        secret = "FAKE_DYNCTX_SPLIT_TOKEN_9Z7Q"
        command = f"curl -u https://user:{secret}\\\n123@example.invalid/p"
        _write_skill(temp_dir, "```!\n" + command + "\n```\n")

        violations = _check(temp_dir)

        assert len(violations) == 1
        message = violations[0].message
        assert secret not in message
        assert "user:" not in message
        assert "123@example" not in message
        assert "[redacted]" in message

    def test_truncated_credential_is_redacted_from_command_display(self, temp_dir):
        # A colon-free credential longer than the display cap leaves a tail
        # with nothing credential-shaped about it — truncating before
        # redacting must still look past the cut for the ``@`` that names
        # the tail userinfo, or the token rides into the message verbatim.
        secret = "T" * 600
        command = f"curl https://user:{secret}@example.invalid/x"
        _write_skill(temp_dir, "```!\n" + command + "\n```\n")

        violations = _check(temp_dir)

        assert len(violations) == 1
        message = violations[0].message
        assert secret not in message
        assert "TTT" not in message
        assert "[redacted]" in message

    def test_credential_severed_after_a_continuation_is_fully_redacted(self, temp_dir):
        # The cut lands past a backslash-newline that joins the credential's
        # words: the backward boundary must skip the pair like the redaction
        # scan does, or only the fragment after the split is replaced and
        # ``user:SECRET`` stays visible ahead of it.
        command = "curl https://user:SECRET\\" + "\n" + "T" * 480 + "@example.invalid/x"
        _write_skill(temp_dir, "```!\n" + command + "\n```\n")

        violations = _check(temp_dir)

        assert len(violations) == 1
        message = violations[0].message
        assert "SECRET" not in message
        assert "TTT" not in message
        assert "[redacted]" in message

    def test_html_comment_content_is_not_classified(self, temp_dir):
        # Pins the recorded boundary: dynamic-context syntax inside an HTML
        # comment is not expanded by clients and is not reported here —
        # hidden directives in comments are security-hidden-instructions'
        # territory.
        _write_skill(temp_dir, "<!-- !`git diff HEAD` -->\n\n<!--\n```!\ngit status\n```\n-->\n")

        assert _check(temp_dir) == []

    def test_multiline_inline_span_is_not_classified(self, temp_dir):
        # Pins the recorded boundary: an inline code span that wraps across
        # lines has no trustworthy column, so it is skipped; the fenced form
        # is the supported representation for multi-line commands.
        _write_skill(temp_dir, "Run !`git\nstatus` when reviewing.\n")

        assert _check(temp_dir) == []

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
