"""
Rules for Cursor's repository-shipped configuration

Cursor reads AGENTS.md for portable instructions, so these rules cover only
what is Cursor-specific and structural: the `.mdc` rule frontmatter that
decides whether a rule ever activates, and the `.cursor/hooks.json` lifecycle
configuration.
"""

from .hooks_valid import CursorHooksValidRule
from .rules_valid import CursorRulesValidRule

__all__ = [
    "CursorHooksValidRule",
    "CursorRulesValidRule",
]
