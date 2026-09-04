"""
Rules for Muse Code repository configuration.

Muse Code reads AGENTS.md for portable instructions and ``.agents/memory/``
for committed project memory, both covered by skillsaw's universal rules.
Structural validation focuses on ``.muse/hooks.json`` to ensure lifecycle
hooks run reliably across interactive and headless sessions.
"""

from .hooks_valid import MuseHooksValidRule

__all__ = [
    "MuseHooksValidRule",
]
