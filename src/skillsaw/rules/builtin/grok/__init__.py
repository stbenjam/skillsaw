"""
Rules for Grok Build's repository-shipped configuration

Grok Build reads ``AGENTS.md`` for portable instructions and portable Agent
Skills from ``.grok/skills/``, both of which the shared content, security
and skill rules already cover. What is Grok's own and structural is
``.grok/hooks/*.json``: its loader refuses a whole file over one wrong-typed
field and reports nothing when it does.
"""

from .hooks_valid import GrokHooksValidRule

__all__ = [
    "GrokHooksValidRule",
]
