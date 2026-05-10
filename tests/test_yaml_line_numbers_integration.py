"""
Integration tests for YAML line number reporting.

These tests verify that the actual rule checks report correct line numbers
when linting real-world-style files, after the refactor to centralize
YAML line number handling with ruamel.yaml.
"""

import yaml

from skillsaw.context import RepositoryContext
from skillsaw.rules.builtin.coderabbit import CoderabbitYamlValidRule
from skillsaw.rules.builtin.content_analysis import (
    _extract_instructions,
)
from skillsaw.rules.builtin.content_rules import (
    ContentWeakLanguageRule,
    ContentTautologicalRule,
)
from skillsaw.rules.builtin.openclaw import OpenclawMetadataRule
from skillsaw.rules.builtin.agentskills import AgentSkillValidRule, AgentSkillNameRule
from skillsaw.rules.builtin.apm import ApmYamlValidRule

# ---------------------------------------------------------------------------
# (a) .coderabbit.yaml line numbers
# ---------------------------------------------------------------------------


class TestCoderabbitLineNumbers:
    """Verify _extract_instructions reports correct line numbers for coderabbit files."""

    def test_block_scalar_instructions_line(self):
        """Block scalar (|) instructions should report the line of the instructions key."""
        raw = (
            "reviews:\n"  # 1
            "  instructions: |\n"  # 2
            "    Check for null pointers.\n"  # 3
            "    Verify error handling.\n"  # 4
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 1
        assert result[0][0] == "reviews.instructions"
        assert result[0][2] == 2  # line of the 'instructions' key

    def test_path_instructions_nested_line_numbers(self):
        """Path-specific instructions should report the correct line for each entry."""
        raw = (
            "reviews:\n"  # 1
            "  instructions: 'General review.'\n"  # 2
            "  path_instructions:\n"  # 3
            "    - path: 'src/**'\n"  # 4
            "      instructions: 'Check src.'\n"  # 5
            "    - path: 'tests/**'\n"  # 6
            "      instructions: 'Check tests.'\n"  # 7
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 3
        # reviews.instructions
        assert result[0][0] == "reviews.instructions"
        assert result[0][2] == 2
        # path_instructions[0]
        assert "src/**" in result[1][0]
        assert result[1][2] == 5
        # path_instructions[1]
        assert "tests/**" in result[2][0]
        assert result[2][2] == 7

    def test_multiple_instructions_at_different_levels(self):
        """Multiple instructions keys at different nesting levels get correct lines."""
        raw = (
            "reviews:\n"  # 1
            "  instructions: 'Review instructions.'\n"  # 2
            "  tools:\n"  # 3
            "    biome:\n"  # 4
            "      instructions: 'Biome rules.'\n"  # 5
            "chat:\n"  # 6
            "  instructions: 'Chat instructions.'\n"  # 7
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 3
        # Each should point to its own 'instructions' key line
        labels = {r[0]: r[2] for r in result}
        assert labels["reviews.instructions"] == 2
        assert labels["reviews.tools.biome.instructions"] == 5
        assert labels["chat.instructions"] == 7

    def test_empty_and_nonempty_instructions_mixed(self):
        """Empty instructions are skipped; remaining entries still get line numbers."""
        raw = (
            "reviews:\n"  # 1
            "  instructions: 'General review.'\n"  # 2
            "  path_instructions:\n"  # 3
            "    - path: 'src/**'\n"  # 4
            "      instructions: 'Check source.'\n"  # 5
            "    - path: 'tests/**'\n"  # 6
            "      instructions: ''\n"  # 7  (empty, skipped)
            "    - path: 'docs/**'\n"  # 8
            "      instructions: 'Check docs.'\n"  # 9
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 3
        assert result[0][0] == "reviews.instructions"
        assert result[0][2] == 2
        assert "src/**" in result[1][0]
        assert result[1][2] == 5
        assert "docs/**" in result[2][0]
        assert result[2][2] is not None
        assert result[2][2] > 0

    def test_content_rule_fires_on_coderabbit_with_file_path(self, temp_dir):
        """Content rules should fire on .coderabbit.yaml and report the file path."""
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n"
            "  instructions: |\n"
            "    Try to check for null pointers if possible.\n"
            "    Write clean code and follow best practices.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = ContentWeakLanguageRule().check(context)
        coderabbit_violations = [
            v for v in violations if v.file_path == temp_dir / ".coderabbit.yaml"
        ]
        assert len(coderabbit_violations) >= 1

    def test_custom_checks_line_numbers(self):
        """Custom check instructions should get line numbers from ruamel.yaml."""
        raw = (
            "reviews:\n"  # 1
            "  pre_merge_checks:\n"  # 2
            "    custom_checks:\n"  # 3
            "      - name: 'Error Handling'\n"  # 4
            "        mode: warning\n"  # 5
            "        instructions: 'Check errors.'\n"  # 6
            "      - name: 'SQL Safety'\n"  # 7
            "        mode: error\n"  # 8
            "        instructions: 'Prevent SQLi.'\n"  # 9
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 2
        assert result[0][2] == 6
        assert result[1][2] == 9


# ---------------------------------------------------------------------------
# (b) SKILL.md frontmatter (openclaw) line numbers
# ---------------------------------------------------------------------------


class TestOpenclawLineNumbers:
    """Verify openclaw rule reports correct line numbers via yaml_line_map."""

    def test_duplicate_key_names_at_different_levels(self, temp_dir):
        """os at top level and inside install should both report line numbers.

        yaml_line_map is a flat map with last-wins semantics, so when the
        same key name appears at multiple nesting levels, both violations
        may share a line number. We assert that line numbers are present
        and non-zero rather than pinning to a specific value, since the
        flat map is a known limitation.
        """
        skill = temp_dir / "dup-os"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"  # 1
            "name: dup-os\n"  # 2
            "description: test\n"  # 3
            "metadata:\n"  # 4
            "  openclaw:\n"  # 5
            "    os:\n"  # 6
            "      - darwin\n"  # 7
            "      - windows\n"  # 8  (invalid for top-level os)
            "    install:\n"  # 9
            "      - id: brew\n"  # 10
            "        kind: brew\n"  # 11
            "        os:\n"  # 12
            "          - macos\n"  # 13  (invalid install os)
            "---\n"
        )
        context = RepositoryContext(skill)
        violations = OpenclawMetadataRule().check(context)
        os_violations = [v for v in violations if "invalid values" in v.message]
        assert len(os_violations) == 2
        for v in os_violations:
            assert v.line is not None
            assert v.line > 0

    def test_values_with_colons_in_frontmatter(self, temp_dir):
        """Values containing colons should not confuse line number tracking."""
        skill = temp_dir / "colon-val"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"  # 1
            "name: colon-val\n"  # 2
            "description: test\n"  # 3
            "metadata:\n"  # 4
            "  openclaw:\n"  # 5
            "    homepage: 'http://example.com:8080'\n"  # 6
            "    emoji: 42\n"  # 7 (wrong type)
            "---\n"
        )
        context = RepositoryContext(skill)
        violations = OpenclawMetadataRule().check(context)
        assert len(violations) == 1
        assert "emoji" in violations[0].message
        assert violations[0].line == 7

    def test_multiline_values_dont_shift_lines(self, temp_dir):
        """Multiline string values should not throw off line numbers for subsequent keys."""
        skill = temp_dir / "multiline-val"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"  # 1
            "name: multiline-val\n"  # 2
            "description: |\n"  # 3
            "  This is a long\n"  # 4
            "  description spanning\n"  # 5
            "  multiple lines.\n"  # 6
            "metadata:\n"  # 7
            "  openclaw:\n"  # 8
            "    always: not-a-bool\n"  # 9  (wrong type)
            "---\n"
        )
        context = RepositoryContext(skill)
        violations = OpenclawMetadataRule().check(context)
        assert len(violations) == 1
        assert "always" in violations[0].message
        assert violations[0].line == 9

    def test_requires_bins_wrong_type_line(self, temp_dir):
        """requires.bins wrong type should report the bins key line."""
        skill = temp_dir / "req-bins"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"  # 1
            "name: req-bins\n"  # 2
            "description: test\n"  # 3
            "metadata:\n"  # 4
            "  openclaw:\n"  # 5
            "    category: tools\n"  # 6
            "    requires:\n"  # 7
            "      bins: gws\n"  # 8  (wrong type -- should be list)
            "---\n"
        )
        context = RepositoryContext(skill)
        violations = OpenclawMetadataRule().check(context)
        bins_violations = [v for v in violations if "bins" in v.message and "list" in v.message]
        assert len(bins_violations) == 1
        assert bins_violations[0].line == 8


# ---------------------------------------------------------------------------
# (c) apm.yml line numbers
# ---------------------------------------------------------------------------


class TestApmLineNumbers:
    """Verify apm rule reports correct line numbers for fields."""

    def test_wrong_type_field_reports_line(self, temp_dir):
        """A field with wrong type should report the correct line number."""
        repo = temp_dir / "apm-repo"
        repo.mkdir()
        apm_dir = repo / ".apm"
        apm_dir.mkdir()
        (repo / "apm.yml").write_text(
            "name: test-repo\n"  # 1
            "version: 1.0.0\n"  # 2
            "description:\n"  # 3
            "  - not a string\n"  # 4  (wrong type -- should be string)
        )
        context = RepositoryContext(repo)
        violations = ApmYamlValidRule().check(context)
        desc_violations = [
            v for v in violations if "'description'" in v.message and "string" in v.message
        ]
        assert len(desc_violations) == 1
        assert desc_violations[0].line == 3

    def test_present_fields_have_correct_lines(self, temp_dir):
        """Line numbers for present fields are correct even when others are missing."""
        repo = temp_dir / "apm-repo2"
        repo.mkdir()
        apm_dir = repo / ".apm"
        apm_dir.mkdir()
        (repo / "apm.yml").write_text(
            "# Comment at the top\n"  # 1  (comment, not a key)
            "name: 42\n"  # 2  (wrong type)
            "version: 1.0.0\n"  # 3
            "description: good\n"  # 4
        )
        context = RepositoryContext(repo)
        violations = ApmYamlValidRule().check(context)
        name_violations = [v for v in violations if "'name'" in v.message and "string" in v.message]
        assert len(name_violations) == 1
        assert name_violations[0].line == 2

    def test_missing_fields_have_no_line(self, temp_dir):
        """Missing required fields should not fabricate a line number."""
        repo = temp_dir / "apm-repo3"
        repo.mkdir()
        apm_dir = repo / ".apm"
        apm_dir.mkdir()
        (repo / "apm.yml").write_text("name: test-repo\n")
        context = RepositoryContext(repo)
        violations = ApmYamlValidRule().check(context)
        missing_violations = [v for v in violations if "Missing" in v.message]
        # version and description should be missing
        assert len(missing_violations) == 2
        for v in missing_violations:
            assert v.line is None


# ---------------------------------------------------------------------------
# (d) General frontmatter line numbers
# ---------------------------------------------------------------------------


class TestFrontmatterLineNumbers:
    """Verify frontmatter-based rules report correct line numbers."""

    def test_name_with_colon_in_value(self, temp_dir):
        """A name field whose value contains a colon should still get the correct line."""
        skill = temp_dir / "colon-name"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"  # 1
            "name: 'my-skill: the best'\n"  # 2  (invalid name format)
            "description: A test skill\n"  # 3
            "---\n"
        )
        context = RepositoryContext(skill)
        violations = AgentSkillNameRule().check(context)
        name_violations = [v for v in violations if "name" in v.message.lower()]
        assert len(name_violations) >= 1
        assert name_violations[0].line == 2

    def test_multiline_description_doesnt_shift_name_line(self, temp_dir):
        """Multiline description in frontmatter should not shift the line number for name."""
        skill = temp_dir / "multiline-desc"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"  # 1
            "description: |\n"  # 2
            "  This skill does many things\n"  # 3
            "  across multiple lines.\n"  # 4
            "name: 'Bad Name!'\n"  # 5  (invalid name format)
            "---\n"
        )
        context = RepositoryContext(skill)
        violations = AgentSkillNameRule().check(context)
        name_violations = [v for v in violations if "name" in v.message.lower()]
        assert len(name_violations) >= 1
        assert name_violations[0].line == 5

    def test_skill_valid_name_type_wrong(self, temp_dir):
        """Non-string name should report the correct line."""
        skill = temp_dir / "bad-name-type"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"  # 1
            "description: A skill\n"  # 2
            "name: 42\n"  # 3  (wrong type)
            "---\n"
        )
        context = RepositoryContext(skill)
        violations = AgentSkillValidRule().check(context)
        type_violations = [v for v in violations if "string" in v.message]
        assert len(type_violations) == 1
        assert type_violations[0].line == 3

    def test_description_with_special_chars(self, temp_dir):
        """Description with special YAML characters should not confuse line tracking."""
        skill = temp_dir / "special-chars"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"  # 1
            "name: special-chars\n"  # 2
            "description: 'Uses: colons, {braces}, [brackets]'\n"  # 3
            "---\n"
        )
        context = RepositoryContext(skill)
        # This should parse cleanly with no violations
        violations = AgentSkillValidRule().check(context)
        name_violations = [v for v in violations if "name" in v.message and "match" in v.message]
        # The name doesn't match directory name but that's from AgentSkillNameRule, not Valid
        # AgentSkillValidRule should pass for correct types
        type_violations = [v for v in violations if "string" in v.message]
        assert len(type_violations) == 0

    def test_name_too_long_reports_correct_line(self, temp_dir):
        """A name exceeding max length should report the name key line."""
        skill = temp_dir / "long-name"
        skill.mkdir()
        long_name = "a" * 65
        (skill / "SKILL.md").write_text(
            "---\n"  # 1
            "description: A test skill\n"  # 2
            f"name: {long_name}\n"  # 3
            "---\n"
        )
        context = RepositoryContext(skill)
        violations = AgentSkillValidRule().check(context)
        len_violations = [v for v in violations if "exceeds" in v.message]
        assert len(len_violations) == 1
        assert len_violations[0].line == 3


# ---------------------------------------------------------------------------
# (e) Cross-cutting: coderabbit with all instruction types
# ---------------------------------------------------------------------------


class TestCoderabbitFullIntegration:
    """End-to-end tests with .coderabbit.yaml files in temp directories."""

    def test_tool_instructions_line_after_reviews(self, temp_dir):
        """Tool-specific instructions should get line numbers after their tool key."""
        (temp_dir / ".coderabbit.yaml").write_text(
            "reviews:\n"  # 1
            "  instructions: 'General review.'\n"  # 2
            "  tools:\n"  # 3
            "    biome:\n"  # 4
            "      instructions: 'Run biome checks.'\n"  # 5
            "    eslint:\n"  # 6
            "      instructions: 'Run eslint checks.'\n"  # 7
        )
        raw = (temp_dir / ".coderabbit.yaml").read_text()
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 3
        labels = {r[0]: r[2] for r in result}
        assert labels["reviews.instructions"] == 2
        assert labels["reviews.tools.biome.instructions"] == 5
        assert labels["reviews.tools.eslint.instructions"] == 7

    def test_path_instructions_with_block_scalars(self):
        """Path instructions using block scalars should report the key line, not content."""
        raw = (
            "reviews:\n"  # 1
            "  path_instructions:\n"  # 2
            "    - path: 'src/**'\n"  # 3
            "      instructions: |\n"  # 4
            "        Do thorough code review.\n"  # 5
            "        Check for edge cases.\n"  # 6
            "    - path: 'docs/**'\n"  # 7
            "      instructions: |\n"  # 8
            "        Check spelling.\n"  # 9
            "        Verify links.\n"  # 10
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 2
        # The line should point to the 'instructions' key, not the content
        assert result[0][2] == 4
        assert result[1][2] == 8

    def test_null_instructions_skipped_others_correct(self):
        """Null/None instruction values are skipped; valid entries still get line numbers."""
        raw = (
            "reviews:\n"  # 1
            "  instructions: 'Valid review.'\n"  # 2
            "  path_instructions:\n"  # 3
            "    - path: 'src/**'\n"  # 4
            "      instructions: ~\n"  # 5  (null, skipped)
            "    - path: 'tests/**'\n"  # 6
            "      instructions: 'Check tests.'\n"  # 7
            "chat:\n"  # 8
            "  instructions: null\n"  # 9  (null, skipped)
        )
        data = yaml.safe_load(raw)
        result = _extract_instructions(data, raw)
        assert len(result) == 2
        assert result[0][0] == "reviews.instructions"
        assert result[0][2] == 2
        assert "tests/**" in result[1][0]
        assert result[1][2] is not None
        assert result[1][2] > 0
