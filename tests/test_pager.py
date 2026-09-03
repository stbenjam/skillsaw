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
    monkeypatch.delenv("MANPAGER", raising=False)
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

        def close(self):
            if getattr(self, "_close_called", False):
                return
            self._close_called = True
            raise OSError("close failed")

    broken = BrokenStream()
    _write_fallback("hello", stream=broken)


def test_write_fallback_default_stream(capsys):
    _write_fallback("default stream fallback\n")
    captured = capsys.readouterr()
    assert "default stream fallback" in captured.out


def test_should_use_pager_stream_none_defaults_to_stdout(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.setenv("PAGER", "cat")
    monkeypatch.setenv("TERM", "xterm")
    args = SimpleNamespace(pager=None)
    with patch("sys.stdout", MockTTYStream()), patch("sys.stdin", MockTTYStream()):
        assert should_use_pager(args) is True


def test_should_use_pager_stream_attribute_error():
    class NoIsatty:
        pass

    args = SimpleNamespace(pager=None)
    assert should_use_pager(args, stream=NoIsatty()) is False


def test_should_use_pager_stream_value_error():
    buf = io.StringIO()
    buf.close()
    args = SimpleNamespace(pager=None)
    assert should_use_pager(args, stream=buf) is False


def test_should_use_pager_stdin_none(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    tty = MockTTYStream()
    args = SimpleNamespace(pager=None)
    assert should_use_pager(args, stream=tty) is False


def test_should_use_pager_stdin_attribute_error(monkeypatch):
    class NoIsatty:
        pass

    monkeypatch.setattr(sys, "stdin", NoIsatty())
    tty = MockTTYStream()
    args = SimpleNamespace(pager=None)
    assert should_use_pager(args, stream=tty) is False


def test_should_use_pager_no_pager_available(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.delenv("PAGER", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    tty = MockTTYStream()
    args = SimpleNamespace(pager=None)
    with patch("sys.stdin", MockTTYStream()), patch("shutil.which", return_value=None):
        assert should_use_pager(args, stream=tty) is False


def test_resolve_pager_empty_split():
    with patch("shlex.split", return_value=[]):
        assert resolve_pager_command("dummy") is None


def test_resolve_pager_manpager_whitespace_no_pager(monkeypatch):
    monkeypatch.delenv("PAGER", raising=False)
    monkeypatch.setenv("MANPAGER", "   ")
    assert resolve_pager_command() is None


def test_resolve_pager_fallback_to_more(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.delenv("PAGER", raising=False)

    def mock_which(cmd):
        if cmd == "more":
            return "/usr/bin/more"
        return None

    with patch("shutil.which", side_effect=mock_which):
        resolved = resolve_pager_command()
        assert resolved is not None
        cmd_parts, _ = resolved
        assert cmd_parts == ["more"]


def test_resolve_pager_fallback_none_found(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.delenv("PAGER", raising=False)
    with patch("shutil.which", return_value=None):
        assert resolve_pager_command() is None


def test_resolve_pager_windows_path_semantics(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with patch("shutil.which", return_value=r"C:\bin\less.exe"):
        resolved = resolve_pager_command(r"C:\bin\less.exe -R")
        assert resolved is not None
        cmd_parts, _ = resolved
        assert cmd_parts == [r"C:\bin\less.exe", "-R"]


def test_page_text_with_pager_cmd_none(tmp_path):
    out_file = tmp_path / "out.txt"
    cmd = f'{sys.executable} -c "import sys, pathlib; pathlib.Path({repr(str(out_file))}).write_text(sys.stdin.read())"'
    with patch.dict(os.environ, {"PAGER": cmd, "MANPAGER": ""}):
        page_text("Paging with resolved command")
    assert out_file.read_text() == "Paging with resolved command\n"


def test_page_text_pager_cmd_none_unresolvable():
    buf = io.StringIO()
    with patch("skillsaw.cli._pager.resolve_pager_command", return_value=None):
        page_text("Unresolvable text", pager_cmd=None, stream=buf)
    assert buf.getvalue() == "Unresolvable text\n"


def test_page_text_unexpected_exception():
    class DummyProc:
        def __init__(self):
            self.stdin = SimpleNamespace(
                write=self._write,
                close=lambda: None,
            )
            self.terminated = False

        def _write(self, text):
            raise RuntimeError("Unexpected failure writing to stdin")

        def terminate(self):
            self.terminated = True

        def wait(self):
            pass

    dummy = DummyProc()
    with patch("subprocess.Popen", return_value=dummy):
        try:
            page_text("hello", pager_cmd=["dummy"])
        except RuntimeError as e:
            assert "Unexpected failure" in str(e)
            assert dummy.terminated is True
        else:
            assert False, "Expected RuntimeError"


def test_page_text_keyboard_interrupt_wait():
    class DummyProc:
        def __init__(self):
            self.stdin = SimpleNamespace(
                write=lambda text: None,
                close=lambda: None,
            )
            self.wait_count = 0

        def wait(self):
            self.wait_count += 1
            if self.wait_count == 1:
                raise KeyboardInterrupt()
            return 0

    dummy = DummyProc()
    with patch("subprocess.Popen", return_value=dummy):
        page_text("hello", pager_cmd=["dummy"])
    assert dummy.wait_count == 2


def test_display_paged_pager_enabled():
    buf = io.StringIO()
    args = SimpleNamespace(pager=True)
    with patch("skillsaw.cli._pager.page_text") as mock_page:
        with patch(
            "skillsaw.cli._pager.resolve_pager_command", return_value=(["cat"], {})
        ) as mock_resolve:
            display_paged("hello world", args, stream=buf)
            assert mock_page.called
            assert mock_page.call_args[0][0] == "hello world"
            assert mock_resolve.call_args[1].get("force") is True


def test_resolve_pager_empty_pager_with_force(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.setenv("PAGER", "   ")
    with patch("shutil.which", return_value="/usr/bin/less"):
        resolved = resolve_pager_command(force=True)
        assert resolved is not None
        assert resolved[0] == ["less"]


def test_should_use_pager_force_with_empty_pager(monkeypatch):
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.setenv("PAGER", "")
    args = SimpleNamespace(pager=True)
    with patch("shutil.which", return_value="/usr/bin/less"):
        assert should_use_pager(args) is True


def test_should_use_pager_force_no_pager_installed():
    args = SimpleNamespace(pager=True)
    with patch("shutil.which", return_value=None):
        assert should_use_pager(args) is False


def test_display_paged_default_stream(capsys):
    args = SimpleNamespace(pager=False)
    display_paged("hello default stream\n", args)
    captured = capsys.readouterr()
    assert "hello default stream" in captured.out
