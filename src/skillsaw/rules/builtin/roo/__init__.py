"""
Rules for legacy Roo Code configuration

Roo Code (the VS Code extension) shut down in May 2026, but repositories
still carry the files it read, and other tools migrate them. Its prose —
`.roorules` and `.roo/rules*/` — needs no rule of its own: it is attached
as instruction content and picked up by the content and security rules.
What is Roo-specific and structural is `.roomodes`, the custom-mode
definitions, which is what this package validates.
"""

from .modes_valid import RooModesValidRule

__all__ = ["RooModesValidRule"]
