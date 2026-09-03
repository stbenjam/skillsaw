"""
Rules for Muse Code's repository-shipped configuration

Muse Code reads AGENTS.md for portable instructions and ``.agents/memory/``
for project memory, both of which the shared content and security rules
already cover. What is Muse-specific and structural is ``.muse/hooks.json``:
its loader is strict where Claude's is lenient, and it reports nothing when
it rejects a file, a matcher group, or a handler.
"""

from .hooks_valid import MuseHooksValidRule

__all__ = [
    "MuseHooksValidRule",
]
