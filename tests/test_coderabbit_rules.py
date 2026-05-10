"""Tests for .coderabbit.yaml linting rules."""

import yaml

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.coderabbit import (
    CoderabbitYamlValidRule,
)
from skillsaw.rules.builtin.content_analysis import (
    _extract_instructions,
    _extract_coderabbit_instructions_body,
    gather_all_content_files,
    _get_body,
)
from skillsaw.rules.builtin.content_rules import (
    ContentWeakLanguageRule,
    ContentTautologicalRule,
)

# ---------------------------------------------------------------------------
# CoderabbitYamlValidRule
# ---------------------------------------------------------------------------


class TestCoderabbitYamlValidRule:
    def test_rule_metadata(self):
        rule = CoderabbitYamlValidRule()
        assert rule.rule_id == "coderabbit-yaml-valid"
        assert rule.default_severity() == Severity.ERROR
        assert rule.repo_types == {RepositoryType.CODERABBIT}

    def test_no_file_passes(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = CoderabbitYamlValidRule().check(context)
        assert len(violations) == 0

    def test_valid_yaml_passes(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text("language: en-US\nreviews:\n  profile: chill\n")
        context = RepositoryContext(temp_dir)
        violations = CoderabbitYamlValidRule().check(context)
        assert len(violations) == 0

    def test_empty_yaml_passes(self, temp_dir):
        # Empty YAML is valid (loads as None) but top-level must be a mapping
        (temp_dir / ".coderabbit.yaml").write_text("")
        context = RepositoryContext(temp_dir)
        violations = CoderabbitYamlValidRule().check(context)
        # yaml.safe_load("") returns None, which is not a dict
        assert len(violations) == 1
        assert "mapping" in violations[0].message.lower()

    def test_invalid_yaml_fails(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(":\n  - :\n  bad: [unterminated\n")
        context = RepositoryContext(temp_dir)
        violations = CoderabbitYamlValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR
        assert "invalid yaml" in violations[0].message.lower()

    def test_invalid_yaml_reports_line(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text("good: value\nbad: [unterminated\n")
        context = RepositoryContext(temp_dir)
        violations = CoderabbitYamlValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].line is not None

    def test_non_mapping_top_level(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text("- item1\n- item2\n")
        context = RepositoryContext(temp_dir)
        violations = CoderabbitYamlValidRule().check(context)
        assert len(violations) == 1
        assert "mapping" in violations[0].message.lower()

    def test_unreadable_file(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_bytes(b"\x80\x81\x82\x83")
        context = RepositoryContext(temp_dir)
        violations = CoderabbitYamlValidRule().check(context)
        assert len(violations) == 1
        assert (
            "read" in violations[0].message.lower() or "encoding" in violations[0].message.lower()
        )


# ---------------------------------------------------------------------------
# Content rules on .coderabbit.yaml instructions
# ---------------------------------------------------------------------------


class TestContentRulesOnCoderabbit:
    """Verify that content-* rules fire on .coderabbit.yaml instruction text."""

    def test_weak_language_detected_in_reviews_instructions(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n  instructions: 'Try to check for null pointers if possible.'\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) >= 1
        phrases = [v.message for v in coderabbit_violations]
        assert any("try to" in msg.lower() or "if possible" in msg.lower() for msg in phrases)

    def test_clean_instructions_no_violations(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n  instructions: 'Always check for null pointers.'\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) == 0

    def test_tautological_detected_in_instructions(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n  instructions: 'Write clean code and follow best practices.'\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentTautologicalRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) >= 1

    def test_no_instructions_no_content_violations(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text("language: en-US\nreviews:\n  profile: chill\n")
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) == 0

    def test_invalid_yaml_no_content_violations(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(":\n  bad: [unterminated\n")
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) == 0

    def test_weak_language_in_chat_instructions(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(
            "chat:\n  instructions: 'You might want to be helpful.'\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) >= 1

    def test_weak_language_in_tool_instructions(self, temp_dir):
        content = (
            "reviews:\n"
            "  tools:\n"
            "    biome:\n"
            "      instructions: 'Try to follow the style guide.'\n"
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) >= 1

    def test_violation_line_numbers_match_real_file_inline(self, temp_dir):
        """Violations in .coderabbit.yaml should report real YAML line numbers."""
        content = (
            "language: en-US\n"  # line 1
            "reviews:\n"  # line 2
            "  instructions: 'Try to check for null pointers.'\n"  # line 3
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) >= 1
        # "Try to" is on the instructions: key line (line 3), not line 1
        for v in coderabbit_violations:
            assert v.line == 3, f"Expected line 3, got {v.line}: {v.message}"

    def test_violation_line_numbers_match_real_file_block_scalar(self, temp_dir):
        """Block scalar instructions should report real YAML line numbers."""
        content = (
            "reviews:\n"  # line 1
            "  instructions: |\n"  # line 2
            "    Always check for null pointers.\n"  # line 3
            "    Try to validate all inputs.\n"  # line 4
            "    Handle errors with retries.\n"  # line 5
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) >= 1
        # "Try to" is on line 4 of the real file
        try_violations = [v for v in coderabbit_violations if "try to" in v.message.lower()]
        assert len(try_violations) == 1
        assert try_violations[0].line == 4, f"Expected line 4, got {try_violations[0].line}"

    def test_violation_line_numbers_multiple_instruction_sections(self, temp_dir):
        """Line numbers should be correct across multiple instruction sections."""
        content = (
            "reviews:\n"  # line 1
            "  instructions: |\n"  # line 2
            "    Always check null pointers.\n"  # line 3
            "    Validate all inputs.\n"  # line 4
            "  path_instructions:\n"  # line 5
            "    - path: 'src/**'\n"  # line 6
            "      instructions: 'Try to follow the style guide.'\n"  # line 7
            "chat:\n"  # line 8
            "  instructions: 'You might want to add docs.'\n"  # line 9
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) >= 2
        lines = sorted(v.line for v in coderabbit_violations)
        # "Try to" is on line 7, "You might want to" is on line 9
        assert 7 in lines, f"Expected line 7 in {lines}"
        assert 9 in lines, f"Expected line 9 in {lines}"


# ---------------------------------------------------------------------------
# _get_body for .coderabbit.yaml
# ---------------------------------------------------------------------------


class TestGetBodyCoderabbit:
    """Verify _get_body extracts instruction text from .coderabbit.yaml."""

    def test_extracts_review_instructions(self, temp_dir):
        cr = temp_dir / ".coderabbit.yaml"
        cr.write_text("reviews:\n  instructions: 'Do stuff.'\n")
        body = _get_body(cr)
        assert body is not None
        assert "Do stuff." in body

    def test_extracts_multiple_instruction_fields(self, temp_dir):
        cr = temp_dir / ".coderabbit.yaml"
        cr.write_text(
            "reviews:\n"
            "  instructions: 'Review stuff.'\n"
            "chat:\n"
            "  instructions: 'Chat stuff.'\n"
        )
        body = _get_body(cr)
        assert body is not None
        assert "Review stuff." in body
        assert "Chat stuff." in body

    def test_returns_empty_for_no_instructions(self, temp_dir):
        cr = temp_dir / ".coderabbit.yaml"
        cr.write_text("language: en-US\n")
        body = _get_body(cr)
        assert body == ""

    def test_returns_empty_for_invalid_yaml(self, temp_dir):
        cr = temp_dir / ".coderabbit.yaml"
        cr.write_text(":\n  bad: [unterminated\n")
        body = _get_body(cr)
        assert body == ""

    def test_body_preserves_line_numbers_for_block_scalar(self, temp_dir):
        """_get_body should place instruction text at real YAML line positions."""
        cr = temp_dir / ".coderabbit.yaml"
        cr.write_text(
            "reviews:\n"  # line 1
            "  instructions: |\n"  # line 2
            "    First instruction.\n"  # line 3
            "    Second instruction.\n"  # line 4
        )
        body = _get_body(cr)
        assert body is not None
        lines = body.splitlines()
        # lines[2] (0-indexed) is line 3 (1-indexed) -> "First instruction."
        assert "First instruction." in lines[2]
        assert "Second instruction." in lines[3]

    def test_body_preserves_line_numbers_for_inline_scalar(self, temp_dir):
        """Inline instruction text should appear at the key's line."""
        cr = temp_dir / ".coderabbit.yaml"
        cr.write_text(
            "language: en-US\n"  # line 1
            "reviews:\n"  # line 2
            "  instructions: 'Do stuff.'\n"  # line 3
        )
        body = _get_body(cr)
        assert body is not None
        lines = body.splitlines()
        # line 3 (1-indexed) = lines[2] (0-indexed)
        assert "Do stuff." in lines[2]


# ---------------------------------------------------------------------------
# _extract_coderabbit_instructions_body line alignment
# ---------------------------------------------------------------------------


class TestCoderabbitBodyLineAlignment:
    """Verify _extract_coderabbit_instructions_body aligns text to real lines."""

    def test_block_scalar_alignment(self):
        raw = (
            "reviews:\n"  # line 1
            "  instructions: |\n"  # line 2
            "    Check nulls.\n"  # line 3
            "    Validate inputs.\n"  # line 4
        )
        body = _extract_coderabbit_instructions_body(raw)
        lines = body.splitlines()
        assert lines[2] == "Check nulls."  # line 3
        assert lines[3] == "Validate inputs."  # line 4

    def test_inline_scalar_alignment(self):
        raw = (
            "reviews:\n"  # line 1
            "  instructions: 'Do stuff.'\n"  # line 2
        )
        body = _extract_coderabbit_instructions_body(raw)
        lines = body.splitlines()
        assert lines[1] == "Do stuff."  # line 2

    def test_multiple_sections_alignment(self):
        raw = (
            "reviews:\n"  # line 1
            "  instructions: |\n"  # line 2
            "    Review stuff.\n"  # line 3
            "chat:\n"  # line 4
            "  instructions: 'Chat stuff.'\n"  # line 5
        )
        body = _extract_coderabbit_instructions_body(raw)
        lines = body.splitlines()
        assert lines[2] == "Review stuff."  # line 3
        assert lines[4] == "Chat stuff."  # line 5

    def test_padding_lines_are_blank(self):
        raw = (
            "language: en-US\n"  # line 1
            "reviews:\n"  # line 2
            "  instructions: 'Do stuff.'\n"  # line 3
        )
        body = _extract_coderabbit_instructions_body(raw)
        lines = body.splitlines()
        # Lines 1-2 should be blank padding
        assert lines[0] == ""
        assert lines[1] == ""
        assert lines[2] == "Do stuff."

    def test_block_scalar_with_comment_alignment(self):
        """Block scalar indicator with trailing YAML comment should still work."""
        raw = (
            "reviews:\n"  # line 1
            "  instructions: | # this is a comment\n"  # line 2
            "    Check nulls.\n"  # line 3
            "    Validate inputs.\n"  # line 4
        )
        body = _extract_coderabbit_instructions_body(raw)
        lines = body.splitlines()
        assert lines[2] == "Check nulls."  # line 3
        assert lines[3] == "Validate inputs."  # line 4

    def test_empty_body_on_no_instructions(self):
        raw = "language: en-US\n"
        body = _extract_coderabbit_instructions_body(raw)
        assert body == ""

    def test_empty_body_on_invalid_yaml(self):
        raw = ":\n  bad: [unterminated\n"
        body = _extract_coderabbit_instructions_body(raw)
        assert body == ""


# ---------------------------------------------------------------------------
# gather_all_content_files includes .coderabbit.yaml
# ---------------------------------------------------------------------------


class TestGatherContentFilesCoderabbit:
    def test_includes_coderabbit_yaml(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text("reviews:\n  instructions: 'Do stuff.'\n")
        context = RepositoryContext(temp_dir)
        files = gather_all_content_files(context)
        paths = [cf.path for cf in files]
        assert temp_dir / ".coderabbit.yaml" in paths
        categories = {cf.category for cf in files if cf.path == temp_dir / ".coderabbit.yaml"}
        assert "coderabbit" in categories

    def test_not_included_when_absent(self, temp_dir):
        context = RepositoryContext(temp_dir)
        files = gather_all_content_files(context)
        paths = [cf.path for cf in files]
        assert temp_dir / ".coderabbit.yaml" not in paths


# ---------------------------------------------------------------------------
# _extract_instructions helper
# ---------------------------------------------------------------------------


class TestExtractInstructions:
    def test_reviews_instructions(self):
        raw = "reviews:\n  instructions: 'Do stuff.'\n"
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 1
        assert result[0][0] == "reviews.instructions"
        assert result[0][1] == "Do stuff."

    def test_path_instructions(self):
        raw = (
            "reviews:\n"
            "  path_instructions:\n"
            "    - path: 'src/**'\n"
            "      instructions: 'Check src.'\n"
            "    - path: 'tests/**'\n"
            "      instructions: 'Check tests.'\n"
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 2
        assert "src/**" in result[0][0]
        assert "tests/**" in result[1][0]

    def test_tool_instructions(self):
        raw = (
            "reviews:\n"
            "  tools:\n"
            "    biome:\n"
            "      instructions: 'Use biome rules.'\n"
            "    eslint:\n"
            "      instructions: 'Use eslint rules.'\n"
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 2
        tool_names = [r[0] for r in result]
        assert any("biome" in t for t in tool_names)
        assert any("eslint" in t for t in tool_names)

    def test_chat_instructions(self):
        raw = "chat:\n  instructions: 'Be helpful.'\n"
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 1
        assert result[0][0] == "chat.instructions"
        assert result[0][1] == "Be helpful."

    def test_empty_instructions_skipped(self):
        raw = "reviews:\n  instructions: ''\n"
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 0

    def test_non_string_instructions_skipped(self):
        raw = "reviews:\n  instructions:\n    - item1\n    - item2\n"
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 0

    def test_custom_check_instructions(self):
        raw = (
            "reviews:\n"
            "  pre_merge_checks:\n"
            "    custom_checks:\n"
            "      - name: 'Go Error Handling'\n"
            "        mode: warning\n"
            "        instructions: 'Check error handling.'\n"
            "      - name: 'SQL Injection'\n"
            "        mode: error\n"
            "        instructions: 'Prevent SQL injection.'\n"
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 2
        assert "Go Error Handling" in result[0][0]
        assert result[0][1] == "Check error handling."
        assert "SQL Injection" in result[1][0]
        assert result[1][1] == "Prevent SQL injection."

    def test_custom_check_instructions_line_numbers(self):
        raw = (
            "reviews:\n"
            "  pre_merge_checks:\n"
            "    custom_checks:\n"
            "      - name: 'Go Error Handling'\n"
            "        instructions: 'Check error handling.'\n"
            "      - name: 'SQL Injection'\n"
            "        instructions: 'Prevent SQL injection.'\n"
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 2
        assert result[0][2] == 5  # line of first instructions key
        assert result[1][2] == 7  # line of second instructions key

    def test_custom_check_empty_instructions_skipped(self):
        raw = (
            "reviews:\n"
            "  pre_merge_checks:\n"
            "    custom_checks:\n"
            "      - name: 'Check A'\n"
            "        instructions: ''\n"
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 0

    def test_custom_check_no_instructions_field(self):
        raw = (
            "reviews:\n"
            "  pre_merge_checks:\n"
            "    custom_checks:\n"
            "      - name: 'Check A'\n"
            "        mode: warning\n"
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 0

    def test_no_reviews_no_chat(self):
        raw = "language: en-US\n"
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Multi-type detection
# ---------------------------------------------------------------------------


class TestCoderabbitMultiType:
    def test_coderabbit_rules_fire_alongside_dot_claude(self, temp_dir):
        """CodeRabbit rules should fire when .coderabbit.yaml is present alongside .claude/"""
        claude_dir = temp_dir / ".claude"
        claude_dir.mkdir()
        (claude_dir / "commands").mkdir()
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n  instructions: 'Try to be strict.'\n"
        )

        context = RepositoryContext(temp_dir)
        assert RepositoryType.CODERABBIT in context.repo_types
        assert RepositoryType.DOT_CLAUDE in context.repo_types

        # Content weak-language rule should fire on the coderabbit instruction text
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) >= 1

    def test_coderabbit_rules_auto_enabled_with_coderabbit_type(self, temp_dir):
        """When repo has CODERABBIT type, auto-enabled coderabbit rules should fire"""
        (temp_dir / ".coderabbit.yaml").write_text("language: en-US\n")
        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()

        assert config.is_rule_enabled(
            "coderabbit-yaml-valid",
            context,
            {RepositoryType.CODERABBIT},
        )

    def test_coderabbit_rules_not_enabled_without_coderabbit_type(self, temp_dir):
        """Without .coderabbit.yaml, auto-enabled coderabbit rules should not fire"""
        context = RepositoryContext(temp_dir)
        config = LinterConfig.default()

        assert not config.is_rule_enabled(
            "coderabbit-yaml-valid",
            context,
            {RepositoryType.CODERABBIT},
        )


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestCoderabbitConfig:
    def test_yaml_valid_default_auto(self):
        config = LinterConfig.default()
        assert config.get_rule_config("coderabbit-yaml-valid").get("enabled") == "auto"

    def test_yaml_valid_default_severity_error(self):
        config = LinterConfig.default()
        assert config.get_rule_config("coderabbit-yaml-valid").get("severity") == "error"
