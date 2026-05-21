"""Tests for the TUI module."""

from __future__ import annotations

from skillsaw.tui import (
    LOGO_BANNER,
    SLOGANS,
    FixApp,
    FixParams,
    _escape_markup,
    _fmt_duration,
    _truncate_to_width,
    _visible_len,
)


class TestVisibleLen:
    def test_plain_text(self):
        assert _visible_len("hello") == 5

    def test_empty(self):
        assert _visible_len("") == 0

    def test_with_ansi(self):
        assert _visible_len("\033[91mhello\033[0m") == 5

    def test_multiple_codes(self):
        assert _visible_len("\033[1m\033[92mAB\033[0m") == 2

    def test_no_text_only_codes(self):
        assert _visible_len("\033[0m") == 0


class TestTruncateToWidth:
    def test_short_string(self):
        assert _truncate_to_width("abc", 10) == "abc"

    def test_exact_width(self):
        assert _truncate_to_width("abcde", 5) == "abcde"

    def test_truncates_plain(self):
        result = _truncate_to_width("abcdef", 3)
        assert _visible_len(result) == 3
        assert result.endswith("\033[0m")

    def test_preserves_ansi_before_cut(self):
        s = "\033[91mhello world\033[0m"
        result = _truncate_to_width(s, 5)
        assert _visible_len(result) == 5
        assert "hello" in result

    def test_empty(self):
        assert _truncate_to_width("", 5) == ""


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
