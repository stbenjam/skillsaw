"""
Rules for OpenCode's repository-shipped configuration

OpenCode reads AGENTS.md for portable instructions, so nothing here
reimplements an instruction format. What is OpenCode-specific and structural
is the project config — ``opencode.json(c)`` at the repository root or under
``.opencode/`` — which carries the MCP servers, agents and commands the tool
loads, and fails silently when a key is misspelled.
"""

from .config_valid import OpenCodeConfigValidRule

__all__ = [
    "OpenCodeConfigValidRule",
]
