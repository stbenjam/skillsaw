"""Terminal pager support for interactive CLI commands."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence, TextIO


def should_use_pager(args, stream: TextIO | None = None) -> bool:
    """Determine whether output should be directed to a pager.

    Paging is enabled when:
    1. Explicitly requested via ``--pager`` (i.e. ``args.pager is True``).
    2. Auto-detected (``args.pager is None``):
       - stdout is a TTY
       - stdin is a TTY
       - TERM is not 'dumb' or 'emacs'
       - PAGER / MANPAGER is not explicitly empty ("")
       - A pager command is available on the system

    Paging is disabled when:
    - ``--no-pager`` is passed (``args.pager is False``)
    - stdout or stdin is not a TTY (in auto mode)
    - TERM is 'dumb' or 'emacs' (in auto mode)
    - PAGER or MANPAGER is explicitly set to empty string
    - No pager binary is available
    """
    pager_opt = getattr(args, "pager", None)
    if pager_opt is False:
        return False
    if pager_opt is True:
        return resolve_pager_command(force=True) is not None

    if stream is None:
        stream = sys.stdout

    # Auto-detection
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False

    stdin = sys.stdin
    if stdin is None:
        return False
    try:
        if not stdin.isatty():
            return False
    except (AttributeError, ValueError):
        return False

    if os.environ.get("TERM") in ("dumb", "emacs"):
        return False

    if resolve_pager_command() is None:
        return False

    return True


def resolve_pager_command(
    pager_env: str | None = None,
    *,
    force: bool = False,
) -> tuple[list[str], dict[str, str]] | None:
    """Resolve pager command arguments and environment.

    Checks ``MANPAGER``, then ``PAGER``, falling back to ``less`` or ``more``.
    Returns a tuple of (command_parts, environment_dict), or ``None`` if
    no valid pager is available or paging is disabled via empty string.
    When ``force=True``, an empty environment setting is ignored in favor of
    an available fallback pager.
    """
    raw_cmd = pager_env
    if raw_cmd is None:
        if os.environ.get("MANPAGER", "").strip():
            raw_cmd = os.environ["MANPAGER"]
        elif "PAGER" in os.environ:
            raw_cmd = os.environ["PAGER"]
        elif "MANPAGER" in os.environ:
            raw_cmd = os.environ["MANPAGER"]

    if raw_cmd is not None:
        raw_cmd = raw_cmd.strip()
        if not raw_cmd:
            if not force:
                return None
            raw_cmd = None

    if raw_cmd is not None:
        try:
            cmd_parts = shlex.split(raw_cmd, posix=sys.platform != "win32")
        except ValueError:
            return None
        if sys.platform == "win32" and cmd_parts:
            cmd_parts = [
                (
                    part[1:-1]
                    if len(part) >= 2 and part[0] == part[-1] and part[0] in ('"', "'")
                    else part
                )
                for part in cmd_parts
            ]
        if not cmd_parts:
            return None
        if not shutil.which(cmd_parts[0]):
            return None
    else:
        # Default fallback: less, then more
        if shutil.which("less"):
            cmd_parts = ["less"]
        elif shutil.which("more"):
            cmd_parts = ["more"]
        else:
            return None

    env = dict(os.environ)
    cmd_name = cmd_parts[0].replace("\\", "/").split("/")[-1].lower().removesuffix(".exe")
    # When using less and LESS is unset, enable raw ANSI escape sequences
    # so colored output displays properly.
    if cmd_name == "less":
        if "LESS" not in env:
            env["LESS"] = "-R"
        env.setdefault("LESSCHARSET", "utf-8")

    return cmd_parts, env


def page_text(
    text: str,
    pager_cmd: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
) -> None:
    """Feed text to a pager process."""
    if stream is None:
        stream = sys.stdout

    if not text.endswith("\n"):
        text += "\n"

    if pager_cmd is None:
        resolved = resolve_pager_command()
        if resolved is None:
            _write_fallback(text, stream=stream)
            return
        pager_cmd, default_env = resolved
        if env is None:
            env = default_env

    if env is None:
        env = dict(os.environ)

    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        encoding = "utf-8"

    try:
        proc = subprocess.Popen(
            list(pager_cmd),
            stdin=subprocess.PIPE,
            text=True,
            encoding=encoding,
            env=dict(env),
            errors="replace",
        )
    except (OSError, ValueError):
        _write_fallback(text, stream=stream)
        return

    try:
        if proc.stdin is not None:
            proc.stdin.write(text)
            proc.stdin.close()
    except (BrokenPipeError, OSError):
        # Pager was closed early (e.g. user pressed 'q' in less)
        pass
    except Exception:
        proc.terminate()
        raise
    finally:
        while True:
            try:
                proc.wait()
                break
            except KeyboardInterrupt:
                pass


def _write_fallback(text: str, stream: TextIO | None = None) -> None:
    """Write text directly to stream, handling broken pipes safely."""
    if stream is None:
        stream = sys.stdout

    if not text.endswith("\n"):
        text += "\n"
    try:
        stream.write(text)
        stream.flush()
    except BrokenPipeError:
        try:
            stream.close()
        except Exception:
            pass


def display_paged(text: str, args, stream: TextIO | None = None) -> None:
    """Display text using a pager if appropriate, otherwise write directly."""
    if stream is None:
        stream = sys.stdout

    force = getattr(args, "pager", None) is True
    if should_use_pager(args, stream=stream):
        resolved = resolve_pager_command(force=force)
        if resolved is not None:
            cmd_parts, pager_env = resolved
            page_text(text, pager_cmd=cmd_parts, env=pager_env, stream=stream)
            return
    _write_fallback(text, stream=stream)
