"""Tests for .coderabbit.yaml linting rules."""

from pathlib import Path

import yaml

from skillsaw.config import LinterConfig
from skillsaw.context import RepositoryContext, RepositoryType
from skillsaw.rule import Severity
from skillsaw.rules.builtin.coderabbit import (
    CoderabbitYamlValidRule,
)
from skillsaw.rules.builtin.content_analysis import (
    _extract_instructions,
    gather_all_content_files,
    _get_body_from_cf,
    ContentFile,
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


# ---------------------------------------------------------------------------
# Per-instruction ContentFile for .coderabbit.yaml
# ---------------------------------------------------------------------------


class TestGetBodyCoderabbit:
    """Verify _get_body_from_cf returns pre-populated body for coderabbit ContentFiles."""

    def test_returns_body_from_cf(self):
        cf = ContentFile(path=Path(".coderabbit.yaml"), category="coderabbit", body="Do stuff.")
        body = _get_body_from_cf(cf)
        assert body == "Do stuff."

    def test_returns_none_for_no_body_missing_file(self, temp_dir):
        cf = ContentFile(path=temp_dir / "nonexistent.yaml", category="coderabbit")
        body = _get_body_from_cf(cf)
        assert body is None


# ---------------------------------------------------------------------------
# gather_all_content_files yields per-instruction ContentFiles
# ---------------------------------------------------------------------------


class TestGatherContentFilesCoderabbit:
    def test_yields_one_per_instruction(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n"
            "  instructions: 'Review stuff.'\n"
            "chat:\n"
            "  instructions: 'Chat stuff.'\n"
        )
        context = RepositoryContext(temp_dir)
        files = gather_all_content_files(context)
        cr_files = [cf for cf in files if cf.category == "coderabbit"]
        assert len(cr_files) == 2
        bodies = [cf.body for cf in cr_files]
        assert "Review stuff." in bodies
        assert "Chat stuff." in bodies

    def test_line_offsets_are_correct(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n"  # 1
            "  instructions: 'Review stuff.'\n"  # 2
            "chat:\n"  # 3
            "  instructions: 'Chat stuff.'\n"  # 4
        )
        context = RepositoryContext(temp_dir)
        files = gather_all_content_files(context)
        cr_files = [cf for cf in files if cf.category == "coderabbit"]
        assert len(cr_files) == 2
        # line_offset = line - 1, so body line 1 + offset = YAML line
        assert cr_files[0].line_offset == 1  # instructions key on line 2
        assert cr_files[1].line_offset == 3  # instructions key on line 4

    def test_no_instructions_yields_nothing(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text("language: en-US\n")
        context = RepositoryContext(temp_dir)
        files = gather_all_content_files(context)
        cr_files = [cf for cf in files if cf.category == "coderabbit"]
        assert len(cr_files) == 0

    def test_invalid_yaml_yields_nothing(self, temp_dir):
        (temp_dir / ".coderabbit.yaml").write_text(":\n  bad: [unterminated\n")
        context = RepositoryContext(temp_dir)
        files = gather_all_content_files(context)
        cr_files = [cf for cf in files if cf.category == "coderabbit"]
        assert len(cr_files) == 0

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
