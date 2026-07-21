"""
Unit tests for the CLI color/hyperlink capability cascade (GH-415).

``color_enabled`` implements the standard precedence every mature CLI
ships: --color/--no-color > FORCE_COLOR > NO_COLOR > terminal
heuristics (``TERM=dumb`` disables, else stream.isatty()).
``hyperlinks_enabled`` additionally requires a real terminal that is not
``TERM=dumb`` — OSC 8 sequences are never forced through a pipe.
"""

import pytest

from skillsaw.cli._helpers import _ansi_colors, color_enabled, hyperlinks_enabled


class _Stream:
    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


TTY = _Stream(True)
PIPE = _Stream(False)


@pytest.fixture(autouse=True)
def _clean_color_env(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)


# --- color_enabled: isatty default ---


def test_tty_defaults_to_color():
    assert color_enabled(TTY) is True


def test_pipe_defaults_to_plain():
    assert color_enabled(PIPE) is False


def test_stream_without_isatty_defaults_to_plain():
    assert color_enabled(object()) is False


# --- color_enabled: TERM=dumb sits in the terminal-heuristic tier ---


def test_dumb_terminal_disables_color_on_tty(monkeypatch):
    """Emacs shell-mode etc. set TERM=dumb on a real pty: escape codes
    would render as literal ^[[91m garbage, so auto-detect stays plain."""
    monkeypatch.setenv("TERM", "dumb")
    assert color_enabled(TTY) is False


def test_dumb_terminal_stays_plain_on_pipe(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    assert color_enabled(PIPE) is False


def test_force_color_beats_dumb_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert color_enabled(TTY) is True


def test_color_flag_beats_dumb_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    assert color_enabled(TTY, color=True) is True


def test_capable_terminal_keeps_isatty_default(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    assert color_enabled(TTY) is True
    assert color_enabled(PIPE) is False


# --- color_enabled: NO_COLOR overrides isatty ---


def test_no_color_disables_on_tty(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert color_enabled(TTY) is False


def test_no_color_empty_string_still_disables(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "")
    assert color_enabled(TTY) is False


# --- color_enabled: FORCE_COLOR overrides NO_COLOR ---


def test_force_color_enables_on_pipe(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert color_enabled(PIPE) is True


def test_force_color_beats_no_color(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    assert color_enabled(PIPE) is True


def test_force_color_zero_disables_on_tty(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "0")
    assert color_enabled(TTY) is False


def test_force_color_empty_falls_through_to_isatty(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "")
    assert color_enabled(TTY) is True
    assert color_enabled(PIPE) is False


# --- color_enabled: --color / --no-color flag overrides everything ---


def test_color_flag_beats_no_color_and_pipe(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert color_enabled(PIPE, color=True) is True


def test_no_color_flag_beats_force_color_and_tty(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert color_enabled(TTY, color=False) is False


# --- hyperlinks_enabled ---


def test_hyperlinks_on_color_tty():
    assert hyperlinks_enabled(TTY, color=True) is True


def test_hyperlinks_require_color():
    assert hyperlinks_enabled(TTY, color=False) is False


def test_hyperlinks_never_through_pipe():
    """Even forced color (CI logs) must not emit OSC 8 through a pipe."""
    assert hyperlinks_enabled(PIPE, color=True) is False


def test_hyperlinks_suppressed_on_dumb_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    assert hyperlinks_enabled(TTY, color=True) is False


def test_hyperlinks_allowed_on_capable_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    assert hyperlinks_enabled(TTY, color=True) is True


# --- _ansi_colors ---


def test_ansi_colors_enabled_has_codes():
    c = _ansi_colors(True)
    assert c["red"] == "\033[91m"
    assert c["reset"] == "\033[0m"


def test_ansi_colors_disabled_is_all_empty():
    c = _ansi_colors(False)
    assert all(v == "" for v in c.values())
