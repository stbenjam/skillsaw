"""Tests for terminal pager support in CLI commands."""

import io
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

from skillsaw.cli._pager import (
    _write_fallback,
    display_paged,
    page_text,
    resolve_pager_command,
    should_use_pager,
)


class MockTTYStream(io.StringIO):
    def isatty(self):
        return True


class MockNonTTYStream(io.StringIO):
    def isatty(self):
        return False


def test_should_use_pager_explicit_flag():
    args_true = SimpleNamespace(pager=True)
    args_false = SimpleNamespace(pager=False)
    non_tty = MockNonTTYStream()

    # --pager forces paging even without a TTY
    assert should_use_pager(args_true, stream=non_tty) is True

    # --no-pager disables paging even on a TTY
    tty = MockTTYStream()
    assert should_use_pager(args_false, stream=tty) is False


def test_should_use_pager_non_tty(monkeypatch):
    monkeypatch.setenv("PAGER", "cat")
    non_tty = MockNonTTYStream()
    args = SimpleNamespace(pager=None)
    assert should_use_pager(args, stream=non_tty) is False


def test_should_use_pager_stdin_not_tty(monkeypatch):
    monkeypatch.setenv("PAGER", "cat")
    tty = MockTTYStream()
    args = SimpleNamespace(pager=None)
    with patch("sys.stdin", MockNonTTYStream()):
        assert should_use_pager(args, stream=tty) is False


def test_should_use_pager_dumb_terminal(monkeypatch):
    monkeypatch.setenv("PAGER", "cat")
    monkeypatch.setenv("TERM", "dumb")
    tty = MockTTYStream()
    args = SimpleNamespace(pager=None)
    with patch("sys.stdin", MockTTYStream()):
        assert should_use_pager(args, stream=tty) is False


def test_should_use_pager_emacs_terminal(monkeypatch):
    monkeypatch.setenv("PAGER", "cat")
    monkeypatch.setenv("TERM", "emacs")
    tty = MockTTYStream()
    args = SimpleNamespace(pager=None)
    with patch("sys.stdin", MockTTYStream()):
        assert should_use_pager(args, stream=tty) is False


def test_should_use_pager_empty_pager(monkeypatch):
    monkeypatch.setenv("PAGER", "")
    monkeypatch.delenv("MANPAGER", raising=False)
    tty = MockTTYStream()
    args = SimpleNamespace(pager=None)
    with patch("sys.stdin", MockTTYStream()):
        assert should_use_pager(args, stream=tty) is False


def test_should_use_pager_active_when_tty(monkeypatch):
    monkeypatch.setenv("PAGER", "cat")
    monkeypatch.setenv("TERM", "xterm-256color")
    tty = MockTTYStream()
    args = SimpleNamespace(pager=None)
    with patch("sys.stdin", MockTTYStream()):
        assert should_use_pager(args, stream=tty) is True


def test_resolve_pager_manpager_precedence(monkeypatch):
    monkeypatch.setenv("MANPAGER", "cat")
    monkeypatch.setenv("PAGER", "more")
    cmd_parts, env = resolve_pager_command()
    assert cmd_parts == ["cat"]


def test_resolve_pager_manpager_empty_falls_back_to_pager(monkeypatch):
    monkeypatch.setenv("MANPAGER", "")
    monkeypatch.setenv("PAGER", "cat")
    cmd_parts, env = resolve_pager_command()
    assert cmd_parts == ["cat"]


def test_resolve_pager_empty_pager_returns_none(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.setenv("PAGER", "   ")
    assert resolve_pager_command() is None


def test_resolve_pager_nonexistent_command(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.setenv("PAGER", "definitely_not_a_valid_pager_command_12345")
    assert resolve_pager_command() is None


def test_resolve_pager_malformed_syntax(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.setenv("PAGER", 'less "unclosed quote')
    assert resolve_pager_command() is None


def test_resolve_pager_less_sets_less_r(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.delenv("PAGER", raising=False)
    monkeypatch.delenv("LESS", raising=False)
    resolved = resolve_pager_command()
    if resolved is not None and resolved[0][0] == "less":
        cmd_parts, env = resolved
        assert env.get("LESS") == "-R"


def test_resolve_pager_preserves_existing_less(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.delenv("PAGER", raising=False)
    monkeypatch.setenv("LESS", "-FRX")
    resolved = resolve_pager_command()
    if resolved is not None and resolved[0][0] == "less":
        cmd_parts, env = resolved
        assert env.get("LESS") == "-FRX"


def test_page_text_pipes_to_command(tmp_path):
    out_file = tmp_path / "out.txt"
    cmd = [
        sys.executable,
        "-c",
        f"import sys, pathlib; pathlib.Path({repr(str(out_file))}).write_text(sys.stdin.read())",
    ]
    page_text("Hello world", pager_cmd=cmd, env=dict(os.environ))
    assert out_file.read_text() == "Hello world\n"


def test_page_text_broken_pipe_handled(tmp_path):
    cmd = [sys.executable, "-c", "import sys; sys.exit(0)"]
    large_text = "x" * 100_000
    page_text(large_text, pager_cmd=cmd, env=dict(os.environ))


def test_page_text_invalid_cmd_fallback():
    buf = io.StringIO()
    page_text("Fallback content", pager_cmd=["/nonexistent/bin/pager"], stream=buf)
    assert "Fallback content" in buf.getvalue()


def test_display_paged_direct_write_when_no_pager():
    buf = io.StringIO()
    args = SimpleNamespace(pager=False)
    display_paged("Direct content", args, stream=buf)
    assert buf.getvalue() == "Direct content\n"


def test_write_fallback_broken_pipe():
    class BrokenStream(io.StringIO):
        def write(self, s):
            raise BrokenPipeError()

    broken = BrokenStream()
    _write_fallback("hello", stream=broken)
