"""Tests for content analysis shared analyzers."""

import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.rules.builtin.content_analysis import (
    WeakLanguageDetector,
    TautologicalDetector,
    CriticalPositionAnalyzer,
    RedundancyDetector,
    InstructionBudgetAnalyzer,
    gather_all_instruction_files,
    gather_all_content_files,
    ContentFile,
    _strip_fenced_code_blocks,
)
from skillsaw.context import RepositoryContext


def _cf(path: Path, category: str = "instruction") -> ContentFile:
    return ContentFile(path=path, category=category)


@pytest.fixture
def temp_dir():
    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp)


class TestStripFencedCodeBlocks:
    def test_strips_backtick_blocks(self):
        content = "Line 1\n```\ncode line\n```\nLine 5\n"
        result = _strip_fenced_code_blocks(content)
        lines = result.splitlines()
        assert lines[0] == "Line 1"
        assert lines[1] == ""
        assert lines[2] == ""
        assert lines[3] == ""
        assert lines[4] == "Line 5"

    def test_strips_tilde_blocks(self):
        content = "Line 1\n~~~\ncode\n~~~\nLine 5\n"
        result = _strip_fenced_code_blocks(content)
        assert "code" not in result
        assert result.count("\n") == content.count("\n")

    def test_preserves_line_count(self):
        content = "Before\n```python\nline1\nline2\nline3\n```\nAfter\n"
        result = _strip_fenced_code_blocks(content)
        assert result.count("\n") == content.count("\n")

    def test_no_code_blocks(self):
        content = "Just text.\nMore text.\n"
        result = _strip_fenced_code_blocks(content)
        assert result == content

    def test_multiple_code_blocks(self):
        content = "A\n```\nx\n```\nB\n```\ny\n```\nC\n"
        result = _strip_fenced_code_blocks(content)
        lines = result.splitlines()
        assert lines[0] == "A"
        assert lines[4] == "B"
        assert lines[8] == "C"

    def test_strips_indented_backtick_blocks_1_space(self):
        content = "Before\n ```\n code here\n ```\nAfter\n"
        result = _strip_fenced_code_blocks(content)
        assert "code here" not in result
        assert result.count("\n") == content.count("\n")

    def test_strips_indented_backtick_blocks_2_spaces(self):
        content = "- Example:\n  ```\n  Try to handle errors gracefully.\n  ```\nMore text.\n"
        result = _strip_fenced_code_blocks(content)
        assert "Try to handle errors gracefully" not in result
        assert result.count("\n") == content.count("\n")

    def test_strips_indented_backtick_blocks_3_spaces(self):
        content = "Before\n   ```\n   code\n   ```\nAfter\n"
        result = _strip_fenced_code_blocks(content)
        assert "code" not in result
        assert result.count("\n") == content.count("\n")

    def test_4_space_indent_not_stripped(self):
        """4+ spaces of indentation is not a valid CommonMark code fence."""
        content = "Before\n    ```\n    code\n    ```\nAfter\n"
        result = _strip_fenced_code_blocks(content)
        assert "code" in result

    def test_strips_indented_tilde_blocks(self):
        content = "Before\n  ~~~\n  code\n  ~~~\nAfter\n"
        result = _strip_fenced_code_blocks(content)
        assert "code" not in result
        assert result.count("\n") == content.count("\n")

    def test_indented_fence_preserves_line_count(self):
        content = "Line 1\n  ```python\n  x = 1\n  y = 2\n  ```\nLine 6\n"
        result = _strip_fenced_code_blocks(content)
        assert result.count("\n") == content.count("\n")

    def test_indented_closing_fence_allows_different_indent(self):
        """Closing fence can have different indentation (0-3 spaces) than opening fence."""
        content = "Before\n  ```\n  code\n```\nAfter\n"
        result = _strip_fenced_code_blocks(content)
        # Per CommonMark spec, closing fence can be 0-3 spaces regardless of opening
        assert "code" not in result
        assert result.count("\n") == content.count("\n")

    def test_closing_fence_longer_than_opening(self):
        """Closing fence can be longer than the opening fence per CommonMark spec."""
        content = "Before\n```\ncode\n`````\nAfter\n"
        result = _strip_fenced_code_blocks(content)
        assert "code" not in result
        assert result.count("\n") == content.count("\n")

    def test_closing_fence_shorter_than_opening_does_not_close(self):
        """Closing fence shorter than opening does NOT close the block."""
        content = "Before\n`````\ncode\n```\nAfter\n"
        result = _strip_fenced_code_blocks(content)
        # The ``` does not close `````, so everything after ````` is inside the block
        assert "code" not in result
        assert "After" not in result

    def test_mismatched_fence_char_does_not_close(self):
        """Closing fence must use the same character as the opening fence."""
        content = "Before\n```\ncode\n~~~\nAfter\n"
        result = _strip_fenced_code_blocks(content)
        # ~~~ does not close ```, so code stays inside
        assert "code" not in result
        assert "After" not in result


class TestWeakLanguageDetector:
    def test_detects_hedging(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Try to use consistent naming.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 1
        assert results[0].category == "hedging"
        assert "try to" in results[0].phrase.lower()

    def test_detects_vagueness(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Handle errors gracefully.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 1
        assert results[0].category == "vagueness"

    def test_detects_non_actionable(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Be aware of the rate limits.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 1
        assert results[0].category == "non-actionable"

    def test_clean_file_no_matches(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use 4-space indentation.\nRun tests before committing.\n"
        )
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) == 0

    def test_reports_correct_line_numbers(self, temp_dir):
        content = "Line one.\nLine two.\nTry to be careful here.\nLine four.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert any(r.line == 3 for r in results)

    def test_multiple_matches_per_line(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Try to handle errors gracefully if possible.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 3

    def test_case_insensitive(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("TRY TO use PROPERLY.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 2

    def test_skips_fenced_code_blocks(self, temp_dir):
        content = "Real instruction.\n```\nTry to handle errors gracefully.\n```\nMore text.\n"
        (temp_dir / "code_block.md").write_text(content)
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "code_block.md"))
        assert len(results) == 0

    def test_skips_indented_fenced_code_blocks(self, temp_dir):
        content = "Real instruction.\n- Example:\n  ```\n  Try to handle errors gracefully.\n  ```\nMore text.\n"
        (temp_dir / "indented.md").write_text(content)
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "indented.md"))
        assert len(results) == 0

    def test_consider_requires_action_verb(self, temp_dir):
        (temp_dir / "consider_fp.md").write_text("Consider this example:\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "consider_fp.md"))
        assert len(results) == 0

    def test_consider_using_flagged(self, temp_dir):
        (temp_dir / "consider_tp.md").write_text("Consider using TypeScript.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "consider_tp.md"))
        assert len(results) >= 1
        assert results[0].category == "hedging"

    def test_detects_you_might_want_to(self, temp_dir):
        (temp_dir / "might.md").write_text("You might want to add error handling.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "might.md"))
        assert len(results) >= 1
        assert results[0].category == "hedging"

    def test_detects_perhaps(self, temp_dir):
        (temp_dir / "perhaps.md").write_text("Perhaps use a different approach.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "perhaps.md"))
        assert len(results) >= 1
        assert results[0].category == "hedging"

    def test_detects_you_should_probably(self, temp_dir):
        (temp_dir / "probably.md").write_text("You should probably refactor this.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(_cf(temp_dir / "probably.md"))
        assert len(results) >= 1
        assert results[0].category == "hedging"


class TestTautologicalDetector:
    def test_detects_write_clean_code(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Always write clean code.\n")
        detector = TautologicalDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 1
        assert "clean code" in results[0].phrase.lower()

    def test_detects_follow_best_practices(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Follow best practices.\n")
        detector = TautologicalDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 1

    def test_detects_be_helpful(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Be helpful to the user.\n")
        detector = TautologicalDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 1

    def test_specific_instructions_pass(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use 4-space indentation for Python files.\nReturn 404 for missing resources.\n"
        )
        detector = TautologicalDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) == 0

    def test_reports_reason(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use common sense.\n")
        detector = TautologicalDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 1
        assert results[0].reason

    def test_case_insensitive(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("WRITE CLEAN CODE.\n")
        detector = TautologicalDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 1


class TestCriticalPositionAnalyzer:
    def _make_file(self, temp_dir, num_lines, critical_line):
        lines = [f"Line {i}" for i in range(1, num_lines + 1)]
        lines[critical_line - 1] = "IMPORTANT: Never skip tests."
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")

    def test_critical_in_middle_flagged(self, temp_dir):
        self._make_file(temp_dir, 50, 25)
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 1
        assert results[0].position_score == 0.5

    def test_critical_at_top_not_flagged(self, temp_dir):
        self._make_file(temp_dir, 50, 3)
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) == 0

    def test_critical_at_bottom_not_flagged(self, temp_dir):
        self._make_file(temp_dir, 50, 48)
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) == 0

    def test_short_file_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("IMPORTANT: do this.\nNEVER do that.\n")
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) == 0

    def test_multiple_keywords(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[24] = "MUST follow this rule."
        lines[26] = "NEVER skip that step."
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert len(results) >= 2

    def test_reports_keyword(self, temp_dir):
        self._make_file(temp_dir, 50, 25)
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(_cf(temp_dir / "CLAUDE.md"))
        assert results[0].keyword == "IMPORTANT"

    def test_lowercase_must_not_flagged(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[24] = "This function must return a value."
        (temp_dir / "crit_lower.md").write_text("\n".join(lines) + "\n")
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(_cf(temp_dir / "crit_lower.md"))
        assert len(results) == 0

    def test_lowercase_required_not_flagged(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[24] = "The required fields are: name, email."
        (temp_dir / "crit_req.md").write_text("\n".join(lines) + "\n")
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(_cf(temp_dir / "crit_req.md"))
        assert len(results) == 0

    def test_allcaps_must_flagged(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[24] = "You MUST always run tests."
        (temp_dir / "crit_caps.md").write_text("\n".join(lines) + "\n")
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(_cf(temp_dir / "crit_caps.md"))
        assert len(results) >= 1
        assert results[0].keyword == "MUST"


class TestRedundancyDetector:
    def test_detects_indent_with_editorconfig(self, temp_dir):
        (temp_dir / ".editorconfig").write_text("[*]\nindent_size = 4\n")
        (temp_dir / "CLAUDE.md").write_text("Use 4 spaces for indentation.\n")
        detector = RedundancyDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"), temp_dir)
        assert len(results) >= 1
        assert ".editorconfig" in results[0].existing_config_file

    def test_no_editorconfig_no_match(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use 4 spaces for indentation.\n")
        detector = RedundancyDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"), temp_dir)
        assert len(results) == 0

    def test_detects_style_with_prettier(self, temp_dir):
        (temp_dir / ".prettierrc").write_text('{"singleQuote": true}')
        (temp_dir / "CLAUDE.md").write_text("Use single quotes for strings.\n")
        detector = RedundancyDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"), temp_dir)
        assert len(results) >= 1

    def test_detects_tsconfig_strict(self, temp_dir):
        (temp_dir / "tsconfig.json").write_text('{"compilerOptions": {"strict": true}}')
        (temp_dir / "CLAUDE.md").write_text("Use strict TypeScript mode.\n")
        detector = RedundancyDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"), temp_dir)
        assert len(results) >= 1
        assert "tsconfig.json" in results[0].existing_config_file

    def test_clean_content_no_matches(self, temp_dir):
        (temp_dir / ".editorconfig").write_text("[*]\nindent_size = 4\n")
        (temp_dir / "CLAUDE.md").write_text("Focus on user experience.\n")
        detector = RedundancyDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"), temp_dir)
        assert len(results) == 0

    def test_detects_tabs_with_editorconfig(self, temp_dir):
        (temp_dir / ".editorconfig").write_text("[*]\nindent_style = tab\n")
        (temp_dir / "CLAUDE.md").write_text("Use tabs for indentation.\n")
        detector = RedundancyDetector()
        results = detector.analyze(_cf(temp_dir / "CLAUDE.md"), temp_dir)
        assert len(results) >= 1


class TestInstructionBudgetAnalyzer:
    def test_counts_imperative_lines(self, temp_dir):
        content = "- Use 4-space indentation\n- Run tests before commits\n- Check for errors\nSome description.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        analyzer = InstructionBudgetAnalyzer()
        budget = analyzer.analyze_file(_cf(temp_dir / "CLAUDE.md"))
        assert budget.total_count == 3
        assert not budget.over_budget

    def test_over_budget(self, temp_dir):
        lines = [f"- Use tool_{i}" for i in range(160)]
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        analyzer = InstructionBudgetAnalyzer()
        budget = analyzer.analyze_file(_cf(temp_dir / "CLAUDE.md"))
        assert budget.over_budget
        assert budget.budget_remaining == 0

    def test_empty_file(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("")
        analyzer = InstructionBudgetAnalyzer()
        budget = analyzer.analyze_file(_cf(temp_dir / "CLAUDE.md"))
        assert budget.total_count == 0
        assert not budget.over_budget

    def test_single_file_counted(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("- Use X\n- Run Y\n")
        analyzer = InstructionBudgetAnalyzer()
        budget = analyzer.analyze_file(_cf(temp_dir / "CLAUDE.md"))
        assert budget.total_count == 2
        assert len(budget.files_counted) == 1

    def test_non_imperative_not_counted(self, temp_dir):
        content = "# Instructions\n\nThis project is a web app.\nIt was built in 2024.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        analyzer = InstructionBudgetAnalyzer()
        budget = analyzer.analyze_file(_cf(temp_dir / "CLAUDE.md"))
        assert budget.total_count == 0


class TestGatherAllInstructionFiles:
    def test_gathers_claude_md(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Claude\n")
        context = RepositoryContext(temp_dir)
        files = gather_all_instruction_files(context)
        assert any(f.name == "CLAUDE.md" for f in files)

    def test_gathers_agents_md(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Agents\n")
        context = RepositoryContext(temp_dir)
        files = gather_all_instruction_files(context)
        assert any(f.name == "AGENTS.md" for f in files)

    def test_gathers_cursorrules(self, temp_dir):
        (temp_dir / ".cursorrules").write_text("Some rules\n")
        context = RepositoryContext(temp_dir)
        files = gather_all_instruction_files(context)
        assert any(f.name == ".cursorrules" for f in files)

    def test_gathers_copilot_instructions(self, temp_dir):
        gh = temp_dir / ".github"
        gh.mkdir()
        (gh / "copilot-instructions.md").write_text("# Copilot\n")
        context = RepositoryContext(temp_dir)
        files = gather_all_instruction_files(context)
        assert any(f.name == "copilot-instructions.md" for f in files)

    def test_gathers_cursor_mdc(self, temp_dir):
        rules_dir = temp_dir / ".cursor" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "style.mdc").write_text("---\ndescription: style\n---\nContent\n")
        context = RepositoryContext(temp_dir)
        files = gather_all_instruction_files(context)
        assert any(f.name == "style.mdc" for f in files)

    def test_no_duplicates(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Claude\n")
        context = RepositoryContext(temp_dir)
        files = gather_all_instruction_files(context)
        resolved = [f.resolve() for f in files]
        assert len(resolved) == len(set(resolved))

    def test_empty_repo(self, temp_dir):
        context = RepositoryContext(temp_dir)
        files = gather_all_instruction_files(context)
        assert files == []


class TestGatherAllContentFiles:
    def test_categorizes_instruction_files(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Claude\n")
        (temp_dir / "AGENTS.md").write_text("# Agents\n")
        (temp_dir / "GEMINI.md").write_text("# Gemini\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        cats = {cf.path.name: cf.category for cf in cfs}
        assert cats["CLAUDE.md"] == "claude-md"
        assert cats["AGENTS.md"] == "agents-md"
        assert cats["GEMINI.md"] == "gemini-md"

    def test_copilot_is_instruction(self, temp_dir):
        gh = temp_dir / ".github"
        gh.mkdir()
        (gh / "copilot-instructions.md").write_text("# Copilot\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(
            cf.path.name == "copilot-instructions.md" and cf.category == "instruction" for cf in cfs
        )

    def test_cursorrules_is_instruction(self, temp_dir):
        (temp_dir / ".cursorrules").write_text("Some rules\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == ".cursorrules" and cf.category == "instruction" for cf in cfs)

    def test_cursor_mdc_is_instruction(self, temp_dir):
        rules_dir = temp_dir / ".cursor" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "style.mdc").write_text("---\ndescription: style\n---\nContent\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "style.mdc" and cf.category == "instruction" for cf in cfs)

    def test_gathers_skill_md(self, temp_dir):
        (temp_dir / "SKILL.md").write_text("---\nname: my-skill\n---\nContent\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "SKILL.md" and cf.category == "skill" for cf in cfs)

    def test_gathers_skill_references(self, temp_dir):
        (temp_dir / "SKILL.md").write_text("---\nname: my-skill\n---\nContent\n")
        refs_dir = temp_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "api.md").write_text("# API\n")
        (refs_dir / "guide.md").write_text("# Guide\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        ref_files = [cf for cf in cfs if cf.category == "skill-ref"]
        assert len(ref_files) == 2
        names = {cf.path.name for cf in ref_files}
        assert names == {"api.md", "guide.md"}

    def test_gathers_commands(self, temp_dir):
        (temp_dir / ".claude-plugin").mkdir()
        cmd_dir = temp_dir / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "deploy.md").write_text("# Deploy\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "deploy.md" and cf.category == "command" for cf in cfs)

    def test_gathers_agents(self, temp_dir):
        (temp_dir / ".claude-plugin").mkdir()
        agents_dir = temp_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "reviewer.md").write_text("# Reviewer\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "reviewer.md" and cf.category == "agent" for cf in cfs)

    def test_gathers_rules(self, temp_dir):
        (temp_dir / ".claude-plugin").mkdir()
        rules_dir = temp_dir / "rules"
        rules_dir.mkdir()
        (rules_dir / "style.md").write_text("# Style\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "style.md" and cf.category == "rule" for cf in cfs)

    def test_extra_globs(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "setup.md").write_text("# Setup\n")
        context = RepositoryContext(temp_dir)
        context.content_paths = ["docs/*.md"]
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "setup.md" and cf.category == "extra" for cf in cfs)

    def test_exclude_patterns(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Claude\n")
        cursor_dir = temp_dir / ".cursor" / "rules"
        cursor_dir.mkdir(parents=True)
        (cursor_dir / "dev.mdc").write_text("# Dev\n")
        context = RepositoryContext(temp_dir)
        context.exclude_patterns = [".cursor/*"]
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "CLAUDE.md" for cf in cfs)
        assert not any(cf.path.name == "dev.mdc" for cf in cfs)

    def test_exclude_glob_nested(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Claude\n")
        claude_dir = temp_dir / ".claude"
        claude_dir.mkdir()
        skills_dir = claude_dir / "skills" / "my-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("# Skill\n")
        context = RepositoryContext(temp_dir)
        context.exclude_patterns = [".claude/*"]
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "CLAUDE.md" for cf in cfs)
        assert not any(".claude" in str(cf.path) and cf.path.name == "SKILL.md" for cf in cfs)

    def test_no_duplicates(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Claude\n")
        (temp_dir / "AGENTS.md").write_text("# Agents\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        resolved = [cf.path.resolve() for cf in cfs]
        assert len(resolved) == len(set(resolved))

    def test_empty_repo(self, temp_dir):
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert cfs == []

    def test_backward_compat_wrapper(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Claude\n")
        context = RepositoryContext(temp_dir)
        old = gather_all_instruction_files(context)
        new = [cf.path for cf in gather_all_content_files(context)]
        assert all(isinstance(p, Path) for p in old)
        assert set(p.resolve() for p in old) <= set(p.resolve() for p in new)

    def test_windsurfrules(self, temp_dir):
        (temp_dir / ".windsurfrules").write_text("Some rules\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == ".windsurfrules" and cf.category == "instruction" for cf in cfs)

    def test_clinerules_file(self, temp_dir):
        (temp_dir / ".clinerules").write_text("Some rules\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == ".clinerules" and cf.category == "instruction" for cf in cfs)

    def test_kiro_steering(self, temp_dir):
        steering = temp_dir / ".kiro" / "steering"
        steering.mkdir(parents=True)
        (steering / "guide.md").write_text("# Guide\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "guide.md" and cf.category == "instruction" for cf in cfs)

    def test_apm_instructions_gathered(self, temp_dir):
        """APM instruction files should be gathered with 'instruction' category."""
        apm_dir = temp_dir / ".apm"
        instr_dir = apm_dir / "instructions"
        instr_dir.mkdir(parents=True)
        (instr_dir / "dev.instructions.md").write_text("# Dev instructions\n")
        (instr_dir / "style.instructions.md").write_text("# Style guide\n")
        (temp_dir / "apm.yml").write_text("name: test\nversion: '1.0.0'\ndescription: Test\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        instr_files = [cf for cf in cfs if cf.category == "instruction"]
        names = {cf.path.name for cf in instr_files}
        assert "dev.instructions.md" in names
        assert "style.instructions.md" in names

    def test_apm_agents_gathered(self, temp_dir):
        """APM agent files should be gathered with 'agent' category."""
        apm_dir = temp_dir / ".apm"
        agents_dir = apm_dir / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "reviewer.agent.md").write_text("# Reviewer agent\n")
        (temp_dir / "apm.yml").write_text("name: test\nversion: '1.0.0'\ndescription: Test\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "reviewer.agent.md" and cf.category == "agent" for cf in cfs)

    def test_apm_prompts_gathered(self, temp_dir):
        """APM prompt files should be gathered with 'prompt' category."""
        apm_dir = temp_dir / ".apm"
        prompts_dir = apm_dir / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "review.md").write_text("# Review prompt\n")
        (temp_dir / "apm.yml").write_text("name: test\nversion: '1.0.0'\ndescription: Test\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "review.md" and cf.category == "prompt" for cf in cfs)

    def test_apm_chatmodes_gathered(self, temp_dir):
        """APM chatmode files should be gathered with 'chatmode' category."""
        apm_dir = temp_dir / ".apm"
        chatmodes_dir = apm_dir / "chatmodes"
        chatmodes_dir.mkdir(parents=True)
        (chatmodes_dir / "concise.md").write_text("# Concise mode\n")
        (temp_dir / "apm.yml").write_text("name: test\nversion: '1.0.0'\ndescription: Test\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "concise.md" and cf.category == "chatmode" for cf in cfs)

    def test_apm_context_gathered(self, temp_dir):
        """APM context files should be gathered with 'context' category."""
        apm_dir = temp_dir / ".apm"
        context_dir = apm_dir / "context"
        context_dir.mkdir(parents=True)
        (context_dir / "project-overview.md").write_text("# Project Overview\n")
        (temp_dir / "apm.yml").write_text("name: test\nversion: '1.0.0'\ndescription: Test\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "project-overview.md" and cf.category == "context" for cf in cfs)

    def test_apm_all_content_types_gathered(self, temp_dir):
        """All APM content types should be gathered when present."""
        apm_dir = temp_dir / ".apm"
        for subdir, filename in [
            ("instructions", "dev.instructions.md"),
            ("agents", "helper.agent.md"),
            ("prompts", "template.md"),
            ("chatmodes", "brief.md"),
            ("context", "overview.md"),
        ]:
            d = apm_dir / subdir
            d.mkdir(parents=True, exist_ok=True)
            (d / filename).write_text(f"# {subdir}\n")
        (temp_dir / "apm.yml").write_text("name: test\nversion: '1.0.0'\ndescription: Test\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        categories = {cf.category for cf in cfs}
        assert "instruction" in categories
        assert "agent" in categories
        assert "prompt" in categories
        assert "chatmode" in categories
        assert "context" in categories

    def test_apm_skips_compiled_cursor_rules(self, temp_dir):
        """When APM is present, .cursor/rules/ should be skipped."""
        apm_dir = temp_dir / ".apm"
        apm_dir.mkdir()
        (temp_dir / "apm.yml").write_text("name: test\nversion: '1.0.0'\ndescription: Test\n")
        # Create compiled cursor rules
        cursor_rules = temp_dir / ".cursor" / "rules"
        cursor_rules.mkdir(parents=True)
        (cursor_rules / "generated.mdc").write_text("---\ndescription: gen\n---\nContent\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert not any(cf.path.name == "generated.mdc" for cf in cfs)

    def test_apm_skips_compiled_plugin_content(self, temp_dir):
        """When APM is present, plugin content in .claude/ should be skipped."""
        apm_dir = temp_dir / ".apm"
        skills_dir = apm_dir / "skills" / "my-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A skill\n---\n")
        (temp_dir / "apm.yml").write_text("name: test\nversion: '1.0.0'\ndescription: Test\n")
        # Create compiled .claude/ output with agents
        claude_agents = temp_dir / ".claude" / "agents"
        claude_agents.mkdir(parents=True)
        (claude_agents / "compiled-agent.md").write_text("# Compiled agent\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert not any(cf.path.name == "compiled-agent.md" for cf in cfs)

    def test_apm_keeps_root_instruction_files(self, temp_dir):
        """Root-level CLAUDE.md/AGENTS.md should still be gathered with APM."""
        apm_dir = temp_dir / ".apm"
        apm_dir.mkdir()
        (temp_dir / "apm.yml").write_text("name: test\nversion: '1.0.0'\ndescription: Test\n")
        (temp_dir / "CLAUDE.md").write_text("# Claude instructions\n")
        context = RepositoryContext(temp_dir)
        cfs = gather_all_content_files(context)
        assert any(cf.path.name == "CLAUDE.md" for cf in cfs)
