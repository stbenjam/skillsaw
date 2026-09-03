"""
Rules for Grok Build's repository-shipped configuration

Grok Build reads ``AGENTS.md`` for portable instructions and portable Agent
Skills from ``.grok/skills/``, both of which the shared content, security
and skill rules already cover. What is Grok's own and structural is the two
surfaces its loader refuses without a word: ``.grok/hooks/*.json``, where one
wrong-typed field costs the whole file, and ``.grok/agents/*.md``, where a
missing ``name`` or ``description`` costs the subagent.

``.grok/commands/*.md`` has no rule of its own by design — Grok loads a
command with no frontmatter at all, naming it from the filename, so there is
nothing structural to require.
"""

from .agent_valid import GrokAgentValidRule
from .hooks_valid import GrokHooksValidRule

__all__ = [
    "GrokAgentValidRule",
    "GrokHooksValidRule",
]
