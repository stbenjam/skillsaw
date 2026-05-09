"""Tests for .coderabbit.yaml linting rules."""

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext
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
        assert rule.repo_types is None

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
        assert rule.repo_types is None

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

    def test_no_reviews_no_chat(self):
        raw = "language: en-US\n"
        import yaml

        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 0


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
