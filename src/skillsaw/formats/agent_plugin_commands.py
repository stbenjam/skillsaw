"""Executable tokens and path containment shared by portable MCP and hooks."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from skillsaw.paths import contained_resolve, is_absolute_path, safe_is_dir


def is_control_character(char: str) -> bool:
    """Whether *char* is a C0 control, DEL, or a C1 control (0x80-0x9F)."""
    point = ord(char)
    return point < 32 or 127 <= point <= 159


def normalized_parts(value: str) -> Optional[List[str]]:
    """The path components *value* names, or ``None`` when it escapes.

    Safe internal normalization such as ``cache/../cache`` is valid under
    the spec's post-resolution containment rule. Treat both separators as
    portable input so a value checked on POSIX cannot escape on Windows.
    An empty list means the value names its own logical root.
    """
    parts: List[str] = []
    for part in value.replace("\\", "/").split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return parts


def command_problem(command: str, plugin_dir: Path, plugin_root: Path) -> Optional[str]:
    """Why *command* is not a portable executable token, or ``None``."""
    # A control character in an executable token is either a mis-encoded
    # value or an attempt to smuggle one token past a naive reader; it is
    # never part of a real program name, in either accepted form.
    if any(is_control_character(char) for char in command):
        return "'command' must not contain control characters"
    if command.startswith("./"):
        suffix = command[2:]
        resolved = contained_resolve(plugin_dir / command, plugin_root)
        parts = normalized_parts(suffix)
        if is_absolute_path(suffix) or parts is None or resolved is None:
            return "'command' resolves outside the plugin root"
        # './', './.' and './bin/..' all name the plugin root itself, which
        # is a directory, not the executable the field must identify. The
        # lexical check catches those without requiring the binary to
        # exist (it may only appear post-install); the filesystem check
        # rejects a path that already exists as a directory.
        if not parts or safe_is_dir(resolved):
            return "'command' must name an executable file, not a directory"
        return None
    if is_absolute_path(command) or "/" in command or "\\" in command:
        return "'command' must be a bare executable name or begin with './'"
    # A bare name cannot be a path, so whitespace means the value packs
    # arguments into the executable token ("node --eval …", "sh -c").
    # Only whitespace is rejected: shell metacharacters are legal in file
    # names, and rejecting them would fail valid single-token commands.
    if any(char.isspace() for char in command):
        return "'command' must be a single executable token; arguments must be supplied via 'args'"
    return None
