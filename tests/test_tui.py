"""Tests for the TUI module."""

from __future__ import annotations

from pathlib import Path

from skillsaw.tui import (
    LOGO_BANNER,
    SLOGANS,
    FixApp,
    FixParams,
    TreeApp,
    _escape_markup,
    _fmt_duration,
)


class TestFmtDuration:
    def test_seconds(self):
        assert _fmt_duration(0) == "0s"
        assert _fmt_duration(42) == "42s"
        assert _fmt_duration(59) == "59s"

    def test_minutes(self):
        assert _fmt_duration(60) == "1m"
        assert _fmt_duration(90) == "1m30s"
        assert _fmt_duration(125) == "2m05s"


class TestEscapeMarkup:
    def test_brackets(self):
        assert _escape_markup("[bold]text[/]") == "\\[bold]text\\[/]"

    def test_no_brackets(self):
        assert _escape_markup("plain text") == "plain text"

    def test_diff_line(self):
        assert _escape_markup("+[new] line") == "+\\[new] line"


class TestLogoBanner:
    def test_banner_has_content(self):
        assert len(LOGO_BANNER) > 0

    def test_banner_is_3_lines(self):
        lines = LOGO_BANNER.split("\n")
        non_empty = [line for line in lines if line.strip()]
        assert len(non_empty) == 3


class TestSlogans:
    def test_slogans_not_empty(self):
        assert len(SLOGANS) > 0

    def test_slogans_are_strings(self):
        for s in SLOGANS:
            assert isinstance(s, str)
            assert len(s) > 0


class TestFixParams:
    def test_defaults(self):
        p = FixParams(
            linter=None,
            provider=None,
            min_severity=None,
            max_workers=4,
            dry_run=False,
        )
        assert p.model_name == ""
        assert p.total_violations == 0
        assert p.dry_run is False


class TestTreeApp:
    def test_creation(self):
        from skillsaw.lint_target import LintTarget

        root = LintTarget(path=Path("/tmp/test"))
        app = TreeApp(root, Path("/tmp/test"))
        assert app._lint_tree is root
        assert app._root_path == Path("/tmp/test")

    def test_with_children(self):
        from skillsaw.lint_target import LintTarget

        root = LintTarget(path=Path("/tmp/test"))
        child = LintTarget(path=Path("/tmp/test/child.md"))
        root.children = [child]
        app = TreeApp(root, Path("/tmp/test"))
        assert len(app._lint_tree.children) == 1
