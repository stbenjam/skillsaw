"""Tests for .coderabbit.yaml linting rules."""

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.coderabbit import (
    CoderabbitYamlValidRule,
    CoderabbitInstructionsRule,
    _extract_instructions,
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
# CoderabbitInstructionsRule
# ---------------------------------------------------------------------------


class TestCoderabbitInstructionsRule:
    def test_rule_metadata(self):
        rule = CoderabbitInstructionsRule()
        assert rule.rule_id == "coderabbit-instructions"
        assert rule.default_severity() == Severity.WARNING
        assert rule.repo_types == {RepositoryType.CODERABBIT}

    def test_no_file_passes(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 0

    def test_no_instructions_passes(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text("language: en-US\nreviews:\n  profile: chill\n")
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 0

    def test_clean_instructions_passes(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n  instructions: 'Always check for null pointers.'\n"
        )
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 0

    def test_weak_language_in_reviews_instructions(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n  instructions: 'Maybe check for null pointers if possible.'\n"
        )
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert "weak" in violations[0].message.lower() or "hedge" in violations[0].message.lower()
        assert "reviews.instructions" in violations[0].message

    def test_weak_language_in_path_instructions(self, temp_dir):
        content = (
            "reviews:\n"
            "  path_instructions:\n"
            "    - path: 'src/**'\n"
            "      instructions: 'Perhaps validate inputs here.'\n"
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert "path_instructions" in violations[0].message

    def test_weak_language_in_tool_instructions(self, temp_dir):
        content = (
            "reviews:\n"
            "  tools:\n"
            "    biome:\n"
            "      instructions: 'Try to follow the style guide.'\n"
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert "biome" in violations[0].message

    def test_weak_language_in_chat_instructions(self, temp_dir):
        content = "chat:\n  instructions: 'You might want to be helpful.'\n"
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert "chat.instructions" in violations[0].message

    def test_weak_language_in_custom_check_instructions(self, temp_dir):
        content = (
            "reviews:\n"
            "  pre_merge_checks:\n"
            "    custom_checks:\n"
            "      - name: 'Go Error Handling'\n"
            "        mode: warning\n"
            "        instructions: 'Maybe check for error handling.'\n"
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert "custom_checks" in violations[0].message
        assert "Go Error Handling" in violations[0].message

    def test_clean_custom_check_instructions_passes(self, temp_dir):
        content = (
            "reviews:\n"
            "  pre_merge_checks:\n"
            "    custom_checks:\n"
            "      - name: 'Go Error Handling'\n"
            "        mode: warning\n"
            "        instructions: 'Ensure all errors are wrapped with fmt.Errorf.'\n"
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 0

    def test_custom_check_instructions_line_number(self, temp_dir):
        content = (
            "language: en-US\n"
            "reviews:\n"
            "  pre_merge_checks:\n"
            "    custom_checks:\n"
            "      - name: 'Go Error Handling'\n"
            "        mode: warning\n"
            "        instructions: 'Maybe check things.'\n"
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 7

    def test_multiple_custom_checks_with_issues(self, temp_dir):
        content = (
            "reviews:\n"
            "  pre_merge_checks:\n"
            "    custom_checks:\n"
            "      - name: 'Check A'\n"
            "        instructions: 'Maybe do A.'\n"
            "      - name: 'Check B'\n"
            "        instructions: 'Perhaps do B.'\n"
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 2
        assert "Check A" in violations[0].message
        assert "Check B" in violations[1].message

    def test_multiple_instruction_fields_with_issues(self, temp_dir):
        content = (
            "reviews:\n"
            "  instructions: 'Maybe be strict.'\n"
            "chat:\n"
            "  instructions: 'Perhaps answer questions.'\n"
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 2

    def test_truncation_with_many_weak_phrases(self, temp_dir):
        """When 4+ weak-language matches are found, the message should truncate with '(and N more)'."""
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n"
            "  instructions: |\n"
            "    Maybe check for nulls.\n"
            "    Perhaps validate inputs.\n"
            "    Try to follow the style guide.\n"
            "    You might want to add tests.\n"
            "    Could potentially break things.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert "(and 2 more)" in violations[0].message

    def test_consider_with_action_verb_flagged(self, temp_dir):
        """'consider using' should be flagged as weak language."""
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n  instructions: 'Consider using type hints everywhere.'\n"
        )
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert "consider" in violations[0].message.lower()

    def test_consider_without_action_verb_passes(self, temp_dir):
        """'consider the following' should NOT be flagged -- it is legitimate."""
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n  instructions: 'Consider the following constraints when reviewing.'\n"
        )
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 0

    def test_severity_override_respected(self, temp_dir):
        """User severity overrides from config should apply to weak-language violations."""
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n  instructions: 'Maybe check for null pointers.'\n"
        )
        context = RepositoryContext(temp_dir)
        rule = CoderabbitInstructionsRule(config={"severity": "error"})
        violations = rule.check(context)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR

    def test_invalid_yaml_skipped(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(":\n  bad: [unterminated\n")
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 0

    def test_line_number_reported(self, temp_dir):
        content = (
            "language: en-US\n"
            "reviews:\n"
            "  profile: chill\n"
            "  instructions: 'Maybe check things.'\n"
        )
        (temp_dir / ".coderabbit.yaml").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 4

    def test_file_path_reported(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text("reviews:\n  instructions: 'Maybe do things.'\n")
        context = RepositoryContext(temp_dir)
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert violations[0].file_path == temp_dir / ".coderabbit.yaml"


# ---------------------------------------------------------------------------
# _extract_instructions helper
# ---------------------------------------------------------------------------


class TestExtractInstructions:
    def test_reviews_instructions(self):
        raw = "reviews:\n  instructions: 'Do stuff.'\n"
        import yaml

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
        import yaml

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
        import yaml

        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 2
        tool_names = [r[0] for r in result]
        assert any("biome" in t for t in tool_names)
        assert any("eslint" in t for t in tool_names)

    def test_chat_instructions(self):
        raw = "chat:\n  instructions: 'Be helpful.'\n"
        import yaml

        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 1
        assert result[0][0] == "chat.instructions"
        assert result[0][1] == "Be helpful."

    def test_empty_instructions_skipped(self):
        raw = "reviews:\n  instructions: ''\n"
        import yaml

        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 0

    def test_non_string_instructions_skipped(self):
        raw = "reviews:\n  instructions:\n    - item1\n    - item2\n"
        import yaml

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
        import yaml

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
        import yaml

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
        import yaml

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
        import yaml

        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 0

    def test_no_reviews_no_chat(self):
        raw = "language: en-US\n"
        import yaml

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
        (temp_dir / ".coderabbit.yaml").write_text("reviews:\n  instructions: 'Maybe be strict.'\n")

        context = RepositoryContext(temp_dir)
        assert RepositoryType.CODERABBIT in context.repo_types
        assert RepositoryType.DOT_CLAUDE in context.repo_types

        # The coderabbit rules should still fire
        violations = CoderabbitInstructionsRule().check(context)
        assert len(violations) == 1
        assert "weak" in violations[0].message.lower() or "hedge" in violations[0].message.lower()

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

    def test_instructions_default_auto(self):
        config = LinterConfig.default()
        assert config.get_rule_config("coderabbit-instructions").get("enabled") == "auto"

    def test_yaml_valid_default_severity_error(self):
        config = LinterConfig.default()
        assert config.get_rule_config("coderabbit-yaml-valid").get("severity") == "error"

    def test_instructions_default_severity_warning(self):
        config = LinterConfig.default()
        assert config.get_rule_config("coderabbit-instructions").get("severity") == "warning"
