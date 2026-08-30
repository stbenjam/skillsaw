"""Tests for instruction file validation rules (AGENTS.md, CLAUDE.md, GEMINI.md)"""

import time

import pytest
from pathlib import Path
import tempfile
import shutil

from skillsaw.blocks import ClaudeMdBlock
from skillsaw.context import HAS_AGENTS_MD, HAS_CLAUDE_MD, RepositoryContext
from skillsaw.markdown_doc import MarkdownDoc
from skillsaw.rule import AutofixConfidence, Severity
from skillsaw.rules.builtin import BUILTIN_RULES
from skillsaw.rules.builtin.utils import invalidate_read_caches
from skillsaw.rules.builtin.content.instruction_drift import ContentInstructionDriftRule
from skillsaw.rules.builtin.instructions import (
    ClaudeMdAgentsImportRule,
    InstructionFileValidRule,
    InstructionImportsValidRule,
)
from skillsaw.rules.builtin.instructions import _helpers as instruction_helpers


@pytest.fixture
def temp_dir():
    # Resolve symlinks (macOS /var -> /private/var) so path assertions match
    # the resolved paths the imports rule reports for nested files.
    tmp = tempfile.mkdtemp()
    yield Path(tmp).resolve()
    shutil.rmtree(tmp)


class TestInstructionFileValidRule:
    def test_rule_metadata(self):
        rule = InstructionFileValidRule()
        assert rule.rule_id == "instruction-file-valid"
        assert rule.default_severity() == Severity.WARNING
        assert rule.repo_types is None

    def test_no_instruction_files_passes(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_valid_agents_md_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Instructions\nDo stuff.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_valid_claude_md_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Claude\nBe helpful.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_valid_gemini_md_passes(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("# Gemini\nInstructions here.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_valid_qwen_md_passes(self, temp_dir):
        (temp_dir / "QWEN.md").write_text("# Qwen\nInstructions here.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_empty_qwen_md_fails(self, temp_dir):
        (temp_dir / "QWEN.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 1
        assert "QWEN.md is empty" in violations[0].message

    def test_all_three_valid_passes(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("# Agents\n")
        (temp_dir / "CLAUDE.md").write_text("# Claude\n")
        (temp_dir / "GEMINI.md").write_text("# Gemini\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 0

    def test_empty_file_fails(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 1
        assert "empty" in violations[0].message.lower()

    def test_whitespace_only_file_fails(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("   \n\n  \n")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 1
        assert "empty" in violations[0].message.lower()

    def test_invalid_encoding_fails(self, temp_dir):
        (temp_dir / "GEMINI.md").write_bytes(b"\x80\x81\x82\x83")
        context = RepositoryContext(temp_dir)
        violations = InstructionFileValidRule().check(context)
        assert len(violations) == 1
        assert (
            "read" in violations[0].message.lower() or "encoding" in violations[0].message.lower()
        )

    def test_empty_devin_global_rules_fails(self, temp_dir):
        rules = temp_dir / ".devin" / "global_rules.md"
        rules.parent.mkdir()
        rules.write_text("")

        violations = InstructionFileValidRule().check(RepositoryContext(temp_dir))

        assert len(violations) == 1
        assert "global_rules.md is empty" in violations[0].message

    def test_invalid_windsurf_global_rules_encoding_fails(self, temp_dir):
        rules = temp_dir / ".windsurf" / "global_rules.md"
        rules.parent.mkdir()
        rules.write_bytes(b"\x80\x81\x82\x83")

        violations = InstructionFileValidRule().check(RepositoryContext(temp_dir))

        assert len(violations) == 1
        assert "invalid encoding" in violations[0].message


class TestInstructionImportsValidRule:
    def test_rule_metadata(self):
        rule = InstructionImportsValidRule()
        assert rule.rule_id == "instruction-imports-valid"
        assert rule.default_severity() == Severity.WARNING
        assert rule.repo_types is None

    def test_no_files_no_violations(self, temp_dir):
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_no_imports_passes(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Instructions\nJust plain text.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_unreadable_instruction_file_skipped(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_bytes(b"\x80\x81\x82")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_valid_import_passes(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "setup.md").write_text("# Setup\n")
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@docs/setup.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    @pytest.mark.parametrize(
        "content",
        [
            "Please read **@docs/setup.md** first.\n",
            "- _@docs/setup.md_ — canonical instructions.\n",
            "~~@docs/setup.md~~\n",
        ],
    )
    def test_markdown_emphasis_preserves_the_import_target(self, temp_dir, content):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "setup.md").write_text("# Setup\n")
        (temp_dir / "CLAUDE.md").write_text(content)
        assert InstructionImportsValidRule().check(RepositoryContext(temp_dir)) == []

    def test_missing_emphasized_import_reports_the_normalized_target(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("- **@missing** — required context.\n")
        violations = InstructionImportsValidRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert violations[0].line == 1
        assert "@missing" in violations[0].message
        assert "**" not in violations[0].message

    @pytest.mark.parametrize("filename", ["guide_", "guide~"])
    def test_real_trailing_path_markers_are_not_stripped(self, temp_dir, filename):
        (temp_dir / filename).write_text("# Guide\n")
        (temp_dir / "CLAUDE.md").write_text(f"@{filename}\n")
        assert InstructionImportsValidRule().check(RepositoryContext(temp_dir)) == []

    def test_missing_import_fails(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@docs/missing.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "non-existent" in violations[0].message.lower()
        assert violations[0].line == 3

    @pytest.mark.parametrize(
        ("host", "content"),
        [
            ("CLAUDE.md", "@CLAUDE.local.md\n"),
            ("CLAUDE.md", "- @CLAUDE.local.md\n"),
            ("CLAUDE.md", "Load @CLAUDE.local.md for personal overrides.\n"),
            ("AGENTS.md", "@AGENTS.local.md\n"),
            ("AGENTS.md", "- @config/AGENTS.local.md\n"),
        ],
    )
    def test_missing_conventional_local_override_is_optional(self, temp_dir, host, content):
        (temp_dir / host).write_text(content)
        assert InstructionImportsValidRule().check(RepositoryContext(temp_dir)) == []

    def test_present_local_override_is_recursively_validated(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("@CLAUDE.local.md\n")
        (temp_dir / "CLAUDE.local.md").write_text("# Personal notes\n\n@missing.md\n")
        violations = InstructionImportsValidRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert violations[0].file_path == temp_dir / "CLAUDE.local.md"
        assert violations[0].line == 3
        assert "missing.md" in violations[0].message

    @pytest.mark.parametrize(
        "target",
        ["CLAUDE.local.mdx", "claude.local.md", "AGENTS.local.md.bak"],
    )
    def test_near_local_override_names_still_report(self, temp_dir, target):
        (temp_dir / "CLAUDE.md").write_text(f"@{target}\n")
        violations = InstructionImportsValidRule().check(RepositoryContext(temp_dir))
        assert len(violations) == 1
        assert target in violations[0].message

    def test_local_override_import_must_stay_inside_repository(self, temp_dir):
        repo = temp_dir / "repo"
        repo.mkdir()
        (temp_dir / "CLAUDE.local.md").write_text("# Outside\n")
        (repo / "CLAUDE.md").write_text("@../CLAUDE.local.md\n")
        violations = InstructionImportsValidRule().check(RepositoryContext(repo))
        assert len(violations) == 1
        assert "escapes repository root" in violations[0].message

    def test_unresolvable_import_reports_missing_without_stat(self, temp_dir, monkeypatch):
        """A rejected import target must not be revived for an unsafe stat."""
        from skillsaw.rules.builtin.instructions import imports_valid as rule_module

        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@hostile.md\n")
        context = RepositoryContext(temp_dir)
        _ = context.lint_tree
        real_safe_resolve = rule_module.safe_resolve
        real_exists = Path.exists

        def hostile_resolve(path):
            """Reject the hostile fixture path while resolving other paths."""
            if path.name == "hostile.md":
                return None
            return real_safe_resolve(path)

        def hostile_exists(path):
            """Fail if the rejected hostile path reaches a raw stat call."""
            if path.name == "hostile.md":
                raise OSError("cannot stat hostile import")
            return real_exists(path)

        monkeypatch.setattr(rule_module, "safe_resolve", hostile_resolve)
        monkeypatch.setattr(Path, "exists", hostile_exists)

        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "non-existent" in violations[0].message.lower()

    def test_mid_line_missing_path_import_fails(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n\nFollow the workflow in @docs/missing.md before coding.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "docs/missing.md" in violations[0].message
        assert violations[0].line == 3

    def test_mid_line_missing_extension_import_fails(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n\nLoad @settings.yaml before changing config.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "settings.yaml" in violations[0].message
        assert violations[0].line == 3

    def test_mid_line_handle_like_token_not_checked(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n\nAsk @platform-team before changing deploys.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_long_marker_run_before_prose_stays_a_mention(self, temp_dir):
        marker_prefix = "*" * 64
        (temp_dir / "CLAUDE.md").write_text(
            f"{marker_prefix} Ask @platform-team before changing deploys.\n"
        )

        violations = InstructionImportsValidRule().check(RepositoryContext(temp_dir))

        assert violations == []

    @pytest.mark.parametrize(
        "content",
        [
            "[@platform-team](https://example.com)\n",
            "![@platform-team](image.png)\n",
            "`code` @platform-team\n",
            "&copy; @platform-team\n",
            "# @platform-team\n",
            "<br> @platform-team\n",
        ],
    )
    def test_nonprose_ast_construct_before_mention_is_not_line_start(self, temp_dir, content):
        (temp_dir / "CLAUDE.md").write_text(content)

        violations = InstructionImportsValidRule().check(RepositoryContext(temp_dir))

        assert violations == []

    def test_unknown_import_column_is_not_treated_as_line_start(self):
        markdown = MarkdownDoc("@platform-team\n")
        segment = markdown.text_segments()[0]
        segment.col_start = None

        imports = list(instruction_helpers.iter_markdown_instruction_imports(markdown))

        assert len(imports) == 1
        assert imports[0].line_start is False

    @pytest.mark.parametrize("prefix", ["_ ", "~ ", "*_ "])
    def test_malformed_marker_then_space_does_not_make_a_line_start_import(self, temp_dir, prefix):
        (temp_dir / "CLAUDE.md").write_text(f"{prefix}@platform-team\n")

        violations = InstructionImportsValidRule().check(RepositoryContext(temp_dir))

        assert violations == []

    def test_many_imports_classify_the_source_prefix_once(self, monkeypatch):
        import_count = 10_000
        markdown = MarkdownDoc(" ".join("@mention" for _ in range(import_count)))
        calls = []
        classify = instruction_helpers._is_line_start_import_prefix

        def count_classifications(line, end):
            calls.append((line, end))
            return classify(line, end)

        monkeypatch.setattr(
            instruction_helpers,
            "_is_line_start_import_prefix",
            count_classifications,
        )

        actual_count = sum(
            1 for _ in instruction_helpers.iter_markdown_instruction_imports(markdown)
        )

        assert actual_count == import_count
        assert len(calls) == 1

    def test_many_imports_are_normalized_in_linear_time(self):
        import_count = 256_000
        line = " ".join("@mention" for _ in range(import_count))

        started = time.process_time()
        actual_count = sum(1 for _ in instruction_helpers.iter_instruction_imports(line))
        elapsed = time.process_time() - started

        assert actual_count == import_count
        assert elapsed < 1.0, f"import scan took {elapsed:.2f}s — likely superlinear"

    def test_github_team_mention_not_checked(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n\nAsk @org/platform-team before changing deploys.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_dotted_user_mention_not_checked(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n\nAsk @jane.doe before changing deploys.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_punctuation_only_import_token_not_checked(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\nSee @. before coding.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_mid_line_bare_existing_import_is_followed(self, temp_dir):
        (temp_dir / "README").write_text("# Overview\n\n@docs/missing.md\n")
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\nSee @README for project overview.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].file_path == temp_dir / "README"
        assert violations[0].line == 3
        assert "docs/missing.md" in violations[0].message

    def test_multiple_imports_mixed(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "exists.md").write_text("# Exists\n")
        content = "# Instructions\n@docs/exists.md\n@docs/missing.md\n@also/gone.md\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 2
        messages = [v.message for v in violations]
        assert any("missing.md" in m for m in messages)
        assert any("gone.md" in m for m in messages)

    def test_import_line_number_accurate(self, temp_dir):
        content = "line 1\nline 2\nline 3\nline 4\n@nonexistent.md\nline 6\n"
        (temp_dir / "GEMINI.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 5

    def test_gemini_md_imports_checked(self, temp_dir):
        (temp_dir / "GEMINI.md").write_text("@missing-file.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1

    def test_qwen_md_imports_checked(self, temp_dir):
        (temp_dir / "QWEN.md").write_text("@missing-file.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1

    def test_agents_md_missing_import_fails(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("@some-reference.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "non-existent" in violations[0].message.lower()

    def test_agents_md_valid_import_passes(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "setup.md").write_text("# Setup\n")
        (temp_dir / "AGENTS.md").write_text("# Instructions\n\n@docs/setup.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_import_escapes_repo_root(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("@../../etc/passwd\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "escapes" in violations[0].message.lower()

    def test_home_import_not_checked(self, temp_dir):
        # Claude Code's ``@~/.claude/...`` memory syntax points at
        # machine-local files that aren't in the repo. Existence checking
        # them is always noise in CI, so they must be skipped (issue #322).
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@~/.claude/my-file.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_home_import_skipped_but_relative_still_fails(self, temp_dir):
        content = "# Instructions\n@~/.claude/env-specific.md\n@docs/missing.md\n"
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "missing.md" in violations[0].message

    def test_import_with_leading_whitespace(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("  @nonexistent.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1

    def test_bare_import_in_list_item_checked(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n- @missing\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "missing" in violations[0].message

    def test_bare_import_in_blockquote_checked(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n> @missing\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "missing" in violations[0].message

    def test_inline_at_not_matched(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text("Contact user@example.com for help\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_nested_import_resolves_relative_to_importing_file(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "entry.md").write_text("# Entry\n\n@details.md\n")
        (docs_dir / "details.md").write_text("# Details\n")
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@docs/entry.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_nested_missing_import_reported_on_importing_file(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "entry.md").write_text("# Entry\n\nUse @more/missing.md for detail.\n")
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@docs/entry.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].file_path == docs_dir / "entry.md"
        assert violations[0].line == 3
        assert "more/missing.md" in violations[0].message

    def test_recursive_import_cycle_skipped(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "entry.md").write_text("# Entry\n\n@../CLAUDE.md\n")
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@docs/entry.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_unreadable_imported_file_skipped(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "entry.md").write_bytes(b"\x80\x81\x82")
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@docs/entry.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_mid_line_relative_import_reported(self, temp_dir):
        # A mid-line ``@./…`` reference is unambiguously an import path.
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\nLoad @./config.md before running.\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "config.md" in violations[0].message
        assert violations[0].line == 3

    def test_mid_line_slash_import_reported_when_parent_dir_exists(self, temp_dir):
        # ``@docs/missing`` (no extension) is shaped like a GitHub team mention,
        # but the ``docs/`` directory exists, so it's a broken import, not prose.
        (temp_dir / "docs").mkdir()
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n\nFollow the guide in @docs/missing before coding.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "docs/missing" in violations[0].message
        assert violations[0].line == 3

    def test_mid_line_slash_mention_not_checked_when_parent_dir_absent(self, temp_dir):
        # ``@org/platform-team`` has no matching ``org/`` directory, so it reads
        # as a team mention rather than an import and must stay quiet.
        (temp_dir / "CLAUDE.md").write_text(
            "# Instructions\n\nAsk @org/platform-team before changing deploys.\n"
        )
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_deep_then_shallow_path_revisits_for_nested_violation(self, temp_dir):
        # ``hub.md`` is first reached at the hop limit (its children can't be
        # followed), then again directly. The shallow re-entry must recurse into
        # its child and surface the child's broken import (regression for the
        # visited-set-by-path-only bug).
        shared = temp_dir / "shared"
        shared.mkdir()
        (shared / "hub.md").write_text("# Hub\n\n@child.md\n")
        (shared / "child.md").write_text("# Child\n\n@missing.md\n")
        (temp_dir / "p1.md").write_text("# P1\n\n@p2.md\n")
        (temp_dir / "p2.md").write_text("# P2\n\n@p3.md\n")
        (temp_dir / "p3.md").write_text("# P3\n\n@shared/hub.md\n")
        # Deep chain first (reaches hub at depth 4), then the direct import.
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@p1.md\n@shared/hub.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].file_path == shared / "child.md"
        assert "missing.md" in violations[0].message

    def test_import_recursion_stops_at_hop_limit(self, temp_dir):
        # A five-deep chain: the fifth file's broken import must not be reported
        # because recursion stops after four hops.
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@a.md\n")
        (temp_dir / "a.md").write_text("# A\n\n@b.md\n")
        (temp_dir / "b.md").write_text("# B\n\n@c.md\n")
        (temp_dir / "c.md").write_text("# C\n\n@d.md\n")
        (temp_dir / "d.md").write_text("# D\n\n@e.md\n")
        (temp_dir / "e.md").write_text("# E\n\n@beyond-the-limit.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_at_in_fenced_code_block_not_matched(self, temp_dir):
        content = (
            "# Instructions\n"
            "\n"
            "```python\n"
            "import functools\n"
            "\n"
            "class MyService:\n"
            "    @functools.lru_cache(maxsize=128)\n"
            "    def fetch_data(self, key: str) -> dict:\n"
            "        ...\n"
            "```\n"
        )
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_at_import_in_fenced_code_block_not_matched(self, temp_dir):
        content = (
            "# Instructions\n"
            "\n"
            "Example import syntax:\n"
            "\n"
            "```\n"
            "@docs/setup.md\n"
            "```\n"
        )
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_at_import_outside_fenced_block_still_checked(self, temp_dir):
        content = (
            "# Instructions\n" "\n" "```python\n" "@decorator\n" "```\n" "\n" "@nonexistent.md\n"
        )
        (temp_dir / "CLAUDE.md").write_text(content)
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert violations[0].line == 7

    def test_import_to_existing_directory(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (temp_dir / "GEMINI.md").write_text("@docs\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 0

    def test_nested_import_escapes_repo_root(self, temp_dir):
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (temp_dir / "CLAUDE.md").write_text("# Instructions\n\n@docs/entry.md\n")
        (docs_dir / "entry.md").write_text("# Entry\n\n@../../outside.md\n")
        context = RepositoryContext(temp_dir)
        violations = InstructionImportsValidRule().check(context)
        assert len(violations) == 1
        assert "escapes" in violations[0].message.lower()
        assert violations[0].file_path == docs_dir / "entry.md"


# --- claude-md-agents-import ---

AGENTS_BODY = (
    "# Contributor guide for agents\n"
    "\n"
    "## Testing\n"
    "\n"
    "Run `make test` before every push. The integration suite talks to a\n"
    "Postgres container, so start it with `make docker-up` first.\n"
)


class TestClaudeMdAgentsImportRule:
    """The CLAUDE.md <-> AGENTS.md duplication rule."""

    def _check(self, root, **config):
        return ClaudeMdAgentsImportRule(config).check(RepositoryContext(root))

    def test_rule_metadata(self):
        rule = ClaudeMdAgentsImportRule()
        assert rule.rule_id == "claude-md-agents-import"
        assert rule.default_severity() == Severity.INFO
        assert rule.default_enabled == "auto"
        assert rule.since == "0.20.0"
        assert rule.formats == frozenset({HAS_CLAUDE_MD, HAS_AGENTS_MD})
        assert rule.config_schema["allow-extra"]["default"] is True
        assert rule.supports_autofix
        assert rule.autofix_confidence == AutofixConfidence.SUGGEST

    # -- silence -----------------------------------------------------

    def test_claude_md_alone_is_silent(self, temp_dir):
        (temp_dir / "CLAUDE.md").write_text(AGENTS_BODY)
        assert self._check(temp_dir) == []

    def test_agents_md_alone_is_silent(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        assert self._check(temp_dir) == []

    def test_import_only_claude_md_is_silent(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text("@AGENTS.md\n")
        assert self._check(temp_dir) == []

    def test_relative_dot_slash_import_is_silent(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text("@./AGENTS.md\n")
        assert self._check(temp_dir) == []

    def test_html_comments_and_blank_lines_are_tolerated(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(
            "<!-- Shared instructions live in AGENTS.md; keep this file a\n"
            "     one-line import so both assistants read one source. -->\n"
            "\n"
            "@AGENTS.md\n"
            "\n"
            "<!-- nothing else belongs here -->\n"
        )
        assert self._check(temp_dir) == []

    def test_empty_claude_md_is_left_to_instruction_file_valid(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text("\n\n")
        assert self._check(temp_dir) == []
        assert len(InstructionFileValidRule().check(RepositoryContext(temp_dir))) == 1

    def test_generated_claude_md_is_skipped_by_default(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(
            "<!-- Generated by APM CLI from .apm/ primitives -->\n" + AGENTS_BODY
        )
        assert self._check(temp_dir) == []
        assert len(self._check(temp_dir, **{"ignore-generated": False})) == 1

    def test_symlinked_claude_md_is_not_a_pair(self, temp_dir):
        """One file under two names is the other honest answer.

        openshift-eng/ai-helpers ships exactly this: ``CLAUDE.md`` is a
        symlink to ``AGENTS.md``. There is no second copy to drift, so the
        rule stays quiet.
        """
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").symlink_to("AGENTS.md")
        assert self._check(temp_dir) == []

    def test_pairing_follows_nested_devin_instruction_discovery(self, temp_dir):
        """Devin-supported nested instruction pairs are checked in place."""
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text("@AGENTS.md\n")
        nested = temp_dir / "packages" / "api"
        nested.mkdir(parents=True)
        (nested / "AGENTS.md").write_text(AGENTS_BODY)
        (nested / "CLAUDE.md").write_text(AGENTS_BODY)
        context = RepositoryContext(temp_dir)
        assert {b.path for b in context.lint_tree.find(ClaudeMdBlock)} == {
            temp_dir / "CLAUDE.md",
            nested / "CLAUDE.md",
        }
        violations = ClaudeMdAgentsImportRule().check(context)
        assert len(violations) == 1
        assert violations[0].file_path == nested / "CLAUDE.md"

    # -- firing ------------------------------------------------------

    def test_duplicated_pair_fires_and_is_fixable(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(AGENTS_BODY)
        violations = self._check(temp_dir)
        assert len(violations) == 1
        assert violations[0].rule_id == "claude-md-agents-import"
        assert violations[0].severity == Severity.INFO
        assert violations[0].line == 1
        assert violations[0].file_path == temp_dir / "CLAUDE.md"
        assert violations[0].fixable is True
        assert violations[0].fix_confidence == AutofixConfidence.SUGGEST
        assert "@AGENTS.md" in violations[0].message

    def test_trailing_whitespace_only_difference_is_still_fixable(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(AGENTS_BODY.replace("## Testing\n", "## Testing   \n"))
        violations = self._check(temp_dir)
        assert len(violations) == 1
        assert violations[0].fixable is True

    def test_diverged_pair_fires_but_is_not_fixable(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(AGENTS_BODY + "\nAlways run `make lint` too.\n")
        violations = self._check(temp_dir)
        assert len(violations) == 1
        assert violations[0].fixable is False

    def test_default_message_keeps_disjoint_claude_instructions(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("Run `make test` before pushing.\n")
        (temp_dir / "CLAUDE.md").write_text("Use plan mode for billing changes.\n")
        violations = self._check(temp_dir)
        assert len(violations) == 1
        assert violations[0].fixable is False
        assert "does not import" in violations[0].message
        assert "keep Claude-specific instructions" in violations[0].message
        assert "replace its contents" not in violations[0].message

    def test_exact_duplicate_message_recommends_replacement(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(AGENTS_BODY)
        violations = self._check(temp_dir)
        assert len(violations) == 1
        assert violations[0].fixable is True
        assert "duplicates its sibling" in violations[0].message
        assert "replace its contents" in violations[0].message

    def test_strict_message_preserves_disjoint_claude_instructions(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text("Run tests.\n")
        (temp_dir / "CLAUDE.md").write_text("Use plan mode for billing changes.\n")
        violations = self._check(temp_dir, **{"allow-extra": False})
        assert len(violations) == 1
        assert violations[0].fixable is False
        assert "instructions that must be kept" in violations[0].message
        assert "then make CLAUDE.md" in violations[0].message

    def test_reported_line_is_the_first_non_import_content(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(
            "<!-- header comment -->\n"
            "\n"
            "@AGENTS.md\n"
            "\n"
            "## Claude Code specifics\n"
            "\n"
            "Load the `release` skill before cutting a tag.\n"
        )
        violations = self._check(temp_dir, **{"allow-extra": False})
        assert len(violations) == 1
        assert violations[0].line == 5
        assert "move them into AGENTS.md" in violations[0].message

    def test_code_fence_counts_as_content(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text("@AGENTS.md\n\n```sh\nmake deploy\n```\n")
        violations = self._check(temp_dir, **{"allow-extra": False})
        assert len(violations) == 1
        assert violations[0].line == 3

    # -- allow-extra -------------------------------------------------

    def test_default_accepts_import_plus_claude_specific_content(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(
            "@AGENTS.md\n\n## Claude Code\n\nUse plan mode for changes under `src/billing/`.\n"
        )
        assert self._check(temp_dir) == []

    @pytest.mark.parametrize(
        "content",
        [
            "- @AGENTS.md\n",
            "> @AGENTS.md\n",
            "Read @./AGENTS.md\n",
            "Include: @./AGENTS.md\n",
            "Read @AGENTS.md and @README.md\n",
            "Please read **@AGENTS.md** first.\n",
            "- **@AGENTS.md** — canonical instructions.\n",
            "_@AGENTS.md_\n",
            "~~@AGENTS.md~~\n",
        ],
    )
    def test_allow_extra_recognizes_wrapped_sibling_imports(self, temp_dir, content):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(content)
        assert self._check(temp_dir, **{"allow-extra": True}) == []

    @pytest.mark.parametrize(
        "content",
        [
            "- @AGENTS.md\n",
            "> @AGENTS.md\n",
            "Read @./AGENTS.md\n",
            "Include: @./AGENTS.md\n",
            "Please read **@AGENTS.md** first.\n",
            "- **@AGENTS.md** — canonical instructions.\n",
            "_@AGENTS.md_\n",
            "~~@AGENTS.md~~\n",
        ],
    )
    def test_strict_mode_still_reports_wrapped_sibling_imports(self, temp_dir, content):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(content)
        violations = self._check(temp_dir, **{"allow-extra": False})
        assert len(violations) == 1
        assert violations[0].line == 1
        assert "imports AGENTS.md but also" in violations[0].message

    @pytest.mark.parametrize(
        "content",
        [
            "```markdown\n@AGENTS.md\n```\n",
            "    @AGENTS.md\n",
            "`@AGENTS.md`\n",
            "<!-- @AGENTS.md -->\nClaude-only text.\n",
        ],
    )
    def test_allow_extra_ignores_imports_in_non_prose(self, temp_dir, content):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(content)
        assert len(self._check(temp_dir, **{"allow-extra": True})) == 1

    def test_default_still_reports_a_missing_import(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(AGENTS_BODY)
        assert len(self._check(temp_dir)) == 1

    # -- fix ---------------------------------------------------------

    def test_fix_replaces_an_identical_copy_with_the_import(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(AGENTS_BODY)
        rule = ClaudeMdAgentsImportRule()
        context = RepositoryContext(temp_dir)
        violations = rule.check(context)
        fixes = rule.fix(context, violations)
        assert len(fixes) == 1
        assert fixes[0].confidence == AutofixConfidence.SUGGEST
        assert fixes[0].fixed_content == "@AGENTS.md\n"
        # A file-restructuring fix, not an in-place splice: the line count
        # changing is the point, so nothing here asserts it is preserved.
        assert len(fixes[0].fixed_content.splitlines()) == 1

    def test_fix_declines_a_diverged_copy(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(AGENTS_BODY + "\nAlso run `make lint`.\n")
        rule = ClaudeMdAgentsImportRule()
        context = RepositoryContext(temp_dir)
        assert rule.fix(context, rule.check(context)) == []

    def test_fix_is_idempotent(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(AGENTS_BODY)
        rule = ClaudeMdAgentsImportRule()
        context = RepositoryContext(temp_dir)
        fixes = rule.fix(context, rule.check(context))
        (temp_dir / "CLAUDE.md").write_text(fixes[0].fixed_content)
        invalidate_read_caches()
        context2 = RepositoryContext(temp_dir)
        assert rule.check(context2) == []
        assert rule.fix(context2, []) == []


class TestClaudeMdAgentsImportInteractions:
    """The recommended end state must be clean under every other rule."""

    def _import_only_repo(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text("@AGENTS.md\n")
        return RepositoryContext(temp_dir)

    def test_instruction_drift_stays_silent_on_the_end_state(self, temp_dir):
        """An import-only CLAUDE.md is the *solution* to drift, not drift.

        It carries no headings, so it contributes no comparable sections —
        the drift rule needs no teaching to stay quiet here, and this test
        pins that.
        """
        context = self._import_only_repo(temp_dir)
        assert ContentInstructionDriftRule().check(context) == []
        assert ClaudeMdAgentsImportRule().check(context) == []

    def test_drift_fires_only_once_the_copies_diverge(self, temp_dir):
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text(AGENTS_BODY)
        # Identical copies are intentional sync — drift never fires, this
        # rule does.
        assert ContentInstructionDriftRule().check(RepositoryContext(temp_dir)) == []
        assert len(ClaudeMdAgentsImportRule().check(RepositoryContext(temp_dir))) == 1

        (temp_dir / "CLAUDE.md").write_text(
            AGENTS_BODY.replace(
                "Postgres container, so start it with `make docker-up` first.\n",
                "Postgres container, so start it with `make docker-up` first.\n"
                "Coverage may never drop below the committed floor.\n",
            )
        )
        invalidate_read_caches()
        context = RepositoryContext(temp_dir)
        drift = ContentInstructionDriftRule({"min-section-words": 10}).check(context)
        assert len(drift) == 1
        assert len(ClaudeMdAgentsImportRule().check(context)) == 1

    def test_the_import_passes_instruction_imports_valid(self, temp_dir):
        context = self._import_only_repo(temp_dir)
        assert InstructionImportsValidRule().check(context) == []

    def test_a_broken_import_is_reported_only_by_imports_valid(self, temp_dir):
        """This rule must not duplicate ``instruction-imports-valid``.

        ``@AGENTS.mdx`` is a broken import, so imports-valid reports it —
        and because it does not resolve to the paired AGENTS.md, this rule
        reads it as ordinary content and recommends the real import once.
        """
        (temp_dir / "AGENTS.md").write_text(AGENTS_BODY)
        (temp_dir / "CLAUDE.md").write_text("@AGENTS.mdx\n")
        context = RepositoryContext(temp_dir)
        imports = InstructionImportsValidRule().check(context)
        assert len(imports) == 1
        assert "non-existent" in imports[0].message
        ours = ClaudeMdAgentsImportRule().check(context)
        assert len(ours) == 1
        assert "non-existent" not in ours[0].message

    def test_no_builtin_rule_fires_on_the_import_only_layout(self, temp_dir):
        """The recommended end state must lint completely clean.

        Every builtin rule runs against the fixture directly (bypassing
        config gating), so a rule with a minimum-content expectation that
        trips on the one-liner shows up here rather than in the field.
        """
        context = self._import_only_repo(temp_dir)
        reported = []
        for rule_class in BUILTIN_RULES:
            reported.extend(rule_class().check(context))
        assert reported == [], [f"{v.rule_id}: {v.message}" for v in reported]
