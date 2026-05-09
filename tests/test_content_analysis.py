"""Tests for content analysis shared analyzers."""

import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.rules.builtin.content_analysis import (
    WeakLanguageDetector,
    DeadReferenceScanner,
    TautologicalDetector,
    CriticalPositionAnalyzer,
    RedundancyDetector,
    InstructionBudgetAnalyzer,
    gather_all_instruction_files,
    _strip_fenced_code_blocks,
)
from skillsaw.context import RepositoryContext


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


class TestWeakLanguageDetector:
    def test_detects_hedging(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Try to use consistent naming.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 1
        assert results[0].category == "hedging"
        assert "try to" in results[0].phrase.lower()

    def test_detects_vagueness(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Handle errors gracefully.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 1
        assert results[0].category == "vagueness"

    def test_detects_non_actionable(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Be aware of the rate limits.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 1
        assert results[0].category == "non-actionable"

    def test_clean_file_no_matches(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use 4-space indentation.\nRun tests before committing.\n"
        )
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) == 0

    def test_reports_correct_line_numbers(self, temp_dir):
        content = "Line one.\nLine two.\nTry to be careful here.\nLine four.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert any(r.line == 3 for r in results)

    def test_multiple_matches_per_line(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Try to handle errors gracefully if possible.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 3

    def test_case_insensitive(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("TRY TO use PROPERLY.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 2

    def test_skips_fenced_code_blocks(self, temp_dir):
        content = "Real instruction.\n```\nTry to handle errors gracefully.\n```\nMore text.\n"
        (temp_dir / "code_block.md").write_text(content)
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "code_block.md")
        assert len(results) == 0

    def test_consider_requires_action_verb(self, temp_dir):
        (temp_dir / "consider_fp.md").write_text("Consider this example:\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "consider_fp.md")
        assert len(results) == 0

    def test_consider_using_flagged(self, temp_dir):
        (temp_dir / "consider_tp.md").write_text("Consider using TypeScript.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "consider_tp.md")
        assert len(results) >= 1
        assert results[0].category == "hedging"

    def test_detects_you_might_want_to(self, temp_dir):
        (temp_dir / "might.md").write_text("You might want to add error handling.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "might.md")
        assert len(results) >= 1
        assert results[0].category == "hedging"

    def test_detects_perhaps(self, temp_dir):
        (temp_dir / "perhaps.md").write_text("Perhaps use a different approach.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "perhaps.md")
        assert len(results) >= 1
        assert results[0].category == "hedging"

    def test_detects_you_should_probably(self, temp_dir):
        (temp_dir / "probably.md").write_text("You should probably refactor this.\n")
        detector = WeakLanguageDetector()
        results = detector.analyze(temp_dir / "probably.md")
        assert len(results) >= 1
        assert results[0].category == "hedging"


class TestDeadReferenceScanner:
    def test_detects_missing_backtick_path(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Edit the file `src/config/settings.py`.\n")
        scanner = DeadReferenceScanner()
        results = scanner.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 1
        assert "src/config/settings.py" in results[0].reference

    def test_existing_path_no_violation(self, temp_dir):
        src = temp_dir / "src" / "main.py"
        src.parent.mkdir(parents=True)
        src.write_text("# main")
        (temp_dir / "CLAUDE.md").write_text("See `src/main.py` for details.\n")
        scanner = DeadReferenceScanner()
        results = scanner.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 0

    def test_detects_missing_md_link(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("See [setup guide](./docs/setup.md) for details.\n")
        scanner = DeadReferenceScanner()
        results = scanner.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 1
        assert "./docs/setup.md" in results[0].reference

    def test_existing_md_link_no_violation(self, temp_dir):
        docs = temp_dir / "docs"
        docs.mkdir()
        (docs / "setup.md").write_text("# Setup")
        (temp_dir / "CLAUDE.md").write_text("See [setup](./docs/setup.md).\n")
        scanner = DeadReferenceScanner()
        results = scanner.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 0

    def test_detects_missing_npm_script(self, temp_dir):
        (temp_dir / "package.json").write_text('{"scripts": {"test": "jest"}}')
        (temp_dir / "CLAUDE.md").write_text("Run `npm run lint` before committing.\n")
        scanner = DeadReferenceScanner()
        results = scanner.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 1
        assert "npm run lint" in results[0].reference

    def test_existing_npm_script_no_violation(self, temp_dir):
        (temp_dir / "package.json").write_text('{"scripts": {"test": "jest", "lint": "eslint ."}}')
        (temp_dir / "CLAUDE.md").write_text("Run `npm run lint` before committing.\n")
        scanner = DeadReferenceScanner()
        results = scanner.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 0

    def test_detects_missing_make_target(self, temp_dir):
        (temp_dir / "Makefile").write_text("build:\n\tgo build\n")
        (temp_dir / "CLAUDE.md").write_text("Run `make deploy` to deploy.\n")
        scanner = DeadReferenceScanner()
        results = scanner.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 1
        assert "make deploy" in results[0].reference

    def test_existing_make_target_no_violation(self, temp_dir):
        (temp_dir / "Makefile").write_text("build:\n\tgo build\n\ndeploy:\n\tkubectl apply\n")
        (temp_dir / "CLAUDE.md").write_text("Run `make deploy` to deploy.\n")
        scanner = DeadReferenceScanner()
        results = scanner.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 0

    def test_see_reference(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("See docs/architecture.md for details.\n")
        scanner = DeadReferenceScanner()
        results = scanner.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 1


class TestTautologicalDetector:
    def test_detects_write_clean_code(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Always write clean code.\n")
        detector = TautologicalDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 1
        assert "clean code" in results[0].phrase.lower()

    def test_detects_follow_best_practices(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Follow best practices.\n")
        detector = TautologicalDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 1

    def test_detects_be_helpful(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Be helpful to the user.\n")
        detector = TautologicalDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 1

    def test_specific_instructions_pass(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "Use 4-space indentation for Python files.\nReturn 404 for missing resources.\n"
        )
        detector = TautologicalDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) == 0

    def test_reports_reason(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use common sense.\n")
        detector = TautologicalDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 1
        assert results[0].reason

    def test_case_insensitive(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("WRITE CLEAN CODE.\n")
        detector = TautologicalDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 1


class TestCriticalPositionAnalyzer:
    def _make_file(self, temp_dir, num_lines, critical_line):
        lines = [f"Line {i}" for i in range(1, num_lines + 1)]
        lines[critical_line - 1] = "IMPORTANT: Never skip tests."
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")

    def test_critical_in_middle_flagged(self, temp_dir):
        self._make_file(temp_dir, 50, 25)
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 1
        assert results[0].position_score == 0.5

    def test_critical_at_top_not_flagged(self, temp_dir):
        self._make_file(temp_dir, 50, 3)
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(temp_dir / "CLAUDE.md")
        assert len(results) == 0

    def test_critical_at_bottom_not_flagged(self, temp_dir):
        self._make_file(temp_dir, 50, 48)
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(temp_dir / "CLAUDE.md")
        assert len(results) == 0

    def test_short_file_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("IMPORTANT: do this.\nNEVER do that.\n")
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(temp_dir / "CLAUDE.md")
        assert len(results) == 0

    def test_multiple_keywords(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[24] = "MUST follow this rule."
        lines[26] = "NEVER skip that step."
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(temp_dir / "CLAUDE.md")
        assert len(results) >= 2

    def test_reports_keyword(self, temp_dir):
        self._make_file(temp_dir, 50, 25)
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(temp_dir / "CLAUDE.md")
        assert results[0].keyword == "IMPORTANT"

    def test_lowercase_must_not_flagged(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[24] = "This function must return a value."
        (temp_dir / "crit_lower.md").write_text("\n".join(lines) + "\n")
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(temp_dir / "crit_lower.md")
        assert len(results) == 0

    def test_lowercase_required_not_flagged(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[24] = "The required fields are: name, email."
        (temp_dir / "crit_req.md").write_text("\n".join(lines) + "\n")
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(temp_dir / "crit_req.md")
        assert len(results) == 0

    def test_allcaps_must_flagged(self, temp_dir):
        lines = [f"Line {i}" for i in range(1, 51)]
        lines[24] = "You MUST always run tests."
        (temp_dir / "crit_caps.md").write_text("\n".join(lines) + "\n")
        analyzer = CriticalPositionAnalyzer()
        results = analyzer.analyze(temp_dir / "crit_caps.md")
        assert len(results) >= 1
        assert results[0].keyword == "MUST"


class TestRedundancyDetector:
    def test_detects_indent_with_editorconfig(self, temp_dir):
        (temp_dir / ".editorconfig").write_text("[*]\nindent_size = 4\n")
        (temp_dir / "CLAUDE.md").write_text("Use 4 spaces for indentation.\n")
        detector = RedundancyDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) >= 1
        assert ".editorconfig" in results[0].existing_config_file

    def test_no_editorconfig_no_match(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Use 4 spaces for indentation.\n")
        detector = RedundancyDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 0

    def test_detects_style_with_prettier(self, temp_dir):
        (temp_dir / ".prettierrc").write_text('{"singleQuote": true}')
        (temp_dir / "CLAUDE.md").write_text("Use single quotes for strings.\n")
        detector = RedundancyDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) >= 1

    def test_detects_tsconfig_strict(self, temp_dir):
        (temp_dir / "tsconfig.json").write_text('{"compilerOptions": {"strict": true}}')
        (temp_dir / "CLAUDE.md").write_text("Use strict TypeScript mode.\n")
        detector = RedundancyDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) >= 1
        assert "tsconfig.json" in results[0].existing_config_file

    def test_clean_content_no_matches(self, temp_dir):
        (temp_dir / ".editorconfig").write_text("[*]\nindent_size = 4\n")
        (temp_dir / "CLAUDE.md").write_text("Focus on user experience.\n")
        detector = RedundancyDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) == 0

    def test_detects_tabs_with_editorconfig(self, temp_dir):
        (temp_dir / ".editorconfig").write_text("[*]\nindent_style = tab\n")
        (temp_dir / "CLAUDE.md").write_text("Use tabs for indentation.\n")
        detector = RedundancyDetector()
        results = detector.analyze(temp_dir / "CLAUDE.md", temp_dir)
        assert len(results) >= 1


class TestInstructionBudgetAnalyzer:
    def test_counts_imperative_lines(self, temp_dir):
        content = "- Use 4-space indentation\n- Run tests before commits\n- Check for errors\nSome description.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        analyzer = InstructionBudgetAnalyzer()
        budget = analyzer.analyze([temp_dir / "CLAUDE.md"])
        assert budget.total_count == 3
        assert not budget.over_budget

    def test_over_budget(self, temp_dir):
        lines = [f"- Use tool_{i}" for i in range(160)]
        (temp_dir / "CLAUDE.md").write_text("\n".join(lines) + "\n")
        analyzer = InstructionBudgetAnalyzer()
        budget = analyzer.analyze([temp_dir / "CLAUDE.md"])
        assert budget.over_budget
        assert budget.budget_remaining == 0

    def test_empty_file(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("")
        analyzer = InstructionBudgetAnalyzer()
        budget = analyzer.analyze([temp_dir / "CLAUDE.md"])
        assert budget.total_count == 0
        assert not budget.over_budget

    def test_multiple_files(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("- Use X\n- Run Y\n")
        (temp_dir / "AGENTS.md").write_text("- Check Z\n- Avoid W\n")
        analyzer = InstructionBudgetAnalyzer()
        budget = analyzer.analyze([temp_dir / "CLAUDE.md", temp_dir / "AGENTS.md"])
        assert budget.total_count == 4
        assert len(budget.files_counted) == 2

    def test_non_imperative_not_counted(self, temp_dir):
        content = "# Instructions\n\nThis project is a web app.\nIt was built in 2024.\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        analyzer = InstructionBudgetAnalyzer()
        budget = analyzer.analyze([temp_dir / "CLAUDE.md"])
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
