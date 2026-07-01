"""Dispatch to plugin-provided CLI subcommands (``skillsaw <plugin> ...``).

A plugin package can ship a console script named ``skillsaw-<name>``
(matching its ``skillsaw.plugins`` entry point name). ``skillsaw <name>
[args...]`` then runs that executable with the remaining arguments, git-style.

Only *registered* plugins are eligible: an arbitrary ``skillsaw-foo`` on
PATH is never executed unless a plugin named ``foo`` is installed.
Registration is checked from package metadata alone, so no plugin code is
imported to dispatch. Builtin subcommands always take precedence.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def find_plugin_command(name: str) -> Optional[str]:
    """Resolve ``skillsaw <name>`` to a plugin-provided executable, if any.

    Returns the executable path when ``name`` is a registered plugin's entry
    point name and a ``skillsaw-<name>`` executable exists; None otherwise.
    """
    if not name or name.startswith("-"):
        return None
    # Anything with a path separator is a lint path, never a command name.
    if os.sep in name or (os.altsep and os.altsep in name):
        return None

    from ..plugins import installed_plugin_names

    if name not in installed_plugin_names():
        return None

    exe = shutil.which(f"skillsaw-{name}")
    if exe is None:
        # Console scripts install next to the interpreter (a venv's bin/),
        # which is not necessarily on PATH when skillsaw itself was invoked
        # through an absolute path or a pipx/uvx shim.
        exe = shutil.which(f"skillsaw-{name}", path=str(Path(sys.executable).parent))
    return exe


def run_plugin_command(exe: str, name: str, args: List[str]) -> int:
    """Run a plugin command, forwarding arguments and its exit code."""
    if Path(name).exists():
        print(
            f"note: '{name}' matches an installed plugin command; running "
            f"skillsaw-{name}. Use `skillsaw lint {name}` to lint the path instead.",
            file=sys.stderr,
        )
    try:
        return subprocess.run([exe, *args]).returncode
    except KeyboardInterrupt:
        return 130
